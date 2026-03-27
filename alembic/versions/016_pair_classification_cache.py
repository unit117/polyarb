"""Add pair classification cache for detector LLM reuse.

Revision ID: 016
Revises: 015
Create Date: 2026-03-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pair_classification_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_a_id", sa.Integer(), nullable=False),
        sa.Column("market_b_id", sa.Integer(), nullable=False),
        sa.Column("classifier_model", sa.String(length=128), nullable=False),
        sa.Column("prompt_adapter", sa.String(length=32), nullable=False),
        sa.Column("cache_version", sa.String(length=32), nullable=False),
        sa.Column("market_a_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("market_b_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("classification", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["market_a_id"], ["markets.id"]),
        sa.ForeignKeyConstraint(["market_b_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pair_classification_cache_lookup",
        "pair_classification_cache",
        [
            "market_a_id",
            "market_b_id",
            "classifier_model",
            "prompt_adapter",
            "cache_version",
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pair_classification_cache_lookup",
        table_name="pair_classification_cache",
    )
    op.drop_table("pair_classification_cache")
