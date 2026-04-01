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
from shared.models import Market, MarketPair, PriceSnapshot
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


RESOLUTION_THRESHOLD = 0.98  # price >= this suggests market resolved


def _extract_winner(raw_market: dict) -> str | None:
    """Extract winning outcome from a closed Gamma API market.

    Polymarket sets the winning token's price to 1.0 after resolution.
    """
    outcomes = parse_stringified_json(raw_market.get("outcomes", "[]"))
    # outcomePrices is a stringified JSON array like '["1","0"]'
    prices = parse_stringified_json(raw_market.get("outcomePrices", "[]"))

    if not outcomes or not prices or len(outcomes) != len(prices):
        return None

    for outcome, price in zip(outcomes, prices):
        try:
            if float(price) >= 0.99:
                return outcome
        except (ValueError, TypeError):
            continue
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
        resolution_price_threshold: float = RESOLUTION_THRESHOLD,
    ):
        self._gamma = gamma
        self._clob = clob
        self._embedder = embedder
        self._session_factory = session_factory
        self._redis = redis
        self._poll_interval = poll_interval
        self._fetch_order_books = fetch_order_books
        self._max_snapshot_markets = max_snapshot_markets
        self._resolution_threshold = resolution_price_threshold
        self._ws_client = None

    def set_ws_client(self, ws_client) -> None:
        self._ws_client = ws_client

    def get_eligible_token_ids(self, markets: list[Market]) -> list[str]:
        """Return token IDs for markets eligible for price streaming."""
        markets_by_id = {m.id: m for m in markets if m.token_ids}
        by_liquidity = sorted(markets_by_id.values(), key=lambda m: m.liquidity or 0, reverse=True)
        eligible_ids = {m.id for m in by_liquidity[: self._max_snapshot_markets]}

        # Include paired markets (same logic as snapshot_prices)
        # Can't query DB synchronously here, so collect all token_ids from top + paired
        token_ids = []
        for mid in eligible_ids:
            m = markets_by_id.get(mid)
            if m and m.token_ids:
                token_ids.extend(str(t) for t in m.token_ids)
        return token_ids

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
                "venue": "polymarket",
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
        seen_ids = list(rows_by_id.keys())
        log.info("sync_markets_deduped", unique=len(rows), raw=len(raw_markets))

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
                log.info("sync_markets_batch", offset=i, batch_size=len(batch))

            # Gamma returns the currently active Polymarket markets, so only rows
            # outside that seen set need to be flipped inactive.
            stale_result = await session.execute(
                update(Market)
                .where(
                    Market.venue == "polymarket",
                    Market.active == True,  # noqa: E712
                    ~Market.polymarket_id.in_(seen_ids),
                )
                .values(active=False)
            )

            # Deactivate markets past their end_date — Gamma may still return
            # them as active but they can't be traded and waste pipeline cycles.
            expired_result = await session.execute(
                update(Market)
                .where(
                    Market.active == True,  # noqa: E712
                    Market.end_date != None,  # noqa: E711
                    Market.end_date < datetime.now(timezone.utc),
                )
                .values(active=False)
            )
            expired_count = expired_result.rowcount or 0
            if expired_count:
                log.info("sync_markets_expired_deactivated", count=expired_count)

            await session.commit()

            result = await session.execute(
                select(Market).where(Market.active == True, Market.venue == "polymarket")  # noqa: E712
            )
            markets = list(result.scalars().all())

        log.info(
            "sync_markets_done",
            active_count=len(markets),
            stale_marked_inactive=stale_result.rowcount or 0,
        )
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
        # Top N by liquidity + any market that's part of a detected pair
        markets_by_id = {m.id: m for m in markets if m.token_ids}

        # Start with top N by liquidity
        by_liquidity = sorted(markets_by_id.values(), key=lambda m: m.liquidity or 0, reverse=True)
        eligible_ids = {m.id for m in by_liquidity[: self._max_snapshot_markets]}

        # Add markets from detected pairs
        async with self._session_factory() as session:
            result = await session.execute(select(MarketPair.market_a_id, MarketPair.market_b_id))
            for row in result.fetchall():
                if row.market_a_id in markets_by_id:
                    eligible_ids.add(row.market_a_id)
                if row.market_b_id in markets_by_id:
                    eligible_ids.add(row.market_b_id)

        eligible = [markets_by_id[mid] for mid in eligible_ids if mid in markets_by_id]
        log.info("snapshots_start", eligible=len(eligible), paired_extra=len(eligible_ids) - self._max_snapshot_markets, total=len(markets))

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

        # Check for near-terminal prices (resolution inference)
        for snap_data in snapshots_to_insert:
            for outcome, price_str in snap_data["prices"].items():
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    continue
                if price >= self._resolution_threshold:
                    market_id = snap_data["market_id"]
                    # Mark as resolved in DB and publish event
                    async with self._session_factory() as session:
                        mkt = await session.get(Market, market_id)
                        if mkt and not mkt.resolved_outcome:
                            mkt.resolved_outcome = outcome
                            mkt.resolved_at = datetime.now(timezone.utc)
                            mkt.active = False
                            await session.commit()
                            await publish(self._redis, CHANNEL_MARKET_RESOLVED, {
                                "market_id": market_id,
                                "resolved_outcome": outcome,
                                "source": "price_inference",
                                "price": price,
                            })

        log.info("snapshots_done", count=len(snapshots_to_insert))
        await publish(
            self._redis,
            CHANNEL_SNAPSHOT_CREATED,
            {
                "count": len(snapshots_to_insert),
                "source": "polling",
                "market_ids": [s["market_id"] for s in snapshots_to_insert],
            },
        )

    async def check_resolved_markets(self) -> None:
        """Fetch closed markets from Gamma API and mark resolved ones in DB."""
        try:
            closed_markets = await self._gamma.list_markets(active=False, closed=True)
        except Exception:
            log.exception("resolution_check_error")
            return

        resolved_count = 0
        deferred_resolution_events: list[dict] = []
        async with self._session_factory() as session:
            for raw in closed_markets:
                polymarket_id = str(raw.get("id", ""))
                if not polymarket_id:
                    continue

                result = await session.execute(
                    select(Market).where(
                        Market.polymarket_id == polymarket_id,
                        Market.venue == "polymarket",
                    )
                )
                market = result.scalar_one_or_none()
                if not market or market.resolved_outcome:
                    continue

                # Determine winner: the outcome whose token price is ~1.0
                winning_outcome = _extract_winner(raw)
                if not winning_outcome:
                    continue

                market.resolved_outcome = winning_outcome
                market.resolved_at = datetime.now(timezone.utc)
                market.active = False
                resolved_count += 1

                deferred_resolution_events.append({
                    "market_id": market.id,
                    "resolved_outcome": winning_outcome,
                    "source": "gamma_api",
                })

            if resolved_count > 0:
                await session.commit()
                # Publish after commit so subscribers see durable rows
                for event in deferred_resolution_events:
                    await publish(self._redis, CHANNEL_MARKET_RESOLVED, event)
                log.info("resolution_check_done", resolved=resolved_count)

    async def poll_once(self) -> list[Market]:
        log.info("poll_cycle_start")
        markets = await self.sync_markets()

        # Update WS subscriptions with current eligible markets
        if self._ws_client is not None:
            try:
                await self._ws_client._build_token_map()
                eligible = set(self.get_eligible_token_ids(markets))
                # Also add paired market tokens
                async with self._session_factory() as session:
                    result = await session.execute(
                        select(MarketPair.market_a_id, MarketPair.market_b_id)
                    )
                    markets_by_id = {m.id: m for m in markets if m.token_ids}
                    for row in result.fetchall():
                        for mid in (row.market_a_id, row.market_b_id):
                            m = markets_by_id.get(mid)
                            if m and m.token_ids:
                                eligible.update(str(t) for t in m.token_ids)
                await self._ws_client.update_subscriptions(eligible)
            except Exception:
                log.exception("ws_subscription_update_error")

        # Keep price ingestion and settlement progressing even if embeddings fail.
        try:
            await self.snapshot_prices(markets)
        except Exception:
            log.exception("snapshot_prices_error")

        try:
            await self.check_resolved_markets()
        except Exception:
            log.exception("resolution_check_error")

        try:
            await self.compute_embeddings(markets)
        except Exception:
            log.exception("compute_embeddings_error")

        log.info("poll_cycle_done")
        return markets

    async def run(self) -> None:
        log.info("poller_start", interval=self._poll_interval)
        while True:
            try:
                await self.poll_once()
            except Exception:
                log.exception("poll_cycle_error")

            # Graceful degradation: if WS is down, poll at 30s instead of 300s
            if self._ws_client is not None and not self._ws_client.connected:
                interval = 30
                log.warning("poll_ws_down_fast_mode", interval=interval)
            else:
                interval = self._poll_interval
            await asyncio.sleep(interval)
