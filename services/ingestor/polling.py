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

        # Stream pages from Gamma instead of accumulating all 30k+ markets.
        seen_ids: set[str] = set()
        total_raw = 0

        async with self._session_factory() as session:
            async for page in self._gamma.iter_market_pages():
                total_raw += len(page)

                rows: list[dict] = []
                for raw in page:
                    polymarket_id = str(raw.get("id", ""))
                    if not polymarket_id or polymarket_id in seen_ids:
                        continue
                    seen_ids.add(polymarket_id)
                    rows.append({
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
                    })

                if rows:
                    stmt = insert(Market).values(rows)
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

            log.info("sync_markets_fetched", raw=total_raw, unique=len(seen_ids))

            if not seen_ids:
                return []

            # Gamma returns the currently active Polymarket markets, so only rows
            # outside that seen set need to be flipped inactive.
            # Chunk seen_ids to stay under asyncpg's 32767 parameter limit.
            # Strategy: fetch all active polymarket IDs, compute stale set in
            # Python, then batch-update those.
            active_result = await session.execute(
                select(Market.id, Market.polymarket_id).where(
                    Market.venue == "polymarket",
                    Market.active == True,  # noqa: E712
                )
            )
            stale_market_ids = [
                row.id for row in active_result.all()
                if row.polymarket_id not in seen_ids
            ]
            stale_count = 0
            STALE_CHUNK = 10_000
            for i in range(0, len(stale_market_ids), STALE_CHUNK):
                chunk = stale_market_ids[i : i + STALE_CHUNK]
                r = await session.execute(
                    update(Market)
                    .where(Market.id.in_(chunk))
                    .values(active=False)
                )
                stale_count += r.rowcount or 0

            await session.commit()

            result = await session.execute(
                select(Market).where(Market.active == True, Market.venue == "polymarket")  # noqa: E712
            )
            markets = list(result.scalars().all())

        log.info(
            "sync_markets_done",
            active_count=len(markets),
            stale_marked_inactive=stale_count,
        )
        await publish(
            self._redis,
            CHANNEL_MARKET_UPDATED,
            {"action": "sync", "count": len(markets)},
        )
        return markets

    async def sync_fee_rates(self, markets: list[Market]) -> None:
        """Populate fee_rate_bps from CLOB API for markets missing it.

        Prioritizes markets in active pairs (needed by optimizer/simulator)
        and caps per-cycle work to avoid blocking the poll loop.
        """
        need_fee = [m for m in markets if m.fee_rate_bps is None and m.token_ids]
        if not need_fee:
            return

        # Prioritize: markets in pairs with recent opportunities first,
        # then other paired markets, then unpaired.
        need_by_id = {m.id: m for m in need_fee}
        from datetime import datetime, timedelta, timezone as tz
        from shared.models import ArbitrageOpportunity
        hot_ids: set[int] = set()
        paired_ids: set[int] = set()
        async with self._session_factory() as session:
            # Markets in pairs with recent opportunities (last 24h)
            cutoff = datetime.now(tz.utc) - timedelta(hours=24)
            result = await session.execute(
                select(MarketPair.market_a_id, MarketPair.market_b_id)
                .join(ArbitrageOpportunity, ArbitrageOpportunity.pair_id == MarketPair.id)
                .where(ArbitrageOpportunity.timestamp > cutoff)
                .distinct()
            )
            for row in result.fetchall():
                hot_ids.add(row.market_a_id)
                hot_ids.add(row.market_b_id)
            # All paired markets
            result = await session.execute(
                select(MarketPair.market_a_id, MarketPair.market_b_id)
            )
            for row in result.fetchall():
                paired_ids.add(row.market_a_id)
                paired_ids.add(row.market_b_id)

        hot_need = [need_by_id[mid] for mid in hot_ids if mid in need_by_id]
        cold_paired = [m for m in need_fee if m.id in paired_ids and m.id not in hot_ids]
        unpaired_need = [m for m in need_fee if m.id not in paired_ids]

        # Cap per-cycle: all hot + 500 cold paired + 200 unpaired.
        MAX_COLD_PAIRED = 500
        MAX_UNPAIRED = 200
        batch = hot_need + cold_paired[:MAX_COLD_PAIRED] + unpaired_need[:MAX_UNPAIRED]
        log.info("fee_rates_start", hot=len(hot_need),
                 cold_paired=min(len(cold_paired), MAX_COLD_PAIRED),
                 unpaired_batch=min(len(unpaired_need), MAX_UNPAIRED),
                 total_remaining=len(need_fee))

        updated = 0
        COMMIT_EVERY = 100
        async with self._session_factory() as session:
            for idx, market in enumerate(batch):
                token_id = str(market.token_ids[0])
                try:
                    bps = await self._clob.get_fee_rate(token_id)
                    if bps is not None:
                        await session.execute(
                            update(Market)
                            .where(Market.id == market.id)
                            .values(fee_rate_bps=bps)
                        )
                        updated += 1
                except Exception:
                    log.debug("fee_rate_fetch_failed", market_id=market.id)
                # Intermediate commit to avoid losing progress on failure
                if (idx + 1) % COMMIT_EVERY == 0:
                    await session.commit()
            await session.commit()
        log.info("fee_rates_done", updated=updated, batch_size=len(batch))

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
        # Top N by liquidity + paired markets with recent opportunities.
        # Cap total to avoid multi-hour poll cycles at 2 RPS.
        # WS already provides real-time prices for subscribed markets;
        # CLOB midpoint is a fallback for markets WS might miss.
        markets_by_id = {m.id: m for m in markets if m.token_ids}

        # Start with top N by liquidity
        by_liquidity = sorted(markets_by_id.values(), key=lambda m: m.liquidity or 0, reverse=True)
        eligible_ids = {m.id for m in by_liquidity[: self._max_snapshot_markets]}

        # Add markets from pairs with recent opportunities (not ALL pairs)
        from datetime import datetime, timedelta, timezone as tz
        from shared.models import ArbitrageOpportunity
        cutoff = datetime.now(tz.utc) - timedelta(hours=24)
        async with self._session_factory() as session:
            result = await session.execute(
                select(MarketPair.market_a_id, MarketPair.market_b_id)
                .join(ArbitrageOpportunity, ArbitrageOpportunity.pair_id == MarketPair.id)
                .where(ArbitrageOpportunity.timestamp > cutoff)
                .distinct()
            )
            for row in result.fetchall():
                if row.market_a_id in markets_by_id:
                    eligible_ids.add(row.market_a_id)
                if row.market_b_id in markets_by_id:
                    eligible_ids.add(row.market_b_id)

        # Hard cap to keep poll cycle under ~10 min at 2 RPS
        MAX_CLOB_SNAPSHOTS = 500
        eligible = [markets_by_id[mid] for mid in eligible_ids if mid in markets_by_id]
        if len(eligible) > MAX_CLOB_SNAPSHOTS:
            eligible.sort(key=lambda m: m.liquidity or 0, reverse=True)
            eligible = eligible[:MAX_CLOB_SNAPSHOTS]
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
        """Fetch closed markets from Gamma API and mark resolved ones in DB.

        Streams pages from Gamma instead of loading all closed markets into
        memory, and pre-loads the set of unresolved polymarket_ids we track
        so each page only does set lookups instead of per-row DB queries.
        """
        try:
            # Pre-load unresolved polymarket_ids we care about
            async with self._session_factory() as session:
                result = await session.execute(
                    select(Market.polymarket_id, Market.id).where(
                        Market.venue == "polymarket",
                        Market.resolved_outcome.is_(None),
                        Market.active.is_(True),
                    )
                )
                unresolved = {row[0]: row[1] for row in result.fetchall()}

            if not unresolved:
                return

            resolved_count = 0
            pages = 0

            async for page in self._gamma.iter_market_pages(
                active=False, closed=True
            ):
                pages += 1
                page_events: list[dict] = []
                async with self._session_factory() as session:
                    for raw in page:
                        polymarket_id = str(raw.get("id", ""))
                        if polymarket_id not in unresolved:
                            continue

                        market_db_id = unresolved[polymarket_id]
                        market = await session.get(Market, market_db_id)
                        if not market or market.resolved_outcome:
                            continue

                        winning_outcome = _extract_winner(raw)
                        if not winning_outcome:
                            continue

                        market.resolved_outcome = winning_outcome
                        market.resolved_at = datetime.now(timezone.utc)
                        market.active = False
                        resolved_count += 1
                        del unresolved[polymarket_id]

                        page_events.append({
                            "market_id": market.id,
                            "resolved_outcome": winning_outcome,
                            "source": "gamma_api",
                        })

                    await session.commit()

                # Publish events immediately after commit — avoids unbounded
                # accumulation across 2000+ pages of closed markets.
                for event in page_events:
                    await publish(self._redis, CHANNEL_MARKET_RESOLVED, event)

                # All tracked markets resolved — no need to keep paginating
                if not unresolved:
                    log.info("resolution_early_exit", pages=pages)
                    break

            if resolved_count > 0:
                log.info("resolution_check_done", resolved=resolved_count, pages=pages)
        except Exception:
            log.exception("resolution_check_error")

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

        # Fee rates before resolved check — fee sync is fast and needed by
        # optimizer/simulator, while resolved check paginates 130k+ markets.
        try:
            await self.sync_fee_rates(markets)
        except Exception:
            log.exception("sync_fee_rates_error")

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
