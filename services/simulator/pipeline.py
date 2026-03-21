"""Simulator pipeline: executes paper trades for optimized opportunities."""

from decimal import Decimal

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
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
        fee_rate: float,
    ):
        self.session_factory = session_factory
        self.redis = redis
        self.portfolio = portfolio
        self.max_position_size = max_position_size
        self.fee_rate = fee_rate

    async def simulate_opportunity(self, opportunity_id: int) -> dict:
        """Simulate executing trades for an optimized opportunity."""
        async with self.session_factory() as session:
            opp = await session.get(ArbitrageOpportunity, opportunity_id)
            if not opp:
                return {"status": "not_found"}

            if opp.status not in ("optimized", "unconverged"):
                return {"status": "skipped", "reason": opp.status}

            if not opp.optimal_trades or not opp.optimal_trades.get("trades"):
                return {"status": "no_trades"}

            pair = await session.get(MarketPair, opp.pair_id)
            if not pair:
                return {"status": "no_pair"}

            # Load markets for IDs
            market_a = await session.get(Market, pair.market_a_id)
            market_b = await session.get(Market, pair.market_b_id)

            trades_executed = 0
            total_pnl = Decimal("0")

            # Compute base position size from net estimated profit.
            # A 0.10 net profit (after fees) → full max_position_size.
            # Scale linearly below that, with a floor of 0.
            net_profit = opp.optimal_trades.get("estimated_profit", 0)
            if net_profit <= 0:
                return {"status": "no_trades"}
            profit_ratio = min(net_profit / 0.10, 1.0)
            base_size = profit_ratio * self.max_position_size

            for trade in opp.optimal_trades["trades"]:
                market = market_a if trade["market"] == "A" else market_b
                if not market:
                    continue

                # Get order book for VWAP
                snapshot = await _get_latest_snapshot(session, market.id)
                order_book = snapshot.order_book if snapshot else None
                midpoint = trade.get("market_price", 0.5)

                size = base_size
                fill = compute_vwap(order_book, trade["side"], size, midpoint)

                fees = fill["vwap_price"] * fill["filled_size"] * self.fee_rate

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

                    if existing_position > 0:
                        realized = (exit_price - avg_entry) * close_size
                    else:
                        realized = (avg_entry - exit_price) * close_size

                    self.portfolio.realized_pnl += realized
                    self.portfolio.mark_settled(is_winner=realized > 0)

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
                )
                session.add(paper_trade)
                trades_executed += 1

                await publish(
                    self.redis,
                    CHANNEL_TRADE_EXECUTED,
                    {
                        "trade_id": paper_trade.id,
                        "opportunity_id": opp.id,
                        "market_id": market.id,
                        "outcome": trade["outcome"],
                        "side": trade["side"],
                        "size": fill["filled_size"],
                        "vwap_price": fill["vwap_price"],
                        "slippage": fill["slippage"],
                    },
                )

            # Update opportunity status
            opp.status = "simulated"
            await session.commit()

            logger.info(
                "simulation_complete",
                opportunity_id=opp.id,
                trades_executed=trades_executed,
                cash_remaining=float(self.portfolio.cash),
            )

            return {
                "status": "simulated",
                "trades_executed": trades_executed,
                "cash_remaining": float(self.portfolio.cash),
            }

    async def settle_resolved_markets(self) -> dict:
        """Close all positions in markets that have resolved."""
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
            await self.snapshot_portfolio()
            logger.info("settlement_complete", **stats)

        return stats

    async def purge_contaminated_positions(self) -> dict:
        """One-time cleanup: close ALL open positions at current market prices.

        Used after fixing classification bugs to give the portfolio a clean start.
        Records PURGE trades for auditability, then resets counters.
        """
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
        await self.snapshot_portfolio()

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
        """Persist current portfolio state to DB."""
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

    async def process_pending(self) -> dict:
        """Simulate all optimized opportunities not yet simulated."""
        stats = {"processed": 0, "simulated": 0, "skipped": 0, "errors": 0}

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

        # Snapshot portfolio after batch
        if stats["simulated"] > 0:
            await self.snapshot_portfolio()

        if stats["processed"] > 0:
            logger.info("batch_simulation_complete", **stats)

        return stats


async def _get_latest_snapshot(session, market_id: int):
    result = await session.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
