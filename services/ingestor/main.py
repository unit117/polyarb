import asyncio

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import get_redis
from shared.logging import setup_logging
from services.ingestor.clob_client import ClobClient
from services.ingestor.embedder import Embedder
from services.ingestor.gamma_client import GammaClient
from services.ingestor.polling import MarketPoller
from services.ingestor.ws_client import ClobWebSocket

import structlog

log = structlog.get_logger()


async def main() -> None:
    setup_logging(settings.log_level)

    await init_db()

    gamma = GammaClient(settings.gamma_api_base, settings.rate_limit_rps)
    clob = ClobClient(settings.clob_api_base, settings.rate_limit_rps)
    embedder = Embedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    redis = await get_redis()

    # Capture posture, logged once so a mis-set .env is visible at a glance
    log.info(
        "capture_posture",
        fetch_order_books=settings.fetch_order_books,
        order_books_paired_only=settings.order_books_paired_only,
        order_book_depth_levels=settings.order_book_depth_levels,
        capture_ws_trades=settings.capture_ws_trades,
        fold_trade_prices_into_midpoints=settings.fold_trade_prices_into_midpoints,
        max_clob_snapshots=settings.max_clob_snapshots,
        max_ws_subscriptions=settings.max_ws_subscriptions,
        snapshot_retention_days=settings.snapshot_retention_days,
        trades_retention_days=settings.trades_retention_days,
    )

    # When WS is enabled, slow polling to 5-minute reconciliation
    poll_interval = 300 if settings.ws_enabled else settings.poll_interval_seconds

    poller = MarketPoller(
        gamma=gamma,
        clob=clob,
        embedder=embedder,
        session_factory=SessionFactory,
        redis=redis,
        poll_interval=poll_interval,
        fetch_order_books=settings.fetch_order_books,
        max_snapshot_markets=settings.max_snapshot_markets,
    )

    # Optional Kalshi poller
    kalshi_client = None
    kalshi_poller = None
    if settings.kalshi_enabled:
        from services.ingestor.kalshi_client import KalshiClient
        from services.ingestor.kalshi_polling import KalshiPoller

        log.info("kalshi_init", api_key_set=bool(settings.kalshi_api_key))
        kalshi_client = KalshiClient(
            api_key=settings.kalshi_api_key,
            private_key_pem=settings.kalshi_api_secret,
            rate_limit_rps=settings.kalshi_rate_limit_rps,
        )
        kalshi_poller = KalshiPoller(
            client=kalshi_client,
            embedder=embedder,
            session_factory=SessionFactory,
            redis=redis,
            poll_interval=settings.kalshi_poll_interval_seconds,
            max_markets=settings.kalshi_max_markets,
            max_snapshot_markets=settings.max_snapshot_markets,
        )

    ws_client = None
    if settings.ws_enabled:
        ws_client = ClobWebSocket(
            redis=redis,
            session_factory=SessionFactory,
            ws_url=settings.ws_clob_url,
            reconnect_base_delay=settings.ws_reconnect_base_delay,
            reconnect_max_delay=settings.ws_reconnect_max_delay,
            ping_interval=settings.ws_ping_interval,
            buffer_seconds=settings.ws_snapshot_buffer_seconds,
            resolution_threshold=settings.resolution_price_threshold,
            max_snapshot_markets=settings.max_snapshot_markets,
            max_ws_subscriptions=settings.max_ws_subscriptions,
        )
        poller.set_ws_client(ws_client)

    try:
        tasks = [poller.run()]
        if ws_client:
            tasks.append(ws_client.run())
        if kalshi_poller:
            tasks.append(kalshi_poller.run())
        if settings.snapshot_retention_days > 0 or settings.trades_retention_days > 0:
            tasks.append(_retention_loop())
        await asyncio.gather(*tasks)
    finally:
        if ws_client:
            await ws_client.close()
        if kalshi_client:
            await kalshi_client.close()
        await gamma.close()
        await clob.close()
        await redis.aclose()


RETENTION_BATCH_ROWS = 50_000
RETENTION_MAX_BATCHES_PER_WAKE = 20


async def _prune_batched(model, ts_col, cutoff, label: str) -> None:
    """Delete rows older than cutoff in bounded batches.

    price_snapshots is ~180 GB on the NAS and has no pure-timestamp index —
    a single DELETE would hold locks and write WAL for the whole backlog.
    Batches walk the PK (id order ≈ insertion order), each in its own
    transaction; a one-row oldest-id probe skips the scan entirely when
    there is nothing old enough to prune.
    """
    from sqlalchemy import delete, select

    total = 0
    for _ in range(RETENTION_MAX_BATCHES_PER_WAKE):
        async with SessionFactory() as session:
            oldest = await session.execute(
                select(ts_col).order_by(model.id).limit(1)
            )
            oldest_ts = oldest.scalar_one_or_none()
            if oldest_ts is None or oldest_ts >= cutoff:
                break
            result = await session.execute(
                delete(model).where(
                    model.id.in_(
                        select(model.id)
                        .where(ts_col < cutoff)
                        .order_by(model.id)
                        .limit(RETENTION_BATCH_ROWS)
                    )
                )
            )
            await session.commit()
            total += result.rowcount or 0
            if (result.rowcount or 0) < RETENTION_BATCH_ROWS:
                break
    if total:
        log.info(f"{label}_retention_pruned", rows=total)


async def _retention_loop() -> None:
    """Prune old price_snapshots / market_trades on a 6h cadence.

    Off by default (retention 0 = keep forever — the whole point of the
    capture work is future backtests). Enable via .env once NAS disk
    headroom demands it; the batch cap spreads a large first-enablement
    backlog across wakes instead of one catastrophic delete.
    """
    from datetime import datetime, timedelta, timezone

    from shared.models import MarketTrade, PriceSnapshot

    while True:
        try:
            now = datetime.now(timezone.utc)
            if settings.snapshot_retention_days > 0:
                await _prune_batched(
                    PriceSnapshot,
                    PriceSnapshot.timestamp,
                    now - timedelta(days=settings.snapshot_retention_days),
                    "snapshot",
                )
            if settings.trades_retention_days > 0:
                await _prune_batched(
                    MarketTrade,
                    MarketTrade.received_at,
                    now - timedelta(days=settings.trades_retention_days),
                    "trades",
                )
        except Exception:
            log.exception("retention_loop_error")
        await asyncio.sleep(6 * 3600)


if __name__ == "__main__":
    asyncio.run(main())
