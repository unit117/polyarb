"""Reset backtest DB with live verified pairs and their markets.

Copies only markets referenced by verified pairs from the live DB into
polyarb_backtest via dblink. Truncates existing backtest data first.

Usage (inside backtest-setup or backtest container):
    python -m scripts.backtest_reset_from_live
"""

from __future__ import annotations

import asyncio
import sys

import structlog

sys.path.insert(0, ".")

from shared.config import settings

log = structlog.get_logger()

BACKTEST_DB = "polyarb_backtest"


LIVE_DB = "polyarb"


def _live_dsn() -> str:
    return (
        f"dbname={LIVE_DB} user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )


async def main() -> None:
    import asyncpg

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))

    # Ensure backtest DB exists
    admin = await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database="postgres",
    )
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", BACKTEST_DB
        )
        if not exists:
            await admin.execute(f'CREATE DATABASE "{BACKTEST_DB}"')
            log.info("created_database", name=BACKTEST_DB)
    finally:
        await admin.close()

    # Create schema
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from shared.models import Base

    url = (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{BACKTEST_DB}"
    )
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    log.info("schema_ready")

    # Connect to backtest DB and copy via dblink
    conn = await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=BACKTEST_DB,
    )
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS dblink")

        live_dsn = _live_dsn()

        # Clear existing data
        await conn.execute(
            "TRUNCATE price_snapshots, portfolio_snapshots, paper_trades, "
            "arbitrage_opportunities, market_pairs, markets CASCADE"
        )
        log.info("truncated_backtest_tables")

        # Copy only markets referenced by verified pairs
        await conn.execute(f"""
            INSERT INTO markets (
                id, polymarket_id, venue, event_id, question, description,
                outcomes, token_ids, active, end_date, volume, liquidity,
                embedding, resolved_outcome, resolved_at, created_at, updated_at
            )
            SELECT
                id, polymarket_id, venue, event_id, question, description,
                outcomes, token_ids, active, end_date, volume, liquidity,
                embedding, resolved_outcome, resolved_at, created_at, updated_at
            FROM dblink('{live_dsn}', $$
                SELECT id, polymarket_id, venue, event_id, question, description,
                       outcomes, token_ids, active, end_date, volume, liquidity,
                       embedding, resolved_outcome, resolved_at, created_at, updated_at
                FROM markets
                WHERE id IN (
                    SELECT market_a_id FROM market_pairs WHERE verified = true
                    UNION
                    SELECT market_b_id FROM market_pairs WHERE verified = true
                )
            $$)
            AS t(
                id integer, polymarket_id text, venue varchar(32), event_id text,
                question text, description text, outcomes jsonb, token_ids jsonb,
                active boolean, end_date timestamptz, volume numeric, liquidity numeric,
                embedding vector(384), resolved_outcome text, resolved_at timestamptz,
                created_at timestamptz, updated_at timestamptz
            )
            ON CONFLICT DO NOTHING
        """)
        market_count = await conn.fetchval("SELECT count(*) FROM markets")
        log.info("copied_markets", count=market_count)

        # Copy verified pairs with all columns
        await conn.execute(f"""
            INSERT INTO market_pairs (
                id, market_a_id, market_b_id, dependency_type, confidence,
                constraint_matrix, detected_at, verified,
                resolution_vectors, implication_direction, classification_source
            )
            SELECT
                id, market_a_id, market_b_id, dependency_type, confidence,
                constraint_matrix, detected_at, verified,
                resolution_vectors, implication_direction, classification_source
            FROM dblink('{live_dsn}', $$
                SELECT id, market_a_id, market_b_id, dependency_type, confidence,
                       constraint_matrix, detected_at, verified,
                       resolution_vectors, implication_direction, classification_source
                FROM market_pairs
                WHERE verified = true
            $$)
            AS t(
                id integer, market_a_id integer, market_b_id integer,
                dependency_type varchar, confidence double precision,
                constraint_matrix jsonb, detected_at timestamptz, verified boolean,
                resolution_vectors jsonb, implication_direction varchar,
                classification_source varchar
            )
            ON CONFLICT DO NOTHING
        """)
        pair_count = await conn.fetchval(
            "SELECT count(*) FROM market_pairs WHERE verified = true"
        )
        log.info("copied_pairs", count=pair_count)

        # Reset sequences
        max_market = await conn.fetchval("SELECT COALESCE(MAX(id), 1) FROM markets")
        await conn.execute(f"SELECT setval('markets_id_seq', {max_market})")
        max_pair = await conn.fetchval("SELECT COALESCE(MAX(id), 1) FROM market_pairs")
        await conn.execute(f"SELECT setval('market_pairs_id_seq', {max_pair})")

    finally:
        await conn.close()

    print("\n" + "=" * 55)
    print("  BACKTEST DB RESET FROM LIVE")
    print("=" * 55)
    print(f"  Markets copied:        {market_count}")
    print(f"  Verified pairs copied: {pair_count}")
    print(f"  Price snapshots:       0 (ready for PMXT load)")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
