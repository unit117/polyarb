import asyncio
from decimal import Decimal

import structlog
from sqlalchemy import select, desc, func

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import (
    get_redis,
    subscribe,
    CHANNEL_OPTIMIZATION_COMPLETE,
    CHANNEL_MARKET_RESOLVED,
)
from shared.logging import setup_logging
from shared.models import PortfolioSnapshot, PaperTrade
from services.simulator.pipeline import SimulatorPipeline
from services.simulator.portfolio import Portfolio

logger = structlog.get_logger()


async def _restore_portfolio() -> Portfolio:
    """Restore portfolio state from the latest DB snapshot + trade history."""
    portfolio = Portfolio(settings.initial_capital)

    async with SessionFactory() as session:
        # Get latest snapshot
        latest = await session.scalar(
            select(PortfolioSnapshot)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .limit(1)
        )

        if not latest:
            logger.info("portfolio_fresh_start", msg="No snapshot found, starting fresh")
            return portfolio

        # Restore cash and counters
        portfolio.cash = Decimal(str(latest.cash))
        portfolio.realized_pnl = Decimal(str(latest.realized_pnl))
        portfolio.total_trades = latest.total_trades
        portfolio.settled_trades = latest.settled_trades or 0
        portfolio.winning_trades = latest.winning_trades

        # Restore positions from snapshot
        if latest.positions:
            for key, shares in latest.positions.items():
                portfolio.positions[key] = Decimal(str(shares))

        # Rebuild cost basis from trade history
        trades = await session.execute(
            select(PaperTrade).order_by(PaperTrade.executed_at)
        )
        for t in trades.scalars().all():
            key = f"{t.market_id}:{t.outcome}"
            if t.side in ("SETTLE", "PURGE"):
                # Settlement/purge trades already closed the position
                portfolio.cost_basis.pop(key, None)
            elif t.side == "BUY":
                portfolio.cost_basis[key] = portfolio.cost_basis.get(
                    key, Decimal("0")
                ) + Decimal(str(t.size)) * Decimal(str(t.vwap_price))
            elif t.side == "SELL" and key in portfolio.cost_basis:
                # Proportionally reduce cost basis
                pos = portfolio.positions.get(key, Decimal("0")) + Decimal(str(t.size))
                if pos > 0:
                    avg = portfolio.cost_basis[key] / pos
                    portfolio.cost_basis[key] -= Decimal(str(t.size)) * avg

        # Clean up cost basis for positions that no longer exist
        for key in list(portfolio.cost_basis.keys()):
            if key not in portfolio.positions:
                del portfolio.cost_basis[key]

        trade_count = await session.scalar(
            select(func.count()).select_from(PaperTrade)
        )

        logger.info(
            "portfolio_restored",
            cash=float(portfolio.cash),
            positions=len(portfolio.positions),
            total_value=portfolio.total_value(),
            total_trades=portfolio.total_trades,
            cost_basis_entries=len(portfolio.cost_basis),
            trades_in_db=trade_count,
        )

    return portfolio


async def main() -> None:
    setup_logging(settings.log_level)

    await init_db()

    redis = await get_redis()
    portfolio = await _restore_portfolio()

    pipeline = SimulatorPipeline(
        session_factory=SessionFactory,
        redis=redis,
        portfolio=portfolio,
        max_position_size=settings.max_position_size,
        fee_rate=settings.fee_rate,
    )

    logger.info(
        "simulator_started",
        initial_capital=settings.initial_capital,
        max_position=settings.max_position_size,
        fee_rate=settings.fee_rate,
        restored_cash=float(portfolio.cash),
        restored_positions=len(portfolio.positions),
    )

    # Create an initial snapshot with current prices after restore
    try:
        await pipeline.snapshot_portfolio()
        logger.info("initial_snapshot_created")
    except Exception:
        logger.exception("initial_snapshot_error")

    await asyncio.gather(
        _periodic_loop(pipeline, settings.simulator_interval_seconds),
        _snapshot_loop(pipeline),
        _event_loop(pipeline, redis),
        _settlement_loop(pipeline, settings.settlement_interval_seconds),
        _resolution_event_loop(pipeline, redis),
    )


async def _periodic_loop(pipeline: SimulatorPipeline, interval: int) -> None:
    while True:
        try:
            await pipeline.process_pending()
        except Exception:
            logger.exception("periodic_simulation_error")
        await asyncio.sleep(interval)


async def _snapshot_loop(pipeline: SimulatorPipeline) -> None:
    """Periodically snapshot portfolio to keep unrealized PnL fresh."""
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        try:
            await pipeline.snapshot_portfolio()
        except Exception:
            logger.exception("snapshot_loop_error")


async def _event_loop(pipeline: SimulatorPipeline, redis) -> None:
    async for event in subscribe(redis, CHANNEL_OPTIMIZATION_COMPLETE):
        opp_id = event.get("opportunity_id")
        if opp_id:
            logger.info("triggered_by_optimization", opportunity_id=opp_id)
            try:
                await pipeline.simulate_opportunity(opp_id)
                await pipeline.snapshot_portfolio()
            except Exception:
                logger.exception("event_simulation_error", opportunity_id=opp_id)


async def _settlement_loop(pipeline: SimulatorPipeline, interval: int) -> None:
    """Periodically check for resolved markets and settle positions."""
    while True:
        try:
            await pipeline.settle_resolved_markets()
        except Exception:
            logger.exception("settlement_loop_error")
        await asyncio.sleep(interval)


async def _resolution_event_loop(pipeline: SimulatorPipeline, redis) -> None:
    """Immediately settle when a market resolution event is received."""
    async for event in subscribe(redis, CHANNEL_MARKET_RESOLVED):
        market_id = event.get("market_id")
        if market_id:
            logger.info("triggered_by_resolution", market_id=market_id)
            try:
                await pipeline.settle_resolved_markets()
            except Exception:
                logger.exception("resolution_settlement_error", market_id=market_id)


if __name__ == "__main__":
    asyncio.run(main())
