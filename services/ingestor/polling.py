import asyncio
from datetime import datetime
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.events import CHANNEL_MARKET_UPDATED, CHANNEL_SNAPSHOT_CREATED, publish
from shared.models import Market, PriceSnapshot
from services.ingestor.clob_client import ClobClient
from services.ingestor.embedder import Embedder
from services.ingestor.gamma_client import GammaClient, parse_stringified_json

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


class MarketPoller:
    def __init__(
        self,
        gamma: GammaClient,
        clob: ClobClient,
        embedder: Embedder,
        session_factory: async_sessionmaker,
        redis,
        poll_interval: int = 30,
        fetch_order_books: bool = False,
        max_snapshot_markets: int = 100,
    ):
        self._gamma = gamma
        self._clob = clob
        self._embedder = embedder
        self._session_factory = session_factory
        self._redis = redis
        self._poll_interval = poll_interval
        self._fetch_order_books = fetch_order_books
        self._max_snapshot_markets = max_snapshot_markets

    async def sync_markets(self) -> list[Market]:
        log.info("sync_markets_start")
        raw_markets = await self._gamma.list_markets()
        log.info("sync_markets_fetched", count=len(raw_markets))

        if not raw_markets:
            return []

        # Prepare all rows for batch upsert, deduplicating by polymarket_id
        rows_by_id: dict[str, dict] = {}
        for raw in raw_markets:
            polymarket_id = str(raw.get("id", ""))
            if not polymarket_id:
                continue
            rows_by_id[polymarket_id] = {
                "polymarket_id": polymarket_id,
                "event_id": raw.get("eventId"),
                "question": raw.get("question", ""),
                "description": raw.get("description"),
                "outcomes": parse_stringified_json(raw.get("outcomes", "[]")),
                "token_ids": parse_stringified_json(raw.get("clobTokenIds", "[]")),
                "active": raw.get("active", True),
                "end_date": _parse_iso_date(raw.get("endDateIso")),
                "volume": _safe_decimal(raw.get("volumeNum")),
                "liquidity": _safe_decimal(raw.get("liquidityNum")),
            }
        rows = list(rows_by_id.values())
        seen_ids = set(rows_by_id.keys())
        log.info("sync_markets_deduped", unique=len(rows), raw=len(raw_markets))

        BATCH_SIZE = 500
        async with self._session_factory() as session:
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                stmt = insert(Market).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["polymarket_id"],
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
                log.info("sync_markets_batch", offset=i, batch_size=len(batch))

            # Mark stale markets inactive using a subquery approach
            # Instead of notin_ with 30K+ IDs, update all active then re-activate seen ones
            await session.execute(
                update(Market)
                .where(Market.active == True)  # noqa: E712
                .values(active=False)
            )
            # The upserts above already set active=True for all seen markets,
            # but they ran before this update. Re-run a lightweight update for seen IDs in batches.
            for i in range(0, len(rows), BATCH_SIZE):
                batch_ids = [r["polymarket_id"] for r in rows[i : i + BATCH_SIZE]]
                await session.execute(
                    update(Market)
                    .where(Market.polymarket_id.in_(batch_ids))
                    .values(active=True)
                )

            await session.commit()

            result = await session.execute(
                select(Market).where(Market.active == True)  # noqa: E712
            )
            markets = list(result.scalars().all())

        log.info("sync_markets_done", active_count=len(markets))
        await publish(
            self._redis,
            CHANNEL_MARKET_UPDATED,
            {"action": "sync", "count": len(markets)},
        )
        return markets

    async def compute_embeddings(self, markets: list[Market]) -> None:
        need_embedding = [m for m in markets if m.embedding is None]
        if not need_embedding:
            log.info("embeddings_skip", reason="all_embedded")
            return

        log.info("embeddings_start", count=len(need_embedding))
        texts = [
            f"{m.question} {m.description or ''}" for m in need_embedding
        ]
        embeddings = await self._embedder.embed_batch(texts)

        async with self._session_factory() as session:
            for market, embedding in zip(need_embedding, embeddings):
                await session.execute(
                    update(Market)
                    .where(Market.id == market.id)
                    .values(embedding=embedding)
                )
            await session.commit()

        log.info("embeddings_done", count=len(need_embedding))

    async def snapshot_prices(self, markets: list[Market]) -> None:
        # Only snapshot markets with token_ids, sorted by liquidity (top N)
        eligible = [m for m in markets if m.token_ids]
        eligible.sort(key=lambda m: m.liquidity or 0, reverse=True)
        eligible = eligible[: self._max_snapshot_markets]
        log.info("snapshots_start", eligible=len(eligible), total=len(markets))

        snapshots_to_insert = []
        for market in eligible:
            try:
                snapshot_data = await self._clob.get_snapshot_for_market(
                    token_ids=market.token_ids,
                    outcomes=market.outcomes,
                    fetch_order_books=self._fetch_order_books,
                )
                if snapshot_data["prices"]:
                    snapshots_to_insert.append(
                        {
                            "market_id": market.id,
                            "prices": snapshot_data["prices"],
                            "midpoints": snapshot_data["midpoints"],
                            "order_book": snapshot_data["order_book"],
                        }
                    )
            except Exception:
                log.exception(
                    "snapshot_error", market_id=market.polymarket_id
                )

        if snapshots_to_insert:
            async with self._session_factory() as session:
                await session.execute(
                    insert(PriceSnapshot), snapshots_to_insert
                )
                await session.commit()

        log.info("snapshots_done", count=len(snapshots_to_insert))
        await publish(
            self._redis,
            CHANNEL_SNAPSHOT_CREATED,
            {"count": len(snapshots_to_insert)},
        )

    async def poll_once(self) -> None:
        log.info("poll_cycle_start")
        markets = await self.sync_markets()
        await self.compute_embeddings(markets)
        await self.snapshot_prices(markets)
        log.info("poll_cycle_done")

    async def run(self) -> None:
        log.info("poller_start", interval=self._poll_interval)
        while True:
            try:
                await self.poll_once()
            except Exception:
                log.exception("poll_cycle_error")
            await asyncio.sleep(self._poll_interval)
