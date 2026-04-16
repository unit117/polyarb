"""Simulator pipeline: orchestrates paper trade execution for optimized opportunities."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.circuit_breaker import CircuitBreaker
from shared.config import settings
from shared.events import (
    CHANNEL_PORTFOLIO_UPDATED,
    CHANNEL_TRADE_EXECUTED,
    publish_event,
)
from shared.schemas import PortfolioUpdatedEvent, TradeExecutedEvent
from shared.lifecycle import OppStatus, TradeStatus, bulk_transition_values, transition
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PaperTrade,
    PortfolioSnapshot,
    PriceSnapshot,
)
from services.simulator.portfolio import Portfolio
from services.simulator.validation import (
    ValidatedExecutionBundle,
    ValidatedLeg,
    build_validated_bundle,
)
from shared.pricing import get_latest_snapshot
from services.simulator.settlement import (
    settle_resolved_markets as _settle_resolved,
    purge_contaminated_positions as _purge_positions,
)

if TYPE_CHECKING:
    from services.simulator.live_coordinator import LiveTradingCoordinator

logger = structlog.get_logger()


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

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

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

            if opp.status not in (OppStatus.OPTIMIZED, OppStatus.UNCONVERGED):
                return {"status": "skipped", "reason": opp.status}

            if not opp.optimal_trades or not opp.optimal_trades.get("trades", []):
                transition(opp, OppStatus.EXPIRED)
                self._retry_counts.pop(opp.id, None)
                await session.commit()
                logger.info("expired_empty_trades", opportunity_id=opp.id)
                return {"status": "expired", "reason": "no_trades"}

            transition(opp, OppStatus.PENDING)
            await session.commit()

        try:
            return await self._execute_pending(
                opportunity_id, live_coordinator=live_coordinator,
            )
        except Exception:
            logger.exception("pending_execution_failed", opportunity_id=opportunity_id)
            try:
                async with self.session_factory() as session:
                    opp = await session.get(ArbitrageOpportunity, opportunity_id)
                    if opp and opp.status == OppStatus.PENDING:
                        transition(opp, OppStatus.OPTIMIZED)
                        await session.commit()
            except Exception:
                logger.exception("pending_revert_failed", opportunity_id=opportunity_id)
            raise

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_pending(
        self,
        opportunity_id: int,
        live_coordinator: LiveTradingCoordinator | None = None,
    ) -> dict:
        async with self.session_factory() as session:
            opp = await session.get(ArbitrageOpportunity, opportunity_id)
            if not opp or opp.status != OppStatus.PENDING:
                return {"status": "skipped", "reason": "status_changed"}

            pair = await session.get(MarketPair, opp.pair_id)
            if not pair:
                transition(opp, OppStatus.OPTIMIZED)
                await session.commit()
                return {"status": "no_pair"}

            market_a = await session.get(Market, pair.market_a_id)
            market_b = await session.get(Market, pair.market_b_id)

            current_prices = await self._get_current_prices()
            bundle = await build_validated_bundle(
                session, opp, market_a, market_b,
                portfolio=self.portfolio,
                max_position_size=self.max_position_size,
                circuit_breaker=self.circuit_breaker,
                current_prices=current_prices,
            )
            if not bundle or not bundle.legs:
                return await self._handle_blocked(session, opp, market_a, market_b)

            trades_executed = 0
            deferred_trade_events: list[TradeExecutedEvent] = []
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
                    status=TradeStatus.FILLED,
                    source=self.source,
                    venue=leg.trade_venue,
                )
                session.add(paper_trade)
                await session.flush()
                trades_executed += 1

                deferred_trade_events.append(TradeExecutedEvent(
                    trade_id=paper_trade.id,
                    opportunity_id=opp.id,
                    market_id=leg.market_id,
                    outcome=leg.outcome,
                    side=leg.side,
                    size=leg.size,
                    vwap_price=leg.vwap_price,
                    slippage=leg.slippage,
                ))

            if trades_executed > 0:
                transition(opp, OppStatus.SIMULATED)
                self._retry_counts.pop(opp.id, None)
            else:
                transition(opp, OppStatus.OPTIMIZED)
            await session.commit()

            for event in deferred_trade_events:
                await publish_event(self.redis, CHANNEL_TRADE_EXECUTED, event)

            if live_coordinator and trades_executed > 0:
                try:
                    await live_coordinator.submit_validated_bundle(bundle)
                except Exception:
                    logger.exception("live_submission_error", opportunity_id=opp.id)

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

    async def _handle_blocked(self, session, opp, market_a, market_b) -> dict:
        """Handle validation failure: expire or retry based on market state."""
        either_resolved = any(
            m and m.resolved_outcome is not None
            for m in (market_a, market_b)
        )
        if either_resolved:
            transition(opp, OppStatus.EXPIRED)
            self._retry_counts.pop(opp.id, None)
        else:
            retries = self._retry_counts.get(opp.id, 0) + 1
            self._retry_counts[opp.id] = retries
            if retries >= self._max_retries:
                transition(opp, OppStatus.EXPIRED)
                self._retry_counts.pop(opp.id, None)
                logger.warning(
                    "expired_max_retries",
                    opportunity_id=opp.id,
                    retries=retries,
                )
            else:
                transition(opp, OppStatus.OPTIMIZED)
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

    # ------------------------------------------------------------------
    # Settlement (delegates to settlement module)
    # ------------------------------------------------------------------

    async def settle_resolved_markets(self) -> dict:
        """Close all positions in markets that have resolved."""
        async with self._execution_lock:
            stats = await _settle_resolved(
                self.session_factory, self.portfolio,
                self.circuit_breaker, self.source,
            )
            if stats["settled"] > 0:
                await self._snapshot_portfolio_inner()
            return stats

    async def purge_contaminated_positions(self) -> dict:
        """One-time cleanup: close ALL open positions at current market prices."""
        async with self._execution_lock:
            current_prices = await self._get_current_prices()
            stats = await _purge_positions(
                self.session_factory, self.portfolio,
                self.source, current_prices,
            )
            await self._snapshot_portfolio_inner()
            return stats

    # ------------------------------------------------------------------
    # Portfolio snapshots & pricing
    # ------------------------------------------------------------------

    async def _get_current_prices(self) -> dict[str, float]:
        """Fetch latest prices for all open positions.

        Resolved markets are priced at their settlement value (1.0 or 0.0)
        regardless of stale snapshots.
        """
        prices: dict[str, float] = {}
        if not self.portfolio.positions:
            return prices

        market_ids: set[int] = set()
        for key in self.portfolio.positions:
            parts = key.split(":")
            if len(parts) == 2:
                market_ids.add(int(parts[0]))

        if not market_ids:
            return prices

        async with self.session_factory() as session:
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

                if market_id in resolved:
                    prices[key] = 1.0 if position_outcome == resolved[market_id] else 0.0
                    continue

                snapshot = await get_latest_snapshot(session, market_id)
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

        await publish_event(
            self.redis,
            CHANNEL_PORTFOLIO_UPDATED,
            PortfolioUpdatedEvent.model_validate(snap),
        )

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    async def _revert_stale_pending(self) -> None:
        """Revert pending opportunities older than 5 minutes to optimized."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        async with self.session_factory() as session:
            result = await session.execute(
                update(ArbitrageOpportunity)
                .where(
                    ArbitrageOpportunity.status == OppStatus.PENDING,
                    ArbitrageOpportunity.pending_at.isnot(None),
                    ArbitrageOpportunity.pending_at < cutoff,
                )
                .values(**bulk_transition_values(OppStatus.PENDING, OppStatus.OPTIMIZED))
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

        # Expire stale opportunities older than 24h
        try:
            async with self.session_factory() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                expired = await session.execute(
                    update(ArbitrageOpportunity)
                    .where(
                        ArbitrageOpportunity.status.in_((OppStatus.OPTIMIZED, OppStatus.UNCONVERGED)),
                        ArbitrageOpportunity.timestamp < cutoff,
                    )
                    .values(**bulk_transition_values(OppStatus.OPTIMIZED, OppStatus.EXPIRED))
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
                .where(ArbitrageOpportunity.status.in_((OppStatus.OPTIMIZED, OppStatus.UNCONVERGED)))
                .order_by(ArbitrageOpportunity.timestamp.desc())
                .limit(50)
            )
            opp_ids = [row[0] for row in result.fetchall()]

        for opp_id in opp_ids:
            try:
                result = await self.simulate_opportunity(
                    opp_id, live_coordinator=live_coordinator,
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
