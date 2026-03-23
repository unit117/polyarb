"""Simulator pipeline: executes paper trades for optimized opportunities."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.events import (
    CHANNEL_TRADE_EXECUTED,
    CHANNEL_PORTFOLIO_UPDATED,
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
from shared.config import settings, venue_fee
from shared.circuit_breaker import CircuitBreaker
from services.simulator.portfolio import Portfolio
from services.simulator.vwap import compute_vwap

logger = structlog.get_logger()


class SimulatorPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        redis: aioredis.Redis,
        portfolio: Portfolio,
        max_position_size: float,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self.session_factory = session_factory
        self.redis = redis
        self.portfolio = portfolio
        self.max_position_size = max_position_size
        self.circuit_breaker = circuit_breaker
        self._in_flight: set[int] = set()  # opportunity_ids currently being processed
        self._execution_lock = asyncio.Lock()  # serialize portfolio mutations across opportunities

    async def simulate_opportunity(self, opportunity_id: int) -> dict:
        """Simulate executing trades for an optimized opportunity.

        Uses _execution_lock to serialize portfolio mutations so that
        concurrent opportunities (from periodic loop + event loop) cannot
        interleave validation and execution against stale portfolio state.
        """
        if opportunity_id in self._in_flight:
            return {"status": "skipped", "reason": "in_flight"}
        self._in_flight.add(opportunity_id)
        try:
            async with self._execution_lock:
                return await self._simulate_opportunity_inner(opportunity_id)
        finally:
            self._in_flight.discard(opportunity_id)

    async def _simulate_opportunity_inner(self, opportunity_id: int) -> dict:
        # Mark as pending in a short transaction so the detector won't
        # reset this opportunity while we're mid-execution.
        async with self.session_factory() as session:
            opp = await session.get(ArbitrageOpportunity, opportunity_id)
            if not opp:
                return {"status": "not_found"}

            if opp.status not in ("optimized", "unconverged"):
                return {"status": "skipped", "reason": opp.status}

            if not opp.optimal_trades or not opp.optimal_trades.get("trades"):
                return {"status": "no_trades"}

            opp.status = "pending"
            opp.pending_at = datetime.now(timezone.utc)
            await session.commit()

        try:
            return await self._execute_pending(opportunity_id)
        except Exception:
            # Revert pending → optimized so the opportunity isn't stranded
            logger.exception(
                "pending_execution_failed",
                opportunity_id=opportunity_id,
            )
            try:
                async with self.session_factory() as session:
                    opp = await session.get(
                        ArbitrageOpportunity, opportunity_id
                    )
                    if opp and opp.status == "pending":
                        opp.status = "optimized"
                        await session.commit()
            except Exception:
                logger.exception(
                    "pending_revert_failed",
                    opportunity_id=opportunity_id,
                )
            raise

    async def _execute_pending(self, opportunity_id: int) -> dict:
        async with self.session_factory() as session:
            opp = await session.get(ArbitrageOpportunity, opportunity_id)
            if not opp or opp.status != "pending":
                return {"status": "skipped", "reason": "status_changed"}

            pair = await session.get(MarketPair, opp.pair_id)
            if not pair:
                opp.status = "optimized"
                await session.commit()
                return {"status": "no_pair"}

            # Load markets for IDs
            market_a = await session.get(Market, pair.market_a_id)
            market_b = await session.get(Market, pair.market_b_id)

            trades_executed = 0
            total_pnl = Decimal("0")
            deferred_trade_events: list[dict] = []

            # Half-Kelly position sizing using the optimizer's edge estimate.
            # kelly_fraction = (edge / max_loss) * 0.5, where max_loss ≈ 1
            # (binary market: you lose your full stake in the worst case).
            net_profit = opp.optimal_trades.get("estimated_profit", 0)
            if net_profit <= 0:
                opp.status = "optimized"
                await session.commit()
                return {"status": "no_trades"}
            kelly_fraction = min(net_profit * 0.5, 1.0)

            # Fetch current prices so drawdown includes position value
            current_prices = await self._get_current_prices()

            # Scale down when portfolio is in drawdown
            total_value = self.portfolio.total_value(current_prices)
            drawdown = 1.0 - (total_value / float(self.portfolio.initial_capital))
            if drawdown > 0.05:
                # Linear scale-down: at 5% drawdown → 100%, at 10%+ → 50%
                drawdown_scale = max(0.5, 1.0 - (drawdown - 0.05) / 0.10)
                kelly_fraction *= drawdown_scale

            base_size = kelly_fraction * self.max_position_size

            # --- Pass 1: validate all legs (VWAP, edge, breaker) ---
            # Arb requires both legs; if any leg fails, skip the whole
            # opportunity to avoid one-sided exposure.
            validated_legs: list[dict] = []
            all_legs_valid = True
            reserved_cash = Decimal("0")  # Track cash reserved by earlier BUY legs

            for trade in opp.optimal_trades["trades"]:
                market = market_a if trade["market"] == "A" else market_b
                if not market:
                    all_legs_valid = False
                    break

                # Get order book for VWAP — skip if snapshot is stale
                snapshot = await _get_latest_snapshot(
                    session, market.id, settings.max_snapshot_age_seconds
                )
                if not snapshot:
                    logger.info(
                        "stale_snapshot_skipped",
                        opportunity_id=opp.id,
                        market_id=market.id,
                    )
                    all_legs_valid = False
                    break
                order_book = snapshot.order_book
                midpoint = trade.get("market_price", 0.5)

                size = base_size
                fill = compute_vwap(order_book, trade["side"], size, midpoint)

                trade_venue = trade.get("venue", getattr(market, "venue", "polymarket"))
                fees = venue_fee(trade_venue, fill["vwap_price"], trade["side"]) * fill["filled_size"]

                # Cash reservation: ensure BUY legs won't starve each other
                if trade["side"] == "BUY":
                    cost = Decimal(str(fill["filled_size"])) * Decimal(str(fill["vwap_price"])) + Decimal(str(fees))
                    available = self.portfolio.cash - reserved_cash
                    if cost > available:
                        logger.info(
                            "insufficient_cash_for_leg",
                            opportunity_id=opp.id,
                            market_id=market.id,
                            cost=float(cost),
                            available=float(available),
                        )
                        all_legs_valid = False
                        break
                    reserved_cash += cost

                # Post-VWAP edge validation: check the edge survived slippage.
                fair_price = trade.get("fair_price", 0.0)
                if fair_price > 0:
                    if trade["side"] == "BUY":
                        post_vwap_edge = fair_price - fill["vwap_price"]
                    else:
                        post_vwap_edge = fill["vwap_price"] - fair_price
                    per_share_fee = venue_fee(trade_venue, fill["vwap_price"], trade["side"])
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
                        all_legs_valid = False
                        break

                # Circuit breaker gate
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
                        all_legs_valid = False
                        break

                validated_legs.append({
                    "trade": trade,
                    "market": market,
                    "fill": fill,
                    "fees": fees,
                    "trade_venue": trade_venue,
                    "midpoint": midpoint,
                })

            if not all_legs_valid or not validated_legs:
                opp.status = "optimized"
                await session.commit()
                logger.info(
                    "simulation_complete",
                    opportunity_id=opp.id,
                    trades_executed=0,
                    cash_remaining=float(self.portfolio.cash),
                )
                return {
                    "status": "blocked",
                    "trades_executed": 0,
                    "cash_remaining": float(self.portfolio.cash),
                }

            # --- Pass 2: execute all validated legs ---
            for leg in validated_legs:
                trade = leg["trade"]
                market = leg["market"]
                fill = leg["fill"]
                fees = leg["fees"]
                trade_venue = leg["trade_venue"]
                midpoint = leg["midpoint"]

                # Track rebalancing exit PNL before executing
                key = f"{market.id}:{trade['outcome']}"
                existing_position = self.portfolio.positions.get(key, Decimal("0"))
                is_exit = (
                    (trade["side"] == "SELL" and existing_position > 0)
                    or (trade["side"] == "BUY" and existing_position < 0)
                )

                # Capture cost basis BEFORE execute_trade modifies it
                pre_trade_cost = self.portfolio.cost_basis.get(key, Decimal("0"))

                # Execute on portfolio
                result = self.portfolio.execute_trade(
                    market_id=market.id,
                    outcome=trade["outcome"],
                    side=trade["side"],
                    size=fill["filled_size"],
                    vwap_price=fill["vwap_price"],
                    fees=fees,
                )

                # Realize PNL for the portion that closed an existing position
                if is_exit and existing_position != 0 and result["executed"]:
                    close_size = min(
                        abs(existing_position), Decimal(str(fill["filled_size"]))
                    )
                    avg_entry = pre_trade_cost / abs(existing_position)
                    exit_price = Decimal(str(fill["vwap_price"]))

                    # Subtract exit fees proportional to close size
                    exit_fees = Decimal(str(fees)) * close_size / Decimal(str(fill["filled_size"])) if fill["filled_size"] > 0 else Decimal("0")

                    if existing_position > 0:
                        realized = (exit_price - avg_entry) * close_size - exit_fees
                    else:
                        realized = (avg_entry - exit_price) * close_size - exit_fees

                    self.portfolio.realized_pnl += realized

                    # Feed realized losses into circuit breaker daily tracker
                    if self.circuit_breaker and realized < 0:
                        self.circuit_breaker.record_loss(float(abs(realized)))

                if not result["executed"]:
                    continue

                # Persist paper trade
                paper_trade = PaperTrade(
                    opportunity_id=opp.id,
                    market_id=market.id,
                    outcome=trade["outcome"],
                    side=trade["side"],
                    size=Decimal(str(fill["filled_size"])),
                    entry_price=Decimal(str(midpoint)),
                    vwap_price=Decimal(str(fill["vwap_price"])),
                    slippage=Decimal(str(fill["slippage"])),
                    fees=Decimal(str(fees)),
                    status="filled",
                    venue=trade_venue,
                )
                session.add(paper_trade)
                await session.flush()  # Assign PK before capturing trade_id
                trades_executed += 1

                deferred_trade_events.append({
                    "trade_id": paper_trade.id,
                    "opportunity_id": opp.id,
                    "market_id": market.id,
                    "outcome": trade["outcome"],
                    "side": trade["side"],
                    "size": fill["filled_size"],
                    "vwap_price": fill["vwap_price"],
                    "slippage": fill["slippage"],
                })

            # Mark simulated if trades executed; revert to optimized
            # if all were blocked so it can be retried after cooldown.
            if trades_executed > 0:
                opp.status = "simulated"
            else:
                opp.status = "optimized"
            await session.commit()

            # Publish trade events after commit so subscribers
            # can read the rows from DB.
            for event in deferred_trade_events:
                await publish(self.redis, CHANNEL_TRADE_EXECUTED, event)

            # Record success/loss on circuit breaker
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

    async def settle_resolved_markets(self) -> dict:
        """Close all positions in markets that have resolved."""
        async with self._execution_lock:
            return await self._settle_resolved_markets_inner()

    async def _settle_resolved_markets_inner(self) -> dict:
        stats = {"settled": 0, "pnl_realized": 0.0}

        if not self.portfolio.positions:
            return stats

        # Collect market IDs from open positions
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

                    # Feed settlement losses into circuit breaker
                    if self.circuit_breaker and close_result["pnl"] < 0:
                        self.circuit_breaker.record_loss(abs(close_result["pnl"]))

                    paper_trade = PaperTrade(
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
                    )
                    session.add(paper_trade)

            await session.commit()

        if stats["settled"] > 0:
            await self._snapshot_portfolio_inner()
            logger.info("settlement_complete", **stats)

        return stats

    async def purge_contaminated_positions(self) -> dict:
        """One-time cleanup: close ALL open positions at current market prices.

        Used after fixing classification bugs to give the portfolio a clean start.
        Records PURGE trades for auditability, then resets counters.
        """
        async with self._execution_lock:
            return await self._purge_contaminated_positions_inner()

    async def _purge_contaminated_positions_inner(self) -> dict:
        if not self.portfolio.positions:
            return {"purged": 0, "pnl_realized": 0.0}

        current_prices = await self._get_current_prices()
        stats = {"purged": 0, "pnl_realized": 0.0, "positions_before": len(self.portfolio.positions)}

        async with self.session_factory() as session:
            for key in list(self.portfolio.positions.keys()):
                parts = key.split(":")
                if len(parts) != 2:
                    continue

                market_id = int(parts[0])
                outcome = parts[1]

                # Use current market price, fall back to 0.5 if unknown
                price = current_prices.get(key, 0.5)
                shares = self.portfolio.positions[key]

                close_result = self.portfolio.close_position(key, price)
                if not close_result["closed"]:
                    continue

                stats["purged"] += 1
                stats["pnl_realized"] += close_result["pnl"]

                # Record a PURGE trade for audit trail
                paper_trade = PaperTrade(
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
                )
                session.add(paper_trade)

            await session.commit()

        # Reset win/loss counters so post-fix metrics are clean
        self.portfolio.total_trades = 0
        self.portfolio.settled_trades = 0
        self.portfolio.winning_trades = 0
        self.portfolio.realized_pnl = Decimal("0")

        # Snapshot the clean state
        await self._snapshot_portfolio_inner()

        logger.info(
            "contamination_purge_complete",
            positions_closed=stats["purged"],
            pnl_realized=stats["pnl_realized"],
            cash_after=float(self.portfolio.cash),
        )

        return stats

    async def _get_current_prices(self) -> dict[str, float]:
        """Fetch latest prices for all open positions."""
        prices: dict[str, float] = {}
        if not self.portfolio.positions:
            return prices

        async with self.session_factory() as session:
            for key in self.portfolio.positions:
                parts = key.split(":")
                if len(parts) != 2:
                    continue
                market_id = int(parts[0])
                outcome = parts[1]
                snapshot = await _get_latest_snapshot(session, market_id)
                if snapshot and snapshot.midpoints:
                    # midpoints is a dict of outcome -> price
                    price = snapshot.midpoints.get(outcome)
                    if price is not None:
                        prices[key] = float(price)
                elif snapshot and snapshot.prices:
                    price = snapshot.prices.get(outcome)
                    if price is not None:
                        prices[key] = float(price)
        return prices

    async def snapshot_portfolio(self) -> None:
        """Persist current portfolio state to DB (acquires execution lock)."""
        async with self._execution_lock:
            await self._snapshot_portfolio_inner()

    async def _snapshot_portfolio_inner(self) -> None:
        """Persist current portfolio state — caller must hold _execution_lock."""
        current_prices = await self._get_current_prices()
        snap = self.portfolio.to_snapshot_dict(current_prices)

        async with self.session_factory() as session:
            ps = PortfolioSnapshot(
                cash=Decimal(str(snap["cash"])),
                positions=snap["positions"],
                total_value=Decimal(str(snap["total_value"])),
                realized_pnl=Decimal(str(snap["realized_pnl"])),
                unrealized_pnl=Decimal(str(snap["unrealized_pnl"])),
                total_trades=snap["total_trades"],
                settled_trades=snap["settled_trades"],
                winning_trades=snap["winning_trades"],
            )
            session.add(ps)
            await session.commit()

        await publish(
            self.redis,
            CHANNEL_PORTFOLIO_UPDATED,
            snap,
        )

    async def _revert_stale_pending(self) -> None:
        """Revert pending opportunities older than 5 minutes to optimized.

        Safety valve for the rare case where the simulator's exception
        handler fails to revert pending status (e.g., transient DB error).
        Without this, the pair is permanently blocked by the unique index.
        Uses pending_at (when the row entered pending) rather than timestamp
        (opportunity creation time) to avoid sweeping mid-execution opps.
        """
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
                    ids=[r[0] for r in reverted],
                )

    async def process_pending(self) -> dict:
        """Simulate all optimized opportunities not yet simulated."""
        stats = {"processed": 0, "simulated": 0, "skipped": 0, "errors": 0}

        # Safety valve: revert any pending opportunities older than 5 min.
        # These are stranded from a failed execution whose DB revert also
        # failed (e.g., transient DB error during exception handler).
        try:
            await self._revert_stale_pending()
        except Exception:
            logger.exception("stale_pending_revert_error")

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
                result = await self.simulate_opportunity(opp_id)
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

        # Snapshot portfolio after batch
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
