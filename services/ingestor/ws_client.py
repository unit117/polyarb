"""WebSocket client for real-time Polymarket CLOB price streaming.

Connects to wss://ws-subscriptions-clob.polymarket.com/ws/market and
converts price_change / last_trade_price events into PriceSnapshot rows,
publishing CHANNEL_SNAPSHOT_CREATED exactly like the polling path.
"""

import asyncio
import json
import random
import time
from datetime import datetime, timezone

import structlog
import websockets
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.events import (
    CHANNEL_MARKET_RESOLVED,
    CHANNEL_SNAPSHOT_CREATED,
    publish,
)
from shared.models import Market, PriceSnapshot

log = structlog.get_logger()


class ClobWebSocket:
    """Manages a WebSocket connection to Polymarket CLOB for real-time prices."""

    def __init__(
        self,
        redis,
        session_factory: async_sessionmaker,
        ws_url: str,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 60.0,
        ping_interval: int = 10,
        buffer_seconds: float = 2.0,
        resolution_threshold: float = 0.98,
        max_snapshot_markets: int = 100,
    ):
        self._redis = redis
        self._session_factory = session_factory
        self._ws_url = ws_url
        self._reconnect_base = reconnect_base_delay
        self._reconnect_max = reconnect_max_delay
        self._ping_interval = ping_interval
        self._buffer_seconds = buffer_seconds
        self._resolution_threshold = resolution_threshold
        self._max_snapshot_markets = max_snapshot_markets

        self._ws = None
        self._subscribed_tokens: set[str] = set()
        self._token_map: dict[str, tuple[int, str]] = {}  # token_id -> (market_id, outcome)
        self._pending_snapshots: dict[int, dict] = {}  # market_id -> {prices, midpoints}
        self._last_known_prices: dict[int, dict] = {}  # market_id -> {outcome: price} full state
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self.connected = False  # Exposed for graceful degradation
        # After reconnect, tracks markets whose prices were DB-seeded and
        # still have outcomes not yet refreshed by WS.  Maps market_id →
        # set of outcome names still awaiting a WS update.  Markets in
        # this dict are excluded from detector snapshot events to prevent
        # phantom arbs from mixed old-DB / new-WS prices.
        self._reconnect_pending: dict[int, set[str]] = {}

    async def _build_token_map(self) -> None:
        """Build token_id -> (market_id, outcome_name) lookup from DB."""
        self._token_map.clear()
        async with self._session_factory() as session:
            result = await session.execute(
                select(Market.id, Market.token_ids, Market.outcomes).where(
                    Market.active == True  # noqa: E712
                )
            )
            for row in result.fetchall():
                market_id, token_ids, outcomes = row
                if not token_ids or not outcomes:
                    continue
                for i, token_id in enumerate(token_ids):
                    outcome = outcomes[i] if i < len(outcomes) else f"outcome_{i}"
                    self._token_map[str(token_id)] = (market_id, outcome)

        log.info("ws_token_map_built", tokens=len(self._token_map))

    async def _get_eligible_token_ids(self) -> list[str]:
        """Get token IDs for top markets by liquidity + paired markets."""
        from shared.models import MarketPair

        async with self._session_factory() as session:
            # Top N by liquidity
            result = await session.execute(
                select(Market.id, Market.token_ids, Market.liquidity)
                .where(Market.active == True)  # noqa: E712
                .where(Market.token_ids != None)  # noqa: E711
                .order_by(Market.liquidity.desc().nullslast())
                .limit(self._max_snapshot_markets)
            )
            eligible_ids = set()
            market_tokens: dict[int, list[str]] = {}
            for row in result.fetchall():
                eligible_ids.add(row.id)
                market_tokens[row.id] = [str(t) for t in row.token_ids] if row.token_ids else []

            # Add paired markets
            pair_result = await session.execute(
                select(MarketPair.market_a_id, MarketPair.market_b_id)
            )
            paired_ids = set()
            for row in pair_result.fetchall():
                paired_ids.add(row.market_a_id)
                paired_ids.add(row.market_b_id)

            # Fetch tokens for paired markets not already in top N
            missing = paired_ids - eligible_ids
            if missing:
                missing_result = await session.execute(
                    select(Market.id, Market.token_ids)
                    .where(Market.id.in_(missing))
                    .where(Market.token_ids != None)  # noqa: E711
                )
                for row in missing_result.fetchall():
                    market_tokens[row.id] = [str(t) for t in row.token_ids] if row.token_ids else []
                eligible_ids |= missing

        token_ids = []
        for mid in eligible_ids:
            token_ids.extend(market_tokens.get(mid, []))

        log.info("ws_eligible_tokens", markets=len(eligible_ids), tokens=len(token_ids))
        return token_ids

    async def update_subscriptions(self, eligible_token_ids: set[str]) -> None:
        """Add/remove subscriptions to match the eligible set."""
        if not self._ws:
            return

        to_add = eligible_token_ids - self._subscribed_tokens
        to_remove = self._subscribed_tokens - eligible_token_ids

        if to_remove:
            # Unsubscribe in batches of 100
            remove_list = list(to_remove)
            for i in range(0, len(remove_list), 100):
                batch = remove_list[i : i + 100]
                try:
                    await self._ws.send(json.dumps({
                        "assets_ids": batch,
                        "operation": "unsubscribe",
                    }))
                except Exception:
                    log.exception("ws_unsubscribe_error")
                    return
            self._subscribed_tokens -= to_remove
            log.info("ws_unsubscribed", count=len(to_remove))

        if to_add:
            add_list = list(to_add)
            for i in range(0, len(add_list), 100):
                batch = add_list[i : i + 100]
                try:
                    await self._ws.send(json.dumps({
                        "assets_ids": batch,
                        "operation": "subscribe",
                    }))
                except Exception:
                    log.exception("ws_subscribe_error")
                    return
            self._subscribed_tokens |= to_add
            log.info("ws_subscribed", count=len(to_add))

    async def _connect(self, token_ids: list[str]) -> None:
        """Establish WS connection and send initial subscription."""
        self._ws = await websockets.connect(
            self._ws_url,
            ping_interval=None,  # We handle pings manually
            close_timeout=5,
        )
        # Initial subscription — send first batch with type: "market"
        if token_ids:
            # Send in batches of 100
            first_batch = token_ids[:100]
            await self._ws.send(json.dumps({
                "assets_ids": first_batch,
                "type": "market",
            }))
            self._subscribed_tokens = set(first_batch)

            # Subscribe remaining in follow-up messages
            for i in range(100, len(token_ids), 100):
                batch = token_ids[i : i + 100]
                await self._ws.send(json.dumps({
                    "assets_ids": batch,
                    "operation": "subscribe",
                }))
                self._subscribed_tokens.update(batch)

        log.info("ws_connected", subscriptions=len(self._subscribed_tokens))

    async def _ping_loop(self) -> None:
        """Send PING every N seconds to keep connection alive."""
        while self._running and self._ws:
            try:
                await self._ws.send("PING")
                await asyncio.sleep(self._ping_interval)
            except Exception:
                break

    async def _seed_last_known_prices(self, market_ids: list[int]) -> None:
        """Load the latest complete snapshot for each market from DB.

        If we're in a post-reconnect window, records the seeded outcomes
        so we can track when each market has been fully refreshed by WS.
        """
        if not market_ids:
            return
        async with self._session_factory() as session:
            for market_id in market_ids:
                result = await session.execute(
                    select(PriceSnapshot.prices)
                    .where(PriceSnapshot.market_id == market_id)
                    .order_by(PriceSnapshot.timestamp.desc())
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row:
                    prices = dict(row)
                    self._last_known_prices[market_id] = prices
                    # Track DB-seeded outcomes that need WS refresh
                    if self._reconnect_pending is not None:
                        self._reconnect_pending[market_id] = set(prices.keys())

    async def _flush_snapshots(self) -> None:
        """Periodically flush buffered price updates to DB.

        Merges WS partial updates with last known complete prices so every
        snapshot row contains ALL outcomes, not just the one that changed.
        """
        while self._running:
            await asyncio.sleep(self._buffer_seconds)
            if not self._pending_snapshots:
                continue

            snapshots = self._pending_snapshots.copy()
            self._pending_snapshots.clear()

            # Seed last known prices for markets we haven't seen yet
            unseeded = [mid for mid in snapshots if mid not in self._last_known_prices]
            if unseeded:
                try:
                    await self._seed_last_known_prices(unseeded)
                except Exception:
                    log.exception("ws_seed_prices_error")

            rows = []
            for market_id, data in snapshots.items():
                # Start from last known complete state, overlay WS updates
                merged = dict(self._last_known_prices.get(market_id, {}))
                merged.update(data["prices"])

                # Update last known state for next flush
                self._last_known_prices[market_id] = merged

                rows.append({
                    "market_id": market_id,
                    "prices": merged,
                    "midpoints": merged,
                    "order_book": None,
                })

            try:
                async with self._session_factory() as session:
                    await session.execute(insert(PriceSnapshot), rows)
                    await session.commit()

                # Check for resolution
                for row_data in rows:
                    for outcome, price_str in row_data["prices"].items():
                        try:
                            price = float(price_str)
                        except (ValueError, TypeError):
                            continue
                        if price >= self._resolution_threshold:
                            market_id = row_data["market_id"]
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
                                        "source": "ws_price_inference",
                                        "price": price,
                                    })

                # Exclude markets still pending full WS refresh after
                # reconnect — their prices mix stale DB seed with partial
                # WS updates and could create phantom arb spreads.
                fresh_ids = [
                    r["market_id"] for r in rows
                    if r["market_id"] not in self._reconnect_pending
                ]
                if fresh_ids:
                    await publish(self._redis, CHANNEL_SNAPSHOT_CREATED, {
                        "count": len(fresh_ids),
                        "source": "websocket",
                        "market_ids": fresh_ids,
                    })
                stale_count = len(rows) - len(fresh_ids)
                log.info(
                    "ws_snapshots_flushed",
                    count=len(fresh_ids),
                    stale_suppressed=stale_count,
                )
            except Exception:
                log.exception("ws_flush_error", count=len(rows))

    def _handle_price_change(self, msg: dict) -> None:
        """Process a price_change event — update buffered midpoints."""
        for change in msg.get("price_changes", []):
            asset_id = change.get("asset_id", "")
            mapping = self._token_map.get(asset_id)
            if not mapping:
                continue

            market_id, outcome = mapping
            best_bid = change.get("best_bid")
            best_ask = change.get("best_ask")

            if best_bid is not None and best_ask is not None:
                try:
                    mid = str((float(best_bid) + float(best_ask)) / 2.0)
                except (ValueError, TypeError):
                    continue

                if market_id not in self._pending_snapshots:
                    self._pending_snapshots[market_id] = {"prices": {}, "midpoints": {}}
                self._pending_snapshots[market_id]["prices"][outcome] = mid
                self._pending_snapshots[market_id]["midpoints"][outcome] = mid
                self._mark_outcome_refreshed(market_id, outcome)

    def _handle_last_trade(self, msg: dict) -> None:
        """Process a last_trade_price event — update buffered price."""
        asset_id = msg.get("asset_id", "")
        mapping = self._token_map.get(asset_id)
        if not mapping:
            return

        market_id, outcome = mapping
        price = msg.get("price")
        if price is None:
            return

        if market_id not in self._pending_snapshots:
            self._pending_snapshots[market_id] = {"prices": {}, "midpoints": {}}
        self._pending_snapshots[market_id]["prices"][outcome] = str(price)
        self._mark_outcome_refreshed(market_id, outcome)

    def _mark_outcome_refreshed(self, market_id: int, outcome: str) -> None:
        """Remove an outcome from the reconnect-pending set for a market."""
        if market_id not in self._reconnect_pending:
            return
        self._reconnect_pending[market_id].discard(outcome)
        if not self._reconnect_pending[market_id]:
            del self._reconnect_pending[market_id]

    async def _listen(self) -> None:
        """Main message loop — parse and dispatch events."""
        async for raw in self._ws:
            if not self._running:
                break
            if raw == "PONG" or not raw:
                continue
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            # Server may send arrays of events or single events
            messages = msg if isinstance(msg, list) else [msg]
            for m in messages:
                if not isinstance(m, dict):
                    continue
                event_type = m.get("event_type")
                if event_type == "price_change":
                    self._handle_price_change(m)
                elif event_type == "last_trade_price":
                    self._handle_last_trade(m)
                # book and tick_size_change ignored for now

    async def run(self) -> None:
        """Main entry point — connect, listen, reconnect on failure."""
        self._running = True
        log.info("ws_run_start")
        await self._build_token_map()

        # Subscribe only to eligible markets (top by liquidity + paired)
        initial_token_ids = await self._get_eligible_token_ids()
        log.info("ws_initial_tokens", count=len(initial_token_ids))

        consecutive_failures = 0

        while self._running:
            try:
                log.info("ws_connecting", url=self._ws_url, tokens=len(initial_token_ids))
                # Clear stale cached prices so first flush re-seeds from DB.
                # _reconnect_pending will be populated during seeding to
                # track which markets still need full WS price refresh.
                self._last_known_prices.clear()
                self._pending_snapshots.clear()
                self._reconnect_pending.clear()
                await self._connect(initial_token_ids)
                consecutive_failures = 0
                self.connected = True

                # Start ping and flush loops alongside the listener
                self._flush_task = asyncio.create_task(self._flush_snapshots())
                ping_task = asyncio.create_task(self._ping_loop())

                try:
                    await self._listen()
                finally:
                    self.connected = False
                    ping_task.cancel()
                    self._flush_task.cancel()
                    try:
                        await ping_task
                    except asyncio.CancelledError:
                        pass
                    try:
                        await self._flush_task
                    except asyncio.CancelledError:
                        pass

            except Exception as e:
                self.connected = False
                consecutive_failures += 1
                delay = min(
                    self._reconnect_base * (2 ** consecutive_failures) + random.uniform(0, 1),
                    self._reconnect_max,
                )
                log.exception(
                    "ws_disconnected",
                    error=str(e),
                    error_type=type(e).__name__,
                    attempt=consecutive_failures,
                    reconnect_in=round(delay, 1),
                )
                await asyncio.sleep(delay)

                # Refresh token map on reconnect in case markets changed
                try:
                    await self._build_token_map()
                except Exception:
                    log.exception("ws_token_map_refresh_error")

            finally:
                if self._ws:
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                    self._ws = None
                self._subscribed_tokens.clear()

    async def close(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._ws:
            await self._ws.close()
