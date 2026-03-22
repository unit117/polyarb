"""Import authoritative resolution outcomes from Jon-Becker's dataset.

Reads resolved Polymarket markets from Parquet files via DuckDB and writes
resolved_outcome + resolved_at into the backtest DB's markets table.

This lets the backtest settle from real outcomes instead of the price >= 0.98
heuristic, reusing the same settlement path as the live simulator.

First pass: Polymarket only. Kalshi can be added once this path is proven.

Prerequisites:
  - Dataset downloaded to NAS: /volume1/data/prediction-market-analysis/
  - DuckDB + pyarrow installed in the backtest container
  - Backtest DB bootstrapped via backtest_setup.py

Usage:
    python -m scripts.import_resolved_outcomes [--dataset-path PATH] [--dry-run]
"""

import argparse
import asyncio
import sys

import structlog

sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db

log = structlog.get_logger()

# Default dataset path on NAS (mounted into container)
DEFAULT_DATASET_PATH = "/data/prediction-market-analysis/data"


def load_resolved_markets(dataset_path: str) -> list[dict]:
    """Read resolved Polymarket markets from Parquet via DuckDB.

    The Jon-Becker dataset schema:
      - condition_id: hex hash (NOT the same as our Gamma API polymarket_id)
      - clob_token_ids: JSON array of token IDs (matches our markets.token_ids)
      - outcomes: JSON array like '["Yes", "No"]'
      - outcome_prices: JSON array like '["0.99...", "0.00..."]'
      - closed: boolean
      - end_date: timestamp

    Resolution is encoded in outcome_prices: winning outcome → ~1.0.
    Join key is clob_token_ids (matches our markets.token_ids).

    Returns list of dicts with keys: token_id, outcome, resolved_at
    """
    import duckdb
    import json

    con = duckdb.connect(":memory:")

    # Try sharded parquet glob first, then single file
    markets_glob = f"{dataset_path}/polymarket/markets/markets_*.parquet"
    try:
        count = con.execute(
            f"SELECT count(*) FROM read_parquet('{markets_glob}')"
        ).fetchone()[0]
        markets_file = markets_glob
        log.info("found_parquet_shards", pattern=markets_file, total_rows=count)
    except Exception:
        # Fallback to single file
        markets_file = f"{dataset_path}/polymarket/markets.parquet"
        try:
            count = con.execute(
                f"SELECT count(*) FROM read_parquet('{markets_file}')"
            ).fetchone()[0]
            log.info("found_parquet_single", path=markets_file, total_rows=count)
        except Exception:
            log.error(
                "no_parquet_found",
                dataset_path=dataset_path,
                hint="Download the dataset first: see ECOSYSTEM_PLAN.md E1a1",
            )
            return []

    # Query closed markets with outcome prices
    rows = con.execute(f"""
        SELECT clob_token_ids, outcomes, outcome_prices, end_date
        FROM read_parquet('{markets_file}')
        WHERE closed = true
          AND clob_token_ids IS NOT NULL
          AND outcome_prices IS NOT NULL
    """).fetchall()
    log.info("closed_markets_loaded", count=len(rows))

    results = []
    for clob_tokens_str, outcomes_str, prices_str, end_date in rows:
        try:
            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            tokens = json.loads(clob_tokens_str) if isinstance(clob_tokens_str, str) else clob_tokens_str
        except (json.JSONDecodeError, TypeError):
            continue

        if not outcomes or not prices or not tokens:
            continue
        if len(outcomes) != len(prices):
            continue

        # Determine winner: outcome with price closest to 1.0
        # Skip markets where no outcome clearly won (all prices near 0 or near 0.5)
        max_price = -1.0
        winner = None
        for outcome, price_str in zip(outcomes, prices):
            try:
                p = float(price_str)
            except (ValueError, TypeError):
                continue
            if p > max_price:
                max_price = p
                winner = outcome

        if winner is None or max_price < 0.90:
            # No clear resolution — skip
            continue

        # Use first token ID as join key (each token maps to one market row)
        for token in tokens:
            results.append({
                "token_id": str(token).strip('"'),
                "outcome": winner,
                "resolved_at": end_date,
            })

    con.close()
    log.info("resolved_entries", count=len(results))
    return results


async def import_outcomes(
    resolved: list[dict],
    dry_run: bool = False,
) -> dict:
    """Match resolved markets to our DB and update resolved_outcome/resolved_at.

    Join key: token_ids from dataset ↔ markets.token_ids in our DB.
    Each market row stores token_ids as a JSONB array of token ID strings.
    """
    import json
    from sqlalchemy import select, update
    from shared.models import Market

    stats = {
        "total_resolved": len(resolved),
        "matched": 0,
        "unmatched_tokens": 0,
        "already_resolved": 0,
        "updated": 0,
    }

    # Build lookup: token_id → resolution info
    resolution_map = {}
    for entry in resolved:
        resolution_map[entry["token_id"]] = entry

    log.info("resolution_map_built", unique_tokens=len(resolution_map))

    async with SessionFactory() as session:
        # Load all polymarket markets with their token_ids
        result = await session.execute(
            select(Market.id, Market.token_ids, Market.resolved_outcome)
            .where(Market.venue == "polymarket")
        )
        db_markets = result.all()

        log.info("db_markets_loaded", count=len(db_markets))

        updates = []
        for market_id, token_ids, existing_outcome in db_markets:
            if not token_ids:
                continue

            # token_ids is a JSONB array — check each token
            tokens = token_ids if isinstance(token_ids, list) else json.loads(token_ids)
            resolution = None
            for token in tokens:
                resolution = resolution_map.get(str(token).strip('"'))
                if resolution:
                    break

            if not resolution:
                stats["unmatched_tokens"] += 1
                continue

            stats["matched"] += 1

            if existing_outcome:
                stats["already_resolved"] += 1
                continue

            update_vals = {"resolved_outcome": resolution["outcome"]}
            if "resolved_at" in resolution and resolution["resolved_at"] is not None:
                update_vals["resolved_at"] = resolution["resolved_at"]

            updates.append((market_id, update_vals))

        if dry_run:
            stats["would_update"] = len(updates)
            log.info("dry_run_results", **stats)
            return stats

        # Batch update
        for market_id, vals in updates:
            await session.execute(
                update(Market).where(Market.id == market_id).values(**vals)
            )
            stats["updated"] += 1

        await session.commit()

    log.info("import_complete", **stats)
    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Import resolved outcomes from Jon-Becker dataset"
    )
    parser.add_argument(
        "--dataset-path", type=str, default=DEFAULT_DATASET_PATH,
        help=f"Path to prediction-market-analysis data (default: {DEFAULT_DATASET_PATH})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be updated without writing to DB",
    )
    args = parser.parse_args()

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
    await init_db()

    log.info("loading_dataset", path=args.dataset_path)
    resolved = load_resolved_markets(args.dataset_path)

    if not resolved:
        log.error("no_resolved_data")
        return

    stats = await import_outcomes(resolved, dry_run=args.dry_run)

    # Print coverage summary
    if stats["matched"] > 0:
        match_rate = stats["matched"] / stats["total_resolved"] * 100
        unmatched = stats.get("unmatched_tokens", 0)
        coverage = stats["matched"] / (stats["matched"] + unmatched) * 100
        log.info(
            "coverage_summary",
            match_rate_pct=round(match_rate, 1),
            db_coverage_pct=round(coverage, 1),
            total_in_dataset=stats["total_resolved"],
            matched_in_db=stats["matched"],
        )


if __name__ == "__main__":
    asyncio.run(main())
