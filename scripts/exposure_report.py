"""Compute capital exposure metrics from backtest portfolio snapshots.

Reads the portfolio_snapshots table and calculates:
- Daily exposure (total_value - cash)
- Max / avg / median exposure
- Capital utilization (avg exposure / initial capital)
- Return on deployed capital (PnL / avg exposure)
- Exposure-weighted Sharpe ratio

Usage:
    # On NAS (against backtest DB):
    docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest \
        python -m scripts.exposure_report [--capital 10000]
"""

import argparse
import asyncio
import sys
from decimal import Decimal

import numpy as np
from sqlalchemy import select

sys.path.insert(0, ".")

from shared.db import SessionFactory, init_db
from shared.models import PortfolioSnapshot


async def main(initial_capital: float):
    await init_db()

    async with SessionFactory() as session:
        result = await session.execute(
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.timestamp.asc())
        )
        snapshots = result.scalars().all()

    if not snapshots:
        print("No portfolio snapshots found.")
        return

    # Compute daily exposure and metrics
    exposures = []
    daily_returns_on_exposure = []
    prev_value = initial_capital

    for snap in snapshots:
        cash = float(snap.cash)
        total_value = float(snap.total_value)
        exposure = total_value - cash
        exposures.append(exposure)

        # Daily return on exposure (for Sharpe)
        day_return = total_value - prev_value
        if exposure > 0:
            daily_returns_on_exposure.append(day_return / exposure)
        prev_value = total_value

    exposures_arr = np.array(exposures)
    nonzero_exposures = exposures_arr[exposures_arr > 0]

    final = snapshots[-1]
    first = snapshots[0]
    total_pnl = float(final.total_value) - initial_capital
    realized_pnl = float(final.realized_pnl)

    max_exposure = float(np.max(exposures_arr)) if len(exposures_arr) else 0
    avg_exposure = float(np.mean(nonzero_exposures)) if len(nonzero_exposures) else 0
    median_exposure = float(np.median(nonzero_exposures)) if len(nonzero_exposures) else 0
    days_with_exposure = int(np.sum(exposures_arr > 0))

    capital_utilization = avg_exposure / initial_capital * 100 if initial_capital else 0
    return_on_deployed = total_pnl / avg_exposure * 100 if avg_exposure > 0 else 0
    realized_on_deployed = realized_pnl / avg_exposure * 100 if avg_exposure > 0 else 0

    # Sharpe on deployed capital (annualized)
    if len(daily_returns_on_exposure) > 1:
        ret_arr = np.array(daily_returns_on_exposure)
        sharpe = float(np.mean(ret_arr) / np.std(ret_arr) * np.sqrt(365)) if np.std(ret_arr) > 0 else 0
    else:
        sharpe = 0

    period = f"{first.timestamp.strftime('%Y-%m-%d')} → {final.timestamp.strftime('%Y-%m-%d')}"

    print(f"\n{'='*60}")
    print(f"  CAPITAL EXPOSURE REPORT")
    print(f"{'='*60}")
    print(f"  Period:              {period}")
    print(f"  Days:                {len(snapshots)}")
    print(f"  Initial Capital:     ${initial_capital:,.2f}")
    print(f"  Final Value:         ${float(final.total_value):,.2f}")
    print(f"")
    print(f"  --- Return Metrics ---")
    print(f"  Total PnL:           ${total_pnl:,.2f}")
    print(f"  Return on Capital:   {total_pnl/initial_capital*100:+.2f}%")
    print(f"  Return on Deployed:  {return_on_deployed:+.2f}%")
    print(f"  Realized on Deployed:{realized_on_deployed:+.2f}%")
    print(f"")
    print(f"  --- Exposure Metrics ---")
    print(f"  Max Exposure:        ${max_exposure:,.2f}")
    print(f"  Avg Exposure:        ${avg_exposure:,.2f}")
    print(f"  Median Exposure:     ${median_exposure:,.2f}")
    print(f"  Days w/ Exposure:    {days_with_exposure} / {len(snapshots)} ({days_with_exposure/len(snapshots)*100:.0f}%)")
    print(f"  Capital Utilization: {capital_utilization:.1f}%")
    print(f"")
    print(f"  --- Risk Metrics ---")
    print(f"  Sharpe (deployed):   {sharpe:.2f}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute exposure metrics from backtest snapshots")
    parser.add_argument("--capital", type=float, default=10000, help="Initial capital (default: 10000)")
    args = parser.parse_args()
    asyncio.run(main(args.capital))
