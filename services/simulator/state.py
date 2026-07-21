from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.config import settings
from shared.models import ArbitrageOpportunity, PaperTrade
from services.simulator.portfolio import Portfolio

logger = structlog.get_logger()


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


def replay_trades_into_portfolio(
    portfolio: Portfolio,
    trades: list[PaperTrade],
    pair_map: dict[int, int] | None = None,
    flow_window_start: datetime | None = None,
) -> None:
    """Rebuild cash, positions, cost basis, and counters from the trade ledger.

    When pair_map (opportunity_id -> pair_id) is given, exposure-opening
    BUY/SELL trades newer than flow_window_start also rebuild the per-pair
    flow ledger backing the concentration cap.
    """
    portfolio.cash = portfolio.initial_capital
    portfolio.positions = {}
    portfolio.cost_basis = {}
    portfolio.realized_pnl = Decimal("0")
    portfolio.total_trades = 0
    portfolio.winning_trades = 0
    portfolio.settled_trades = 0
    portfolio.pair_entry_flow = {}

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
        elif trade.side in ("BUY", "SELL"):
            # Mirror the live pipeline's exit accounting: a SELL closing a
            # long (or a BUY covering a short) realizes PnL against the
            # pre-trade cost basis. execute_trade() itself never touches
            # realized_pnl, so without this every restart silently dropped
            # all exit PnL accumulated since the last SETTLE/PURGE.
            pre_position = portfolio.positions.get(key, Decimal("0"))
            pre_cost = portfolio.cost_basis.get(key, Decimal("0"))
            is_exit = (
                (trade.side == "SELL" and pre_position > 0)
                or (trade.side == "BUY" and pre_position < 0)
            )

            result = portfolio.execute_trade(
                market_id=trade.market_id,
                outcome=trade.outcome,
                side=trade.side,
                size=float(size_d),
                vwap_price=float(price_d),
                fees=float(fees_d),
            )

            if (
                not is_exit
                and result["executed"]
                and pair_map is not None
                and trade.opportunity_id is not None
                and (flow_window_start is None or _aware(trade.executed_at) >= flow_window_start)
            ):
                portfolio.record_pair_entry(
                    pair_map.get(trade.opportunity_id),
                    Decimal(str(result["size"])) * price_d,
                    at=_aware(trade.executed_at),
                )

            if is_exit and pre_position != 0 and result["executed"]:
                actual_size = Decimal(str(result["size"]))
                close_size = min(abs(pre_position), actual_size)
                if close_size > 0:
                    avg_entry = pre_cost / abs(pre_position)
                    exit_fees = fees_d * close_size / actual_size
                    if pre_position > 0:
                        realized = (price_d - avg_entry) * close_size - exit_fees
                    else:
                        realized = (avg_entry - price_d) * close_size - exit_fees
                    portfolio.realized_pnl += realized


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

        opp_ids = {t.opportunity_id for t in trades if t.opportunity_id is not None}
        pair_map: dict[int, int] = {}
        if opp_ids:
            rows = await session.execute(
                select(ArbitrageOpportunity.id, ArbitrageOpportunity.pair_id).where(
                    ArbitrageOpportunity.id.in_(opp_ids)
                )
            )
            pair_map = {oid: pid for oid, pid in rows.all()}

        flow_window_start = datetime.now(timezone.utc) - timedelta(
            seconds=settings.pair_flow_window_seconds
        )
        replay_trades_into_portfolio(
            portfolio, trades, pair_map=pair_map, flow_window_start=flow_window_start
        )

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
