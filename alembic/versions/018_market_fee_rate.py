"""Add fee_rate_bps column to markets.

Stores the per-market taker fee rate in basis points as returned by the
Polymarket CLOB API (GET /fee-rate?token_id=X). Category-specific rates
range from 0 (geopolitics) to 180 (crypto). NULL means unknown — falls
back to the legacy 150 bps (1.5%) conservative estimate.

Revision ID: 018
Revises: 017
Create Date: 2026-04-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "markets",
        sa.Column("fee_rate_bps", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("markets", "fee_rate_bps")
