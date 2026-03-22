"""Add resolution vector columns to market_pairs.

Stores LLM classification metadata: resolution_vectors (valid outcome
combinations from Saguillo et al. methodology), implication_direction
(a_implies_b / b_implies_a), and classification_source (rule_based /
resolution_vector / llm_label).

Revision ID: 012
Revises: 011
Create Date: 2026-03-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "market_pairs",
        sa.Column("resolution_vectors", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "market_pairs",
        sa.Column("implication_direction", sa.String, nullable=True),
    )
    op.add_column(
        "market_pairs",
        sa.Column("classification_source", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_pairs", "classification_source")
    op.drop_column("market_pairs", "implication_direction")
    op.drop_column("market_pairs", "resolution_vectors")
