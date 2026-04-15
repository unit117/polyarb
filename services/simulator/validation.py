"""Trade validation: build and validate execution bundles before trading."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from shared.circuit_breaker import CircuitBreaker
from shared.config import settings, venue_fee
from shared.models import PriceSnapshot
from shared.schemas import OptimalTrades
from services.simulator.portfolio import Portfolio
from services.simulator.vwap import compute_vwap

logger = structlog.get_logger()


@dataclass(frozen=True)
class ValidatedLeg:
    market_id: int
    outcome: str
    side: str
    size: float
    entry_price: float
    vwap_price: float
    slippage: float
    fees: float
    fair_price: float
    trade_venue: str


@dataclass(frozen=True)
class ValidatedExecutionBundle:
    opportunity_id: int
    pair_id: int
    estimated_profit: float
    kelly_fraction: float
    current_prices: dict[str, float]
    legs: list[ValidatedLeg]


async def build_validated_bundle(
    session,
    opp,
    market_a,
    market_b,
    *,
    portfolio: Portfolio,
    max_position_size: float,
    circuit_breaker: CircuitBreaker | None,
    current_prices: dict[str, float],
) -> ValidatedExecutionBundle | None:
    """Validate an opportunity and build an execution bundle.

    Checks: market resolution, VWAP fill, edge after slippage,
    cash availability, and circuit breaker pre-trade limits.

    Returns None if any validation fails (all-or-none).
    """
    # Reject opportunities on resolved or inactive markets
    for m in (market_a, market_b):
        if m and (m.resolved_outcome is not None or not m.active):
            logger.info(
                "resolved_market_skipped",
                opportunity_id=opp.id,
                market_id=m.id,
                resolved=m.resolved_outcome,
                active=m.active,
            )
            return None

    try:
        optimal = OptimalTrades.model_validate(opp.optimal_trades)
    except Exception:
        logger.warning("invalid_optimal_trades", opportunity_id=opp.id)
        return None

    if optimal.estimated_profit <= 0:
        return None
    net_profit = optimal.estimated_profit

    # Half-Kelly with a conservative cap
    kelly_fraction = min(net_profit * 0.5, 0.25)

    total_value = portfolio.total_value(current_prices)
    drawdown = 1.0 - (total_value / float(portfolio.initial_capital))
    if drawdown > 0.05:
        drawdown_scale = max(0.5, 1.0 - (drawdown - 0.05) / 0.10)
        kelly_fraction *= drawdown_scale

    base_size = kelly_fraction * max_position_size
    validated_legs: list[ValidatedLeg] = []
    from decimal import Decimal
    reserved_cash = Decimal("0")

    for trade in optimal.trades:
        market = market_a if trade.market == "A" else market_b
        if not market:
            return None

        snapshot = await get_latest_snapshot(
            session, market.id, settings.max_snapshot_age_seconds
        )
        if not snapshot:
            logger.info(
                "stale_snapshot_skipped",
                opportunity_id=opp.id,
                market_id=market.id,
            )
            return None

        midpoint = trade.market_price or 0.5
        fill = compute_vwap(snapshot.order_book, trade.side, base_size, midpoint)
        trade_venue = trade.venue or getattr(market, "venue", "polymarket")
        fee_bps = trade.fee_rate_bps if trade.fee_rate_bps is not None else getattr(market, "fee_rate_bps", None)
        fees = (
            venue_fee(trade_venue, fill["vwap_price"], trade.side,
                      fee_rate_bps=fee_bps)
            * fill["filled_size"]
        )

        if trade.side == "BUY":
            cost = (
                Decimal(str(fill["filled_size"]))
                * Decimal(str(fill["vwap_price"]))
                + Decimal(str(fees))
            )
            available = portfolio.cash - reserved_cash
            if cost > available:
                logger.info(
                    "insufficient_cash_for_leg",
                    opportunity_id=opp.id,
                    market_id=market.id,
                    cost=float(cost),
                    available=float(available),
                )
                return None
            reserved_cash += cost

        if trade.fair_price > 0:
            if trade.side == "BUY":
                post_vwap_edge = trade.fair_price - fill["vwap_price"]
            else:
                post_vwap_edge = fill["vwap_price"] - trade.fair_price
            per_share_fee = venue_fee(trade_venue, fill["vwap_price"], trade.side,
                                     fee_rate_bps=fee_bps)
            if post_vwap_edge - per_share_fee <= 0:
                logger.info(
                    "edge_killed_by_slippage",
                    opportunity_id=opp.id,
                    market_id=market.id,
                    fair_price=trade.fair_price,
                    vwap_price=fill["vwap_price"],
                    post_vwap_edge=round(post_vwap_edge, 6),
                    fee=round(per_share_fee, 6),
                )
                return None

        if circuit_breaker:
            allowed, reason = await circuit_breaker.pre_trade_check(
                portfolio,
                market.id,
                fill["filled_size"],
                trade_side=trade.side,
                outcome=trade.outcome,
                current_prices=current_prices,
            )
            if not allowed:
                logger.warning(
                    "trade_blocked_by_circuit_breaker",
                    opportunity_id=opp.id,
                    market_id=market.id,
                    reason=reason,
                )
                return None

        validated_legs.append(
            ValidatedLeg(
                market_id=market.id,
                outcome=trade.outcome,
                side=trade.side,
                size=fill["filled_size"],
                entry_price=midpoint,
                vwap_price=fill["vwap_price"],
                slippage=fill["slippage"],
                fees=fees,
                fair_price=trade.fair_price,
                trade_venue=trade_venue,
            )
        )

    if not validated_legs:
        return None

    return ValidatedExecutionBundle(
        opportunity_id=opp.id,
        pair_id=opp.pair_id,
        estimated_profit=float(opp.estimated_profit or 0),
        kelly_fraction=kelly_fraction,
        current_prices=current_prices,
        legs=validated_legs,
    )


async def get_latest_snapshot(session, market_id: int, max_age_seconds: int = 0):
    """Fetch the most recent price snapshot for a market."""
    query = (
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    if max_age_seconds > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        query = query.where(PriceSnapshot.timestamp >= cutoff)
    result = await session.execute(query)
    return result.scalar_one_or_none()
