"""Add durable live order and fill audit tables.

Revision ID: 014
Revises: 013
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "live_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("token_id", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("requested_size", sa.Numeric(), nullable=False),
        sa.Column("requested_price", sa.Numeric(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("venue_order_id", sa.String(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.ForeignKeyConstraint(["opportunity_id"], ["arbitrage_opportunities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_live_orders_market_id", "live_orders", ["market_id"])
    op.create_index("ix_live_orders_opportunity_id", "live_orders", ["opportunity_id"])
    op.create_index("ix_live_orders_status", "live_orders", ["status"])
    op.create_index("ix_live_orders_submitted_at", "live_orders", ["submitted_at"])

    op.create_table(
        "live_fills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("live_order_id", sa.Integer(), nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("fill_size", sa.Numeric(), nullable=False),
        sa.Column("fill_price", sa.Numeric(), nullable=False),
        sa.Column("fees", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column(
            "filled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["live_order_id"], ["live_orders.id"]),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_live_fills_live_order_id", "live_fills", ["live_order_id"])
    op.create_index("ix_live_fills_market_id", "live_fills", ["market_id"])
    op.create_index("ix_live_fills_filled_at", "live_fills", ["filled_at"])


def downgrade() -> None:
    op.drop_index("ix_live_fills_filled_at", table_name="live_fills")
    op.drop_index("ix_live_fills_market_id", table_name="live_fills")
    op.drop_index("ix_live_fills_live_order_id", table_name="live_fills")
    op.drop_table("live_fills")

    op.drop_index("ix_live_orders_submitted_at", table_name="live_orders")
    op.drop_index("ix_live_orders_status", table_name="live_orders")
    op.drop_index("ix_live_orders_opportunity_id", table_name="live_orders")
    op.drop_index("ix_live_orders_market_id", table_name="live_orders")
    op.drop_table("live_orders")
