import asyncio
from decimal import Decimal

import structlog
from sqlalchemy import select, desc, func

from shared.config import settings
from shared.circuit_breaker import CircuitBreaker
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

        # Rebuild cost basis from the FULL trade history.
        # cost_basis is not stored in the snapshot, so we must replay all
        # trades to reconstruct it.  We maintain a separate running position
        # tracker for the replay so SELL logic correctly computes the
        # pre-trade position (the snapshot positions reflect end-state and
        # must not be mixed into the replay).
        trades = await session.execute(
            select(PaperTrade).order_by(PaperTrade.executed_at)
        )
        replay_positions: dict[str, Decimal] = {}
        for t in trades.scalars().all():
            key = f"{t.market_id}:{t.outcome}"
            size_d = Decimal(str(t.size))
            price_d = Decimal(str(t.vwap_price))
            fees_d = Decimal(str(t.fees or 0))
            if t.side in ("SETTLE", "PURGE"):
                portfolio.cost_basis.pop(key, None)
                replay_positions.pop(key, None)
            elif t.side == "BUY":
                current = replay_positions.get(key, Decimal("0"))
                if current < 0:
                    # Covering a short — reduce credit-received basis
                    cover_size = min(size_d, abs(current))
                    remainder = size_d - cover_size
                    if key in portfolio.cost_basis and current != 0:
                        avg_credit = portfolio.cost_basis[key] / abs(current)
                        portfolio.cost_basis[key] -= cover_size * avg_credit
                    new_pos = current + size_d
                    if new_pos == 0:
                        portfolio.cost_basis.pop(key, None)
                    elif new_pos > 0:
                        # Flipped to long — basis is cost of the long portion
                        portfolio.cost_basis[key] = remainder * price_d
                    # else: still short, just reduced
                else:
                    # Opening/adding to a long
                    portfolio.cost_basis[key] = portfolio.cost_basis.get(
                        key, Decimal("0")
                    ) + size_d * price_d
                replay_positions[key] = replay_positions.get(key, Decimal("0")) + size_d
            elif t.side == "SELL":
                current = replay_positions.get(key, Decimal("0"))
                if current > 0:
                    # Closing/reducing a long (possibly flipping to short)
                    close_size = min(size_d, current)
                    remainder = size_d - close_size
                    if key in portfolio.cost_basis and current > 0:
                        avg_entry = portfolio.cost_basis[key] / current
                        portfolio.cost_basis[key] -= close_size * avg_entry
                    new_pos = current - size_d
                    if new_pos == 0:
                        portfolio.cost_basis.pop(key, None)
                    elif new_pos < 0:
                        # Flipped to short — basis is net credit for the short portion
                        proportional_short_fees = (
                            fees_d * remainder / size_d if size_d > 0 else Decimal("0")
                        )
                        portfolio.cost_basis[key] = (
                            remainder * price_d - proportional_short_fees
                        )
                    # else: still long, just reduced
                elif current <= 0:
                    # Opening/increasing a short — basis tracks net credit received
                    portfolio.cost_basis[key] = portfolio.cost_basis.get(
                        key, Decimal("0")
                    ) + size_d * price_d - fees_d
                replay_positions[key] = current - size_d

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

    cb = CircuitBreaker(
        redis=redis,
        max_daily_loss=settings.cb_max_daily_loss,
        max_position_per_market=settings.cb_max_position_per_market,
        max_drawdown_pct=settings.cb_max_drawdown_pct,
        max_consecutive_errors=settings.cb_max_consecutive_errors,
        cooldown_seconds=settings.cb_cooldown_seconds,
    )

    pipeline = SimulatorPipeline(
        session_factory=SessionFactory,
        redis=redis,
        portfolio=portfolio,
        max_position_size=settings.max_position_size,
        circuit_breaker=cb,
    )

    logger.info(
        "simulator_started",
        initial_capital=settings.initial_capital,
        max_position=settings.max_position_size,
        restored_cash=float(portfolio.cash),
        restored_positions=len(portfolio.positions),
        circuit_breaker="enabled",
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
            if pipeline.circuit_breaker:
                pipeline.circuit_breaker.record_error()
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
                if pipeline.circuit_breaker:
                    pipeline.circuit_breaker.record_error()


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
