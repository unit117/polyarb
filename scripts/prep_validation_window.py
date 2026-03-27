"""Prep a validation window (Mar 20-25, 2026) for out-of-sample testing.

Reuses the same polyarb_backtest DB (pairs, markets, direction backfills
already in place). Adds price data from PMXT + CLOB for the new window,
then prints a coverage summary.

Three stages:
  1. PMXT T12 backfill for Mar 20-25 (+ Mar 26 for end-of-window)
  2. CLOB /prices-history for markets uncovered by PMXT
  3. Coverage summary

Usage (inside backtest container):
    python -m scripts.prep_validation_window [--pmxt-only] [--clob-only] [--summary-only]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import structlog
from sqlalchemy import select, text

sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.models import Market, PriceSnapshot

log = structlog.get_logger()

# ── Validation window ────────────────────────────────────────────
WINDOW_DATES = [
    "2026-03-20",
    "2026-03-21",
    "2026-03-22",
    "2026-03-23",
    "2026-03-24",
    "2026-03-25",
    "2026-03-26",  # extra day for end-of-window coverage
]
EVAL_DATES = [
    datetime(2026, 3, 20, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 3, 21, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 3, 22, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 3, 23, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 3, 24, 23, 59, 59, tzinfo=timezone.utc),
]

# ── PMXT download ────────────────────────────────────────────────
BASE_URL = "https://r2.pmxt.dev"
TOKEN_ID_RE = re.compile(r'"token_id":\s*"?(\d+)"?')
BEST_BID_RE = re.compile(r'"best_bid":\s*"([^"]*)"')
BEST_ASK_RE = re.compile(r'"best_ask":\s*"([^"]*)"')

# ── CLOB settings ────────────────────────────────────────────────
CLOB_BASE = settings.clob_api_base
RATE_LIMIT = 0.55
CLOB_START = datetime(2026, 3, 13, tzinfo=timezone.utc)  # 7 days pre-window
CLOB_END = datetime(2026, 3, 26, 23, 59, 59, tzinfo=timezone.utc)


async def load_token_map() -> tuple[dict[str, tuple[int, str]], set[int]]:
    """token_id → (market_id, outcome) for all verified-pair markets."""
    token_map: dict[str, tuple[int, str]] = {}
    async with SessionFactory() as session:
        rows = await session.execute(text("""
            SELECT DISTINCT m FROM (
                SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                UNION
                SELECT market_b_id AS m FROM market_pairs WHERE verified = true
            ) x
        """))
        pair_mids = {r[0] for r in rows}
        result = await session.execute(
            select(Market.id, Market.outcomes, Market.token_ids)
            .where(Market.id.in_(pair_mids))
        )
        for mid, outcomes, tokens in result.all():
            if not tokens or not outcomes:
                continue
            tl = tokens if isinstance(tokens, list) else json.loads(tokens)
            ol = outcomes if isinstance(outcomes, list) else json.loads(outcomes)
            for o, t in zip(ol, tl):
                token_map[str(t)] = (mid, o)
    all_mids = {v[0] for v in token_map.values()}
    log.info("token_map", tokens=len(token_map), markets=len(all_mids))
    return token_map, all_mids


async def existing_snapshot_days(market_ids: set[int]) -> set[tuple[int, str]]:
    existing = set()
    async with SessionFactory() as session:
        result = await session.execute(
            select(PriceSnapshot.market_id, PriceSnapshot.timestamp)
            .where(PriceSnapshot.market_id.in_(market_ids))
        )
        for mid, ts in result.all():
            existing.add((mid, ts.strftime("%Y-%m-%d")))
    return existing


# ═══════════════════════════════════════════════════════════════════
#  Stage 1: PMXT backfill
# ═══════════════════════════════════════════════════════════════════

def download_pmxt(date_str: str, hour: int = 12) -> Path | None:
    import urllib.request, urllib.error
    fname = f"polymarket_orderbook_{date_str}T{hour:02d}.parquet"
    url = f"{BASE_URL}/{fname}"
    tmp = Path(tempfile.mkdtemp()) / fname
    log.info("downloading", url=url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
        with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        log.info("downloaded", file=fname, mb=round(tmp.stat().st_size / 1e6, 1))
        return tmp
    except Exception as e:
        log.warning("download_failed", file=fname, error=str(e))
        return None


def scan_parquet(path: Path, targets: set[str]) -> dict[str, tuple[float, float]]:
    import pyarrow.parquet as pq
    prices = {}
    pf = pq.ParquetFile(str(path))
    for rg in range(pf.metadata.num_row_groups):
        table = pf.read_row_group(rg, columns=["data"])
        for val in table.column("data").to_pylist():
            if val is None:
                continue
            m = TOKEN_ID_RE.search(val)
            if not m or m.group(1) not in targets:
                continue
            bm = BEST_BID_RE.search(val)
            am = BEST_ASK_RE.search(val)
            if not bm or not am:
                continue
            try:
                bid, ask = float(bm.group(1)), float(am.group(1))
            except (ValueError, TypeError):
                continue
            if 0 < bid <= 1 and 0 < ask <= 1:
                prices[m.group(1)] = (bid, ask)
    log.info("scanned", file=path.name, found=len(prices))
    return prices


async def pmxt_stage(token_map, all_mids, existing):
    """Download PMXT T12 for each window date and insert snapshots."""
    total = 0
    for date_str in WINDOW_DATES:
        ppath = download_pmxt(date_str)
        if not ppath:
            continue
        try:
            tprices = scan_parquet(ppath, set(token_map.keys()))
            mprices: dict[int, dict[str, float]] = {}
            for tid, (bid, ask) in tprices.items():
                if tid in token_map:
                    mid, outcome = token_map[tid]
                    mprices.setdefault(mid, {})[outcome] = (bid + ask) / 2.0

            inserted = 0
            async with SessionFactory() as session:
                ts = datetime.fromisoformat(date_str).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
                for mid, prices in mprices.items():
                    if (mid, date_str) in existing:
                        continue
                    session.add(PriceSnapshot(
                        market_id=mid,
                        timestamp=ts,
                        prices={k: str(round(v, 6)) for k, v in prices.items()},
                        midpoints={k: str(round(v, 6)) for k, v in prices.items()},
                    ))
                    existing.add((mid, date_str))
                    inserted += 1
                await session.commit()

            total += inserted
            log.info("pmxt_day", date=date_str, markets=len(mprices), inserted=inserted)
        finally:
            try:
                ppath.unlink()
                ppath.parent.rmdir()
            except OSError:
                pass
    print(f"  PMXT stage: {total} snapshots inserted")
    return total


# ═══════════════════════════════════════════════════════════════════
#  Stage 2: CLOB backfill for uncovered markets
# ═══════════════════════════════════════════════════════════════════

async def get_uncovered(all_mids: set[int], window_start: str, window_end: str) -> list[dict]:
    """Markets in verified pairs with no snapshot in [window_start, window_end]."""
    ws = datetime.fromisoformat(window_start).replace(tzinfo=timezone.utc)
    we = datetime.fromisoformat(window_end).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    async with SessionFactory() as session:
        rows = (await session.execute(text("""
            SELECT m.id, m.outcomes, m.token_ids
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
                SELECT 1 FROM price_snapshots ps
                WHERE ps.market_id = m.id
                AND ps.timestamp >= :ws
                AND ps.timestamp <= :we
            )
        """), {"ws": ws, "we": we})).fetchall()

    markets = []
    for r in rows:
        outcomes = r.outcomes if isinstance(r.outcomes, list) else json.loads(r.outcomes or "[]")
        tokens = r.token_ids if isinstance(r.token_ids, list) else json.loads(r.token_ids or "[]")
        if outcomes and tokens:
            markets.append({
                "id": r.id,
                "outcomes": outcomes,
                "tokens": [str(t) for t in tokens],
            })
    return markets


async def clob_stage(all_mids: set[int], existing: set[tuple[int, str]]):
    """Fetch CLOB /prices-history for uncovered markets."""
    uncovered = await get_uncovered(all_mids, WINDOW_DATES[0], WINDOW_DATES[-1])
    print(f"  CLOB stage: {len(uncovered)} uncovered markets to fetch")

    if not uncovered:
        return 0

    start_ts = int(CLOB_START.timestamp())
    end_ts = int(CLOB_END.timestamp())
    total_inserted = 0
    with_data = 0
    empty = 0

    async with httpx.AsyncClient(base_url=CLOB_BASE, timeout=30.0) as client:
        for i, mkt in enumerate(uncovered):
            histories: dict[str, list[dict]] = {}
            for outcome, token in zip(mkt["outcomes"], mkt["tokens"]):
                await asyncio.sleep(RATE_LIMIT)
                try:
                    resp = await client.get("/prices-history", params={
                        "market": token,
                        "startTs": start_ts,
                        "endTs": end_ts,
                        "interval": "1d",
                        "fidelity": 1440,
                    })
                    if resp.status_code == 200:
                        candles = resp.json().get("history", [])
                        if candles:
                            histories[outcome] = candles
                    elif resp.status_code == 429 or resp.status_code >= 500:
                        await asyncio.sleep(5 + random.uniform(0, 2))
                except httpx.HTTPError:
                    pass

            if histories:
                all_ts = set()
                for candles in histories.values():
                    for c in candles:
                        all_ts.add(c["t"])

                inserted = 0
                async with SessionFactory() as session:
                    for ts in sorted(all_ts):
                        prices = {}
                        for outcome, candles in histories.items():
                            for c in candles:
                                if c["t"] == ts:
                                    prices[outcome] = str(c["p"])
                                    break
                        if prices:
                            snap_ts = datetime.fromtimestamp(ts, tz=timezone.utc)
                            d = snap_ts.strftime("%Y-%m-%d")
                            if (mkt["id"], d) not in existing:
                                session.add(PriceSnapshot(
                                    market_id=mkt["id"],
                                    timestamp=snap_ts,
                                    prices=prices,
                                    midpoints=prices,
                                ))
                                existing.add((mkt["id"], d))
                                inserted += 1
                    await session.commit()

                total_inserted += inserted
                with_data += 1
            else:
                empty += 1

            if (i + 1) % 200 == 0:
                log.info("clob_progress", done=i+1, total=len(uncovered),
                         with_data=with_data, empty=empty, inserted=total_inserted)

    print(f"  CLOB stage: {with_data} markets had data, {empty} empty, "
          f"{total_inserted} snapshots inserted")
    return total_inserted


# ═══════════════════════════════════════════════════════════════════
#  Stage 3: Coverage summary
# ═══════════════════════════════════════════════════════════════════

async def print_summary(all_mids: set[int]):
    async with SessionFactory() as session:
        total = len(all_mids)

        # Markets with any snapshot in validation window
        ws = datetime(2026, 3, 20, tzinfo=timezone.utc)
        we = datetime(2026, 3, 26, 23, 59, 59, tzinfo=timezone.utc)
        usable_end = datetime(2026, 3, 25, 23, 59, 59, tzinfo=timezone.utc)

        window_covered = (await session.execute(text("""
            SELECT COUNT(DISTINCT ps.market_id) FROM price_snapshots ps
            WHERE ps.market_id IN (
                SELECT DISTINCT m FROM (
                    SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                    UNION
                    SELECT market_b_id AS m FROM market_pairs WHERE verified = true
                ) x
            )
            AND ps.timestamp >= :ws
            AND ps.timestamp <= :we
        """), {"ws": ws, "we": we})).scalar()

        # Markets with any snapshot <= Mar 25 (usable by backtest)
        usable = (await session.execute(text("""
            SELECT COUNT(DISTINCT ps.market_id) FROM price_snapshots ps
            WHERE ps.market_id IN (
                SELECT DISTINCT m FROM (
                    SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                    UNION
                    SELECT market_b_id AS m FROM market_pairs WHERE verified = true
                ) x
            )
            AND ps.timestamp <= :ue
        """), {"ue": usable_end})).scalar()

        # Snapshot date distribution for validation window
        dist = (await session.execute(text("""
            SELECT DATE(timestamp) as d, COUNT(*) as cnt, COUNT(DISTINCT market_id) as mkt
            FROM price_snapshots
            WHERE timestamp >= :ws
            AND timestamp <= :we
            GROUP BY DATE(timestamp)
            ORDER BY d
        """), {"ws": ws, "we": we})).fetchall()

    print(f"\n{'=' * 70}")
    print(f"  VALIDATION WINDOW COVERAGE  (Mar 20-25, 2026)")
    print(f"{'=' * 70}")
    print(f"  Total pair markets:              {total}")
    print(f"  With window snapshot (Mar 20-26): {window_covered} ({100*window_covered/max(total,1):.1f}%)")
    print(f"  With any snapshot <= Mar 25:      {usable} ({100*usable/max(total,1):.1f}%)")
    print(f"\n  Per-date snapshots:")
    for r in dist:
        print(f"    {r[0]}: {r.cnt:>5} snapshots, {r.mkt:>5} markets")
    print(f"{'=' * 70}\n")


async def main():
    parser = argparse.ArgumentParser(description="Prep validation window Mar 20-25")
    parser.add_argument("--pmxt-only", action="store_true")
    parser.add_argument("--clob-only", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )
    await init_db()

    token_map, all_mids = await load_token_map()
    existing = await existing_snapshot_days(all_mids)

    do_all = not args.pmxt_only and not args.clob_only and not args.summary_only

    if do_all or args.pmxt_only:
        print(f"\n── Stage 1: PMXT T12 backfill ──")
        await pmxt_stage(token_map, all_mids, existing)

    if do_all or args.clob_only:
        print(f"\n── Stage 2: CLOB backfill for uncovered ──")
        await clob_stage(all_mids, existing)

    print(f"\n── Stage 3: Coverage summary ──")
    await print_summary(all_mids)


if __name__ == "__main__":
    asyncio.run(main())
