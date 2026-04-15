"""Kalshi market polling — mirrors MarketPoller pattern for Kalshi venue."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.events import (
    CHANNEL_MARKET_UPDATED,
    CHANNEL_MARKET_RESOLVED,
    CHANNEL_SNAPSHOT_CREATED,
    publish,
)
from shared.models import Market, PriceSnapshot
from services.ingestor.embedder import Embedder
from services.ingestor.kalshi_client import KalshiClient

log = structlog.get_logger()



def _safe_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class KalshiPoller:
    """Polls Kalshi markets and snapshots prices, following MarketPoller patterns."""

    def __init__(
        self,
        client: KalshiClient,
        embedder: Embedder,
        session_factory: async_sessionmaker,
        redis,
        poll_interval: int = 120,
        max_markets: int = 500,
        max_snapshot_markets: int = 100,
    ):
        self._client = client
        self._embedder = embedder
        self._session_factory = session_factory
        self._redis = redis
        self._poll_interval = poll_interval
        self._max_markets = max_markets
        self._max_snapshot_markets = max_snapshot_markets

    async def sync_markets(self) -> list[Market]:
        """Fetch Kalshi markets and upsert into DB with venue='kalshi'."""
        log.info("kalshi_sync_start")
        raw_markets = await self._client.list_markets(max_markets=self._max_markets)
        log.info("kalshi_sync_fetched", count=len(raw_markets))

        if not raw_markets:
            return []

        rows_by_id: dict[str, dict] = {}
        for raw in raw_markets:
            external_id = raw.get("polymarket_id")
            if not external_id:
                continue
            rows_by_id[external_id] = {
                "venue": "kalshi",
                "polymarket_id": external_id,
                "event_id": raw.get("event_id"),
                "question": raw.get("question", ""),
                "description": raw.get("description"),
                "outcomes": raw.get("outcomes", ["Yes", "No"]),
                "token_ids": raw.get("token_ids", [external_id]),
                "active": raw.get("active", True),
                "end_date": _parse_iso_date(raw.get("end_date")),
                "volume": _safe_decimal(raw.get("volume")),
                "liquidity": _safe_decimal(raw.get("liquidity")),
            }
        rows = list(rows_by_id.values())
        log.info("kalshi_sync_deduped", unique=len(rows))

        BATCH_SIZE = 500
        async with self._session_factory() as session:
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                stmt = insert(Market).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["venue", "polymarket_id"],
                    set_={
                        "question": stmt.excluded.question,
                        "description": stmt.excluded.description,
                        "outcomes": stmt.excluded.outcomes,
                        "token_ids": stmt.excluded.token_ids,
                        "active": stmt.excluded.active,
                        "end_date": stmt.excluded.end_date,
                        "volume": stmt.excluded.volume,
                        "liquidity": stmt.excluded.liquidity,
                    },
                )
                await session.execute(stmt)

            # Mark stale Kalshi markets inactive.
            # Use Python-side set diff to avoid asyncpg 32767 parameter limit.
            kalshi_seen = set(rows_by_id.keys())
            active_kalshi = await session.execute(
                select(Market.id, Market.polymarket_id).where(
                    Market.active == True, Market.venue == "kalshi"  # noqa: E712
                )
            )
            stale_ids = [
                row.id for row in active_kalshi.all()
                if row.polymarket_id not in kalshi_seen
            ]
            STALE_CHUNK = 10_000
            for i in range(0, len(stale_ids), STALE_CHUNK):
                chunk = stale_ids[i : i + STALE_CHUNK]
                await session.execute(
                    update(Market).where(Market.id.in_(chunk)).values(active=False)
                )

            await session.commit()

            result = await session.execute(
                select(Market).where(
                    Market.active == True, Market.venue == "kalshi"  # noqa: E712
                )
            )
            markets = list(result.scalars().all())

        log.info("kalshi_sync_done", active=len(markets))
        await publish(
            self._redis,
            CHANNEL_MARKET_UPDATED,
            {"action": "sync", "count": len(markets), "venue": "kalshi"},
        )
        return markets

    async def compute_embeddings(self, markets: list[Market]) -> None:
        """Compute embeddings for Kalshi markets missing them."""
        need_embedding = [m for m in markets if m.embedding is None]
        if not need_embedding:
            log.info("kalshi_embeddings_skip", reason="all_embedded")
            return

        log.info("kalshi_embeddings_start", count=len(need_embedding))
        texts = [f"{m.question} {m.description or ''}" for m in need_embedding]
        embeddings = await self._embedder.embed_batch(texts)

        async with self._session_factory() as session:
            for market, embedding in zip(need_embedding, embeddings):
                await session.execute(
                    update(Market)
                    .where(Market.id == market.id)
                    .values(embedding=embedding)
                )
            await session.commit()

        log.info("kalshi_embeddings_done", count=len(need_embedding))

    async def snapshot_prices(self, markets: list[Market]) -> None:
        """Fetch current prices for top Kalshi markets by volume."""
        # Top N by volume
        by_volume = sorted(markets, key=lambda m: m.volume or 0, reverse=True)
        eligible = by_volume[: self._max_snapshot_markets]
        log.info("kalshi_snapshots_start", eligible=len(eligible))

        snapshots_to_insert = []
        for market in eligible:
            try:
                # Each Kalshi market has one ticker in token_ids
                ticker = market.token_ids[0] if market.token_ids else market.polymarket_id
                prices = await self._client.get_prices(ticker)
                if prices:
                    snapshots_to_insert.append({
                        "market_id": market.id,
                        "prices": prices,
                        "midpoints": prices,  # For Kalshi, midpoints = prices
                        "order_book": None,
                    })
            except Exception:
                log.exception("kalshi_snapshot_error", ticker=market.polymarket_id)

        if snapshots_to_insert:
            async with self._session_factory() as session:
                await session.execute(insert(PriceSnapshot), snapshots_to_insert)
                await session.commit()

        # NOTE: No price-based resolution detection for Kalshi.
        # Kalshi markets routinely trade at 98-99c before official resolution.
        # Resolution is handled by check_resolved_markets() which queries
        # the Kalshi API for explicitly settled markets.

        log.info("kalshi_snapshots_done", count=len(snapshots_to_insert))
        if snapshots_to_insert:
            await publish(
                self._redis,
                CHANNEL_SNAPSHOT_CREATED,
                {
                    "count": len(snapshots_to_insert),
                    "source": "kalshi_polling",
                    "market_ids": [s["market_id"] for s in snapshots_to_insert],
                },
            )

    async def check_resolved_markets(self) -> None:
        """Check for settled Kalshi markets via batch API query.

        Fetches all settled markets from Kalshi in one paginated call,
        then cross-references against our active Kalshi markets to find
        newly resolved ones. This avoids per-market API calls that would
        blow through the rate limit.
        """
        try:
            settled = await self._client.list_settled_markets()
        except Exception:
            log.exception("kalshi_settlement_fetch_error")
            return

        if not settled:
            return

        # Build lookup: ticker → result
        settled_by_ticker = {}
        for raw in settled:
            ticker = raw.get("ticker")
            result_val = raw.get("result")
            if ticker and result_val:
                settled_by_ticker[ticker] = result_val

        if not settled_by_ticker:
            return

        # Find our active Kalshi markets that match settled tickers
        # Chunk to avoid exceeding PostgreSQL's bound-parameter limit
        CHUNK = 5000
        ticker_list = list(settled_by_ticker.keys())
        to_resolve: list[Market] = []
        async with self._session_factory() as session:
            for i in range(0, len(ticker_list), CHUNK):
                chunk = ticker_list[i : i + CHUNK]
                result = await session.execute(
                    select(Market).where(
                        Market.venue == "kalshi",
                        Market.active == True,  # noqa: E712
                        Market.resolved_outcome.is_(None),
                        Market.polymarket_id.in_(chunk),
                    )
                )
                to_resolve.extend(result.scalars().all())

            for market in to_resolve:
                result_val = settled_by_ticker[market.polymarket_id]
                outcome = "Yes" if result_val == "yes" else "No"
                market.resolved_outcome = outcome
                market.resolved_at = datetime.now(timezone.utc)
                market.active = False
                log.info(
                    "kalshi_market_resolved",
                    ticker=market.polymarket_id,
                    outcome=outcome,
                )

            if to_resolve:
                await session.commit()

        # Publish events after commit
        for market in to_resolve:
            await publish(self._redis, CHANNEL_MARKET_RESOLVED, {
                "market_id": market.id,
                "resolved_outcome": market.resolved_outcome,
                "source": "kalshi_api",
            })

    async def poll_once(self) -> list[Market]:
        log.info("kalshi_poll_cycle_start")
        markets = await self.sync_markets()
        await self.compute_embeddings(markets)
        await self.snapshot_prices(markets)
        await self.check_resolved_markets()
        log.info("kalshi_poll_cycle_done")
        return markets

    async def run(self) -> None:
        log.info("kalshi_poller_start", interval=self._poll_interval)
        while True:
            try:
                await self.poll_once()
            except Exception:
                log.exception("kalshi_poll_error")
            await asyncio.sleep(self._poll_interval)
