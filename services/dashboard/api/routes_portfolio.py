"""Portfolio and system statistics API routes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlalchemy import func, select, desc
from sqlalchemy.orm import load_only

from shared.config import settings
from shared.db import SessionFactory
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PaperTrade,
    PortfolioSnapshot,
)
from services.dashboard.api.live_status import build_live_status

router = APIRouter()


@router.get("/stats")
async def get_stats(request: Request, source: str | None = None):
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
        if settings.simulator_reset_epoch:
            trade_query = trade_query.where(PaperTrade.executed_at > settings.simulator_reset_epoch)
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
            "settled_trades": latest_portfolio.settled_trades or 0,
            "winning_trades": latest_portfolio.winning_trades,
            "total_positions": len(latest_portfolio.positions) if latest_portfolio.positions else 0,
        }

    live_status = await build_live_status(request.app.state.redis, SessionFactory)

    return {
        "active_markets": markets,
        "market_pairs": pairs,
        "total_opportunities": opportunities,
        "total_trades": trades,
        "portfolio": portfolio,
        "live_trading": {
            "enabled": live_status["enabled"],
            "active": live_status["active"],
            "dry_run": live_status["dry_run"],
        },
    }


@router.get("/positions")
async def get_positions(source: str | None = None):
    """Open positions from the latest portfolio snapshot, enriched with market info."""
    async with SessionFactory() as session:
        portfolio_query = (
            select(PortfolioSnapshot)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .limit(1)
        )
        if source:
            portfolio_query = portfolio_query.where(PortfolioSnapshot.source == source)
        latest = await session.scalar(portfolio_query)

        if not latest or not latest.positions:
            return {"positions": [], "total": 0, "snapshot_timestamp": None}

        # Collect market IDs from position keys
        market_ids: set[int] = set()
        for key in latest.positions:
            parts = key.split(":")
            if len(parts) == 2:
                try:
                    market_ids.add(int(parts[0]))
                except ValueError:
                    pass

        # Batch-fetch market details
        markets_by_id: dict[int, Market] = {}
        if market_ids:
            result = await session.execute(
                select(Market).where(Market.id.in_(market_ids))
            )
            for m in result.scalars().all():
                markets_by_id[m.id] = m

        # Build response
        cost_basis_dict = latest.cost_basis or {}
        positions = []
        for key, shares in latest.positions.items():
            parts = key.split(":")
            if len(parts) != 2:
                continue
            try:
                market_id = int(parts[0])
            except ValueError:
                continue
            outcome = parts[1]
            market = markets_by_id.get(market_id)
            cb = cost_basis_dict.get(key)

            entry: dict = {
                "key": key,
                "market_id": market_id,
                "outcome": outcome,
                "shares": shares,
                "cost_basis": cb,
                "market_question": market.question[:120] if market else None,
                "venue": getattr(market, "venue", "polymarket") if market else None,
                "resolved_outcome": market.resolved_outcome if market else None,
                "resolved": market.resolved_outcome is not None if market else False,
            }
            positions.append(entry)

        # Sort: unresolved first, then by abs(shares) descending
        positions.sort(key=lambda p: (p["resolved"], -abs(p["shares"])))

    return {
        "positions": positions,
        "total": len(positions),
        "snapshot_timestamp": latest.timestamp.isoformat(),
    }


@router.get("/portfolio/history")
async def get_portfolio_history(hours: int = 24, source: str | None = None):
    """Portfolio value over time, optionally filtered by source."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with SessionFactory() as session:
        query = (
            select(PortfolioSnapshot)
            .options(load_only(
                PortfolioSnapshot.timestamp,
                PortfolioSnapshot.cash,
                PortfolioSnapshot.total_value,
                PortfolioSnapshot.realized_pnl,
                PortfolioSnapshot.unrealized_pnl,
                PortfolioSnapshot.total_trades,
            ))
            .where(PortfolioSnapshot.timestamp >= since)
            .order_by(PortfolioSnapshot.timestamp)
        )
        if source:
            query = query.where(PortfolioSnapshot.source == source)
        if settings.simulator_reset_epoch:
            query = query.where(PortfolioSnapshot.timestamp > settings.simulator_reset_epoch)

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


@router.get("/portfolio/baseline")
async def get_portfolio_baseline(source: str | None = None):
    """Return the stable experiment-start baseline (first post-epoch snapshot).

    Used by the chart as a fixed reference point that doesn't drift
    as the 24h window slides forward.
    """
    if not settings.simulator_reset_epoch:
        return {"status": "none", "total_value": None, "timestamp": None}

    async with SessionFactory() as session:
        q = (
            select(
                PortfolioSnapshot.total_value,
                PortfolioSnapshot.timestamp,
            )
            .where(PortfolioSnapshot.timestamp > settings.simulator_reset_epoch)
            .order_by(PortfolioSnapshot.timestamp)
            .limit(1)
        )
        if source:
            q = q.where(PortfolioSnapshot.source == source)
        row = (await session.execute(q)).first()

    if not row:
        return {"status": "pending", "total_value": None, "timestamp": None}
    return {
        "status": "ready",
        "total_value": float(row[0]),
        "timestamp": row[1].isoformat(),
    }
