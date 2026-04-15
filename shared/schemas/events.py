"""Schemas for Redis pub/sub event payloads.

One model per channel.  Used by ``publish_event()`` / ``subscribe_typed()``
in ``shared.events`` to validate at the serialization boundary.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


# -- Ingestor events -------------------------------------------------------

class MarketUpdatedEvent(BaseModel):
    action: str        # "sync"
    count: int


class SnapshotCreatedEvent(BaseModel):
    count: int
    source: str        # "websocket" | "polling" | "kalshi_polling"
    market_ids: list[int]


class MarketResolvedEvent(BaseModel):
    market_id: int
    resolved_outcome: str
    source: str        # "api" | "price_threshold" | "websocket"
    price: Optional[float] = None


# -- Detector events --------------------------------------------------------

class PairDetectedEvent(BaseModel):
    pair_id: int
    market_a_id: int
    market_b_id: int
    dependency_type: str
    confidence: float


class ArbitrageFoundEvent(BaseModel):
    opportunity_id: int
    pair_id: int
    type: str          # "rebalancing"
    theoretical_profit: float


# -- Optimizer events -------------------------------------------------------

class OptimizationCompleteEvent(BaseModel):
    opportunity_id: int
    pair_id: int
    status: str
    iterations: int
    bregman_gap: float
    estimated_profit: float
    n_trades: int
    converged: bool


# -- Simulator events -------------------------------------------------------

class TradeExecutedEvent(BaseModel):
    trade_id: int
    opportunity_id: int
    market_id: int
    outcome: str
    side: str
    size: float
    vwap_price: float
    slippage: float


class PortfolioUpdatedEvent(BaseModel):
    cash: float
    positions: dict[str, float]
    cost_basis: dict[str, float]
    total_value: float
    realized_pnl: float
    unrealized_pnl: float
    total_trades: int
    settled_trades: int
    winning_trades: int
    positions_in_profit: int = 0
    total_positions: int = 0


# -- Live trading events ----------------------------------------------------

class LiveStatusEvent(BaseModel):
    enabled: bool = False
    dry_run: bool = True
    active: bool = False
    kill_switch: bool = False
    adapter_ready: bool = False
    last_heartbeat: Optional[str] = None
    updated_at: Optional[str] = None
