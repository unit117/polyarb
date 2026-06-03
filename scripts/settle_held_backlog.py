"""Settle held positions whose markets resolved before the live resolution
detector could see them.

Background: while Gamma pagination was 422-stalling (see project_outage fix),
`check_resolved_markets` silently failed, so a backlog of held positions never
settled even though their markets resolved on Polymarket. The detector now uses
closedTime ordering, but it only reaches the most-recent ~10k closures — older
resolutions stay out of reach.

This one-time pass fetches each held, still-unresolved market directly by id
(`GET /markets/{id}` — no pagination cap), and if Polymarket reports a winner,
settles it through the same path the live simulator already consumes:
sets resolved_outcome/resolved_at/active=False and publishes MarketResolvedEvent.

Usage (inside the ingestor container):
    docker compose run --rm ingestor python -m scripts.settle_held_backlog [--dry-run]
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select

sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import CHANNEL_MARKET_RESOLVED, get_redis, publish_event
from shared.models import Market, PortfolioSnapshot
from shared.schemas import MarketResolvedEvent
from services.ingestor.gamma_client import parse_stringified_json

log = structlog.get_logger()


def extract_winner(raw_market: dict) -> str | None:
    """Winning outcome from a resolved Gamma market (winner price -> ~1.0).

    Mirrors services.ingestor.polling._extract_winner.
    """
    outcomes = parse_stringified_json(raw_market.get("outcomes", "[]"))
    prices = parse_stringified_json(raw_market.get("outcomePrices", "[]"))
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    for outcome, price in zip(outcomes, prices):
        try:
            if float(price) >= 0.99:
                return outcome
        except (ValueError, TypeError):
            continue
    return None


async def held_market_ids(session) -> set[int]:
    """Market ids with a non-trivial open position in the latest snapshot."""
    result = await session.execute(
        select(PortfolioSnapshot.positions)
        .where(PortfolioSnapshot.source == "paper")
        .order_by(PortfolioSnapshot.timestamp.desc())
        .limit(1)
    )
    positions = result.scalar_one_or_none() or {}
    ids: set[int] = set()
    for key, shares in positions.items():
        try:
            if abs(float(shares)) <= 1e-4:
                continue
            ids.add(int(str(key).split(":", 1)[0]))
        except (ValueError, TypeError):
            continue
    return ids


async def main(dry_run: bool) -> None:
    await init_db()
    redis = await get_redis()
    settled = 0
    checked = 0
    unresolved_remaining = 0
    try:
        async with SessionFactory() as session:
            ids = await held_market_ids(session)
            result = await session.execute(
                select(Market).where(
                    Market.id.in_(ids),
                    Market.resolved_outcome.is_(None),
                )
            )
            markets = list(result.scalars().all())

        log.info("settle_backlog_start", held_markets=len(ids), unresolved=len(markets), dry_run=dry_run)

        async with httpx.AsyncClient(base_url=settings.gamma_api_base, timeout=30.0) as client:
            for market in markets:
                checked += 1
                if not market.polymarket_id:
                    continue
                try:
                    resp = await client.get(f"/markets/{market.polymarket_id}")
                    resp.raise_for_status()
                    raw = resp.json()
                except httpx.HTTPError as e:
                    log.warning("gamma_fetch_failed", polymarket_id=market.polymarket_id, error=str(e))
                    continue
                if isinstance(raw, list):
                    raw = raw[0] if raw else {}

                if not raw.get("closed"):
                    unresolved_remaining += 1
                    continue
                winner = extract_winner(raw)
                if not winner:
                    unresolved_remaining += 1
                    log.info("no_winner_yet", polymarket_id=market.polymarket_id,
                             question=(market.question or "")[:60])
                    continue

                log.info("settling", market_id=market.id, polymarket_id=market.polymarket_id,
                         winner=winner, question=(market.question or "")[:60])
                if not dry_run:
                    async with SessionFactory() as session:
                        m = await session.get(Market, market.id)
                        if not m or m.resolved_outcome:
                            continue
                        m.resolved_outcome = winner
                        m.resolved_at = datetime.now(timezone.utc)
                        m.active = False
                        await session.commit()
                    await publish_event(redis, CHANNEL_MARKET_RESOLVED, MarketResolvedEvent(
                        market_id=market.id,
                        resolved_outcome=winner,
                        source="gamma_backlog_settle",
                    ))
                settled += 1
                await asyncio.sleep(0.4)  # be gentle with Gamma

        log.info("settle_backlog_done", checked=checked, settled=settled,
                 still_unresolved=unresolved_remaining, dry_run=dry_run)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report without writing or publishing")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
