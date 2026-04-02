from __future__ import annotations

from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.models import PaperTrade
from services.simulator.portfolio import Portfolio

logger = structlog.get_logger()


def replay_trades_into_portfolio(
    portfolio: Portfolio,
    trades: list[PaperTrade],
) -> None:
    """Rebuild cash, positions, cost basis, and counters from the trade ledger."""
    portfolio.cash = portfolio.initial_capital
    portfolio.positions = {}
    portfolio.cost_basis = {}
    portfolio.realized_pnl = Decimal("0")
    portfolio.total_trades = 0
    portfolio.winning_trades = 0
    portfolio.settled_trades = 0

    for trade in trades:
        key = f"{trade.market_id}:{trade.outcome}"
        size_d = Decimal(str(trade.size))
        price_d = Decimal(str(trade.vwap_price))
        fees_d = Decimal(str(trade.fees or 0))

        if trade.side == "SETTLE":
            if key in portfolio.positions:
                portfolio.close_position(key, float(price_d))
            else:
                portfolio.cost_basis.pop(key, None)
        elif trade.side == "PURGE":
            if key in portfolio.positions:
                portfolio.close_position(key, float(price_d))
            else:
                portfolio.cost_basis.pop(key, None)
            # PURGE establishes a new reporting baseline while preserving the
            # post-liquidation cash balance.
            portfolio.total_trades = 0
            portfolio.winning_trades = 0
            portfolio.settled_trades = 0
            portfolio.realized_pnl = Decimal("0")
        elif trade.side == "BUY":
            portfolio.execute_trade(
                market_id=trade.market_id,
                outcome=trade.outcome,
                side="BUY",
                size=float(size_d),
                vwap_price=float(price_d),
                fees=float(fees_d),
            )
        elif trade.side == "SELL":
            portfolio.execute_trade(
                market_id=trade.market_id,
                outcome=trade.outcome,
                side="SELL",
                size=float(size_d),
                vwap_price=float(price_d),
                fees=float(fees_d),
            )


async def restore_portfolio(
    session_factory: async_sessionmaker,
    initial_capital: float,
    source: str = "paper",
) -> Portfolio:
    """Restore portfolio state from the source-filtered trade ledger."""
    portfolio = Portfolio(initial_capital)

    async with session_factory() as session:
        trades_result = await session.execute(
            select(PaperTrade)
            .where(PaperTrade.source == source)
            .order_by(PaperTrade.executed_at)
        )
        trades = trades_result.scalars().all()

        if not trades:
            logger.info(
                "portfolio_fresh_start",
                source=source,
                msg="No trades found, starting fresh",
            )
            return portfolio

        replay_trades_into_portfolio(portfolio, trades)

        logger.info(
            "portfolio_restored",
            source=source,
            cash=float(portfolio.cash),
            positions=len(portfolio.positions),
            total_value=portfolio.total_value(),
            total_trades=portfolio.total_trades,
            cost_basis_entries=len(portfolio.cost_basis),
            trades_in_db=len(trades),
        )

    return portfolio
