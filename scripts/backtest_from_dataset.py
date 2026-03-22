"""Bootstrap a backtest DB entirely from the Jon-Becker dataset.

Instead of copying from the live DB, this imports markets, price history,
and resolution outcomes directly from the Parquet files — enabling offline
backtest against historical data with authoritative settlement.

Steps:
  1. Load closed+resolved markets from dataset (scoped by date window)
  2. Insert into backtest DB markets table
  3. Build daily price snapshots from trade history
  4. Generate embeddings via OpenAI (batched)
  5. After this: run detector → backtest pipeline normally

Usage:
    python -m scripts.backtest_from_dataset \
        --dataset-path /data/prediction-market-analysis/data \
        --start 2025-06-01 --end 2025-12-31 \
        --max-markets 5000
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

import structlog

sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.models import Base, Market, PriceSnapshot

log = structlog.get_logger()

DEFAULT_DATASET_PATH = "/data/prediction-market-analysis/data"


def _make_backtest_url() -> str:
    return (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/polyarb_backtest"
    )


async def create_backtest_db():
    """Create the backtest database if it doesn't exist."""
    import asyncpg

    conn = await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", "polyarb_backtest"
        )
        if not exists:
            await conn.execute('CREATE DATABASE "polyarb_backtest"')
            log.info("created_database", name="polyarb_backtest")
        else:
            log.info("database_exists", name="polyarb_backtest")
    finally:
        await conn.close()

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_make_backtest_url())
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Drop and recreate to ensure schema matches current models
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    log.info("schema_created")


def load_markets_from_dataset(
    dataset_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
    max_markets: int = 5000,
) -> list[dict]:
    """Load closed+resolved markets from the Parquet dataset.

    Returns list of dicts ready for DB insertion.
    """
    import duckdb

    con = duckdb.connect(":memory:")
    markets_glob = f"{dataset_path}/polymarket/markets/markets_*.parquet"

    # Build WHERE clause
    where_parts = ["closed = true", "outcome_prices IS NOT NULL"]
    if start_date:
        where_parts.append(f"end_date >= '{start_date}'::TIMESTAMPTZ")
    if end_date:
        where_parts.append(f"end_date <= '{end_date}'::TIMESTAMPTZ")
    where_clause = " AND ".join(where_parts)

    query = f"""
        SELECT
            condition_id, question, slug, outcomes, outcome_prices,
            clob_token_ids, volume, liquidity, active, closed,
            end_date, created_at
        FROM read_parquet('{markets_glob}')
        WHERE {where_clause}
        ORDER BY volume DESC NULLS LAST
        LIMIT {max_markets}
    """

    rows = con.execute(query).fetchall()
    log.info("dataset_markets_loaded", count=len(rows))

    results = []
    for row in rows:
        (
            condition_id, question, slug, outcomes_str, prices_str,
            tokens_str, volume, liquidity, active, closed,
            end_date_val, created_at,
        ) = row

        try:
            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else (outcomes_str or [])
            prices = json.loads(prices_str) if isinstance(prices_str, str) else (prices_str or [])
            tokens = json.loads(tokens_str) if isinstance(tokens_str, str) else (tokens_str or [])
        except (json.JSONDecodeError, TypeError):
            continue

        if not outcomes or not prices or len(outcomes) != len(prices):
            continue

        # Determine resolved outcome
        max_price = -1.0
        resolved_outcome = None
        for outcome, price_str in zip(outcomes, prices):
            try:
                p = float(price_str)
            except (ValueError, TypeError):
                continue
            if p > max_price:
                max_price = p
                resolved_outcome = outcome

        if max_price < 0.90:
            resolved_outcome = None  # No clear resolution

        # Build outcomes dict like our ingestor does: {"Yes": "token_id_1", "No": "token_id_2"}
        outcomes_dict = outcomes  # Keep as list for compatibility
        token_ids = tokens

        results.append({
            "polymarket_id": condition_id,
            "question": question,
            "outcomes": outcomes_dict,
            "token_ids": token_ids,
            "volume": Decimal(str(volume)) if volume else None,
            "liquidity": Decimal(str(liquidity)) if liquidity else None,
            "active": False,  # Historical
            "end_date": end_date_val,
            "created_at": created_at,
            "resolved_outcome": resolved_outcome,
            "resolved_at": end_date_val if resolved_outcome else None,
        })

    con.close()
    return results


async def insert_markets(markets: list[dict]) -> dict:
    """Insert markets into the backtest DB."""
    from sqlalchemy import text

    stats = {"inserted": 0, "skipped": 0}

    async with SessionFactory() as session:
        # Clear existing markets
        await session.execute(text("TRUNCATE markets, price_snapshots, market_pairs, arbitrage_opportunities, paper_trades, portfolio_snapshots CASCADE"))
        await session.commit()

        for m in markets:
            market = Market(
                polymarket_id=m["polymarket_id"],
                question=m["question"],
                outcomes=m["outcomes"],
                token_ids=m["token_ids"],
                volume=m["volume"],
                liquidity=m["liquidity"],
                active=m["active"],
                end_date=m["end_date"],
                resolved_outcome=m["resolved_outcome"],
                resolved_at=m["resolved_at"],
            )
            session.add(market)
            stats["inserted"] += 1

        await session.commit()

    log.info("markets_inserted", **stats)
    return stats


def load_trade_prices(
    dataset_path: str,
    token_ids: set[str],
) -> dict[str, list[tuple]]:
    """Load trades for specific tokens and compute daily prices.

    Returns: {token_id: [(date, price), ...]}
    """
    import duckdb

    con = duckdb.connect(":memory:")
    trades_glob = f"{dataset_path}/polymarket/trades/trades_*.parquet"

    # For efficiency, load all trades and filter in DuckDB
    # taker_asset_id maps to clob_token_id
    # price = maker_amount / taker_amount (both in base units)
    log.info("loading_trades", token_count=len(token_ids))

    # Build a temp table with our token IDs for join
    token_list = list(token_ids)

    # Process in chunks to avoid memory issues
    chunk_size = 500
    all_prices: dict[str, list[tuple]] = {}

    for i in range(0, len(token_list), chunk_size):
        chunk = token_list[i:i + chunk_size]
        token_csv = ",".join(f"'{t}'" for t in chunk)

        try:
            rows = con.execute(f"""
                SELECT
                    taker_asset_id as token_id,
                    DATE_TRUNC('day', TIMESTAMP '1970-01-01' + INTERVAL (timestamp) SECONDS) as trade_date,
                    AVG(CAST(maker_amount AS DOUBLE) / NULLIF(CAST(taker_amount AS DOUBLE), 0)) as avg_price,
                    COUNT(*) as trade_count
                FROM read_parquet('{trades_glob}')
                WHERE taker_asset_id IN ({token_csv})
                  AND taker_amount > 0
                  AND timestamp IS NOT NULL
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

        if i % 2000 == 0:
            log.info("trade_loading_progress", processed=i, total=len(token_list))

    con.close()
    log.info("trade_prices_loaded", tokens_with_data=len(all_prices))
    return all_prices


async def insert_price_snapshots(
    markets: list[dict],
    trade_prices: dict[str, list[tuple]],
) -> dict:
    """Build daily price snapshots from trade data and insert into DB."""
    stats = {"snapshots": 0, "markets_with_data": 0}

    # Build token_id → market mapping
    # Each market has multiple tokens (one per outcome)
    # We need to combine per-token daily prices into per-market snapshots

    async with SessionFactory() as session:
        # Get market IDs from DB
        from sqlalchemy import select
        result = await session.execute(
            select(Market.id, Market.polymarket_id, Market.outcomes, Market.token_ids)
        )
        db_markets = result.all()

        market_lookup = {}
        for market_id, poly_id, outcomes, tokens in db_markets:
            if not tokens or not outcomes:
                continue
            token_list = tokens if isinstance(tokens, list) else json.loads(tokens)
            outcome_list = outcomes if isinstance(outcomes, list) else json.loads(outcomes)
            market_lookup[market_id] = {
                "outcomes": outcome_list,
                "tokens": token_list,
            }

        for market_id, info in market_lookup.items():
            # Collect all dates where we have price data for any token
            date_prices: dict[str, dict[str, float]] = {}  # date → {outcome: price}

            for outcome, token in zip(info["outcomes"], info["tokens"]):
                token_data = trade_prices.get(str(token), [])
                for trade_date, price in token_data:
                    date_key = str(trade_date.date()) if hasattr(trade_date, 'date') else str(trade_date)[:10]
                    date_prices.setdefault(date_key, {})[outcome] = price

            if not date_prices:
                continue

            stats["markets_with_data"] += 1

            for date_str, prices in sorted(date_prices.items()):
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
                stats["snapshots"] += 1

            # Batch commit every 100 markets
            if stats["markets_with_data"] % 100 == 0:
                await session.commit()
                log.info("snapshot_progress",
                         markets=stats["markets_with_data"],
                         snapshots=stats["snapshots"])

        await session.commit()

    log.info("snapshots_inserted", **stats)
    return stats


async def generate_embeddings(batch_size: int = 100) -> dict:
    """Generate embeddings for all markets without them."""
    import openai

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    stats = {"embedded": 0, "errors": 0}

    async with SessionFactory() as session:
        from sqlalchemy import select, update
        result = await session.execute(
            select(Market.id, Market.question)
            .where(Market.embedding.is_(None))
        )
        markets = result.all()

    log.info("embedding_start", markets_to_embed=len(markets))

    for i in range(0, len(markets), batch_size):
        batch = markets[i:i + batch_size]
        texts = [m.question for m in batch]
        ids = [m.id for m in batch]

        try:
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
                dimensions=384,
            )

            async with SessionFactory() as session:
                for j, emb_data in enumerate(response.data):
                    from sqlalchemy import update
                    await session.execute(
                        update(Market)
                        .where(Market.id == ids[j])
                        .values(embedding=emb_data.embedding)
                    )
                await session.commit()

            stats["embedded"] += len(batch)

        except Exception as e:
            log.warning("embedding_error", batch_start=i, error=str(e))
            stats["errors"] += 1

        if i % 500 == 0 and i > 0:
            log.info("embedding_progress", done=i, total=len(markets))

    log.info("embeddings_complete", **stats)
    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap backtest DB from Jon-Becker dataset"
    )
    parser.add_argument("--dataset-path", default=DEFAULT_DATASET_PATH)
    parser.add_argument("--start", default="2025-06-01",
                        help="Start date for market window (ISO)")
    parser.add_argument("--end", default="2026-02-01",
                        help="End date for market window (ISO)")
    parser.add_argument("--max-markets", type=int, default=5000,
                        help="Max markets to import (sorted by volume)")
    parser.add_argument("--skip-embeddings", action="store_true",
                        help="Skip embedding generation (run separately)")
    parser.add_argument("--skip-prices", action="store_true",
                        help="Skip trade price loading (run separately)")
    parser.add_argument("--skip-markets", action="store_true",
                        help="Skip market import (use existing markets in DB)")
    args = parser.parse_args()

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))

    # Step 0: Create backtest DB (only drop/recreate if importing markets)
    if not args.skip_markets:
        await create_backtest_db()
    await init_db()

    # Step 1: Load and insert markets from dataset
    if not args.skip_markets:
        log.info("step1_loading_markets",
                 start=args.start, end=args.end, max=args.max_markets)
        markets = load_markets_from_dataset(
            args.dataset_path,
            start_date=args.start,
            end_date=args.end,
            max_markets=args.max_markets,
        )

        if not markets:
            log.error("no_markets_found")
            return

        resolved = sum(1 for m in markets if m["resolved_outcome"])
        log.info("markets_summary",
                 total=len(markets),
                 resolved=resolved,
                 resolution_rate=f"{100*resolved/len(markets):.1f}%")

        await insert_markets(markets)
    else:
        log.info("step1_skipped_using_existing_markets")
        # Load market info from DB for subsequent steps
        markets = []
        async with SessionFactory() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Market.polymarket_id, Market.token_ids)
            )
            for poly_id, tids in result.all():
                markets.append({"polymarket_id": poly_id, "token_ids": tids})
        log.info("existing_markets_loaded", count=len(markets))

    # Step 2: Generate embeddings
    if not args.skip_embeddings:
        log.info("step2_generating_embeddings")
        await generate_embeddings()
    else:
        log.info("step2_skipped")

    # Step 3: Load trade prices and create snapshots
    if not args.skip_prices:
        log.info("step3_loading_trade_prices")
        all_tokens = set()
        for m in markets:
            tokens = m["token_ids"]
            if isinstance(tokens, str):
                tokens = json.loads(tokens)
            if tokens:
                for t in tokens:
                    all_tokens.add(str(t))

        trade_prices = load_trade_prices(args.dataset_path, all_tokens)
        await insert_price_snapshots(markets, trade_prices)
    else:
        log.info("step3_skipped")

    log.info("backtest_bootstrap_complete",
             hint="Now run: detector (to find pairs) → backtest --authoritative")


if __name__ == "__main__":
    asyncio.run(main())
