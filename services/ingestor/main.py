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
        )
        poller.set_ws_client(ws_client)

    try:
        tasks = [poller.run()]
        if ws_client:
            tasks.append(ws_client.run())
        if kalshi_poller:
            tasks.append(kalshi_poller.run())
        await asyncio.gather(*tasks)
    finally:
        if ws_client:
            await ws_client.close()
        if kalshi_client:
            await kalshi_client.close()
        await gamma.close()
        await clob.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
