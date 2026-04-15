"""Typed schemas for all cross-boundary payloads.

Every JSONB column, Redis event, and API response has a Pydantic model or
type alias defined here.  Treat JSONB as the *storage format*, not the
contract — these models are the contract.
"""

from shared.schemas.events import (
    ArbitrageFoundEvent,
    LiveStatusEvent,
    MarketResolvedEvent,
    MarketUpdatedEvent,
    OptimizationCompleteEvent,
    PairDetectedEvent,
    PortfolioUpdatedEvent,
    SnapshotCreatedEvent,
    TradeExecutedEvent,
)
from shared.schemas.market import (
    CostBasisMap,
    OrderBook,
    OrderBookLevel,
    Outcomes,
    PositionMap,
    PriceMap,
    ResolutionVector,
    TokenIds,
)
from shared.schemas.opportunity import (
    MarketPriceComparison,
    OptimalTrades,
    TradeLeg,
)
from shared.schemas.pair import (
    ClassificationResult,
    ConstraintMatrix,
)

__all__ = [
    # Market / snapshot
    "CostBasisMap",
    "OrderBook",
    "OrderBookLevel",
    "Outcomes",
    "PositionMap",
    "PriceMap",
    "ResolutionVector",
    "TokenIds",
    # Pair
    "ClassificationResult",
    "ConstraintMatrix",
    # Opportunity
    "MarketPriceComparison",
    "OptimalTrades",
    "TradeLeg",
    # Events
    "ArbitrageFoundEvent",
    "LiveStatusEvent",
    "MarketResolvedEvent",
    "MarketUpdatedEvent",
    "OptimizationCompleteEvent",
    "PairDetectedEvent",
    "PortfolioUpdatedEvent",
    "SnapshotCreatedEvent",
    "TradeExecutedEvent",
]
