from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
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


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True)
    polymarket_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcomes: Mapped[dict] = mapped_column(JSONB)
    token_ids: Mapped[dict] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    end_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    liquidity: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
    resolved_outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )

    snapshots: Mapped[list["PriceSnapshot"]] = relationship(back_populates="market")

    __table_args__ = (
        Index("ix_markets_active", "active", postgresql_where=(active == True)),  # noqa: E712
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    prices: Mapped[dict] = mapped_column(JSONB)
    order_book: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    midpoints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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
    constraint_matrix: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    estimated_profit: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    optimal_trades: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fw_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bregman_gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="detected")

    pair: Mapped["MarketPair"] = relationship(back_populates="opportunities")

    __table_args__ = (
        Index("ix_arbitrage_opportunities_status", "status"),
    )


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int | None] = mapped_column(
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
