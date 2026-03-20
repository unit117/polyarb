"""Initial schema with markets and price_snapshots

Revision ID: 001
Revises:
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

TIMESTAMPTZ = sa.DateTime(timezone=True)

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "markets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("polymarket_id", sa.String, unique=True, index=True, nullable=False),
        sa.Column("event_id", sa.String, nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("outcomes", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("token_ids", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("active", sa.Boolean, default=True, nullable=False),
        sa.Column("end_date", TIMESTAMPTZ, nullable=True),
        sa.Column("volume", sa.Numeric, nullable=True),
        sa.Column("liquidity", sa.Numeric, nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMPTZ,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMPTZ,
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_markets_active",
        "markets",
        ["active"],
        postgresql_where=sa.text("active = true"),
    )

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "market_id",
            sa.Integer,
            sa.ForeignKey("markets.id"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            TIMESTAMPTZ,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("prices", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("order_book", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("midpoints", sa.dialects.postgresql.JSONB(), nullable=True),
    )

    op.create_index(
        "ix_price_snapshots_market_timestamp",
        "price_snapshots",
        ["market_id", sa.text("timestamp DESC")],
    )


def downgrade() -> None:
    op.drop_table("price_snapshots")
    op.drop_table("markets")
    op.execute("DROP EXTENSION IF EXISTS vector")
