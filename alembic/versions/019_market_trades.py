"""Add market_trades table for raw WS trade tape.

WS last_trade_price events were previously folded into price snapshots
(size/side/timestamp discarded), so the live period could not be
backtested from our own data. This table persists the raw tape for
WS-subscribed tokens. Dedup is best-effort via a unique index — WS
events carry no unique id, and NULL fields skip dedup by Postgres
semantics.

Revision ID: 019
Revises: 018
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "market_id",
            sa.Integer(),
            sa.ForeignKey("markets.id"),
            nullable=False,
        ),
        sa.Column("token_id", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("size", sa.Numeric(), nullable=True),
        sa.Column("side", sa.String(length=4), nullable=True),
        sa.Column("fee_rate_bps", sa.Integer(), nullable=True),
        sa.Column("event_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_market_trades_market_id", "market_trades", ["market_id"])
    op.create_index("ix_market_trades_token_id", "market_trades", ["token_id"])
    op.create_index(
        "ix_market_trades_market_ts", "market_trades", ["market_id", "event_ts"]
    )
    op.create_index(
        "ix_market_trades_token_ts", "market_trades", ["token_id", "event_ts"]
    )
    op.create_index(
        "uq_market_trades_dedup",
        "market_trades",
        ["token_id", "event_ts", "price", "size", "side"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("market_trades")
