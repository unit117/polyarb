from datetime import datetime
from decimal import Decimal
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TIMESTAMPTZ = DateTime(timezone=True)
LIVE_ORDER_STATUSES = (
    "dry_run",
    "submitted",
    "filled",
    "partially_filled",
    "cancelled",
    "rejected",
    "expired",
    "settled",
)


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True)
    polymarket_id: Mapped[str] = mapped_column(String, index=True)
    venue: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="polymarket"
    )
    event_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    question: Mapped[str] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcomes: Mapped[dict] = mapped_column(JSONB)
    token_ids: Mapped[dict] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    volume: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    liquidity: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    embedding: Mapped[Optional[list]] = mapped_column(Vector(384), nullable=True)
    resolved_outcome: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )

    snapshots: Mapped[list["PriceSnapshot"]] = relationship(back_populates="market")

    __table_args__ = (
        Index("ix_markets_active", "active", postgresql_where=(active == True)),  # noqa: E712
        Index("ix_markets_venue", "venue"),
        Index(
            "ix_markets_venue_polymarket_id",
            "venue",
            "polymarket_id",
            unique=True,
        ),
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    prices: Mapped[dict] = mapped_column(JSONB)
    order_book: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    midpoints: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    market: Mapped["Market"] = relationship(back_populates="snapshots")

    __table_args__ = (
        Index(
            "ix_price_snapshots_market_timestamp",
            "market_id",
            timestamp.desc(),
        ),
    )


class MarketPair(Base):
    __tablename__ = "market_pairs"

    id: Mapped[int] = mapped_column(primary_key=True)
    market_a_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    market_b_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    dependency_type: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    constraint_matrix: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    resolution_vectors: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    implication_direction: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classification_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    market_a: Mapped["Market"] = relationship(foreign_keys=[market_a_id])
    market_b: Mapped["Market"] = relationship(foreign_keys=[market_b_id])
    opportunities: Mapped[list["ArbitrageOpportunity"]] = relationship(
        back_populates="pair"
    )

    __table_args__ = (
        Index("ix_market_pairs_markets", "market_a_id", "market_b_id", unique=True),
        Index("ix_market_pairs_dependency_type", "dependency_type"),
    )


class ArbitrageOpportunity(Base):
    __tablename__ = "arbitrage_opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("market_pairs.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    type: Mapped[str] = mapped_column(String)
    theoretical_profit: Mapped[Decimal] = mapped_column(Numeric)
    estimated_profit: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    optimal_trades: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    fw_iterations: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bregman_gap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="detected")
    pending_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    expired_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    dependency_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    pair: Mapped["MarketPair"] = relationship(back_populates="opportunities")

    __table_args__ = (
        Index("ix_arbitrage_opportunities_status", "status"),
    )


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arbitrage_opportunities.id"), nullable=True, index=True
    )
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    outcome: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    size: Mapped[Decimal] = mapped_column(Numeric)
    entry_price: Mapped[Decimal] = mapped_column(Numeric)
    vwap_price: Mapped[Decimal] = mapped_column(Numeric)
    slippage: Mapped[Decimal] = mapped_column(Numeric)
    fees: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    executed_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String, default="filled")
    source: Mapped[str] = mapped_column(String, server_default="paper")
    venue: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, server_default="polymarket"
    )

    opportunity: Mapped["ArbitrageOpportunity"] = relationship()
    market: Mapped["Market"] = relationship()


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    cash: Mapped[Decimal] = mapped_column(Numeric)
    positions: Mapped[dict] = mapped_column(JSONB)
    total_value: Mapped[Decimal] = mapped_column(Numeric)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric)
    total_trades: Mapped[int] = mapped_column(Integer)
    settled_trades: Mapped[int] = mapped_column(Integer, server_default="0")
    winning_trades: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String, server_default="paper")

    __table_args__ = (
        Index("ix_portfolio_snapshots_timestamp", timestamp.desc()),
    )


class LiveOrder(Base):
    __tablename__ = "live_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arbitrage_opportunities.id"), nullable=True, index=True
    )
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    outcome: Mapped[str] = mapped_column(String)
    token_id: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    requested_size: Mapped[Decimal] = mapped_column(Numeric)
    requested_price: Mapped[Decimal] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String, default="dry_run")
    dry_run: Mapped[bool] = mapped_column(Boolean, server_default="false")
    venue_order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    opportunity: Mapped[Optional["ArbitrageOpportunity"]] = relationship()
    market: Mapped["Market"] = relationship()
    fills: Mapped[list["LiveFill"]] = relationship(back_populates="live_order")

    __table_args__ = (
        Index("ix_live_orders_status", "status"),
        Index("ix_live_orders_submitted_at", submitted_at.desc()),
        CheckConstraint(
            "status IN ('dry_run','submitted','filled','partially_filled','cancelled','rejected','expired','settled')",
            name="ck_live_orders_status",
        ),
    )


class LiveFill(Base):
    __tablename__ = "live_fills"

    id: Mapped[int] = mapped_column(primary_key=True)
    live_order_id: Mapped[int] = mapped_column(
        ForeignKey("live_orders.id"), index=True
    )
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    outcome: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    venue_fill_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fill_size: Mapped[Decimal] = mapped_column(Numeric)
    fill_price: Mapped[Decimal] = mapped_column(Numeric)
    fees: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    filled_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )

    live_order: Mapped["LiveOrder"] = relationship(back_populates="fills")
    market: Mapped["Market"] = relationship()

    __table_args__ = (
        Index("ix_live_fills_filled_at", filled_at.desc()),
        Index("ix_live_fills_venue_fill_id", "venue_fill_id", unique=True),
    )


class ShadowCandidateLog(Base):
    """Shadow log of every candidate pair evaluation in the detector.

    Captures the full decision context — classification, verification,
    prices, rejection reasons — for offline review of detector quality.
    Phase 0.5 of PMXT Historical Live Replay plan.
    """

    __tablename__ = "shadow_candidate_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    logged_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    pipeline_source: Mapped[str] = mapped_column(String(32))
    # Values: periodic, market_sync, snapshot_rescan, cross_venue
    decision_outcome: Mapped[str] = mapped_column(String(64))
    # Values: classified_none, uncertainty_filtered, unverified,
    #         verified_no_profit, opportunity_created, duplicate_pair, error
    similarity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Pair / opportunity linkage
    pair_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("market_pairs.id"), nullable=True
    )
    opportunity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arbitrage_opportunities.id"), nullable=True
    )

    # Market identification
    market_a_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    market_b_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    market_a_event_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    market_b_event_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    market_a_question: Mapped[str] = mapped_column(Text)
    market_b_question: Mapped[str] = mapped_column(Text)
    market_a_outcomes: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    market_b_outcomes: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    market_a_venue: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    market_b_venue: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    market_a_liquidity: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    market_b_liquidity: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    market_a_volume: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    market_b_volume: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)

    # Price snapshot context
    snapshot_a_timestamp: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    snapshot_b_timestamp: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    prices_a: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    prices_b: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    market_a_best_bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_a_best_ask: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_a_spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_a_visible_depth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_b_best_bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_b_best_ask: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_b_spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_b_visible_depth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Classification output
    dependency_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    implication_direction: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classification_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classifier_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classifier_prompt_adapter: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classifier_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    classification_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Verification result
    verification_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    verification_reasons: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    silver_failure_signature: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Constraint / profit
    profit_bound: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)

    # Downstream gate results
    passed_to_optimization: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )
    optimizer_preview_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    optimizer_preview_estimated_profit: Mapped[Optional[Decimal]] = mapped_column(
        Numeric, nullable=True
    )
    optimizer_preview_trade_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    optimizer_preview_max_edge: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    optimizer_preview_rejection_reason: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    would_trade: Mapped[bool] = mapped_column(Boolean, server_default="false")

    market_a: Mapped["Market"] = relationship(foreign_keys=[market_a_id])
    market_b: Mapped["Market"] = relationship(foreign_keys=[market_b_id])

    __table_args__ = (
        Index("ix_shadow_candidate_logs_logged_at", logged_at.desc()),
        Index("ix_shadow_candidate_logs_decision_outcome", "decision_outcome"),
        Index("ix_shadow_candidate_logs_silver_failure_signature", "silver_failure_signature"),
        Index("ix_shadow_candidate_logs_pair_id", "pair_id"),
        Index("ix_shadow_candidate_logs_opportunity_id", "opportunity_id"),
        Index("ix_shadow_candidate_logs_market_a_id", "market_a_id"),
        Index("ix_shadow_candidate_logs_market_b_id", "market_b_id"),
    )
