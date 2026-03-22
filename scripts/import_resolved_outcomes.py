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
DEFAULT_DATASET_PATH = "/data/prediction-market-analysis"


def load_resolved_markets(dataset_path: str) -> list[dict]:
    """Read resolved Polymarket markets from Parquet via DuckDB.

    Returns list of dicts with keys: condition_id, outcome, resolved_at
    """
    import duckdb

    # Jon-Becker's dataset stores Polymarket data under polymarket/ subdir.
    # The markets/conditions table has resolution info.
    # We try several likely file patterns since the exact layout may vary.
    con = duckdb.connect(":memory:")

    # Discover available parquet files
    parquet_candidates = [
        f"{dataset_path}/polymarket/markets.parquet",
        f"{dataset_path}/polymarket/conditions.parquet",
        f"{dataset_path}/data/polymarket/markets.parquet",
        f"{dataset_path}/data/polymarket/conditions.parquet",
    ]

    markets_file = None
    for path in parquet_candidates:
        try:
            con.execute(f"SELECT count(*) FROM read_parquet('{path}')")
            markets_file = path
            log.info("found_parquet", path=path)
            break
        except Exception:
            continue

    if not markets_file:
        # Try glob pattern
        try:
            result = con.execute(f"""
                SELECT count(*) FROM read_parquet('{dataset_path}/**/markets.parquet')
            """).fetchone()
            if result and result[0] > 0:
                markets_file = f"{dataset_path}/**/markets.parquet"
                log.info("found_parquet_glob", pattern=markets_file)
        except Exception:
            pass

    if not markets_file:
        log.error(
            "no_parquet_found",
            dataset_path=dataset_path,
            tried=parquet_candidates,
            hint="Download the dataset first: see ECOSYSTEM_PLAN.md E1a1",
        )
        return []

    # Inspect available columns
    columns = con.execute(
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = 'read_parquet'"
    )
    # Alternative: just describe
    schema = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{markets_file}') LIMIT 0").fetchall()
    col_names = [row[0] for row in schema]
    log.info("parquet_schema", columns=col_names)

    # Build query based on available columns
    # We need: some form of market ID (condition_id, id, market_id) + resolution status
    id_col = None
    for candidate in ["condition_id", "id", "market_id", "conditionId"]:
        if candidate in col_names:
            id_col = candidate
            break

    outcome_col = None
    for candidate in ["resolved_outcome", "outcome", "resolution", "winner", "result"]:
        if candidate in col_names:
            outcome_col = candidate
            break

    resolved_at_col = None
    for candidate in ["resolved_at", "resolution_time", "end_date_iso", "closed_at"]:
        if candidate in col_names:
            resolved_at_col = candidate
            break

    if not id_col:
        log.error("no_id_column", available=col_names)
        return []

    if not outcome_col:
        log.error("no_outcome_column", available=col_names)
        return []

    log.info(
        "column_mapping",
        id_col=id_col,
        outcome_col=outcome_col,
        resolved_at_col=resolved_at_col,
    )

    # Query resolved markets
    resolved_at_select = f", {resolved_at_col}" if resolved_at_col else ""
    query = f"""
        SELECT {id_col}, {outcome_col}{resolved_at_select}
        FROM read_parquet('{markets_file}')
        WHERE {outcome_col} IS NOT NULL
          AND {outcome_col} != ''
    """

    rows = con.execute(query).fetchall()
    log.info("resolved_rows_loaded", count=len(rows))

    results = []
    for row in rows:
        entry = {
            "condition_id": str(row[0]),
            "outcome": str(row[1]),
        }
        if resolved_at_col and len(row) > 2 and row[2] is not None:
            entry["resolved_at"] = row[2]
        results.append(entry)

    con.close()
    return results


async def import_outcomes(
    resolved: list[dict],
    dry_run: bool = False,
) -> dict:
    """Match resolved markets to our DB and update resolved_outcome/resolved_at.

    Join key: polymarket_id == condition_id from dataset.
    """
    from sqlalchemy import select, update
    from shared.models import Market

    stats = {
        "total_resolved": len(resolved),
        "matched": 0,
        "unmatched": 0,
        "already_resolved": 0,
        "updated": 0,
    }

    # Build lookup: condition_id → resolution info
    resolution_map = {}
    for entry in resolved:
        resolution_map[entry["condition_id"]] = entry

    async with SessionFactory() as session:
        # Load all polymarket markets
        result = await session.execute(
            select(Market.id, Market.polymarket_id, Market.resolved_outcome)
            .where(Market.venue == "polymarket")
        )
        db_markets = result.all()

        log.info("db_markets_loaded", count=len(db_markets))

        updates = []
        for market_id, polymarket_id, existing_outcome in db_markets:
            resolution = resolution_map.get(polymarket_id)
            if not resolution:
                stats["unmatched"] += 1
                continue

            stats["matched"] += 1

            if existing_outcome:
                stats["already_resolved"] += 1
                continue

            update_vals = {"resolved_outcome": resolution["outcome"]}
            if "resolved_at" in resolution:
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
        coverage = stats["matched"] / (stats["matched"] + stats["unmatched"]) * 100
        log.info(
            "coverage_summary",
            match_rate_pct=round(match_rate, 1),
            db_coverage_pct=round(coverage, 1),
            total_in_dataset=stats["total_resolved"],
            matched_in_db=stats["matched"],
        )


if __name__ == "__main__":
    asyncio.run(main())
