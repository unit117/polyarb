"""Backfill 30 days of historical price data from Polymarket CLOB API.

Fetches daily price candles for all active markets and inserts them as
PriceSnapshot rows with proper historical timestamps, so the backtester
can replay the full pipeline day-by-day.

Usage:
    python -m scripts.backfill_history [--days 30] [--max-markets 200]
"""

import argparse
import asyncio
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert

# ── allow running from repo root ──────────────────────────────────
sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.models import Market, MarketPair, PriceSnapshot

log = structlog.get_logger()

CLOB_BASE = settings.clob_api_base          # https://clob.polymarket.com
RATE_LIMIT_INTERVAL = 0.55                   # ~2 req/s with margin


CHUNK_DAYS = 14  # CLOB API rejects intervals > ~14 days


async def _fetch_chunk(
    client: httpx.AsyncClient,
    token_id: str,
    start_ts: int,
    end_ts: int,
    fidelity: int = 1440,
) -> list[dict]:
    """Fetch a single ≤14-day chunk from /prices-history."""
    params = {
        "market": token_id,
        "startTs": start_ts,
        "endTs": end_ts,
        "interval": "1d",
        "fidelity": fidelity,
    }

    for attempt in range(3):
        await asyncio.sleep(RATE_LIMIT_INTERVAL)
        try:
            resp = await client.get("/prices-history", params=params)
            if resp.status_code == 400:
                return []
            if resp.status_code == 429 or resp.status_code >= 500:
                backoff = min(2 ** (attempt + 1), 30) + random.uniform(0, 1)
                log.warning("clob_retry", status=resp.status_code, backoff=round(backoff, 1))
                await asyncio.sleep(backoff)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data.get("history", [])
        except httpx.HTTPError as exc:
            if attempt == 2:
                log.error("clob_fetch_failed", token_id=token_id[:20], error=str(exc))
                return []
            await asyncio.sleep(2 ** (attempt + 1))
    return []


async def fetch_price_history(
    client: httpx.AsyncClient,
    token_id: str,
    start_ts: int,
    end_ts: int,
    fidelity: int = 1440,
) -> list[dict]:
    """GET /prices-history, chunked into ≤14-day windows.

    Returns list of {t: unix_ts, p: price}.
    """
    chunk_seconds = CHUNK_DAYS * 86400
    all_candles: list[dict] = []
    cursor = start_ts

    while cursor < end_ts:
        chunk_end = min(cursor + chunk_seconds, end_ts)
        candles = await _fetch_chunk(client, token_id, cursor, chunk_end, fidelity)
        if not candles:
            # If first chunk fails, token is invalid — skip entirely
            if cursor == start_ts:
                return []
            # Otherwise just move on to next window
            cursor = chunk_end
            continue
        all_candles.extend(candles)
        cursor = chunk_end

    return all_candles


async def backfill_market(
    client: httpx.AsyncClient,
    market: Market,
    start_ts: int,
    end_ts: int,
) -> int:
    """Fetch history for every outcome token in a market, create PriceSnapshots."""
    if not market.token_ids or not market.outcomes:
        return 0

    outcomes = market.outcomes if isinstance(market.outcomes, list) else []
    token_ids = market.token_ids if isinstance(market.token_ids, list) else []

    if not outcomes or not token_ids:
        return 0

    # Fetch price history per token
    histories: dict[str, list[dict]] = {}
    for i, token_id in enumerate(token_ids):
        outcome = outcomes[i] if i < len(outcomes) else f"outcome_{i}"
        candles = await fetch_price_history(client, token_id, start_ts, end_ts)
        if candles:
            histories[outcome] = candles

    if not histories:
        return 0

    # Collect all unique timestamps across all outcomes
    all_ts = set()
    for candles in histories.values():
        for c in candles:
            all_ts.add(c["t"])

    # For each timestamp, build a combined snapshot
    snapshots_to_insert = []
    for ts in sorted(all_ts):
        prices = {}
        midpoints = {}
        for outcome, candles in histories.items():
            # Find the candle for this ts
            for c in candles:
                if c["t"] == ts:
                    prices[outcome] = str(c["p"])
                    midpoints[outcome] = str(c["p"])
                    break

        if prices:
            snapshots_to_insert.append({
                "market_id": market.id,
                "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc),
                "prices": prices,
                "midpoints": midpoints,
                "order_book": None,
            })

    if not snapshots_to_insert:
        return 0

    # Bulk insert, skipping duplicates (same market_id + timestamp)
    async with SessionFactory() as session:
        for snap in snapshots_to_insert:
            session.add(PriceSnapshot(
                market_id=snap["market_id"],
                timestamp=snap["timestamp"],
                prices=snap["prices"],
                midpoints=snap["midpoints"],
                order_book=snap["order_book"],
            ))
        await session.commit()

    return len(snapshots_to_insert)


async def main(days: int = 30, max_markets: int = 3000) -> None:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )
    await init_db()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_ts = int(start.timestamp())
    end_ts = int(now.timestamp())

    log.info(
        "backfill_start",
        days=days,
        start=start.isoformat(),
        end=now.isoformat(),
        max_markets=max_markets,
    )

    # Load only markets that are part of detected pairs (the ones the backtest needs)
    async with SessionFactory() as session:
        from sqlalchemy import union_all
        paired_ids = union_all(
            select(MarketPair.market_a_id.label("mid")),
            select(MarketPair.market_b_id.label("mid")),
        ).subquery()
        result = await session.execute(
            select(Market)
            .where(Market.id.in_(select(paired_ids.c.mid)))
            .where(Market.token_ids != None)  # noqa: E711
            .order_by(Market.liquidity.desc().nullslast())
            .limit(max_markets)
        )
        markets = list(result.scalars().all())

    log.info("markets_loaded", count=len(markets))

    if not markets:
        log.error("no_markets_found", hint="Run the ingestor first to sync markets")
        return

    total_snapshots = 0
    async with httpx.AsyncClient(base_url=CLOB_BASE, timeout=30.0) as client:
        for i, market in enumerate(markets):
            try:
                n = await backfill_market(client, market, start_ts, end_ts)
                total_snapshots += n
                if n > 0:
                    log.info(
                        "market_backfilled",
                        progress=f"{i+1}/{len(markets)}",
                        market_id=market.id,
                        question=market.question[:60],
                        snapshots=n,
                    )
            except Exception:
                log.exception("backfill_error", market_id=market.id)

    # Summary
    async with SessionFactory() as session:
        total = await session.scalar(select(func.count()).select_from(PriceSnapshot))
        earliest = await session.scalar(select(func.min(PriceSnapshot.timestamp)))
        latest = await session.scalar(select(func.max(PriceSnapshot.timestamp)))

    log.info(
        "backfill_complete",
        new_snapshots=total_snapshots,
        total_snapshots_in_db=total,
        date_range=f"{earliest} → {latest}" if earliest else "none",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical price data")
    parser.add_argument("--days", type=int, default=30, help="Days of history to fetch")
    parser.add_argument("--max-markets", type=int, default=3000, help="Max markets to backfill")
    args = parser.parse_args()
    asyncio.run(main(days=args.days, max_markets=args.max_markets))
