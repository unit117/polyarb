"""Simulator pipeline: executes paper trades for optimized opportunities."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.circuit_breaker import CircuitBreaker
from shared.config import settings, venue_fee
from shared.events import (
    CHANNEL_PORTFOLIO_UPDATED,
    CHANNEL_TRADE_EXECUTED,
    publish,
)
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PaperTrade,
    PortfolioSnapshot,
    PriceSnapshot,
)
from services.simulator.portfolio import Portfolio
from services.simulator.vwap import compute_vwap

if TYPE_CHECKING:
    from services.simulator.live_coordinator import LiveTradingCoordinator

logger = structlog.get_logger()


@dataclass(frozen=True)
class ValidatedLeg:
    market_id: int
    outcome: str
    side: str
    size: float
    entry_price: float
    vwap_price: float
    slippage: float
    fees: float
    fair_price: float
    trade_venue: str


@dataclass(frozen=True)
class ValidatedExecutionBundle:
    opportunity_id: int
    pair_id: int
    estimated_profit: float
    kelly_fraction: float
    current_prices: dict[str, float]
    legs: list[ValidatedLeg]


class SimulatorPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        redis: aioredis.Redis,
        portfolio: Portfolio,
        max_position_size: float,
        circuit_breaker: CircuitBreaker | None = None,
        source: str = "paper",
    ):
        self.session_factory = session_factory
        self.redis = redis
        self.portfolio = portfolio
        self.max_position_size = max_position_size
        self.circuit_breaker = circuit_breaker
        self.source = source
        self._in_flight: set[int] = set()
        self._execution_lock = asyncio.Lock()
        self._retry_counts: dict[int, int] = {}
        self._max_retries = settings.max_opportunity_retries

    async def simulate_opportunity(
        self,
        opportunity_id: int,
        live_coordinator: LiveTradingCoordinator | None = None,
    ) -> dict:
        """Simulate executing trades for an optimized opportunity."""
        if opportunity_id in self._in_flight:
            return {"status": "skipped", "reason": "in_flight"}
        self._in_flight.add(opportunity_id)
        try:
            async with self._execution_lock:
                return await self._simulate_opportunity_inner(
                    opportunity_id,
                    live_coordinator=live_coordinator,
                )
        finally:
            self._in_flight.discard(opportunity_id)

    async def _simulate_opportunity_inner(
        self,
        opportunity_id: int,
        live_coordinator: LiveTradingCoordinator | None = None,
    ) -> dict:
        async with self.session_factory() as session:
            opp = await session.get(ArbitrageOpportunity, opportunity_id)
            if not opp:
                return {"status": "not_found"}

            if opp.status not in ("optimized", "unconverged"):
                return {"status": "skipped", "reason": opp.status}

            if not opp.optimal_trades or not opp.optimal_trades.get("trades"):
                opp.status = "expired"
                opp.expired_at = datetime.now(timezone.utc)
                self._retry_counts.pop(opp.id, None)
                await session.commit()
                logger.info(
                    "expired_empty_trades",
                    opportunity_id=opp.id,
                )
                return {"status": "expired", "reason": "no_trades"}

            opp.status = "pending"
            opp.pending_at = datetime.now(timezone.utc)
            await session.commit()

        try:
            return await self._execute_pending(
                opportunity_id,
                live_coordinator=live_coordinator,
            )
        except Exception:
            logger.exception(
                "pending_execution_failed",
                opportunity_id=opportunity_id,
            )
            try:
                async with self.session_factory() as session:
                    opp = await session.get(ArbitrageOpportunity, opportunity_id)
                    if opp and opp.status == "pending":
                        opp.status = "optimized"
                        await session.commit()
            except Exception:
                logger.exception(
                    "pending_revert_failed",
                    opportunity_id=opportunity_id,
                )
            raise

    async def _execute_pending(
        self,
        opportunity_id: int,
        live_coordinator: LiveTradingCoordinator | None = None,
    ) -> dict:
        async with self.session_factory() as session:
            opp = await session.get(ArbitrageOpportunity, opportunity_id)
            if not opp or opp.status != "pending":
                return {"status": "skipped", "reason": "status_changed"}

            pair = await session.get(MarketPair, opp.pair_id)
            if not pair:
                opp.status = "optimized"
                await session.commit()
                return {"status": "no_pair"}

            market_a = await session.get(Market, pair.market_a_id)
            market_b = await session.get(Market, pair.market_b_id)

            bundle = await self._build_validated_bundle(
                session=session,
                opp=opp,
                market_a=market_a,
                market_b=market_b,
            )
            if not bundle or not bundle.legs:
                # Expire if either market is resolved — no point recycling
                either_resolved = any(
                    m and m.resolved_outcome is not None
                    for m in (market_a, market_b)
                )
                if either_resolved:
                    opp.status = "expired"
                    opp.expired_at = datetime.now(timezone.utc)
                    self._retry_counts.pop(opp.id, None)
                else:
                    # Track retry count — expire after max_retries to avoid
                    # infinite loops on permanently blocked opportunities
                    retries = self._retry_counts.get(opp.id, 0) + 1
                    self._retry_counts[opp.id] = retries
                    if retries >= self._max_retries:
                        opp.status = "expired"
                        opp.expired_at = datetime.now(timezone.utc)
                        self._retry_counts.pop(opp.id, None)
                        logger.warning(
                            "expired_max_retries",
                            opportunity_id=opp.id,
                            retries=retries,
                        )
                    else:
                        opp.status = "optimized"
                await session.commit()
                logger.info(
                    "simulation_complete",
                    opportunity_id=opp.id,
                    trades_executed=0,
                    retries=self._retry_counts.get(opp.id, 0),
                    cash_remaining=float(self.portfolio.cash),
                )
                return {
                    "status": "blocked",
                    "trades_executed": 0,
                    "cash_remaining": float(self.portfolio.cash),
                }

            trades_executed = 0
            deferred_trade_events: list[dict] = []
            for leg in bundle.legs:
                key = f"{leg.market_id}:{leg.outcome}"
                existing_position = self.portfolio.positions.get(key, Decimal("0"))
                is_exit = (
                    (leg.side == "SELL" and existing_position > 0)
                    or (leg.side == "BUY" and existing_position < 0)
                )
                pre_trade_cost = self.portfolio.cost_basis.get(key, Decimal("0"))

                result = self.portfolio.execute_trade(
                    market_id=leg.market_id,
                    outcome=leg.outcome,
                    side=leg.side,
                    size=leg.size,
                    vwap_price=leg.vwap_price,
                    fees=leg.fees,
                )

                if is_exit and existing_position != 0 and result["executed"]:
                    close_size = min(abs(existing_position), Decimal(str(leg.size)))
                    avg_entry = pre_trade_cost / abs(existing_position)
                    exit_price = Decimal(str(leg.vwap_price))
                    exit_fees = (
                        Decimal(str(leg.fees)) * close_size / Decimal(str(leg.size))
                        if leg.size > 0
                        else Decimal("0")
                    )

                    if existing_position > 0:
                        realized = (exit_price - avg_entry) * close_size - exit_fees
                    else:
                        realized = (avg_entry - exit_price) * close_size - exit_fees

                    self.portfolio.realized_pnl += realized
                    if self.circuit_breaker and realized < 0:
                        self.circuit_breaker.record_loss(float(abs(realized)))

                if not result["executed"]:
                    continue

                # Use actual executed size (may be reduced by capital/margin limits)
                actual_size = result["size"]
                paper_trade = PaperTrade(
                    opportunity_id=opp.id,
                    market_id=leg.market_id,
                    outcome=leg.outcome,
                    side=leg.side,
                    size=Decimal(str(actual_size)),
                    entry_price=Decimal(str(leg.entry_price)),
                    vwap_price=Decimal(str(leg.vwap_price)),
                    slippage=Decimal(str(leg.slippage)),
                    fees=Decimal(str(leg.fees)),
                    status="filled",
                    source=self.source,
                    venue=leg.trade_venue,
                )
                session.add(paper_trade)
                await session.flush()
                trades_executed += 1

                deferred_trade_events.append(
                    {
                        "trade_id": paper_trade.id,
                        "opportunity_id": opp.id,
                        "market_id": leg.market_id,
                        "outcome": leg.outcome,
                        "side": leg.side,
                        "size": leg.size,
                        "vwap_price": leg.vwap_price,
                        "slippage": leg.slippage,
                    }
                )

            if trades_executed > 0:
                opp.status = "simulated"
                self._retry_counts.pop(opp.id, None)
            else:
                opp.status = "optimized"
            await session.commit()

            for event in deferred_trade_events:
                await publish(self.redis, CHANNEL_TRADE_EXECUTED, event)

            if live_coordinator and trades_executed > 0:
                try:
                    await live_coordinator.submit_validated_bundle(bundle)
                except Exception:
                    logger.exception(
                        "live_submission_error",
                        opportunity_id=opp.id,
                    )

            if self.circuit_breaker and trades_executed > 0:
                self.circuit_breaker.record_success()

            logger.info(
                "simulation_complete",
                opportunity_id=opp.id,
                trades_executed=trades_executed,
                cash_remaining=float(self.portfolio.cash),
            )

            return {
                "status": "simulated" if trades_executed > 0 else "blocked",
                "trades_executed": trades_executed,
                "cash_remaining": float(self.portfolio.cash),
            }

    async def _build_validated_bundle(
        self,
        session,
        opp: ArbitrageOpportunity,
        market_a: Market | None,
        market_b: Market | None,
    ) -> ValidatedExecutionBundle | None:
        # Reject opportunities on resolved or inactive markets
        for m in (market_a, market_b):
            if m and (m.resolved_outcome is not None or not m.active):
                logger.info(
                    "resolved_market_skipped",
                    opportunity_id=opp.id,
                    market_id=m.id,
                    resolved=m.resolved_outcome,
                    active=m.active,
                )
                return None

        net_profit = opp.optimal_trades.get("estimated_profit", 0)
        if net_profit <= 0:
            return None

        # Half-Kelly with a conservative cap — the edge estimates from
        # the optimizer are noisy, so capping at 0.25 keeps per-trade
        # exposure ≤ 25% of max_position_size (~25 shares).
        kelly_fraction = min(net_profit * 0.5, 0.25)
        current_prices = await self._get_current_prices()

        total_value = self.portfolio.total_value(current_prices)
        drawdown = 1.0 - (total_value / float(self.portfolio.initial_capital))
        if drawdown > 0.05:
            drawdown_scale = max(0.5, 1.0 - (drawdown - 0.05) / 0.10)
            kelly_fraction *= drawdown_scale

        base_size = kelly_fraction * self.max_position_size
        validated_legs: list[ValidatedLeg] = []
        reserved_cash = Decimal("0")

        for trade in opp.optimal_trades["trades"]:
            market = market_a if trade["market"] == "A" else market_b
            if not market:
                return None

            snapshot = await _get_latest_snapshot(
                session, market.id, settings.max_snapshot_age_seconds
            )
            if not snapshot:
                logger.info(
                    "stale_snapshot_skipped",
                    opportunity_id=opp.id,
                    market_id=market.id,
                )
                return None

            midpoint = trade.get("market_price", 0.5)
            fill = compute_vwap(snapshot.order_book, trade["side"], base_size, midpoint)
            trade_venue = trade.get("venue", getattr(market, "venue", "polymarket"))
            fee_bps = trade.get("fee_rate_bps", getattr(market, "fee_rate_bps", None))
            fees = (
                venue_fee(trade_venue, fill["vwap_price"], trade["side"],
                          fee_rate_bps=fee_bps)
                * fill["filled_size"]
            )

            if trade["side"] == "BUY":
                cost = (
                    Decimal(str(fill["filled_size"]))
                    * Decimal(str(fill["vwap_price"]))
                    + Decimal(str(fees))
                )
                available = self.portfolio.cash - reserved_cash
                if cost > available:
                    logger.info(
                        "insufficient_cash_for_leg",
                        opportunity_id=opp.id,
                        market_id=market.id,
                        cost=float(cost),
                        available=float(available),
                    )
                    return None
                reserved_cash += cost

            fair_price = trade.get("fair_price", 0.0)
            if fair_price > 0:
                if trade["side"] == "BUY":
                    post_vwap_edge = fair_price - fill["vwap_price"]
                else:
                    post_vwap_edge = fill["vwap_price"] - fair_price
                per_share_fee = venue_fee(trade_venue, fill["vwap_price"], trade["side"],
                                         fee_rate_bps=fee_bps)
                if post_vwap_edge - per_share_fee <= 0:
                    logger.info(
                        "edge_killed_by_slippage",
                        opportunity_id=opp.id,
                        market_id=market.id,
                        fair_price=fair_price,
                        vwap_price=fill["vwap_price"],
                        post_vwap_edge=round(post_vwap_edge, 6),
                        fee=round(per_share_fee, 6),
                    )
                    return None

            if self.circuit_breaker:
                allowed, reason = await self.circuit_breaker.pre_trade_check(
                    self.portfolio,
                    market.id,
                    fill["filled_size"],
                    trade_side=trade["side"],
                    outcome=trade["outcome"],
                    current_prices=current_prices,
                )
                if not allowed:
                    logger.warning(
                        "trade_blocked_by_circuit_breaker",
                        opportunity_id=opp.id,
                        market_id=market.id,
                        reason=reason,
                    )
                    return None

            validated_legs.append(
                ValidatedLeg(
                    market_id=market.id,
                    outcome=trade["outcome"],
                    side=trade["side"],
                    size=fill["filled_size"],
                    entry_price=midpoint,
                    vwap_price=fill["vwap_price"],
                    slippage=fill["slippage"],
                    fees=fees,
                    fair_price=fair_price,
                    trade_venue=trade_venue,
                )
            )

        if not validated_legs:
            return None

        return ValidatedExecutionBundle(
            opportunity_id=opp.id,
            pair_id=opp.pair_id,
            estimated_profit=float(opp.estimated_profit or 0),
            kelly_fraction=kelly_fraction,
            current_prices=current_prices,
            legs=validated_legs,
        )

    async def settle_resolved_markets(self) -> dict:
        """Close all positions in markets that have resolved."""
        async with self._execution_lock:
            return await self._settle_resolved_markets_inner()

    async def _settle_resolved_markets_inner(self) -> dict:
        stats = {"settled": 0, "pnl_realized": 0.0}
        if not self.portfolio.positions:
            return stats

        position_market_ids = set()
        for key in self.portfolio.positions:
            parts = key.split(":")
            if len(parts) == 2:
                position_market_ids.add(int(parts[0]))

        if not position_market_ids:
            return stats

        async with self.session_factory() as session:
            result = await session.execute(
                select(Market).where(
                    Market.resolved_outcome.isnot(None),
                    Market.id.in_(position_market_ids),
                )
            )

            for market in result.scalars().all():
                for key in list(self.portfolio.positions.keys()):
                    if not key.startswith(f"{market.id}:"):
                        continue

                    position_outcome = key.split(":")[1]
                    is_winner = position_outcome == market.resolved_outcome
                    settlement_price = 1.0 if is_winner else 0.0

                    close_result = self.portfolio.close_position(key, settlement_price)
                    if not close_result["closed"]:
                        continue

                    stats["settled"] += 1
                    stats["pnl_realized"] += close_result["pnl"]
                    if self.circuit_breaker and close_result["pnl"] < 0:
                        self.circuit_breaker.record_loss(abs(close_result["pnl"]))

                    session.add(
                        PaperTrade(
                            opportunity_id=None,
                            market_id=market.id,
                            outcome=position_outcome,
                            side="SETTLE",
                            size=Decimal(str(close_result["shares"])),
                            entry_price=Decimal(str(settlement_price)),
                            vwap_price=Decimal(str(settlement_price)),
                            slippage=Decimal("0"),
                            fees=Decimal("0"),
                            status="settled",
                            source=self.source,
                        )
                    )

            await session.commit()

        if stats["settled"] > 0:
            await self._snapshot_portfolio_inner()
            logger.info("settlement_complete", **stats)

        return stats

    async def purge_contaminated_positions(self) -> dict:
        """One-time cleanup: close ALL open positions at current market prices."""
        async with self._execution_lock:
            return await self._purge_contaminated_positions_inner()

    async def _purge_contaminated_positions_inner(self) -> dict:
        if not self.portfolio.positions:
            return {"purged": 0, "pnl_realized": 0.0}

        current_prices = await self._get_current_prices()
        stats = {
            "purged": 0,
            "pnl_realized": 0.0,
            "positions_before": len(self.portfolio.positions),
        }

        async with self.session_factory() as session:
            for key in list(self.portfolio.positions.keys()):
                parts = key.split(":")
                if len(parts) != 2:
                    continue

                market_id = int(parts[0])
                outcome = parts[1]
                price = current_prices.get(key, 0.5)

                close_result = self.portfolio.close_position(key, price)
                if not close_result["closed"]:
                    continue

                stats["purged"] += 1
                stats["pnl_realized"] += close_result["pnl"]
                session.add(
                    PaperTrade(
                        opportunity_id=None,
                        market_id=market_id,
                        outcome=outcome,
                        side="PURGE",
                        size=Decimal(str(close_result["shares"])),
                        entry_price=Decimal(str(price)),
                        vwap_price=Decimal(str(price)),
                        slippage=Decimal("0"),
                        fees=Decimal("0"),
                        status="purged",
                        source=self.source,
                    )
                )

            await session.commit()

        self.portfolio.total_trades = 0
        self.portfolio.settled_trades = 0
        self.portfolio.winning_trades = 0
        self.portfolio.realized_pnl = Decimal("0")

        await self._snapshot_portfolio_inner()

        logger.info(
            "contamination_purge_complete",
            positions_closed=stats["purged"],
            pnl_realized=stats["pnl_realized"],
            cash_after=float(self.portfolio.cash),
        )
        return stats

    async def _get_current_prices(self) -> dict[str, float]:
        """Fetch latest prices for all open positions.

        Resolved markets are priced at their settlement value (1.0 or 0.0)
        regardless of stale snapshots, so that total_value and drawdown
        calculations stay accurate even when the settlement loop hasn't
        run yet.
        """
        prices: dict[str, float] = {}
        if not self.portfolio.positions:
            return prices

        # Collect market IDs from open positions
        market_ids: set[int] = set()
        for key in self.portfolio.positions:
            parts = key.split(":")
            if len(parts) == 2:
                market_ids.add(int(parts[0]))

        if not market_ids:
            return prices

        async with self.session_factory() as session:
            # Batch-query resolved markets — use settlement price instead
            # of stale snapshots so valuation stays accurate.
            resolved: dict[int, str] = {}
            result = await session.execute(
                select(Market.id, Market.resolved_outcome).where(
                    Market.id.in_(market_ids),
                    Market.resolved_outcome.isnot(None),
                )
            )
            for mid, outcome in result.all():
                resolved[mid] = outcome

            for key in self.portfolio.positions:
                parts = key.split(":")
                if len(parts) != 2:
                    continue
                market_id = int(parts[0])
                position_outcome = parts[1]

                # Resolved market → settlement price
                if market_id in resolved:
                    prices[key] = 1.0 if position_outcome == resolved[market_id] else 0.0
                    continue

                snapshot = await _get_latest_snapshot(session, market_id)
                if snapshot and snapshot.midpoints:
                    price = snapshot.midpoints.get(position_outcome)
                    if price is not None:
                        prices[key] = float(price)
                elif snapshot and snapshot.prices:
                    price = snapshot.prices.get(position_outcome)
                    if price is not None:
                        prices[key] = float(price)
        return prices

    async def snapshot_portfolio(self) -> None:
        """Persist current portfolio state to DB (acquires execution lock)."""
        async with self._execution_lock:
            await self._snapshot_portfolio_inner()

    async def _snapshot_portfolio_inner(self) -> None:
        """Persist current portfolio state. Caller must hold _execution_lock."""
        current_prices = await self._get_current_prices()
        snap = self.portfolio.to_snapshot_dict(current_prices)

        async with self.session_factory() as session:
            session.add(
                PortfolioSnapshot(
                    cash=Decimal(str(snap["cash"])),
                    positions=snap["positions"],
                    cost_basis=snap.get("cost_basis"),
                    total_value=Decimal(str(snap["total_value"])),
                    realized_pnl=Decimal(str(snap["realized_pnl"])),
                    unrealized_pnl=Decimal(str(snap["unrealized_pnl"])),
                    total_trades=snap["total_trades"],
                    settled_trades=snap["settled_trades"],
                    winning_trades=snap["winning_trades"],
                    source=self.source,
                )
            )
            await session.commit()

        await publish(self.redis, CHANNEL_PORTFOLIO_UPDATED, snap)

    async def _revert_stale_pending(self) -> None:
        """Revert pending opportunities older than 5 minutes to optimized."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        async with self.session_factory() as session:
            result = await session.execute(
                update(ArbitrageOpportunity)
                .where(
                    ArbitrageOpportunity.status == "pending",
                    ArbitrageOpportunity.pending_at.isnot(None),
                    ArbitrageOpportunity.pending_at < cutoff,
                )
                .values(status="optimized")
                .returning(ArbitrageOpportunity.id)
            )
            reverted = result.fetchall()
            if reverted:
                await session.commit()
                logger.warning(
                    "stale_pending_reverted",
                    count=len(reverted),
                    ids=[row[0] for row in reverted],
                )

    async def process_pending(
        self,
        live_coordinator: LiveTradingCoordinator | None = None,
    ) -> dict:
        """Simulate all optimized opportunities not yet simulated."""
        stats = {"processed": 0, "simulated": 0, "skipped": 0, "errors": 0}

        try:
            await self._revert_stale_pending()
        except Exception:
            logger.exception("stale_pending_revert_error")

        # Expire stale opportunities older than 24h — they clog the batch
        # and will never have fresh enough snapshots for execution
        try:
            async with self.session_factory() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                expired = await session.execute(
                    update(ArbitrageOpportunity)
                    .where(
                        ArbitrageOpportunity.status.in_(("optimized", "unconverged")),
                        ArbitrageOpportunity.timestamp < cutoff,
                    )
                    .values(status="expired")
                    .returning(ArbitrageOpportunity.id)
                )
                expired_ids = [row[0] for row in expired.fetchall()]
                if expired_ids:
                    await session.commit()
                    logger.info("expired_stale_opps", count=len(expired_ids))
        except Exception:
            logger.exception("expire_stale_opps_error")

        async with self.session_factory() as session:
            result = await session.execute(
                select(ArbitrageOpportunity.id)
                .where(ArbitrageOpportunity.status.in_(("optimized", "unconverged")))
                .order_by(ArbitrageOpportunity.timestamp.desc())
                .limit(50)
            )
            opp_ids = [row[0] for row in result.fetchall()]

        for opp_id in opp_ids:
            try:
                result = await self.simulate_opportunity(
                    opp_id,
                    live_coordinator=live_coordinator,
                )
                stats["processed"] += 1
                if result["status"] == "simulated":
                    stats["simulated"] += 1
                else:
                    stats["skipped"] += 1
            except Exception:
                logger.exception("simulation_error", opportunity_id=opp_id)
                stats["errors"] += 1
                if self.circuit_breaker:
                    self.circuit_breaker.record_error()

        if stats["simulated"] > 0:
            await self.snapshot_portfolio()

        if stats["processed"] > 0:
            logger.info("batch_simulation_complete", **stats)

        return stats


async def _get_latest_snapshot(session, market_id: int, max_age_seconds: int = 0):
    query = (
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    if max_age_seconds > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        query = query.where(PriceSnapshot.timestamp >= cutoff)
    result = await session.execute(query)
    return result.scalar_one_or_none()
