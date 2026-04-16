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
