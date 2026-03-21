"""Add partial unique index to arbitrage_opportunities to prevent duplicate active opps.

Revision ID: 007
Revises: 006
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # First deduplicate: for each pair_id with multiple in-flight opportunities,
    # keep only the newest one and mark the rest as 'skipped'.
    op.execute(sa.text("""
        UPDATE arbitrage_opportunities SET status = 'skipped'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY pair_id ORDER BY timestamp DESC
                ) AS rn
                FROM arbitrage_opportunities
                WHERE status IN ('detected', 'pending', 'optimized', 'unconverged')
            ) sub WHERE rn > 1
        )
    """))

    # Create a partial unique index on (pair_id) where status is in-flight.
    # This prevents the race condition between periodic, event, and snapshot loops.
    op.create_index(
        "ix_arbitrage_opportunities_active_unique",
        "arbitrage_opportunities",
        ["pair_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('detected', 'pending', 'optimized', 'unconverged')"),
    )


def downgrade() -> None:
    op.drop_index("ix_arbitrage_opportunities_active_unique", table_name="arbitrage_opportunities")
