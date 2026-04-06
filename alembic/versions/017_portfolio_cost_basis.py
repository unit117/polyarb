"""Add cost_basis JSONB column to portfolio_snapshots.

Stores per-position cost basis alongside the positions dict so the
dashboard can compute per-position unrealized PnL without replaying
the entire trade ledger.

Revision ID: 017
Revises: 016
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "portfolio_snapshots",
        sa.Column("cost_basis", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("portfolio_snapshots", "cost_basis")
