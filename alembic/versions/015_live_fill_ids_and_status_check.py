"""Add live fill idempotency key and live order status validation.

Revision ID: 015
Revises: 014
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "live_fills",
        sa.Column("venue_fill_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_live_fills_venue_fill_id",
        "live_fills",
        ["venue_fill_id"],
        unique=True,
    )
    op.create_check_constraint(
        "ck_live_orders_status",
        "live_orders",
        "status IN ('dry_run','submitted','filled','partially_filled','cancelled','rejected','expired','settled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_live_orders_status", "live_orders", type_="check")
    op.drop_index("ix_live_fills_venue_fill_id", table_name="live_fills")
    op.drop_column("live_fills", "venue_fill_id")
