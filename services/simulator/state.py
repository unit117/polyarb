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
    """Rebuild cash, positions, cost_basis, and counters from trade history.

    This is the single source of truth for portfolio state on restore.
    Every field is recomputed from the trade ledger so that trades
    recorded after the last snapshot are never lost.
    """
    portfolio.cash = portfolio.initial_capital
    portfolio.positions = {}
    portfolio.cost_basis = {}
    portfolio.realized_pnl = Decimal("0")
    portfolio.total_trades = 0
    portfolio.winning_trades = 0
    portfolio.settled_trades = 0

    pending_purge = False

    for trade in trades:
        key = f"{trade.market_id}:{trade.outcome}"
        size_d = Decimal(str(trade.size))
        price_d = Decimal(str(trade.vwap_price))
        fees_d = Decimal(str(trade.fees or 0))

        if trade.side == "PURGE":
            # PURGE rows close positions at mark-to-market.  After all
            # PURGE rows in a batch, the live code zeroes counters to
            # establish a new baseline.  We replicate that by flagging
            # the batch and resetting counters once we leave it.
            pending_purge = True
            if key in portfolio.positions:
                portfolio.close_position(key, float(price_d))
            else:
                portfolio.cost_basis.pop(key, None)
        elif trade.side == "SETTLE":
            if key in portfolio.positions:
                portfolio.close_position(key, float(price_d))
            else:
                portfolio.cost_basis.pop(key, None)
        else:
            # On the first non-PURGE trade after a purge batch, reset
            # counters so post-purge state starts from a clean baseline.
            if pending_purge:
                pending_purge = False
                portfolio.total_trades = 0
                portfolio.settled_trades = 0
                portfolio.winning_trades = 0
                portfolio.realized_pnl = Decimal("0")

            portfolio.execute_trade(
                market_id=trade.market_id,
                outcome=trade.outcome,
                side=trade.side,
                size=float(size_d),
                vwap_price=float(price_d),
                fees=float(fees_d),
            )

    # If the ledger ends with PURGE rows (no subsequent trades), still
    # apply the counter reset.
    if pending_purge:
        portfolio.total_trades = 0
        portfolio.settled_trades = 0
        portfolio.winning_trades = 0
        portfolio.realized_pnl = Decimal("0")


async def restore_portfolio(
    session_factory: async_sessionmaker,
    initial_capital: float,
    source: str = "paper",
) -> Portfolio:
    """Restore portfolio state from the latest source-specific snapshot and trades."""
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
