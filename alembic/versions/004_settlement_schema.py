"""Add settlement columns to markets and make paper_trades.opportunity_id nullable

Revision ID: 004
Revises: 003
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

TIMESTAMPTZ = sa.DateTime(timezone=True)

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE markets ADD COLUMN IF NOT EXISTS resolved_outcome VARCHAR")
    op.execute("ALTER TABLE markets ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_markets_resolved "
        "ON markets (resolved_outcome) WHERE resolved_outcome IS NOT NULL"
    )
    op.alter_column("paper_trades", "opportunity_id", nullable=True)


def downgrade() -> None:
    op.alter_column("paper_trades", "opportunity_id", nullable=False)
    op.drop_index("ix_markets_resolved", table_name="markets")
    op.drop_column("markets", "resolved_at")
    op.drop_column("markets", "resolved_outcome")
