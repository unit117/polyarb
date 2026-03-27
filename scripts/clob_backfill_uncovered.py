"""Backfill price data from CLOB API for markets with no PMXT coverage.

Targets only the ~5k markets in verified pairs that have ZERO price snapshots,
and fetches daily candles from CLOB /prices-history for Feb 15-28, 2026.

Pre-window prices (Feb 15-21) are usable because get_prices_at() uses
timestamp <= as_of, so a Feb 20 snapshot works as stale data on Feb 22.

Rate limited to ~2 req/s. Expected runtime: ~1-2 hours for 5k markets.

Usage (inside backtest container):
    python -m scripts.clob_backfill_uncovered [--dry-run] [--max-markets 500]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select, text

sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.models import Market, PriceSnapshot

log = structlog.get_logger()

CLOB_BASE = settings.clob_api_base
RATE_LIMIT_INTERVAL = 0.55
CHUNK_DAYS = 14

# Fetch window: 7 days pre-window + 7 days in-window
FETCH_START = datetime(2026, 2, 15, tzinfo=timezone.utc)
FETCH_END = datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc)


async def get_uncovered_markets() -> list[dict]:
    """Find markets in verified pairs with no price snapshots at all."""
    async with SessionFactory() as session:
        rows = (await session.execute(text("""
            SELECT m.id, m.question, m.outcomes, m.token_ids
            FROM markets m
            WHERE m.id IN (
                SELECT DISTINCT x.m FROM (
                    SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                    UNION
                    SELECT market_b_id AS m FROM market_pairs WHERE verified = true
                ) x
            )
            AND m.token_ids IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM price_snapshots ps WHERE ps.market_id = m.id
            )
            ORDER BY m.id
        """))).fetchall()

    markets = []
    for r in rows:
        outcomes = r.outcomes if isinstance(r.outcomes, list) else json.loads(r.outcomes or "[]")
        tokens = r.token_ids if isinstance(r.token_ids, list) else json.loads(r.token_ids or "[]")
        if outcomes and tokens:
            markets.append({
                "id": r.id,
                "question": r.question,
                "outcomes": outcomes,
                "tokens": [str(t) for t in tokens],
            })

    return markets


async def fetch_chunk(
    client: httpx.AsyncClient,
    token_id: str,
    start_ts: int,
    end_ts: int,
) -> list[dict]:
    """Fetch a single ≤14-day chunk from /prices-history."""
    params = {
        "market": token_id,
        "startTs": start_ts,
        "endTs": end_ts,
        "interval": "1d",
        "fidelity": 1440,
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
                return []
            await asyncio.sleep(2 ** (attempt + 1))
    return []


async def fetch_market_prices(
    client: httpx.AsyncClient,
    market: dict,
) -> dict[str, list[dict]]:
    """Fetch price history for all outcomes of a market."""
    start_ts = int(FETCH_START.timestamp())
    end_ts = int(FETCH_END.timestamp())

    histories: dict[str, list[dict]] = {}
    for outcome, token_id in zip(market["outcomes"], market["tokens"]):
        candles = await fetch_chunk(client, token_id, start_ts, end_ts)
        if candles:
            histories[outcome] = candles

    return histories


async def insert_market_snapshots(
    market_id: int,
    histories: dict[str, list[dict]],
) -> int:
    """Convert candle histories into PriceSnapshot rows and insert."""
    # Collect all unique timestamps
    all_ts = set()
    for candles in histories.values():
        for c in candles:
            all_ts.add(c["t"])

    if not all_ts:
        return 0

    inserted = 0
    async with SessionFactory() as session:
        for ts in sorted(all_ts):
            prices = {}
            for outcome, candles in histories.items():
                for c in candles:
                    if c["t"] == ts:
                        prices[outcome] = str(c["p"])
                        break

            if not prices:
                continue

            snap_ts = datetime.fromtimestamp(ts, tz=timezone.utc)
            snap = PriceSnapshot(
                market_id=market_id,
                timestamp=snap_ts,
                prices=prices,
                midpoints=prices,
            )
            session.add(snap)
            inserted += 1

        await session.commit()

    return inserted


async def main():
    parser = argparse.ArgumentParser(description="CLOB backfill for uncovered markets")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count uncovered markets without fetching")
    parser.add_argument("--max-markets", type=int, default=0,
                        help="Limit markets to process (0 = all)")
    args = parser.parse_args()

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )
    await init_db()

    uncovered = await get_uncovered_markets()
    print(f"\nUncovered markets in verified pairs: {len(uncovered)}")

    if args.dry_run:
        # Show sample
        print("\nSample uncovered markets:")
        for m in uncovered[:10]:
            print(f"  #{m['id']}: {m['question'][:80]}")
            print(f"    tokens: {m['tokens'][:2]}")
        print(f"\nEstimated API calls: ~{sum(len(m['tokens']) for m in uncovered)}")
        print(f"Estimated time at 2 req/s: ~{sum(len(m['tokens']) for m in uncovered) * 0.55 / 60:.0f} min")
        return

    if args.max_markets > 0:
        uncovered = uncovered[:args.max_markets]

    print(f"Processing {len(uncovered)} markets...")
    print(f"Fetch window: {FETCH_START.date()} → {FETCH_END.date()}")
    print(f"Estimated time: ~{sum(len(m['tokens']) for m in uncovered) * 0.55 / 60:.0f} min\n")

    total_inserted = 0
    markets_with_data = 0
    markets_empty = 0

    async with httpx.AsyncClient(base_url=CLOB_BASE, timeout=30.0) as client:
        for i, market in enumerate(uncovered):
            try:
                histories = await fetch_market_prices(client, market)

                if histories:
                    n = await insert_market_snapshots(market["id"], histories)
                    total_inserted += n
                    if n > 0:
                        markets_with_data += 1
                    else:
                        markets_empty += 1
                else:
                    markets_empty += 1

                if (i + 1) % 100 == 0:
                    log.info("progress",
                             done=i + 1, total=len(uncovered),
                             with_data=markets_with_data,
                             empty=markets_empty,
                             snapshots=total_inserted)

            except Exception:
                log.exception("market_error", market_id=market["id"])

    # Final stats
    async with SessionFactory() as session:
        total_pair_markets = (await session.execute(text("""
            SELECT COUNT(DISTINCT m) FROM (
                SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                UNION
                SELECT market_b_id AS m FROM market_pairs WHERE verified = true
            ) x
        """))).scalar()

        covered_markets = (await session.execute(text("""
            SELECT COUNT(DISTINCT ps.market_id) FROM price_snapshots ps
            WHERE ps.market_id IN (
                SELECT DISTINCT m FROM (
                    SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                    UNION
                    SELECT market_b_id AS m FROM market_pairs WHERE verified = true
                ) x
            )
        """))).scalar()

        window_covered = (await session.execute(text("""
            SELECT COUNT(DISTINCT ps.market_id) FROM price_snapshots ps
            WHERE ps.market_id IN (
                SELECT DISTINCT m FROM (
                    SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                    UNION
                    SELECT market_b_id AS m FROM market_pairs WHERE verified = true
                ) x
            )
            AND ps.timestamp >= '2026-02-15'::timestamptz
            AND ps.timestamp <= '2026-02-28 23:59:59'::timestamptz
        """))).scalar()

    print(f"\n{'=' * 60}")
    print(f"  CLOB BACKFILL COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Markets processed:           {len(uncovered)}")
    print(f"  Markets with CLOB data:      {markets_with_data}")
    print(f"  Markets with no data:        {markets_empty}")
    print(f"  Snapshots inserted:          {total_inserted}")
    print(f"\n  Coverage (verified pair markets):")
    print(f"    Total:                     {total_pair_markets}")
    print(f"    With any snapshot:         {covered_markets} ({100*covered_markets/max(total_pair_markets,1):.1f}%)")
    print(f"    With Feb 15-28 snapshot:   {window_covered} ({100*window_covered/max(total_pair_markets,1):.1f}%)")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
