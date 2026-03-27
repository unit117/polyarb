"""Widen PMXT price corpus for Feb 22-27 backtest window.

The original pmxt_spike_backfill.py only downloaded T12 (noon) snapshots for
Feb 22-28. This script widens coverage by:

1. Downloading multiple hours per day (T00, T06, T12, T18) instead of just T12
2. Extending the date range to Feb 15-28 for stale-but-usable pre-window prices
   (backtest get_prices_at uses timestamp <= as_of, so Feb 20 data works on Feb 22)
3. Deduplicating: only one snapshot per market per day (keeps best bid/ask from
   whichever hour had the most data)

Processes files one at a time to stay within memory limits (~200MB peak).
Idempotent — skips markets that already have a snapshot on a given day.

Usage (inside backtest container):
    python -m scripts.widen_pmxt_prices [--probe] [--hours 0,6,12,18] [--start 2026-02-15]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import structlog

sys.path.insert(0, ".")

from shared.db import SessionFactory, init_db
from shared.models import Market, PriceSnapshot

log = structlog.get_logger()

BASE_URL = "https://r2.pmxt.dev"
TOKEN_ID_RE = re.compile(r'"token_id":\s*"?(\d+)"?')
BEST_BID_RE = re.compile(r'"best_bid":\s*"([^"]*)"')
BEST_ASK_RE = re.compile(r'"best_ask":\s*"([^"]*)"')


async def load_all_pair_tokens() -> tuple[dict[str, tuple[int, str]], set[int]]:
    """Build token_id -> (market_id, outcome) for ALL markets in verified pairs.

    Returns (token_map, all_market_ids).
    """
    from sqlalchemy import select, text

    token_map: dict[str, tuple[int, str]] = {}

    async with SessionFactory() as session:
        rows = await session.execute(text("""
            SELECT DISTINCT m FROM (
                SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                UNION
                SELECT market_b_id AS m FROM market_pairs WHERE verified = true
            ) x
        """))
        pair_market_ids = {r[0] for r in rows}

        result = await session.execute(
            select(Market.id, Market.outcomes, Market.token_ids)
            .where(Market.id.in_(pair_market_ids))
        )

        for market_id, outcomes, tokens in result.all():
            if not tokens or not outcomes:
                continue
            token_list = tokens if isinstance(tokens, list) else json.loads(tokens)
            outcome_list = outcomes if isinstance(outcomes, list) else json.loads(outcomes)
            for outcome, token in zip(outcome_list, token_list):
                token_map[str(token)] = (market_id, outcome)

    all_market_ids = {v[0] for v in token_map.values()}
    log.info("token_map_loaded", tokens=len(token_map), markets=len(all_market_ids))
    return token_map, all_market_ids


async def get_existing_snapshot_days(market_ids: set[int]) -> set[tuple[int, str]]:
    """Return set of (market_id, date_str) for existing snapshots."""
    from sqlalchemy import select

    existing = set()
    async with SessionFactory() as session:
        result = await session.execute(
            select(PriceSnapshot.market_id, PriceSnapshot.timestamp)
            .where(PriceSnapshot.market_id.in_(market_ids))
        )
        for mid, ts in result.all():
            existing.add((mid, ts.strftime("%Y-%m-%d")))

    log.info("existing_snapshots", market_days=len(existing))
    return existing


def download_pmxt_file(date_str: str, hour: int) -> Path | None:
    """Download one PMXT hourly snapshot to a temp file."""
    import urllib.request
    import urllib.error

    hour_str = f"T{hour:02d}"
    filename = f"polymarket_orderbook_{date_str}{hour_str}.parquet"
    url = f"{BASE_URL}/{filename}"

    tmp = Path(tempfile.mkdtemp()) / filename
    log.info("downloading", url=url)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        size_mb = tmp.stat().st_size / (1024 * 1024)
        log.info("downloaded", file=filename, size_mb=round(size_mb, 1))
        return tmp
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.debug("not_found", file=filename)
        else:
            log.warning("download_failed", url=url, status=e.code)
        return None
    except Exception as e:
        log.warning("download_error", url=url, error=str(e))
        return None


def extract_prices_from_parquet(
    parquet_path: Path,
    target_tokens: set[str],
) -> dict[str, tuple[float, float]]:
    """Scan PMXT parquet for target token_ids, extract best bid/ask.

    Returns {token_id: (best_bid, best_ask)}.
    """
    import pyarrow.parquet as pq

    prices: dict[str, tuple[float, float]] = {}

    pf = pq.ParquetFile(str(parquet_path))
    num_rg = pf.metadata.num_row_groups

    for rg_idx in range(num_rg):
        table = pf.read_row_group(rg_idx, columns=["data"])
        data_col = table.column("data")

        for val in data_col.to_pylist():
            if val is None:
                continue

            tid_match = TOKEN_ID_RE.search(val)
            if not tid_match:
                continue
            tid = tid_match.group(1)
            if tid not in target_tokens:
                continue

            bid_match = BEST_BID_RE.search(val)
            ask_match = BEST_ASK_RE.search(val)
            if not bid_match or not ask_match:
                continue

            try:
                best_bid = float(bid_match.group(1))
                best_ask = float(ask_match.group(1))
            except (ValueError, TypeError):
                continue

            if best_bid <= 0 or best_ask <= 0 or best_bid > 1 or best_ask > 1:
                continue

            prices[tid] = (best_bid, best_ask)

    log.info("scan_complete", file=parquet_path.name, tokens_found=len(prices))
    return prices


async def insert_day_snapshots(
    market_prices: dict[int, dict[str, float]],
    date_str: str,
    existing: set[tuple[int, str]],
) -> int:
    """Insert PriceSnapshot rows for one day. Skip existing. Returns count."""
    from sqlalchemy import select, and_

    ts = datetime.fromisoformat(date_str).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )

    inserted = 0
    async with SessionFactory() as session:
        for market_id, prices in market_prices.items():
            if (market_id, date_str) in existing:
                continue

            snap = PriceSnapshot(
                market_id=market_id,
                timestamp=ts,
                prices={k: str(round(v, 6)) for k, v in prices.items()},
                midpoints={k: str(round(v, 6)) for k, v in prices.items()},
            )
            session.add(snap)
            existing.add((market_id, date_str))
            inserted += 1

        await session.commit()

    return inserted


async def probe_mode(token_map, target_tokens, existing):
    """Download a few files and report incremental coverage without inserting."""
    # Check one day across different hours
    test_date = "2026-02-22"
    hours_to_probe = [0, 6, 12, 18]
    seen_markets_by_hour: dict[int, set[int]] = {}
    cumulative = set()

    for hour in hours_to_probe:
        parquet_path = download_pmxt_file(test_date, hour)
        if not parquet_path:
            print(f"  T{hour:02d}: NOT AVAILABLE")
            continue

        try:
            token_prices = extract_prices_from_parquet(parquet_path, target_tokens)
            markets_this_hour = set()
            for tid in token_prices:
                if tid in token_map:
                    markets_this_hour.add(token_map[tid][0])

            new_markets = markets_this_hour - cumulative
            cumulative |= markets_this_hour

            print(f"  T{hour:02d}: {len(markets_this_hour)} markets, "
                  f"{len(new_markets)} NEW (cumulative: {len(cumulative)})")
            seen_markets_by_hour[hour] = markets_this_hour
        finally:
            try:
                parquet_path.unlink()
                parquet_path.parent.rmdir()
            except OSError:
                pass

    # Also probe a pre-window date
    pre_date = "2026-02-18"
    parquet_path = download_pmxt_file(pre_date, 12)
    if parquet_path:
        try:
            token_prices = extract_prices_from_parquet(parquet_path, target_tokens)
            markets_pre = set()
            for tid in token_prices:
                if tid in token_map:
                    markets_pre.add(token_map[tid][0])

            new_from_pre = markets_pre - cumulative
            print(f"\n  Pre-window {pre_date} T12: {len(markets_pre)} markets, "
                  f"{len(new_from_pre)} NEW beyond {test_date} all-hours")
        finally:
            try:
                parquet_path.unlink()
                parquet_path.parent.rmdir()
            except OSError:
                pass
    else:
        print(f"\n  Pre-window {pre_date} T12: NOT AVAILABLE")

    # Summary
    all_pair_markets = {v[0] for v in token_map.values()}
    already_covered = {mid for mid, _ in existing}
    new_from_widen = cumulative - already_covered

    print(f"\n  Total pair markets:          {len(all_pair_markets)}")
    print(f"  Already have snapshots:      {len(already_covered)}")
    print(f"  New from widening probes:    {len(new_from_widen)}")
    print(f"  Still uncovered:             {len(all_pair_markets - already_covered - cumulative)}")


async def main():
    parser = argparse.ArgumentParser(description="Widen PMXT price corpus")
    parser.add_argument("--probe", action="store_true",
                        help="Probe mode: check incremental coverage without inserting")
    parser.add_argument("--hours", type=str, default="0,6,12,18",
                        help="Comma-separated hours to download (default: 0,6,12,18)")
    parser.add_argument("--start", type=str, default="2026-02-15",
                        help="Start date (default: 2026-02-15, 7 days pre-window)")
    parser.add_argument("--end", type=str, default="2026-02-28",
                        help="End date (default: 2026-02-28)")
    args = parser.parse_args()

    hours = [int(h) for h in args.hours.split(",")]

    await init_db()

    # Load token map and existing snapshots
    token_map, all_market_ids = await load_all_pair_tokens()
    target_tokens = set(token_map.keys())
    existing = await get_existing_snapshot_days(all_market_ids)

    if args.probe:
        print("\n" + "=" * 70)
        print("  PROBE MODE — checking incremental coverage")
        print("=" * 70)
        await probe_mode(token_map, target_tokens, existing)
        return

    # Generate date range
    from datetime import timedelta
    start = datetime.fromisoformat(args.start).date()
    end = datetime.fromisoformat(args.end).date()
    dates = []
    d = start
    while d <= end:
        dates.append(str(d))
        d += timedelta(days=1)

    print(f"\n{'=' * 70}")
    print(f"  WIDEN PMXT PRICES")
    print(f"  Dates: {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print(f"  Hours: {hours}")
    print(f"  Total files to try: {len(dates) * len(hours)}")
    print(f"  Existing market-day snapshots: {len(existing)}")
    print(f"{'=' * 70}\n")

    total_inserted = 0
    total_new_markets = set()
    files_downloaded = 0
    files_failed = 0
    stats_per_date: dict[str, int] = {}

    for date_str in dates:
        # Accumulate best prices across all hours for this date
        day_market_prices: dict[int, dict[str, float]] = {}

        for hour in hours:
            parquet_path = download_pmxt_file(date_str, hour)
            if not parquet_path:
                files_failed += 1
                continue

            files_downloaded += 1
            try:
                token_prices = extract_prices_from_parquet(parquet_path, target_tokens)

                # Merge into day-level prices (later hours overwrite earlier)
                for tid, (bid, ask) in token_prices.items():
                    if tid not in token_map:
                        continue
                    market_id, outcome = token_map[tid]
                    mid = (bid + ask) / 2.0
                    day_market_prices.setdefault(market_id, {})[outcome] = mid
            finally:
                try:
                    parquet_path.unlink()
                    parquet_path.parent.rmdir()
                except OSError:
                    pass

        if not day_market_prices:
            stats_per_date[date_str] = 0
            continue

        # Insert (skip existing)
        inserted = await insert_day_snapshots(day_market_prices, date_str, existing)
        total_inserted += inserted
        stats_per_date[date_str] = inserted

        if inserted > 0:
            new_mids = {mid for mid in day_market_prices if (mid, date_str) not in existing}
            total_new_markets |= set(day_market_prices.keys())

        log.info("day_complete", date=date_str,
                 markets_found=len(day_market_prices),
                 inserted=inserted)

    # Final coverage check
    post_existing = await get_existing_snapshot_days(all_market_ids)

    # Window-specific stats (Feb 22-27)
    window_markets = set()
    for mid, d in post_existing:
        if "2026-02-22" <= d <= "2026-02-27":
            window_markets.add(mid)

    print(f"\n{'=' * 70}")
    print(f"  WIDENING COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Files downloaded:            {files_downloaded}")
    print(f"  Files unavailable:           {files_failed}")
    print(f"  Total snapshots inserted:    {total_inserted}")
    print(f"  New markets with data:       {len(total_new_markets)}")
    print(f"\n  Per-date insertions:")
    for d, cnt in sorted(stats_per_date.items()):
        marker = " [window]" if "2026-02-22" <= d <= "2026-02-27" else " [pre]"
        print(f"    {d}: {cnt:>5} inserted{marker}")

    print(f"\n  Window coverage (Feb 22-27):")
    print(f"    Markets with data:         {len(window_markets)} / {len(all_market_ids)}")
    print(f"    Coverage:                  {100*len(window_markets)/max(len(all_market_ids),1):.1f}%")

    all_covered = {mid for mid, _ in post_existing}
    print(f"\n  Overall coverage (any date):")
    print(f"    Markets with any snapshot: {len(all_covered)} / {len(all_market_ids)}")
    print(f"    Coverage:                  {100*len(all_covered)/max(len(all_market_ids),1):.1f}%")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    asyncio.run(main())
