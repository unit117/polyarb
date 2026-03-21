"""Add paper_trades and portfolio_snapshots tables

Revision ID: 003
Revises: 002
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

TIMESTAMPTZ = sa.DateTime(timezone=True)

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.Integer,
            sa.ForeignKey("arbitrage_opportunities.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "market_id",
            sa.Integer,
            sa.ForeignKey("markets.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("side", sa.String, nullable=False),
        sa.Column("size", sa.Numeric, nullable=False),
        sa.Column("entry_price", sa.Numeric, nullable=False),
        sa.Column("vwap_price", sa.Numeric, nullable=False),
        sa.Column("slippage", sa.Numeric, nullable=False),
        sa.Column("fees", sa.Numeric, nullable=False, server_default="0"),
        sa.Column(
            "executed_at",
            TIMESTAMPTZ,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String,
            default="filled",
            nullable=False,
        ),
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "timestamp",
            TIMESTAMPTZ,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("cash", sa.Numeric, nullable=False),
        sa.Column("positions", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("total_value", sa.Numeric, nullable=False),
        sa.Column("realized_pnl", sa.Numeric, nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric, nullable=False),
        sa.Column("total_trades", sa.Integer, nullable=False),
        sa.Column("winning_trades", sa.Integer, nullable=False),
    )

    op.create_index(
        "ix_portfolio_snapshots_timestamp",
        "portfolio_snapshots",
        [sa.text("timestamp DESC")],
    )


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("paper_trades")
