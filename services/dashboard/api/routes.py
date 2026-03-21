"""REST API routes for the dashboard."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import case, cast, func, select, desc, Float
from sqlalchemy.orm import joinedload, load_only

from shared.config import settings
from shared.db import SessionFactory
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PaperTrade,
    PortfolioSnapshot,
    PriceSnapshot,
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
            "settled_trades": latest_portfolio.settled_trades or 0,
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
            .options(
                joinedload(ArbitrageOpportunity.pair)
                .load_only(MarketPair.id, MarketPair.dependency_type, MarketPair.confidence)
                .joinedload(MarketPair.market_a).load_only(Market.id, Market.question),
                joinedload(ArbitrageOpportunity.pair)
                .joinedload(MarketPair.market_b).load_only(Market.id, Market.question),
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
                "market_b": pair.market_b.question[:80] if pair.market_b else None,
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
                joinedload(MarketPair.market_a).load_only(Market.id, Market.question),
                joinedload(MarketPair.market_b).load_only(Market.id, Market.question),
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
            } if pair.market_a else None,
            "market_b": {
                "id": pair.market_b.id,
                "question": pair.market_b.question[:100],
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

        result = await session.execute(query)
        trades = result.unique().scalars().all()

        count_query = select(func.count()).select_from(PaperTrade)
        if source:
            count_query = count_query.where(PaperTrade.source == source)
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
        })

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


# --- Observability Endpoints ---


@router.get("/metrics/timeseries")
async def get_metrics_timeseries(hours: int = 24, source: str | None = None):
    """Hourly aggregates keyed by event time, not current status.

    Detections are counted by ArbitrageOpportunity.timestamp (when the opp
    was created). Trades are counted by PaperTrade.executed_at. This avoids
    the problem of an opp detected at 13:58 and simulated at 14:01 being
    counted as 'simulated' in the 13:00 bucket.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with SessionFactory() as session:
        # Hourly detection counts (all opps, regardless of current status)
        det_hour = func.date_trunc("hour", ArbitrageOpportunity.timestamp)
        det_query = (
            select(
                det_hour.label("hour"),
                func.count().label("detected"),
            )
            .where(ArbitrageOpportunity.timestamp >= since)
            .group_by(det_hour)
            .order_by(det_hour)
        )
        det_rows = (await session.execute(det_query)).all()

        # Hourly trade aggregates (keyed by execution time)
        trade_hour = func.date_trunc("hour", PaperTrade.executed_at)
        trade_query = (
            select(
                trade_hour.label("hour"),
                func.count().label("trades"),
                func.coalesce(func.sum(PaperTrade.fees), 0).label("fees"),
                func.coalesce(func.sum(PaperTrade.size), 0).label("volume"),
            )
            .where(PaperTrade.executed_at >= since)
        )
        if source:
            trade_query = trade_query.where(PaperTrade.source == source)
        trade_query = trade_query.group_by(trade_hour).order_by(trade_hour)
        trade_rows = (await session.execute(trade_query)).all()

        # Hourly expiration counts (keyed by expired_at)
        exp_hour = func.date_trunc("hour", ArbitrageOpportunity.expired_at)
        exp_query = (
            select(
                exp_hour.label("hour"),
                func.count().label("expired"),
            )
            .where(ArbitrageOpportunity.expired_at >= since)
            .group_by(exp_hour)
            .order_by(exp_hour)
        )
        exp_rows = (await session.execute(exp_query)).all()

    # Build hourly buckets
    det_by_hour = {row.hour.isoformat(): row.detected for row in det_rows}
    trade_by_hour = {
        row.hour.isoformat(): {
            "trades": row.trades,
            "fees": float(row.fees),
            "volume": float(row.volume),
        }
        for row in trade_rows
    }
    exp_by_hour = {row.hour.isoformat(): row.expired for row in exp_rows}

    all_hours = sorted(set(det_by_hour) | set(trade_by_hour) | set(exp_by_hour))
    timeseries = []
    for h in all_hours:
        entry: dict = {"hour": h, "detected": det_by_hour.get(h, 0)}
        if h in trade_by_hour:
            entry.update(trade_by_hour[h])
        entry["expired"] = exp_by_hour.get(h, 0)
        timeseries.append(entry)

    return {"timeseries": timeseries, "hours": hours}


@router.get("/metrics/funnel")
async def get_opportunity_funnel(hours: int = 24):
    """Opportunity funnel: detected → optimized → simulated → traded.

    Each stage is cumulative — an opp that reached 'simulated' also counts
    as having been detected and optimized. Status values that imply having
    passed through a stage:
    - detected: everything (all opps start as detected)
    - optimized: optimized, unconverged, pending, simulated, expired
      (expired opps were active enough to have been optimized)
    - simulated: simulated (successfully executed trades)
    - traded: distinct opportunity_ids that have PaperTrade rows
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with SessionFactory() as session:
        # Count opportunities by current status
        result = await session.execute(
            select(
                ArbitrageOpportunity.status,
                func.count().label("count"),
            )
            .where(ArbitrageOpportunity.timestamp >= since)
            .group_by(ArbitrageOpportunity.status)
        )
        status_counts = {row.status: row.count for row in result.all()}

        # Count distinct opportunities that actually produced trades
        # (keyed by trade execution time, not opp detection time)
        traded = await session.scalar(
            select(func.count(func.distinct(PaperTrade.opportunity_id)))
            .where(
                PaperTrade.executed_at >= since,
                PaperTrade.opportunity_id.isnot(None),
                PaperTrade.side.in_(["BUY", "SELL"]),
            )
        )

    # Cumulative funnel: statuses that imply passing through each stage.
    # "expired" is excluded — opportunities can expire while still "detected"
    # (before the optimizer touches them).  We count expired-after-optimization
    # separately via fw_iterations below.
    passed_optimization = {"optimized", "unconverged", "pending", "simulated"}
    detected = sum(status_counts.values())
    optimized = sum(v for k, v in status_counts.items() if k in passed_optimization)

    # Count expired opportunities that actually passed through the optimizer
    # (the optimizer always sets fw_iterations).
    async with SessionFactory() as session:
        expired_optimized = await session.scalar(
            select(func.count(ArbitrageOpportunity.id)).where(
                ArbitrageOpportunity.timestamp >= since,
                ArbitrageOpportunity.status == "expired",
                ArbitrageOpportunity.fw_iterations.isnot(None),
            )
        )
    optimized += expired_optimized or 0
    simulated = status_counts.get("simulated", 0)

    return {
        "funnel": {
            "detected": detected,
            "optimized": optimized,
            "simulated": simulated,
            "traded": traded or 0,
        },
        "status_breakdown": status_counts,
        "hours": hours,
    }


@router.get("/metrics/by-dependency-type")
async def get_metrics_by_dependency_type(hours: int = 24):
    """Per-dependency-type hit rates and profitability."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with SessionFactory() as session:
        # Use the opportunity's own dependency_type snapshot so that
        # pair downgrades don't retroactively relabel historical data.
        # Fall back to the pair's current value for pre-migration rows.
        dep_type_col = func.coalesce(
            ArbitrageOpportunity.dependency_type, MarketPair.dependency_type
        )
        result = await session.execute(
            select(
                dep_type_col.label("dependency_type"),
                func.count(ArbitrageOpportunity.id).label("total_opps"),
                func.sum(
                    case((ArbitrageOpportunity.status == "simulated", 1), else_=0)
                ).label("simulated"),
                func.avg(
                    cast(ArbitrageOpportunity.theoretical_profit, Float)
                ).label("avg_theoretical_profit"),
                func.avg(
                    cast(ArbitrageOpportunity.estimated_profit, Float)
                ).label("avg_estimated_profit"),
            )
            .join(MarketPair, ArbitrageOpportunity.pair_id == MarketPair.id)
            .where(ArbitrageOpportunity.timestamp >= since)
            .group_by(dep_type_col)
        )
        rows = result.all()

    return {
        "by_dependency_type": [
            {
                "dependency_type": row.dependency_type,
                "total_opportunities": row.total_opps,
                "simulated": row.simulated,
                "hit_rate": round(row.simulated / row.total_opps, 3) if row.total_opps else 0,
                "avg_theoretical_profit": round(float(row.avg_theoretical_profit or 0), 4),
                "avg_estimated_profit": round(float(row.avg_estimated_profit or 0), 4),
            }
            for row in rows
        ],
        "hours": hours,
    }


@router.get("/metrics/duration")
async def get_opportunity_duration_stats(hours: int = 168):
    """Opportunity duration histogram — how long opportunities stay profitable."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with SessionFactory() as session:
        # Get all expired opportunities with duration
        result = await session.execute(
            select(
                ArbitrageOpportunity.id,
                ArbitrageOpportunity.timestamp,
                ArbitrageOpportunity.expired_at,
                MarketPair.dependency_type,
            )
            .join(MarketPair, ArbitrageOpportunity.pair_id == MarketPair.id)
            .where(
                ArbitrageOpportunity.timestamp >= since,
                ArbitrageOpportunity.expired_at.isnot(None),
            )
        )
        rows = result.all()

    durations = []
    for row in rows:
        secs = (row.expired_at - row.timestamp).total_seconds()
        durations.append({
            "opportunity_id": row.id,
            "dependency_type": row.dependency_type,
            "duration_seconds": round(secs, 1),
        })

    # Build histogram buckets
    buckets = {"<1s": 0, "1-10s": 0, "10-60s": 0, "1-5m": 0, "5-30m": 0, "30m-2h": 0, ">2h": 0}
    for d in durations:
        s = d["duration_seconds"]
        if s < 1:
            buckets["<1s"] += 1
        elif s < 10:
            buckets["1-10s"] += 1
        elif s < 60:
            buckets["10-60s"] += 1
        elif s < 300:
            buckets["1-5m"] += 1
        elif s < 1800:
            buckets["5-30m"] += 1
        elif s < 7200:
            buckets["30m-2h"] += 1
        else:
            buckets[">2h"] += 1

    total = len(durations)
    avg_duration = sum(d["duration_seconds"] for d in durations) / total if total else 0
    median_duration = sorted(d["duration_seconds"] for d in durations)[total // 2] if total else 0

    return {
        "total_expired": total,
        "avg_duration_seconds": round(avg_duration, 1),
        "median_duration_seconds": round(median_duration, 1),
        "histogram": buckets,
        "hours": hours,
    }


@router.get("/metrics/correlations")
async def get_correlation_validation(
    min_snapshots: int = 10,
    downgrade: bool = False,
):
    """Validate conditional pair correlations against empirical price movements.

    Computes Pearson correlation on price *returns* (changes), not levels,
    to measure co-movement rather than spurious level correlation.

    If downgrade=true, pairs with weak or contradicted correlations are
    downgraded to dependency_type='none' and unverified.
    """
    from statistics import correlation as pearson_correlation

    results = []

    async with SessionFactory() as session:
        pair_result = await session.execute(
            select(MarketPair)
            .where(MarketPair.dependency_type == "conditional")
            .options(
                joinedload(MarketPair.market_a).load_only(Market.id, Market.question),
                joinedload(MarketPair.market_b).load_only(Market.id, Market.question),
            )
        )
        pairs = pair_result.unique().scalars().all()

        for pair in pairs:
            constraint = pair.constraint_matrix or {}
            predicted = constraint.get("correlation")

            # Get Yes price series for both markets
            series_a = await _get_yes_prices(session, pair.market_a_id)
            series_b = await _get_yes_prices(session, pair.market_b_id)

            aligned_a, aligned_b = _align_series(series_a, series_b)

            # Compute returns (price changes) from aligned levels
            returns_a = [aligned_a[i] - aligned_a[i - 1] for i in range(1, len(aligned_a))]
            returns_b = [aligned_b[i] - aligned_b[i - 1] for i in range(1, len(aligned_b))]

            entry = {
                "pair_id": pair.id,
                "market_a": pair.market_a.question[:80] if pair.market_a else None,
                "market_b": pair.market_b.question[:80] if pair.market_b else None,
                "predicted_correlation": predicted,
                "snapshots_a": len(series_a),
                "snapshots_b": len(series_b),
                "aligned_snapshots": len(aligned_a),
            }

            if len(returns_a) >= min_snapshots:
                try:
                    r = pearson_correlation(returns_a, returns_b)
                    entry["empirical_r"] = round(r, 4)
                    entry["empirical_direction"] = "positive" if r > 0 else "negative"
                    entry["matches"] = (
                        entry["empirical_direction"] == predicted if predicted else None
                    )
                    if abs(r) < 0.1:
                        entry["assessment"] = "weak_correlation"
                    elif entry["matches"]:
                        entry["assessment"] = "confirmed"
                    else:
                        entry["assessment"] = "contradicted"
                except Exception:
                    entry["assessment"] = "error"
            else:
                entry["assessment"] = "insufficient_data"

            # Write back downgrade if requested — update both dependency_type
            # AND constraint_matrix so the optimizer (which keys off
            # constraint_matrix["type"]) sees the change too.
            if downgrade and entry.get("assessment") in ("weak_correlation", "contradicted"):
                pair.dependency_type = "none"
                pair.verified = False
                if pair.constraint_matrix:
                    updated_cm = dict(pair.constraint_matrix)
                    updated_cm["type"] = "none"
                    pair.constraint_matrix = updated_cm
                entry["downgraded"] = True

            results.append(entry)

        if downgrade:
            await session.commit()

    confirmed = sum(1 for r in results if r.get("assessment") == "confirmed")
    contradicted = sum(1 for r in results if r.get("assessment") == "contradicted")
    weak = sum(1 for r in results if r.get("assessment") == "weak_correlation")

    return {
        "pairs": results,
        "summary": {
            "total": len(results),
            "confirmed": confirmed,
            "contradicted": contradicted,
            "weak": weak,
            "insufficient_data": len(results) - confirmed - contradicted - weak,
        },
    }


async def _get_yes_prices(session, market_id: int) -> list[tuple[datetime, float]]:
    """Get chronological Yes prices for a market."""
    result = await session.execute(
        select(PriceSnapshot.timestamp, PriceSnapshot.prices)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.asc())
    )
    series = []
    for ts, prices in result.all():
        yes_price = prices.get("Yes") if prices else None
        if yes_price is not None:
            series.append((ts, float(yes_price)))
    return series


def _align_series(
    series_a: list[tuple[datetime, float]],
    series_b: list[tuple[datetime, float]],
) -> tuple[list[float], list[float]]:
    """Align two price series by nearest timestamp within 5 minutes.

    Each series_b point is used at most once to prevent sample reuse.
    """
    max_gap_secs = 300
    aligned_a, aligned_b = [], []
    used_b: set[int] = set()

    for ts_a, price_a in series_a:
        best_j, best_gap = None, None
        for j_candidate in range(len(series_b)):
            if j_candidate in used_b:
                continue
            gap = abs((series_b[j_candidate][0] - ts_a).total_seconds())
            if gap > max_gap_secs:
                # If series_b is past ts_a + max_gap, stop scanning
                if series_b[j_candidate][0] > ts_a and gap > max_gap_secs:
                    break
                continue
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best_j = j_candidate

        if best_j is not None:
            aligned_a.append(price_a)
            aligned_b.append(series_b[best_j][1])
            used_b.add(best_j)

    return aligned_a, aligned_b


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
