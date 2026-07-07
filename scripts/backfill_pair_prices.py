"""Backfill price snapshots for verified pair markets from Becker dataset.

Targeted extraction: only processes the ~400 markets that appear in verified
pairs, and inserts missing PriceSnapshot rows without truncating existing data.

Usage (inside backtest container):
    python -m scripts.backfill_pair_prices \
        --dataset-path /data/prediction-market-analysis/data
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, text

sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.models import Market, MarketPair, PriceSnapshot

log = structlog.get_logger()


async def get_pair_market_info() -> dict[int, dict]:
    """Load market_id → {outcomes, tokens} for all markets in verified pairs."""
    async with SessionFactory() as session:
        # Get distinct market IDs from verified pairs
        rows = await session.execute(text("""
            SELECT DISTINCT m FROM (
                SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                UNION
                SELECT market_b_id AS m FROM market_pairs WHERE verified = true
            ) x
        """))
        pair_market_ids = {r[0] for r in rows}

        # Load their token_ids and outcomes
        result = await session.execute(
            select(Market.id, Market.polymarket_id, Market.outcomes, Market.token_ids)
            .where(Market.id.in_(pair_market_ids))
        )

        market_info = {}
        for market_id, poly_id, outcomes, tokens in result.all():
            if not tokens or not outcomes:
                continue
            token_list = tokens if isinstance(tokens, list) else json.loads(tokens)
            outcome_list = outcomes if isinstance(outcomes, list) else json.loads(outcomes)
            if not token_list or not outcome_list:
                continue
            market_info[market_id] = {
                "polymarket_id": poly_id,
                "outcomes": outcome_list,
                "tokens": token_list,
            }

        log.info("pair_markets_loaded",
                 pair_market_ids=len(pair_market_ids),
                 with_tokens=len(market_info))
        return market_info


def load_trade_prices(
    dataset_path: str,
    token_ids: set[str],
) -> dict[str, list[tuple]]:
    """Load trades for specific tokens and compute daily prices via DuckDB.

    Same logic as backtest_from_dataset.py but isolated for targeted use.
    """
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute("SET memory_limit='3GB'")
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")

    trades_glob = f"{dataset_path}/polymarket/trades/trades_*.parquet"
    blocks_glob = f"{dataset_path}/polymarket/blocks/blocks_*.parquet"

    log.info("loading_trades", token_count=len(token_ids))

    # Materialize blocks table once for fast joins
    log.info("materializing_blocks_table")
    con.execute(f"""
        CREATE TABLE blocks AS
        SELECT block_number, CAST(timestamp AS TIMESTAMP) as ts
        FROM read_parquet('{blocks_glob}')
        WHERE timestamp IS NOT NULL
    """)
    block_count = con.execute("SELECT count(*) FROM blocks").fetchone()[0]
    log.info("blocks_materialized", count=block_count)
    con.execute("CREATE INDEX idx_blocks_bn ON blocks(block_number)")

    token_list = list(token_ids)
    chunk_size = 200
    all_prices: dict[str, list[tuple]] = {}

    for i in range(0, len(token_list), chunk_size):
        chunk = token_list[i:i + chunk_size]
        token_csv = ",".join(f"'{t}'" for t in chunk)

        try:
            rows = con.execute(f"""
                SELECT
                    t.taker_asset_id as token_id,
                    DATE_TRUNC('day', b.ts) as trade_date,
                    AVG(CAST(t.maker_amount AS DOUBLE) / NULLIF(CAST(t.taker_amount AS DOUBLE), 0)) as avg_price,
                    COUNT(*) as trade_count
                FROM read_parquet('{trades_glob}') t
                JOIN blocks b ON t.block_number = b.block_number
                WHERE t.taker_asset_id IN ({token_csv})
                  AND t.taker_amount > 0
                GROUP BY 1, 2
                ORDER BY 1, 2
            """).fetchall()
        except Exception as e:
            log.warning("trade_chunk_error", chunk_start=i, error=str(e))
            continue

        for token_id, trade_date, avg_price, count in rows:
            if avg_price is None or avg_price <= 0 or avg_price > 1:
                continue
            all_prices.setdefault(token_id, []).append(
                (trade_date, float(avg_price))
            )

        log.info("trade_loading_progress",
                 processed=min(i + chunk_size, len(token_list)),
                 total=len(token_list))

    con.close()
    log.info("trade_prices_loaded", tokens_with_data=len(all_prices))
    return all_prices


async def get_existing_snapshots(market_ids: set[int]) -> set[tuple[int, str]]:
    """Return set of (market_id, date_str) for existing snapshots."""
    existing = set()
    async with SessionFactory() as session:
        result = await session.execute(
            select(PriceSnapshot.market_id, PriceSnapshot.timestamp)
            .where(PriceSnapshot.market_id.in_(market_ids))
        )
        for mid, ts in result.all():
            existing.add((mid, ts.strftime("%Y-%m-%d")))
    log.info("existing_snapshots", count=len(existing))
    return existing


async def insert_snapshots(
    market_info: dict[int, dict],
    trade_prices: dict[str, list[tuple]],
) -> dict:
    """Insert missing PriceSnapshot rows for pair markets."""
    existing = await get_existing_snapshots(set(market_info.keys()))

    stats = {"inserted": 0, "skipped_existing": 0, "markets_with_new_data": 0}

    async with SessionFactory() as session:
        for market_id, info in market_info.items():
            # Collect daily prices per outcome from token trade data
            date_prices: dict[str, dict[str, float]] = {}

            for outcome, token in zip(info["outcomes"], info["tokens"]):
                token_data = trade_prices.get(str(token), [])
                for trade_date, price in token_data:
                    date_key = (
                        str(trade_date.date())
                        if hasattr(trade_date, "date")
                        else str(trade_date)[:10]
                    )
                    date_prices.setdefault(date_key, {})[outcome] = price

            if not date_prices:
                continue

            new_for_market = 0
            for date_str, prices in sorted(date_prices.items()):
                if (market_id, date_str) in existing:
                    stats["skipped_existing"] += 1
                    continue

                try:
                    ts = datetime.fromisoformat(date_str).replace(
                        hour=23, minute=59, second=59, tzinfo=timezone.utc
                    )
                except ValueError:
                    continue

                snap = PriceSnapshot(
                    market_id=market_id,
                    timestamp=ts,
                    prices={k: str(v) for k, v in prices.items()},
                )
                session.add(snap)
                stats["inserted"] += 1
                new_for_market += 1

            if new_for_market > 0:
                stats["markets_with_new_data"] += 1

            # Batch commit every 50 markets
            if stats["markets_with_new_data"] % 50 == 0 and stats["markets_with_new_data"] > 0:
                await session.commit()
                log.info("insert_progress", **stats)

        await session.commit()

    log.info("backfill_complete", **stats)
    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Backfill price snapshots for verified pair markets from Becker dataset"
    )
    parser.add_argument(
        "--dataset-path",
        type=str,
        default="/data/prediction-market-analysis/data",
        help="Path to Becker dataset root",
    )
    args = parser.parse_args()

    await init_db()

    # Step 1: Get pair markets and their token IDs
    market_info = await get_pair_market_info()
    if not market_info:
        log.error("no_pair_markets")
        return

    # Collect all token IDs
    all_tokens: set[str] = set()
    for info in market_info.values():
        for token in info["tokens"]:
            all_tokens.add(str(token))

    log.info("tokens_to_fetch", count=len(all_tokens))

    # Step 2: Extract daily prices from Becker trades
    trade_prices = load_trade_prices(args.dataset_path, all_tokens)

    # Step 3: Insert missing snapshots
    stats = await insert_snapshots(market_info, trade_prices)

    # Step 4: Coverage summary
    async with SessionFactory() as session:
        total_snaps = await session.scalar(
            text("SELECT count(*) FROM price_snapshots WHERE market_id IN "
                 "(SELECT DISTINCT m FROM (SELECT market_a_id AS m FROM market_pairs WHERE verified = true "
                 "UNION SELECT market_b_id AS m FROM market_pairs WHERE verified = true) x)")
        )
        markets_with_snaps = await session.scalar(
            text("SELECT count(DISTINCT market_id) FROM price_snapshots WHERE market_id IN "
                 "(SELECT DISTINCT m FROM (SELECT market_a_id AS m FROM market_pairs WHERE verified = true "
                 "UNION SELECT market_b_id AS m FROM market_pairs WHERE verified = true) x)")
        )

    print("\n" + "=" * 60)
    print("  BACKFILL COMPLETE")
    print("=" * 60)
    print(f"  New snapshots inserted:   {stats['inserted']}")
    print(f"  Skipped (existing):       {stats['skipped_existing']}")
    print(f"  Markets with new data:    {stats['markets_with_new_data']}")
    print(f"  Total pair-market snaps:  {total_snaps}")
    print(f"  Pair markets with data:   {markets_with_snaps} / {len(market_info)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
