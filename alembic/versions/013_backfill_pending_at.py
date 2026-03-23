"""Backfill pending_at for pre-existing pending opportunities.

Migration 008 added the pending_at column but did not backfill rows that
were already in 'pending' status.  Without pending_at the stale-pending
sweeper (services/simulator/pipeline.py) cannot see them, blocking their
pair forever.

Sets pending_at = timestamp (creation time) as a reasonable fallback.

Revision ID: 013
Revises: 012
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE arbitrage_opportunities "
        "SET pending_at = timestamp "
        "WHERE status = 'pending' AND pending_at IS NULL"
    )


def downgrade() -> None:
    # Cannot reliably distinguish backfilled rows from naturally-set ones,
    # so downgrade is a no-op.
    pass
