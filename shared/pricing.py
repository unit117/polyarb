"""Shared price-snapshot query utilities.

Canonical implementation — all services import from here instead of
defining their own _get_latest_prices / get_latest_snapshot helpers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from shared.models import PriceSnapshot


async def get_latest_snapshot(
    session, market_id: int, max_age_seconds: int = 0
) -> PriceSnapshot | None:
    """Fetch the most recent price snapshot for a market.

    Args:
        session: async SQLAlchemy session.
        market_id: market to query.
        max_age_seconds: if > 0, reject snapshots older than this.

    Returns:
        The newest PriceSnapshot, or None if nothing matches.
        Callers that only need prices can access `snapshot.prices`.
    """
    query = (
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    if max_age_seconds > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        query = query.where(PriceSnapshot.timestamp >= cutoff)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def is_price_frozen(
    session,
    market_id: int,
    outcome: str,
    *,
    window_seconds: int,
    min_observations: int,
) -> bool:
    """Return True if an outcome's midpoint has not moved across recent snapshots.

    A frozen midpoint over many observations indicates an illiquid or stale
    market whose quoted edge is not actually tradeable — the ingestor keeps
    re-writing the same value, so the freshness check (`max_snapshot_age`)
    passes even though no real trading is happening. Distinguishing "fresh"
    from "live" prevents the optimizer/simulator from re-entering the same
    position every cycle on dead data.

    Returns False when there are fewer than `min_observations` snapshots in the
    window (not enough history to judge — benefit of the doubt for genuinely
    new opportunities). Prices are float-cast (Polymarket stores them as
    strings) and rounded to absorb float-repr noise below the tick size.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    query = (
        select(PriceSnapshot.midpoints, PriceSnapshot.prices)
        .where(
            PriceSnapshot.market_id == market_id,
            PriceSnapshot.timestamp >= cutoff,
        )
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(200)
    )
    result = await session.execute(query)

    values: set[float] = set()
    observations = 0
    for midpoints, prices in result.all():
        source = midpoints or prices
        if not source or outcome not in source:
            continue
        try:
            values.add(round(float(source[outcome]), 6))
            observations += 1
        except (TypeError, ValueError):
            continue

    if observations < min_observations:
        return False
    return len(values) <= 1
