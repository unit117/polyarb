"""Filter PMXT archive parquet files to only markets relevant to polyarb.

Reads PMXT hourly order-book parquet files row-group by row-group to stay
within memory limits (~200MB peak instead of loading full files).

Two filter modes:
  1. --market-ids FILE   : a text file with one condition_id hex per line
  2. --db                : query the polyarb DB for known markets and build
                           a condition_id set from markets.polymarket_id
                           (works for backtest DBs where polymarket_id IS the
                           condition_id) or from token_ids (for live DBs).

Output: one filtered parquet per input file, written to --output-dir.
Only rows whose market_id appears in the filter set are kept.

Designed to run on NAS where RAM is limited but disk is plentiful.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def load_market_ids_from_file(path: str) -> set[str]:
    """Load condition_id hex strings from a text file, one per line."""
    ids: set[str] = set()
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                ids.add(stripped)
    print(f"Loaded {len(ids)} market IDs from {path}")
    return ids


def load_market_ids_from_db(db_url: str) -> set[str]:
    """Query polyarb DB for known market identifiers.

    Returns condition_id hex strings. For backtest DBs (Becker dataset),
    polymarket_id IS the condition_id. For live DBs, we also extract
    token_ids for cross-referencing.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(db_url)
    ids: set[str] = set()

    with engine.connect() as conn:
        # polymarket_id — in backtest DBs this is the condition_id hex
        rows = conn.execute(
            text("SELECT polymarket_id FROM markets WHERE venue = 'polymarket'")
        ).fetchall()
        for (pid,) in rows:
            if pid:
                ids.add(pid)

        print(f"Loaded {len(ids)} polymarket_ids from DB")

    engine.dispose()
    return ids


def load_token_id_to_market_map(db_url: str) -> dict[str, str]:
    """Build a mapping from CLOB token_id -> polymarket_id for live DBs.

    PMXT data contains token_id in the JSON data field. If our DB stores
    token_ids, we can use this as a secondary join key.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(db_url)
    token_map: dict[str, str] = {}

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT polymarket_id, token_ids FROM markets WHERE venue = 'polymarket' AND token_ids IS NOT NULL")
        ).fetchall()
        for pid, tids in rows:
            if tids:
                tokens = tids if isinstance(tids, list) else json.loads(tids)
                for t in tokens:
                    token_map[str(t)] = pid

    engine.dispose()
    print(f"Built token_id map: {len(token_map)} tokens -> {len(set(token_map.values()))} markets")
    return token_map


def extract_token_ids_from_data(data_col: pa.Array) -> list[str | None]:
    """Extract token_id from the JSON data column without full parse.

    Uses string search for speed — the token_id field is always present
    and always follows the pattern "token_id": "DIGITS".
    """
    import re
    pattern = re.compile(r'"token_id":\s*"?(\d+)"?')
    results: list[str | None] = []
    for val in data_col.to_pylist():
        if val is None:
            results.append(None)
            continue
        m = pattern.search(val)
        results.append(m.group(1) if m else None)
    return results


def filter_file(
    input_path: Path,
    output_dir: Path,
    market_ids: set[str],
    token_map: dict[str, str] | None = None,
) -> dict[str, int]:
    """Filter one parquet file, writing only matching rows.

    Returns stats dict with rows_in, rows_out, markets_matched.
    """
    pf = pq.ParquetFile(input_path)
    schema = pf.schema_arrow
    out_path = output_dir / input_path.name

    stats = {"rows_in": 0, "rows_out": 0, "markets_matched": set()}
    writer = None

    try:
        for i in range(pf.metadata.num_row_groups):
            table = pf.read_row_group(i)
            stats["rows_in"] += len(table)

            # Primary filter: market_id column
            mid_col = table.column("market_id")
            mask = pa.array(
                [mid in market_ids for mid in mid_col.to_pylist()],
                type=pa.bool_(),
            )

            # Secondary filter: token_id in data JSON (for live DB join)
            if token_map:
                data_col = table.column("data")
                token_ids = extract_token_ids_from_data(data_col)
                token_mask = pa.array(
                    [
                        (tid is not None and tid in token_map)
                        for tid in token_ids
                    ],
                    type=pa.bool_(),
                )
                # OR the two masks
                mask = pa.compute.or_(mask, token_mask)

            filtered = table.filter(mask)

            if len(filtered) > 0:
                if writer is None:
                    writer = pq.ParquetWriter(str(out_path), schema)
                writer.write_table(filtered)

                for mid in filtered.column("market_id").to_pylist():
                    stats["markets_matched"].add(mid)

            stats["rows_out"] += len(filtered)

            # Progress per row group
            pct = (i + 1) / pf.metadata.num_row_groups * 100
            print(
                f"  row_group {i + 1}/{pf.metadata.num_row_groups} "
                f"({pct:.0f}%) — kept {len(filtered):,}/{len(table):,}",
                end="\r",
            )

            del table, filtered

        print()  # newline after progress
    finally:
        if writer is not None:
            writer.close()

    stats["markets_matched"] = len(stats["markets_matched"])

    if stats["rows_out"] == 0 and out_path.exists():
        out_path.unlink()

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_dir",
        help="Directory containing PMXT parquet files",
    )
    parser.add_argument(
        "--output-dir", "-o",
        required=True,
        help="Directory to write filtered parquet files",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--market-ids",
        help="Text file with condition_id hex strings, one per line",
    )
    group.add_argument(
        "--db",
        help="PostgreSQL connection URL to query market IDs from",
    )
    parser.add_argument(
        "--use-token-ids",
        action="store_true",
        help="Also filter by token_id from data JSON (slower, for live DBs)",
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build filter set
    if args.market_ids:
        market_ids = load_market_ids_from_file(args.market_ids)
    else:
        market_ids = load_market_ids_from_db(args.db)

    token_map = None
    if args.use_token_ids and args.db:
        token_map = load_token_id_to_market_map(args.db)

    if not market_ids and not token_map:
        print("ERROR: No market IDs to filter by", file=sys.stderr)
        return 1

    # Find input files
    files = sorted(
        p for p in input_dir.iterdir()
        if p.suffix == ".parquet"
    )
    if not files:
        print(f"No parquet files found in {input_dir}", file=sys.stderr)
        return 1

    print(f"\nFiltering {len(files)} files against {len(market_ids)} market IDs")
    if token_map:
        print(f"Also matching {len(token_map)} token IDs")
    print(f"Output: {output_dir}\n")

    total_in = 0
    total_out = 0
    total_markets = set()

    for f in files:
        print(f"Processing {f.name} ({f.stat().st_size / 1e6:.0f} MB)...")
        t0 = time.time()
        stats = filter_file(f, output_dir, market_ids, token_map)
        elapsed = time.time() - t0

        total_in += stats["rows_in"]
        total_out += stats["rows_out"]

        ratio = stats["rows_out"] / stats["rows_in"] * 100 if stats["rows_in"] else 0
        print(
            f"  → {stats['rows_out']:,}/{stats['rows_in']:,} rows kept "
            f"({ratio:.1f}%), {stats['markets_matched']} markets matched, "
            f"{elapsed:.1f}s"
        )

    print(f"\n=== TOTAL ===")
    print(f"Rows: {total_out:,} / {total_in:,} kept ({total_out / total_in * 100:.1f}%)")

    # Check output sizes
    out_files = list(output_dir.glob("*.parquet"))
    out_size = sum(f.stat().st_size for f in out_files)
    print(f"Output files: {len(out_files)}, total size: {out_size / 1e6:.1f} MB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
