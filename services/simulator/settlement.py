"""Settlement and position cleanup for resolved/contaminated markets."""
from __future__ import annotations

from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.circuit_breaker import CircuitBreaker
from shared.lifecycle import TradeStatus
from shared.models import Market, PaperTrade
from services.simulator.portfolio import Portfolio

logger = structlog.get_logger()


async def settle_resolved_markets(
    session_factory: async_sessionmaker,
    portfolio: Portfolio,
    circuit_breaker: CircuitBreaker | None,
    source: str,
) -> dict:
    """Close all positions in markets that have resolved.

    Returns stats dict with 'settled' count and 'pnl_realized'.
    Caller must hold any execution lock and snapshot portfolio afterward.
    """
    stats = {"settled": 0, "pnl_realized": 0.0}
    if not portfolio.positions:
        return stats

    position_market_ids = set()
    for key in portfolio.positions:
        parts = key.split(":")
        if len(parts) == 2:
            position_market_ids.add(int(parts[0]))

    if not position_market_ids:
        return stats

    async with session_factory() as session:
        result = await session.execute(
            select(Market).where(
                Market.resolved_outcome.isnot(None),
                Market.id.in_(position_market_ids),
            )
        )

        for market in result.scalars().all():
            for key in list(portfolio.positions.keys()):
                if not key.startswith(f"{market.id}:"):
                    continue

                position_outcome = key.split(":")[1]
                is_winner = position_outcome == market.resolved_outcome
                settlement_price = 1.0 if is_winner else 0.0

                close_result = portfolio.close_position(key, settlement_price)
                if not close_result["closed"]:
                    continue

                stats["settled"] += 1
                stats["pnl_realized"] += close_result["pnl"]
                if circuit_breaker and close_result["pnl"] < 0:
                    circuit_breaker.record_loss(abs(close_result["pnl"]))

                session.add(
                    PaperTrade(
                        opportunity_id=None,
                        market_id=market.id,
                        outcome=position_outcome,
                        side="SETTLE",
                        size=Decimal(str(close_result["shares"])),
                        entry_price=Decimal(str(settlement_price)),
                        vwap_price=Decimal(str(settlement_price)),
                        slippage=Decimal("0"),
                        fees=Decimal("0"),
                        status=TradeStatus.SETTLED,
                        source=source,
                    )
                )

        await session.commit()

    if stats["settled"] > 0:
        logger.info("settlement_complete", **stats)

    return stats


async def purge_contaminated_positions(
    session_factory: async_sessionmaker,
    portfolio: Portfolio,
    source: str,
    current_prices: dict[str, float],
) -> dict:
    """One-time cleanup: close ALL open positions at current market prices.

    Resets portfolio trade counters. Caller must hold any execution lock
    and snapshot portfolio afterward.
    """
    if not portfolio.positions:
        return {"purged": 0, "pnl_realized": 0.0}

    stats = {
        "purged": 0,
        "pnl_realized": 0.0,
        "positions_before": len(portfolio.positions),
    }

    async with session_factory() as session:
        for key in list(portfolio.positions.keys()):
            parts = key.split(":")
            if len(parts) != 2:
                continue

            market_id = int(parts[0])
            outcome = parts[1]
            price = current_prices.get(key, 0.5)

            close_result = portfolio.close_position(key, price)
            if not close_result["closed"]:
                continue

            stats["purged"] += 1
            stats["pnl_realized"] += close_result["pnl"]
            session.add(
                PaperTrade(
                    opportunity_id=None,
                    market_id=market_id,
                    outcome=outcome,
                    side="PURGE",
                    size=Decimal(str(close_result["shares"])),
                    entry_price=Decimal(str(price)),
                    vwap_price=Decimal(str(price)),
                    slippage=Decimal("0"),
                    fees=Decimal("0"),
                    status=TradeStatus.PURGED,
                    source=source,
                )
            )

        await session.commit()

    portfolio.total_trades = 0
    portfolio.settled_trades = 0
    portfolio.winning_trades = 0
    portfolio.realized_pnl = Decimal("0")

    logger.info(
        "contamination_purge_complete",
        positions_closed=stats["purged"],
        pnl_realized=stats["pnl_realized"],
        cash_after=float(portfolio.cash),
    )
    return stats
