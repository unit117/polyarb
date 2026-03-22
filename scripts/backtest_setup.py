"""Set up the backtest database.

Creates the `polyarb_backtest` database on the same Postgres instance,
runs migrations to create the schema, and copies Markets + MarketPairs
from the live database so the backtester has pairs to work with —
without touching the live DB at all.

Usage:
    python -m scripts.backtest_setup
"""

import asyncio
import sys

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, ".")

from shared.config import settings
from shared.models import Base

log = structlog.get_logger()

BACKTEST_DB = "polyarb_backtest"


def _make_url(db_name: str) -> str:
    return (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{db_name}"
    )


async def create_backtest_database() -> None:
    """Create the backtest database if it doesn't exist.

    Connects to the default 'postgres' DB to issue CREATE DATABASE.
    asyncpg requires autocommit for DDL, so we use raw connection.
    """
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
            "SELECT 1 FROM pg_database WHERE datname = $1", BACKTEST_DB
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{BACKTEST_DB}"')
            log.info("created_database", name=BACKTEST_DB)
        else:
            log.info("database_exists", name=BACKTEST_DB)
    finally:
        await conn.close()


async def create_schema() -> None:
    """Create all tables + pgvector extension in the backtest DB."""
    engine = create_async_engine(_make_url(BACKTEST_DB))
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    log.info("schema_created", database=BACKTEST_DB)


async def copy_markets_and_pairs() -> None:
    """Copy Markets and MarketPairs from live DB into the backtest DB.

    Uses dblink to copy directly inside Postgres (no Python memory overhead),
    which handles 39k+ markets with embeddings without OOM.
    """
    import asyncpg

    live_db = settings.postgres_db
    conn = await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=BACKTEST_DB,
    )
    try:
        # Install dblink extension
        await conn.execute("CREATE EXTENSION IF NOT EXISTS dblink")

        live_dsn = (
            f"dbname={live_db} user={settings.postgres_user} "
            f"password={settings.postgres_password}"
        )

        # Clear existing (idempotent re-runs)
        await conn.execute("TRUNCATE markets, market_pairs CASCADE")

        # Copy markets via dblink — explicit column names for schema safety
        market_count = await conn.fetchval(f"""
            INSERT INTO markets (
                id, polymarket_id, venue, event_id, question, description,
                outcomes, token_ids, active, end_date, volume, liquidity,
                embedding, resolved_outcome, resolved_at, created_at, updated_at
            )
            SELECT
                id, polymarket_id, venue, event_id, question, description,
                outcomes, token_ids, active, end_date, volume, liquidity,
                embedding, resolved_outcome, resolved_at, created_at, updated_at
            FROM dblink('{live_dsn}',
                'SELECT id, polymarket_id, venue, event_id, question, description,
                        outcomes, token_ids, active, end_date, volume, liquidity,
                        embedding, resolved_outcome, resolved_at, created_at, updated_at
                 FROM markets'
            )
            AS t(
                id integer, polymarket_id text, venue varchar(32), event_id text,
                question text, description text, outcomes jsonb, token_ids jsonb,
                active boolean, end_date timestamptz, volume numeric, liquidity numeric,
                embedding vector(384), resolved_outcome text, resolved_at timestamptz,
                created_at timestamptz, updated_at timestamptz
            )
            ON CONFLICT DO NOTHING
            RETURNING 1
        """)
        # fetchval returns first row or None; count via separate query
        market_count = await conn.fetchval("SELECT count(*) FROM markets")
        log.info("copied_markets", count=market_count)

        # Copy market_pairs via dblink
        await conn.execute(f"""
            INSERT INTO market_pairs
            SELECT *
            FROM dblink('{live_dsn}', 'SELECT * FROM market_pairs')
            AS t(
                id integer, market_a_id integer, market_b_id integer,
                dependency_type text, confidence double precision,
                constraint_matrix jsonb, detected_at timestamptz, verified boolean
            )
            ON CONFLICT DO NOTHING
        """)
        pair_count = await conn.fetchval("SELECT count(*) FROM market_pairs")
        log.info("copied_pairs", count=pair_count)

        # Reset sequences
        await conn.execute(
            "SELECT setval('markets_id_seq', (SELECT COALESCE(MAX(id),0) FROM markets))"
        )
        await conn.execute(
            "SELECT setval('market_pairs_id_seq', (SELECT COALESCE(MAX(id),0) FROM market_pairs))"
        )

    finally:
        await conn.close()

    log.info("copy_complete")


async def main() -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))

    log.info("backtest_setup_start")
    await create_backtest_database()
    await create_schema()
    await copy_markets_and_pairs()
    log.info("backtest_setup_complete", database=BACKTEST_DB)


if __name__ == "__main__":
    asyncio.run(main())
