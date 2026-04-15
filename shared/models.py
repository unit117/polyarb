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

from shared.lifecycle import OppStatus, OrderStatus, TradeStatus

TIMESTAMPTZ = DateTime(timezone=True)
LIVE_ORDER_STATUSES = tuple(OrderStatus)


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
    fee_rate_bps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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


class PairClassificationCache(Base):
    __tablename__ = "pair_classification_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    market_a_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    market_b_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    classifier_model: Mapped[str] = mapped_column(String(128))
    prompt_adapter: Mapped[str] = mapped_column(String(32))
    cache_version: Mapped[str] = mapped_column(String(32))
    market_a_fingerprint: Mapped[str] = mapped_column(String(64))
    market_b_fingerprint: Mapped[str] = mapped_column(String(64))
    classification: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "ix_pair_classification_cache_lookup",
            "market_a_id",
            "market_b_id",
            "classifier_model",
            "prompt_adapter",
            "cache_version",
            unique=True,
        ),
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
    status: Mapped[str] = mapped_column(String, default=OppStatus.DETECTED)
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
    status: Mapped[str] = mapped_column(String, default=TradeStatus.FILLED)
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
    cost_basis: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    status: Mapped[str] = mapped_column(String, default=OrderStatus.DRY_RUN)
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
