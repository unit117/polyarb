"""Add source column to paper_trades and portfolio_snapshots for paper/live distinction.

Revision ID: 005
Revises: 004
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paper_trades",
        sa.Column("source", sa.String(), server_default="paper", nullable=False),
    )
    op.add_column(
        "portfolio_snapshots",
        sa.Column("source", sa.String(), server_default="paper", nullable=False),
    )
    op.create_index("ix_paper_trades_source", "paper_trades", ["source"])
    op.create_index("ix_portfolio_snapshots_source", "portfolio_snapshots", ["source"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_snapshots_source", "portfolio_snapshots")
    op.drop_index("ix_paper_trades_source", "paper_trades")
    op.drop_column("portfolio_snapshots", "source")
    op.drop_column("paper_trades", "source")
