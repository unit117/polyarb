"""Trading entity API routes: opportunities, pairs, trades."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select, desc
from sqlalchemy.orm import joinedload, load_only

from shared.config import settings
from shared.db import SessionFactory
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PaperTrade,
)

router = APIRouter()


@router.get("/opportunities")
async def get_opportunities(limit: int = 200, offset: int = 0, status: str | None = None):
    """Recent arbitrage opportunities."""
    async with SessionFactory() as session:
        query = (
            select(ArbitrageOpportunity)
            .options(
                joinedload(ArbitrageOpportunity.pair)
                .load_only(MarketPair.id, MarketPair.dependency_type, MarketPair.confidence)
                .joinedload(MarketPair.market_a).load_only(Market.id, Market.question, Market.venue),
                joinedload(ArbitrageOpportunity.pair)
                .joinedload(MarketPair.market_b).load_only(Market.id, Market.question, Market.venue),
            )
            .order_by(desc(ArbitrageOpportunity.timestamp))
            .offset(offset)
            .limit(limit)
        )
        if status:
            query = query.where(ArbitrageOpportunity.status == status)

        result = await session.execute(query)
        opps = result.unique().scalars().all()

        count_query = select(func.count()).select_from(ArbitrageOpportunity)
        if status:
            count_query = count_query.where(ArbitrageOpportunity.status == status)
        total = await session.scalar(count_query)

    items = []
    for opp in opps:
        pair = opp.pair
        # Compute duration if expired
        duration_seconds = None
        if opp.expired_at and opp.timestamp:
            duration_seconds = (opp.expired_at - opp.timestamp).total_seconds()
        items.append({
            "id": opp.id,
            "timestamp": opp.timestamp.isoformat() if opp.timestamp else None,
            "expired_at": opp.expired_at.isoformat() if opp.expired_at else None,
            "duration_seconds": duration_seconds,
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
                "market_a": pair.market_a.question[:80] if pair.market_a else None,
                "market_a_venue": getattr(pair.market_a, "venue", "polymarket") if pair.market_a else None,
                "market_b": pair.market_b.question[:80] if pair.market_b else None,
                "market_b_venue": getattr(pair.market_b, "venue", "polymarket") if pair.market_b else None,
            } if pair else None,
        })

    return {"opportunities": items, "total": total, "offset": offset, "limit": limit}


@router.get("/pairs")
async def get_pairs(limit: int = 200, offset: int = 0):
    """Detected market pairs."""
    # Subquery for opportunity counts per pair
    opp_count_sq = (
        select(
            ArbitrageOpportunity.pair_id,
            func.count().label("opp_count"),
        )
        .group_by(ArbitrageOpportunity.pair_id)
        .subquery()
    )

    async with SessionFactory() as session:
        query = (
            select(MarketPair, func.coalesce(opp_count_sq.c.opp_count, 0).label("opportunity_count"))
            .outerjoin(opp_count_sq, MarketPair.id == opp_count_sq.c.pair_id)
            .options(
                joinedload(MarketPair.market_a).load_only(Market.id, Market.question, Market.venue),
                joinedload(MarketPair.market_b).load_only(Market.id, Market.question, Market.venue),
            )
            .order_by(desc(MarketPair.detected_at))
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(query)
        rows = result.unique().all()

        total = await session.scalar(
            select(func.count()).select_from(MarketPair)
        )

    items = []
    for pair, opp_count in rows:
        items.append({
            "id": pair.id,
            "dependency_type": pair.dependency_type,
            "confidence": pair.confidence,
            "verified": pair.verified,
            "detected_at": pair.detected_at.isoformat() if pair.detected_at else None,
            "market_a": {
                "id": pair.market_a.id,
                "question": pair.market_a.question[:100],
                "venue": getattr(pair.market_a, "venue", "polymarket"),
            } if pair.market_a else None,
            "market_b": {
                "id": pair.market_b.id,
                "question": pair.market_b.question[:100],
                "venue": getattr(pair.market_b, "venue", "polymarket"),
            } if pair.market_b else None,
            "opportunity_count": opp_count,
        })

    return {"pairs": items, "total": total, "offset": offset, "limit": limit}


@router.get("/trades")
async def get_trades(limit: int = 200, offset: int = 0, source: str | None = None):
    """Recent trades, optionally filtered by source (paper/live)."""
    async with SessionFactory() as session:
        query = (
            select(PaperTrade)
            .options(
                joinedload(PaperTrade.market).load_only(Market.id, Market.question),
            )
            .order_by(desc(PaperTrade.executed_at))
            .offset(offset)
            .limit(limit)
        )
        if source:
            query = query.where(PaperTrade.source == source)
        if settings.simulator_reset_epoch:
            query = query.where(PaperTrade.executed_at > settings.simulator_reset_epoch)

        result = await session.execute(query)
        trades = result.unique().scalars().all()

        count_query = select(func.count()).select_from(PaperTrade)
        if source:
            count_query = count_query.where(PaperTrade.source == source)
        if settings.simulator_reset_epoch:
            count_query = count_query.where(PaperTrade.executed_at > settings.simulator_reset_epoch)
        total = await session.scalar(count_query)

    items = []
    for t in trades:
        items.append({
            "id": t.id,
            "opportunity_id": t.opportunity_id,
            "market": t.market.question[:80] if t.market else f"Market #{t.market_id}",
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
            "venue": t.venue or "polymarket",
        })

    return {"trades": items, "total": total, "offset": offset, "limit": limit}
