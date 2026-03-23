from __future__ import annotations

from decimal import Decimal

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.models import PaperTrade, PortfolioSnapshot
from services.simulator.portfolio import Portfolio

logger = structlog.get_logger()


def replay_trades_into_portfolio(
    portfolio: Portfolio,
    trades: list[PaperTrade],
) -> None:
    """Rebuild cost basis from a source-filtered trade history."""
    replay_positions: dict[str, Decimal] = {}

    for trade in trades:
        key = f"{trade.market_id}:{trade.outcome}"
        size_d = Decimal(str(trade.size))
        price_d = Decimal(str(trade.vwap_price))
        fees_d = Decimal(str(trade.fees or 0))

        if trade.side in ("SETTLE", "PURGE"):
            portfolio.cost_basis.pop(key, None)
            replay_positions.pop(key, None)
        elif trade.side == "BUY":
            current = replay_positions.get(key, Decimal("0"))
            if current < 0:
                cover_size = min(size_d, abs(current))
                remainder = size_d - cover_size
                if key in portfolio.cost_basis and current != 0:
                    avg_credit = portfolio.cost_basis[key] / abs(current)
                    portfolio.cost_basis[key] -= cover_size * avg_credit
                new_pos = current + size_d
                if new_pos == 0:
                    portfolio.cost_basis.pop(key, None)
                elif new_pos > 0:
                    portfolio.cost_basis[key] = remainder * price_d
            else:
                portfolio.cost_basis[key] = portfolio.cost_basis.get(
                    key, Decimal("0")
                ) + size_d * price_d
            replay_positions[key] = replay_positions.get(key, Decimal("0")) + size_d
        elif trade.side == "SELL":
            current = replay_positions.get(key, Decimal("0"))
            if current > 0:
                close_size = min(size_d, current)
                remainder = size_d - close_size
                if key in portfolio.cost_basis and current > 0:
                    avg_entry = portfolio.cost_basis[key] / current
                    portfolio.cost_basis[key] -= close_size * avg_entry
                new_pos = current - size_d
                if new_pos == 0:
                    portfolio.cost_basis.pop(key, None)
                elif new_pos < 0:
                    proportional_short_fees = (
                        fees_d * remainder / size_d if size_d > 0 else Decimal("0")
                    )
                    portfolio.cost_basis[key] = (
                        remainder * price_d - proportional_short_fees
                    )
            elif current <= 0:
                portfolio.cost_basis[key] = portfolio.cost_basis.get(
                    key, Decimal("0")
                ) + size_d * price_d - fees_d
            replay_positions[key] = current - size_d

    for key in list(portfolio.cost_basis.keys()):
        if key not in portfolio.positions:
            del portfolio.cost_basis[key]


async def restore_portfolio(
    session_factory: async_sessionmaker,
    initial_capital: float,
    source: str = "paper",
) -> Portfolio:
    """Restore portfolio state from the latest source-specific snapshot and trades."""
    portfolio = Portfolio(initial_capital)

    async with session_factory() as session:
        latest = await session.scalar(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.source == source)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .limit(1)
        )

        if not latest:
            logger.info(
                "portfolio_fresh_start",
                source=source,
                msg="No snapshot found, starting fresh",
            )
            return portfolio

        portfolio.cash = Decimal(str(latest.cash))
        portfolio.realized_pnl = Decimal(str(latest.realized_pnl))
        portfolio.total_trades = latest.total_trades
        portfolio.settled_trades = latest.settled_trades or 0
        portfolio.winning_trades = latest.winning_trades

        if latest.positions:
            for key, shares in latest.positions.items():
                portfolio.positions[key] = Decimal(str(shares))

        trades_result = await session.execute(
            select(PaperTrade)
            .where(PaperTrade.source == source)
            .order_by(PaperTrade.executed_at)
        )
        trades = trades_result.scalars().all()
        replay_trades_into_portfolio(portfolio, trades)

        trade_count = await session.scalar(
            select(func.count()).select_from(PaperTrade).where(PaperTrade.source == source)
        )

        logger.info(
            "portfolio_restored",
            source=source,
            cash=float(portfolio.cash),
            positions=len(portfolio.positions),
            total_value=portfolio.total_value(),
            total_trades=portfolio.total_trades,
            cost_basis_entries=len(portfolio.cost_basis),
            trades_in_db=trade_count,
        )

    return portfolio
