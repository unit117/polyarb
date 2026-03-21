"""One-time script: purge all contaminated pre-fix positions.

Closes every open position at current market price, records PURGE trades,
and resets portfolio counters for a clean post-fix start.

Usage (on NAS):
    docker compose run --rm simulator python -m scripts.purge_positions
"""

import asyncio

import structlog

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import get_redis
from shared.logging import setup_logging
from services.simulator.pipeline import SimulatorPipeline
from services.simulator.main import _restore_portfolio

logger = structlog.get_logger()


async def main() -> None:
    setup_logging(settings.log_level)
    await init_db()

    redis = await get_redis()
    portfolio = await _restore_portfolio()

    logger.info(
        "pre_purge_state",
        cash=float(portfolio.cash),
        positions=len(portfolio.positions),
        realized_pnl=float(portfolio.realized_pnl),
        total_trades=portfolio.total_trades,
    )

    if not portfolio.positions:
        logger.info("nothing_to_purge", msg="No open positions found")
        return

    pipeline = SimulatorPipeline(
        session_factory=SessionFactory,
        redis=redis,
        portfolio=portfolio,
        max_position_size=settings.max_position_size,
        fee_rate=settings.fee_rate,
    )

    stats = await pipeline.purge_contaminated_positions()

    logger.info(
        "purge_complete",
        positions_closed=stats["purged"],
        pnl_written_off=stats["pnl_realized"],
        cash_after=float(portfolio.cash),
        msg="Portfolio reset — ready for clean post-fix trading",
    )


if __name__ == "__main__":
    asyncio.run(main())
