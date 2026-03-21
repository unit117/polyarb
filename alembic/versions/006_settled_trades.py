"""Add settled_trades column to portfolio_snapshots for correct win-rate denominator.

Revision ID: 006
Revises: 005
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "portfolio_snapshots",
        sa.Column("settled_trades", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("portfolio_snapshots", "settled_trades")
