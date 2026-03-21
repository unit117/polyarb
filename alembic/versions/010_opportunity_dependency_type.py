"""Add dependency_type snapshot to arbitrage_opportunities.

Snapshots the pair's dependency_type at opportunity creation time so that
metrics queries don't retroactively relabel historical opportunities when
a pair is later downgraded.

Revision ID: 010
Revises: 009
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "arbitrage_opportunities",
        sa.Column("dependency_type", sa.String(), nullable=True),
    )
    # Backfill from the current pair dependency_type for existing rows
    op.execute(
        """
        UPDATE arbitrage_opportunities ao
        SET dependency_type = mp.dependency_type
        FROM market_pairs mp
        WHERE ao.pair_id = mp.id AND ao.dependency_type IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("arbitrage_opportunities", "dependency_type")
