"""Schemas for Market and PriceSnapshot JSONB fields."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Simple type aliases (no structural validation needed)
# ---------------------------------------------------------------------------

#: Market.outcomes — ordered list of outcome labels, e.g. ["Yes", "No"]
Outcomes = List[str]

#: Market.token_ids — ordered list of CLOB/venue token identifiers
TokenIds = List[str]

#: PriceSnapshot.prices / midpoints — outcome label → price float
PriceMap = Dict[str, float]

#: PortfolioSnapshot.positions — "market_id:outcome" → shares held
PositionMap = Dict[str, float]

#: PortfolioSnapshot.cost_basis — "market_id:outcome" → total cost
CostBasisMap = Dict[str, float]


# ---------------------------------------------------------------------------
# Structured models
# ---------------------------------------------------------------------------

class OrderBookLevel(BaseModel):
    """Single price level: [price, size]."""
    price: float
    size: float


class OrderBook(BaseModel):
    """PriceSnapshot.order_book — L2 depth for one outcome."""
    bids: list[list[float]]
    asks: list[list[float]]


class ResolutionVector(BaseModel):
    """Single feasible joint-outcome combination from LLM classification."""
    a: str
    b: str
