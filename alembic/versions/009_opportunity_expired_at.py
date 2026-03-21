"""Add expired_at timestamp to arbitrage_opportunities.

Tracks when an opportunity's profit dropped below threshold, enabling
duration analysis (how long opportunities stay profitable).

Revision ID: 009
Revises: 008
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "arbitrage_opportunities",
        sa.Column("expired_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("arbitrage_opportunities", "expired_at")
