"""REST API routes for the dashboard."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import func, select, desc

from shared.config import settings
from shared.db import SessionFactory
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PaperTrade,
    PortfolioSnapshot,
)

router = APIRouter()

# Live executor reference (set by main.py if live trading is enabled)
_live_executor = None


def set_live_executor(executor) -> None:
    global _live_executor
    _live_executor = executor


@router.get("/stats")
async def get_stats(source: str | None = None):
    """System-wide statistics, optionally filtered by source (paper/live)."""
    async with SessionFactory() as session:
        markets = await session.scalar(
            select(func.count()).select_from(Market).where(Market.active == True)  # noqa: E712
        )
        pairs = await session.scalar(
            select(func.count()).select_from(MarketPair)
        )
        opportunities = await session.scalar(
            select(func.count()).select_from(ArbitrageOpportunity)
        )

        trade_query = select(func.count()).select_from(PaperTrade)
        if source:
            trade_query = trade_query.where(PaperTrade.source == source)
        trades = await session.scalar(trade_query)

        # Latest portfolio for the given source
        portfolio_query = (
            select(PortfolioSnapshot)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .limit(1)
        )
        if source:
            portfolio_query = portfolio_query.where(PortfolioSnapshot.source == source)
        latest_portfolio = await session.scalar(portfolio_query)

    portfolio = None
    if latest_portfolio:
        unrealized = float(latest_portfolio.unrealized_pnl)
        realized = float(latest_portfolio.realized_pnl)
        portfolio = {
            "cash": float(latest_portfolio.cash),
            "total_value": float(latest_portfolio.total_value),
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": unrealized + realized,
            "total_trades": latest_portfolio.total_trades,
            "winning_trades": latest_portfolio.winning_trades,
            "total_positions": len(latest_portfolio.positions) if latest_portfolio.positions else 0,
        }

    return {
        "active_markets": markets,
        "market_pairs": pairs,
        "total_opportunities": opportunities,
        "total_trades": trades,
        "portfolio": portfolio,
        "live_trading": {
            "enabled": settings.live_trading_enabled,
            "active": _live_executor is not None and not _live_executor.disabled,
            "dry_run": settings.live_trading_dry_run,
        },
    }


@router.get("/opportunities")
async def get_opportunities(limit: int = 200, offset: int = 0, status: str | None = None):
    """Recent arbitrage opportunities."""
    async with SessionFactory() as session:
        query = (
            select(ArbitrageOpportunity)
            .order_by(desc(ArbitrageOpportunity.timestamp))
            .offset(offset)
            .limit(limit)
        )
        if status:
            query = query.where(ArbitrageOpportunity.status == status)

        result = await session.execute(query)
        opps = result.scalars().all()

        items = []
        for opp in opps:
            pair = await session.get(MarketPair, opp.pair_id)
            market_a = await session.get(Market, pair.market_a_id) if pair else None
            market_b = await session.get(Market, pair.market_b_id) if pair else None

            items.append({
                "id": opp.id,
                "timestamp": opp.timestamp.isoformat() if opp.timestamp else None,
                "status": opp.status,
                "type": opp.type,
                "theoretical_profit": float(opp.theoretical_profit) if opp.theoretical_profit else 0,
                "estimated_profit": float(opp.estimated_profit) if opp.estimated_profit else 0,
                "fw_iterations": opp.fw_iterations,
                "bregman_gap": opp.bregman_gap,
                "pair": {
                    "id": pair.id,
                    "dependency_type": pair.dependency_type,
                    "confidence": pair.confidence,
                    "market_a": market_a.question[:80] if market_a else None,
                    "market_b": market_b.question[:80] if market_b else None,
                } if pair else None,
            })

    # Get total count for pagination
    count_query = select(func.count()).select_from(ArbitrageOpportunity)
    if status:
        count_query = count_query.where(ArbitrageOpportunity.status == status)
    async with SessionFactory() as count_session:
        total = await count_session.scalar(count_query)

    return {"opportunities": items, "total": total, "offset": offset, "limit": limit}


@router.get("/pairs")
async def get_pairs(limit: int = 200, offset: int = 0):
    """Detected market pairs."""
    async with SessionFactory() as session:
        result = await session.execute(
            select(MarketPair)
            .order_by(desc(MarketPair.detected_at))
            .offset(offset)
            .limit(limit)
        )
        pairs = result.scalars().all()

        items = []
        for pair in pairs:
            market_a = await session.get(Market, pair.market_a_id)
            market_b = await session.get(Market, pair.market_b_id)

            opp_count = await session.scalar(
                select(func.count())
                .select_from(ArbitrageOpportunity)
                .where(ArbitrageOpportunity.pair_id == pair.id)
            )

            items.append({
                "id": pair.id,
                "dependency_type": pair.dependency_type,
                "confidence": pair.confidence,
                "verified": pair.verified,
                "detected_at": pair.detected_at.isoformat() if pair.detected_at else None,
                "market_a": {
                    "id": market_a.id,
                    "question": market_a.question[:100],
                } if market_a else None,
                "market_b": {
                    "id": market_b.id,
                    "question": market_b.question[:100],
                } if market_b else None,
                "opportunity_count": opp_count,
            })

    # Get total count for pagination
    async with SessionFactory() as count_session:
        total = await count_session.scalar(
            select(func.count()).select_from(MarketPair)
        )

    return {"pairs": items, "total": total, "offset": offset, "limit": limit}


@router.get("/trades")
async def get_trades(limit: int = 200, offset: int = 0, source: str | None = None):
    """Recent trades, optionally filtered by source (paper/live)."""
    async with SessionFactory() as session:
        query = (
            select(PaperTrade)
            .order_by(desc(PaperTrade.executed_at))
            .offset(offset)
            .limit(limit)
        )
        if source:
            query = query.where(PaperTrade.source == source)

        result = await session.execute(query)
        trades = result.scalars().all()

        items = []
        for t in trades:
            market = await session.get(Market, t.market_id)
            items.append({
                "id": t.id,
                "opportunity_id": t.opportunity_id,
                "market": market.question[:80] if market else f"Market #{t.market_id}",
                "outcome": t.outcome,
                "side": t.side,
                "size": float(t.size),
                "entry_price": float(t.entry_price),
                "vwap_price": float(t.vwap_price),
                "slippage": float(t.slippage),
                "fees": float(t.fees),
                "executed_at": t.executed_at.isoformat() if t.executed_at else None,
                "status": t.status,
                "source": t.source,
            })

    # Get total count for pagination
    count_query = select(func.count()).select_from(PaperTrade)
    if source:
        count_query = count_query.where(PaperTrade.source == source)
    async with SessionFactory() as count_session:
        total = await count_session.scalar(count_query)

    return {"trades": items, "total": total, "offset": offset, "limit": limit}


@router.get("/portfolio/history")
async def get_portfolio_history(hours: int = 24, source: str | None = None):
    """Portfolio value over time, optionally filtered by source."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with SessionFactory() as session:
        query = (
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.timestamp >= since)
            .order_by(PortfolioSnapshot.timestamp)
        )
        if source:
            query = query.where(PortfolioSnapshot.source == source)

        result = await session.execute(query)
        snapshots = result.scalars().all()

    return {
        "history": [
            {
                "timestamp": s.timestamp.isoformat(),
                "cash": float(s.cash),
                "total_value": float(s.total_value),
                "realized_pnl": float(s.realized_pnl),
                "unrealized_pnl": float(s.unrealized_pnl),
                "total_trades": s.total_trades,
            }
            for s in snapshots
        ]
    }


# --- Live Trading Endpoints ---


@router.get("/live/status")
async def get_live_status():
    """Live trading status."""
    return {
        "configured": bool(settings.live_trading_api_key),
        "enabled": settings.live_trading_enabled,
        "dry_run": settings.live_trading_dry_run,
        "active": _live_executor is not None and not _live_executor.disabled,
        "bankroll": settings.live_trading_bankroll,
        "max_position_size": settings.live_trading_max_position_size,
        "scale_factor": settings.live_trading_scale_factor,
        "min_edge": settings.live_trading_min_edge,
    }


@router.post("/live/kill")
async def kill_live_trading():
    """Emergency kill switch for live trading."""
    if _live_executor:
        _live_executor.kill()
        return {"status": "killed", "msg": "Live trading disabled"}
    return {"status": "not_active", "msg": "No live executor running"}


@router.post("/live/enable")
async def enable_live_trading():
    """Re-enable live trading after kill switch."""
    if _live_executor:
        _live_executor.enable()
        return {"status": "enabled", "msg": "Live trading re-enabled"}
    return {"status": "not_active", "msg": "No live executor running"}
