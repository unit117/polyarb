"""Add pending_at timestamp to arbitrage_opportunities.

Tracks when an opportunity entered 'pending' status so the stale-pending
sweeper uses transition time rather than creation time.

Revision ID: 008
Revises: 007
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "arbitrage_opportunities",
        sa.Column("pending_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("arbitrage_opportunities", "pending_at")
