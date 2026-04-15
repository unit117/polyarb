"""Schemas for ArbitrageOpportunity JSONB fields."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class TradeLeg(BaseModel):
    """Single leg of an optimal trade bundle."""
    market: str            # "A" or "B"
    outcome: str
    outcome_index: int
    side: str              # "BUY" or "SELL"
    edge: float
    market_price: float
    fair_price: float
    venue: str = "polymarket"
    fee_rate_bps: Optional[int] = None


class MarketPriceComparison(BaseModel):
    """Current vs. optimal prices for one side of the pair."""
    current: list[float]
    optimal: list[float]


class OptimalTrades(BaseModel):
    """ArbitrageOpportunity.optimal_trades — Frank-Wolfe optimization result.

    Built by ``compute_trades()`` in the optimizer.
    Consumed by the simulator to validate and execute paper trades.
    """
    trades: list[TradeLeg]
    estimated_profit: float
    theoretical_profit: float
    market_a_prices: MarketPriceComparison
    market_b_prices: MarketPriceComparison
