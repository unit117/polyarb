"""PMXT thin-slice spike: extract prices from Feb 22-28, 2026 orderbook snapshots.

Downloads one midday (T12) PMXT orderbook snapshot per day, extracts best bid/ask
for markets in verified pairs, and inserts PriceSnapshot rows into backtest DB.

This is a bounded spike — not a general framework.

Usage (inside dataset-bootstrap or backtest container):
    python -m scripts.pmxt_spike_backfill
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import structlog

sys.path.insert(0, ".")

from shared.db import SessionFactory, init_db
from shared.models import Market, MarketPair, PriceSnapshot

log = structlog.get_logger()

# Bounded spike window — proven available via HTTP 200 probes
SPIKE_DATES = [
    "2026-02-22",
    "2026-02-23",
    "2026-02-24",
    "2026-02-25",
    "2026-02-26",
    "2026-02-27",
    "2026-02-28",
]
SNAPSHOT_HOUR = "T12"  # midday snapshot
BASE_URL = "https://r2.pmxt.dev"
TOKEN_ID_RE = re.compile(r'"token_id":\s*"?(\d+)"?')
BEST_BID_RE = re.compile(r'"best_bid":\s*"([^"]*)"')
BEST_ASK_RE = re.compile(r'"best_ask":\s*"([^"]*)"')


async def load_pair_token_map() -> tuple[dict[str, tuple[int, str]], set[str]]:
    """Build token_id -> (market_id, outcome) map for verified pair markets.

    Returns (token_map, all_token_ids).
    """
    token_map: dict[str, tuple[int, str]] = {}

    async with SessionFactory() as session:
        from sqlalchemy import select, text

        # Get distinct market IDs from verified pairs
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

    all_tokens = set(token_map.keys())
    log.info("token_map_loaded", tokens=len(all_tokens),
             markets=len({v[0] for v in token_map.values()}))
    return token_map, all_tokens


def download_pmxt_file(date_str: str) -> Path | None:
    """Download one PMXT hourly snapshot to a temp file. Returns path or None."""
    import urllib.request
    import urllib.error

    filename = f"polymarket_orderbook_{date_str}{SNAPSHOT_HOUR}.parquet"
    url = f"{BASE_URL}/{filename}"

    tmp = Path(tempfile.mkdtemp()) / filename
    log.info("downloading_pmxt", url=url, dest=str(tmp))

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
        with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                f.write(chunk)
        size_mb = tmp.stat().st_size / (1024 * 1024)
        log.info("download_complete", file=filename, size_mb=round(size_mb, 1))
        return tmp
    except urllib.error.HTTPError as e:
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

    Returns {token_id: (best_bid, best_ask)} using the LAST occurrence
    per token (latest update in the file).

    Processes row-group by row-group for memory efficiency.
    """
    import pyarrow.parquet as pq

    prices: dict[str, tuple[float, float]] = {}
    rows_scanned = 0
    matches = 0

    pf = pq.ParquetFile(str(parquet_path))
    num_rg = pf.metadata.num_row_groups
    log.info("scanning_parquet", file=parquet_path.name,
             row_groups=num_rg, target_tokens=len(target_tokens))

    for rg_idx in range(num_rg):
        table = pf.read_row_group(rg_idx, columns=["data"])
        data_col = table.column("data")
        rows_scanned += len(data_col)

        for val in data_col.to_pylist():
            if val is None:
                continue

            # Fast token_id check first
            tid_match = TOKEN_ID_RE.search(val)
            if not tid_match:
                continue
            tid = tid_match.group(1)
            if tid not in target_tokens:
                continue

            # Extract best bid/ask
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
            matches += 1

        if (rg_idx + 1) % 10 == 0:
            log.info("scan_progress", row_group=rg_idx + 1, of=num_rg,
                     rows=rows_scanned, matches=matches)

    log.info("scan_complete", rows=rows_scanned, tokens_found=len(prices),
             total_matches=matches)
    return prices


def build_market_snapshots(
    token_prices: dict[str, tuple[float, float]],
    token_map: dict[str, tuple[int, str]],
) -> dict[int, dict[str, float]]:
    """Convert per-token bid/ask into per-market price dicts.

    Returns {market_id: {outcome: midpoint_price}}.
    """
    market_prices: dict[int, dict[str, float]] = {}

    for tid, (best_bid, best_ask) in token_prices.items():
        if tid not in token_map:
            continue
        market_id, outcome = token_map[tid]
        mid = (best_bid + best_ask) / 2.0
        market_prices.setdefault(market_id, {})[outcome] = mid

    return market_prices


async def insert_snapshots(
    market_prices: dict[int, dict[str, float]],
    date_str: str,
) -> int:
    """Insert PriceSnapshot rows for one day. Skip existing. Returns count inserted."""
    ts = datetime.fromisoformat(date_str).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )

    inserted = 0
    async with SessionFactory() as session:
        from sqlalchemy import select, and_

        for market_id, prices in market_prices.items():
            # Check for existing snapshot
            existing = await session.execute(
                select(PriceSnapshot.id)
                .where(and_(
                    PriceSnapshot.market_id == market_id,
                    PriceSnapshot.timestamp == ts,
                ))
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                continue

            snap = PriceSnapshot(
                market_id=market_id,
                timestamp=ts,
                prices={k: str(round(v, 6)) for k, v in prices.items()},
                midpoints={k: str(round(v, 6)) for k, v in prices.items()},
            )
            session.add(snap)
            inserted += 1

        await session.commit()

    return inserted


async def main():
    await init_db()

    # Step 1: Build token map from backtest DB
    token_map, target_tokens = await load_pair_token_map()
    if not target_tokens:
        log.error("no_tokens_found")
        return

    # Step 2: Process each day
    total_inserted = 0
    coverage: dict[str, int] = {}

    for date_str in SPIKE_DATES:
        log.info("processing_date", date=date_str)

        # Download
        parquet_path = download_pmxt_file(date_str)
        if not parquet_path:
            coverage[date_str] = 0
            continue

        try:
            # Extract prices for our tokens
            token_prices = extract_prices_from_parquet(parquet_path, target_tokens)

            # Convert to market-level snapshots
            market_snapshots = build_market_snapshots(token_prices, token_map)

            # Insert
            inserted = await insert_snapshots(market_snapshots, date_str)
            total_inserted += inserted
            coverage[date_str] = len(market_snapshots)

            log.info("day_complete", date=date_str,
                     tokens_matched=len(token_prices),
                     markets_with_prices=len(market_snapshots),
                     snapshots_inserted=inserted)
        finally:
            # Clean up temp file
            try:
                parquet_path.unlink()
                parquet_path.parent.rmdir()
            except OSError:
                pass

    # Step 3: Coverage summary
    async with SessionFactory() as session:
        from sqlalchemy import text

        total_pair_snaps = await session.scalar(text(
            "SELECT count(*) FROM price_snapshots WHERE market_id IN "
            "(SELECT DISTINCT m FROM (SELECT market_a_id AS m FROM market_pairs WHERE verified = true "
            "UNION SELECT market_b_id AS m FROM market_pairs WHERE verified = true) x) "
            "AND timestamp >= '2026-02-22'::timestamptz AND timestamp <= '2026-02-28 23:59:59'::timestamptz"
        ))
        markets_with_snaps = await session.scalar(text(
            "SELECT count(DISTINCT market_id) FROM price_snapshots WHERE market_id IN "
            "(SELECT DISTINCT m FROM (SELECT market_a_id AS m FROM market_pairs WHERE verified = true "
            "UNION SELECT market_b_id AS m FROM market_pairs WHERE verified = true) x) "
            "AND timestamp >= '2026-02-22'::timestamptz AND timestamp <= '2026-02-28 23:59:59'::timestamptz"
        ))
        pairs_both = await session.scalar(text(
            "SELECT count(*) FROM market_pairs mp WHERE mp.verified = true "
            "AND mp.market_a_id IN (SELECT DISTINCT market_id FROM price_snapshots "
            "WHERE timestamp >= '2026-02-22'::timestamptz AND timestamp <= '2026-02-28 23:59:59'::timestamptz) "
            "AND mp.market_b_id IN (SELECT DISTINCT market_id FROM price_snapshots "
            "WHERE timestamp >= '2026-02-22'::timestamptz AND timestamp <= '2026-02-28 23:59:59'::timestamptz)"
        ))

    print("\n" + "=" * 65)
    print("  PMXT SPIKE BACKFILL: Feb 22-28, 2026")
    print("=" * 65)
    print(f"  Total snapshots inserted:    {total_inserted}")
    print(f"  Per-day coverage:")
    for d, c in coverage.items():
        print(f"    {d}: {c} markets")
    print(f"  ── Feb 22-28 window ──")
    print(f"    Pair-market snapshots:     {total_pair_snaps}")
    print(f"    Pair markets with data:    {markets_with_snaps} / {len(set(v[0] for v in token_map.values()))}")
    print(f"    Pairs with BOTH sides:     {pairs_both} / 294")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
