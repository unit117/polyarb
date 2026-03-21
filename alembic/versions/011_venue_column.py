"""Add venue column to markets and paper_trades.

Supports multi-venue ingestion (Polymarket + Kalshi). The polymarket_id
unique constraint is widened to (venue, polymarket_id) so the same external
ID can exist on different venues.

Revision ID: 011
Revises: 010
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- markets ---
    op.add_column(
        "markets",
        sa.Column(
            "venue",
            sa.String(32),
            nullable=False,
            server_default="polymarket",
        ),
    )
    op.create_index("ix_markets_venue", "markets", ["venue"])

    # Widen unique constraint: polymarket_id alone → (venue, polymarket_id)
    op.drop_constraint("ix_markets_polymarket_id", "markets", type_="unique")
    op.create_unique_constraint(
        "uq_markets_venue_polymarket_id",
        "markets",
        ["venue", "polymarket_id"],
    )

    # --- paper_trades ---
    op.add_column(
        "paper_trades",
        sa.Column(
            "venue",
            sa.String(32),
            nullable=True,
            server_default="polymarket",
        ),
    )


def downgrade() -> None:
    op.drop_column("paper_trades", "venue")
    op.drop_constraint("uq_markets_venue_polymarket_id", "markets", type_="unique")
    op.create_index("ix_markets_polymarket_id", "markets", ["polymarket_id"], unique=True)
    op.drop_index("ix_markets_venue", table_name="markets")
    op.drop_column("markets", "venue")
