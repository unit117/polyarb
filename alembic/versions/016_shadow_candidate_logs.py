"""Add durable detector shadow-candidate review logs.

Revision ID: 016
Revises: 015
Create Date: 2026-03-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

TIMESTAMPTZ = sa.DateTime(timezone=True)

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shadow_candidate_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "logged_at",
            TIMESTAMPTZ,
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("pipeline_source", sa.String(length=32), nullable=False),
        sa.Column("decision_outcome", sa.String(length=64), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("pair_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("market_a_id", sa.Integer(), nullable=False),
        sa.Column("market_b_id", sa.Integer(), nullable=False),
        sa.Column("market_a_event_id", sa.String(), nullable=True),
        sa.Column("market_b_event_id", sa.String(), nullable=True),
        sa.Column("market_a_question", sa.Text(), nullable=False),
        sa.Column("market_b_question", sa.Text(), nullable=False),
        sa.Column("market_a_outcomes", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("market_b_outcomes", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("market_a_venue", sa.String(length=32), nullable=True),
        sa.Column("market_b_venue", sa.String(length=32), nullable=True),
        sa.Column("market_a_liquidity", sa.Numeric(), nullable=True),
        sa.Column("market_b_liquidity", sa.Numeric(), nullable=True),
        sa.Column("market_a_volume", sa.Numeric(), nullable=True),
        sa.Column("market_b_volume", sa.Numeric(), nullable=True),
        sa.Column("snapshot_a_timestamp", TIMESTAMPTZ, nullable=True),
        sa.Column("snapshot_b_timestamp", TIMESTAMPTZ, nullable=True),
        sa.Column("prices_a", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("prices_b", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("market_a_best_bid", sa.Float(), nullable=True),
        sa.Column("market_a_best_ask", sa.Float(), nullable=True),
        sa.Column("market_a_spread", sa.Float(), nullable=True),
        sa.Column("market_a_visible_depth", sa.Float(), nullable=True),
        sa.Column("market_b_best_bid", sa.Float(), nullable=True),
        sa.Column("market_b_best_ask", sa.Float(), nullable=True),
        sa.Column("market_b_spread", sa.Float(), nullable=True),
        sa.Column("market_b_visible_depth", sa.Float(), nullable=True),
        sa.Column("dependency_type", sa.String(), nullable=True),
        sa.Column("implication_direction", sa.String(), nullable=True),
        sa.Column("classification_source", sa.String(), nullable=True),
        sa.Column("classifier_model", sa.String(), nullable=True),
        sa.Column("classifier_prompt_adapter", sa.String(), nullable=True),
        sa.Column("classifier_confidence", sa.Float(), nullable=True),
        sa.Column("classification_reasoning", sa.Text(), nullable=True),
        sa.Column("verification_passed", sa.Boolean(), nullable=True),
        sa.Column("verification_reasons", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("silver_failure_signature", sa.String(length=64), nullable=True),
        sa.Column("profit_bound", sa.Numeric(), nullable=True),
        sa.Column(
            "passed_to_optimization",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("optimizer_preview_status", sa.String(length=64), nullable=True),
        sa.Column("optimizer_preview_estimated_profit", sa.Numeric(), nullable=True),
        sa.Column("optimizer_preview_trade_count", sa.Integer(), nullable=True),
        sa.Column("optimizer_preview_max_edge", sa.Float(), nullable=True),
        sa.Column("optimizer_preview_rejection_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "would_trade",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.ForeignKeyConstraint(["market_a_id"], ["markets.id"]),
        sa.ForeignKeyConstraint(["market_b_id"], ["markets.id"]),
        sa.ForeignKeyConstraint(["opportunity_id"], ["arbitrage_opportunities.id"]),
        sa.ForeignKeyConstraint(["pair_id"], ["market_pairs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shadow_candidate_logs_logged_at",
        "shadow_candidate_logs",
        [sa.text("logged_at DESC")],
    )
    op.create_index(
        "ix_shadow_candidate_logs_decision_outcome",
        "shadow_candidate_logs",
        ["decision_outcome"],
    )
    op.create_index(
        "ix_shadow_candidate_logs_silver_failure_signature",
        "shadow_candidate_logs",
        ["silver_failure_signature"],
    )
    op.create_index(
        "ix_shadow_candidate_logs_pair_id",
        "shadow_candidate_logs",
        ["pair_id"],
    )
    op.create_index(
        "ix_shadow_candidate_logs_opportunity_id",
        "shadow_candidate_logs",
        ["opportunity_id"],
    )
    op.create_index(
        "ix_shadow_candidate_logs_market_a_id",
        "shadow_candidate_logs",
        ["market_a_id"],
    )
    op.create_index(
        "ix_shadow_candidate_logs_market_b_id",
        "shadow_candidate_logs",
        ["market_b_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shadow_candidate_logs_market_b_id", table_name="shadow_candidate_logs")
    op.drop_index("ix_shadow_candidate_logs_market_a_id", table_name="shadow_candidate_logs")
    op.drop_index("ix_shadow_candidate_logs_opportunity_id", table_name="shadow_candidate_logs")
    op.drop_index("ix_shadow_candidate_logs_pair_id", table_name="shadow_candidate_logs")
    op.drop_index("ix_shadow_candidate_logs_silver_failure_signature", table_name="shadow_candidate_logs")
    op.drop_index("ix_shadow_candidate_logs_decision_outcome", table_name="shadow_candidate_logs")
    op.drop_index("ix_shadow_candidate_logs_logged_at", table_name="shadow_candidate_logs")
    op.drop_table("shadow_candidate_logs")
