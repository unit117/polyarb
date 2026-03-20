from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
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
