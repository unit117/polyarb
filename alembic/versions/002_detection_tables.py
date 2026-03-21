"""Add market_pairs and arbitrage_opportunities tables

Revision ID: 002
Revises: 001
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

TIMESTAMPTZ = sa.DateTime(timezone=True)

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_pairs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "market_a_id",
            sa.Integer,
            sa.ForeignKey("markets.id"),
            nullable=False,
        ),
        sa.Column(
            "market_b_id",
            sa.Integer,
            sa.ForeignKey("markets.id"),
            nullable=False,
        ),
        sa.Column(
            "dependency_type",
            sa.String,
            nullable=False,
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column(
            "constraint_matrix",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "detected_at",
            TIMESTAMPTZ,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("verified", sa.Boolean, default=False, nullable=False),
    )

    op.create_index(
        "ix_market_pairs_markets",
        "market_pairs",
        ["market_a_id", "market_b_id"],
        unique=True,
    )
    op.create_index(
        "ix_market_pairs_dependency_type",
        "market_pairs",
        ["dependency_type"],
    )

    op.create_table(
        "arbitrage_opportunities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "pair_id",
            sa.Integer,
            sa.ForeignKey("market_pairs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "timestamp",
            TIMESTAMPTZ,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("theoretical_profit", sa.Numeric, nullable=False),
        sa.Column("estimated_profit", sa.Numeric, nullable=True),
        sa.Column(
            "optimal_trades",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column("fw_iterations", sa.Integer, nullable=True),
        sa.Column("bregman_gap", sa.Float, nullable=True),
        sa.Column(
            "status",
            sa.String,
            default="detected",
            nullable=False,
        ),
    )

    op.create_index(
        "ix_arbitrage_opportunities_status",
        "arbitrage_opportunities",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("arbitrage_opportunities")
    op.drop_table("market_pairs")
