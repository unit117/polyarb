"""One-shot purge: close all contaminated positions and reset counters."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import get_redis
from services.simulator.pipeline import SimulatorPipeline
from services.simulator.main import _restore_portfolio


async def main():
    await init_db()
    redis = await get_redis()
    portfolio = await _restore_portfolio()

    print(f"Before purge:")
    print(f"  Cash: ${float(portfolio.cash):,.2f}")
    print(f"  Positions: {len(portfolio.positions)}")
    print(f"  Realized PnL: ${float(portfolio.realized_pnl):,.2f}")
    print(f"  Total trades: {portfolio.total_trades}")
    print(f"  Settled trades: {portfolio.settled_trades}")
    print(f"  Winning trades: {portfolio.winning_trades}")

    pipeline = SimulatorPipeline(
        session_factory=SessionFactory,
        redis=redis,
        portfolio=portfolio,
        max_position_size=settings.max_position_size,
        fee_rate=settings.fee_rate,
    )

    result = await pipeline.purge_contaminated_positions()

    print(f"\nPurge complete:")
    print(f"  Positions closed: {result['purged']}")
    print(f"  PnL realized: ${result['pnl_realized']:,.2f}")
    print(f"\nAfter purge (counters reset):")
    print(f"  Cash: ${float(portfolio.cash):,.2f}")
    print(f"  Positions: {len(portfolio.positions)}")
    print(f"  Realized PnL: ${float(portfolio.realized_pnl):,.2f}")
    print(f"  Total trades: {portfolio.total_trades}")
    print(f"  Settled trades: {portfolio.settled_trades}")


if __name__ == "__main__":
    asyncio.run(main())
