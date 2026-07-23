"""Trade validation: build and validate execution bundles before trading."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from shared.circuit_breaker import CircuitBreaker
from shared.config import settings, venue_fee, DRAWDOWN_THRESHOLD, DRAWDOWN_WINDOW, DRAWDOWN_MIN_SCALE
from shared.models import PriceSnapshot
from shared.frozen_cooldown import record_frozen_rejection
from shared.metrics import incr_metric
from shared.pricing import get_latest_snapshot, is_price_frozen, select_outcome_book
from shared.schemas import OptimalTrades
from services.simulator.portfolio import Portfolio, opening_exposure_size
from services.simulator.vwap import compute_vwap

logger = structlog.get_logger()

# Anchors the post-restart grace window (import time ≈ process start). For
# simulator_startup_grace_seconds after boot, only snapshots written AFTER
# boot are tradeable: pre-restart snapshots can pass the max-age gate while
# the market moved during the outage.
_PROCESS_START = datetime.now(timezone.utc)


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
    redis=None,
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
        # Deterministic zero-edge pairs used to bypass the frozen-pair
        # cooldown entirely — this return preceded the only
        # record_frozen_rejection call site, so a pair whose optimizer
        # output is exactly zero could recycle detect→optimize→reject
        # forever (pair 51726: ~350 opps in 1.5 days). Count it toward the
        # same threshold as frozen-price rejections.
        if await record_frozen_rejection(redis, opp.pair_id):
            logger.warning(
                "zero_edge_pair_cooldown_started",
                pair_id=opp.pair_id,
                opportunity_id=opp.id,
                cooldown_seconds=settings.frozen_pair_cooldown_seconds,
            )
        return None
    net_profit = optimal.estimated_profit

    # Half-Kelly with a conservative cap
    kelly_fraction = min(net_profit * settings.kelly_multiplier, settings.kelly_fraction_cap)

    total_value = portfolio.total_value(current_prices)
    drawdown = 1.0 - (total_value / float(portfolio.initial_capital))
    if drawdown > DRAWDOWN_THRESHOLD:
        drawdown_scale = max(DRAWDOWN_MIN_SCALE, 1.0 - (drawdown - DRAWDOWN_THRESHOLD) / DRAWDOWN_WINDOW)
        kelly_fraction *= drawdown_scale

    base_size = kelly_fraction * max_position_size
    validated_legs: list[ValidatedLeg] = []
    from decimal import Decimal
    reserved_cash = Decimal("0")
    opening_flow = Decimal("0")  # dollars of NEW exposure this bundle opens

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

        # Post-restart grace: within the window, refuse snapshots written
        # before this process booted (they may look fresh but predate the
        # restart, and the market moved while everything was down).
        if settings.simulator_startup_grace_seconds > 0:
            since_boot = (datetime.now(timezone.utc) - _PROCESS_START).total_seconds()
            if since_boot < settings.simulator_startup_grace_seconds:
                snap_ts = snapshot.timestamp
                if snap_ts.tzinfo is None:
                    snap_ts = snap_ts.replace(tzinfo=timezone.utc)
                if snap_ts < _PROCESS_START:
                    await incr_metric(redis, "startup_grace_skips")
                    logger.info(
                        "startup_grace_stale_snapshot_skipped",
                        opportunity_id=opp.id,
                        market_id=market.id,
                        snapshot_age_seconds=round(
                            (datetime.now(timezone.utc) - snap_ts).total_seconds()
                        ),
                        grace_remaining_seconds=round(
                            settings.simulator_startup_grace_seconds - since_boot
                        ),
                    )
                    return None

        # A fresh snapshot is necessary but not sufficient: the ingestor
        # re-writes identical prices for illiquid/dead markets, so a frozen
        # midpoint passes the freshness check above. Reject those — their
        # "edge" is fabricated from stale quotes, and trading them re-enters
        # the same position every cycle, accumulating on dead data.
        if settings.reject_frozen_prices and await is_price_frozen(
            session,
            market.id,
            trade.outcome,
            window_seconds=settings.price_staleness_window_seconds,
            min_observations=settings.price_staleness_min_observations,
        ):
            logger.info(
                "frozen_price_skipped",
                opportunity_id=opp.id,
                market_id=market.id,
                outcome=trade.outcome,
                window_seconds=settings.price_staleness_window_seconds,
            )
            # Tell the rest of the pipeline this pair keeps failing on frozen
            # quotes; past the threshold the detector stops re-creating its
            # opportunities and the ingestor stops polling it.
            if await record_frozen_rejection(redis, opp.pair_id):
                logger.warning(
                    "frozen_pair_cooldown_started",
                    pair_id=opp.pair_id,
                    opportunity_id=opp.id,
                    market_id=market.id,
                    cooldown_seconds=settings.frozen_pair_cooldown_seconds,
                )
            return None

        midpoint = trade.market_price or 0.5
        fill = compute_vwap(
            select_outcome_book(snapshot.order_book, trade.outcome),
            trade.side,
            base_size,
            midpoint,
        )

        # Exposure-opening dollars count toward the per-pair flow cap. Both
        # directions open exposure: BUYs opening/adding longs AND SELLs
        # opening/adding shorts (pair 53507 hit 20% of net cash flow with
        # 188 short-opening SELLs — a BUY-only cap would have missed it).
        # Flip-aware: a leg larger than the position it closes opens the
        # remainder as new exposure.
        leg_key = f"{market.id}:{trade.outcome}"
        leg_existing = portfolio.positions.get(leg_key, Decimal("0"))
        opening_size = opening_exposure_size(
            trade.side, leg_existing, fill["filled_size"]
        )
        if opening_size > 0:
            opening_flow += opening_size * Decimal(str(fill["vwap_price"]))
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

    # Per-pair concentration cap: bound the dollars of new exposure one pair
    # may open within the rolling window. Exits are never blocked.
    if (
        settings.max_pair_weekly_flow > 0
        and opp.pair_id is not None
        and opening_flow > 0
    ):
        recent_flow = portfolio.pair_flow(
            opp.pair_id, settings.pair_flow_window_seconds
        )
        if recent_flow + opening_flow > Decimal(str(settings.max_pair_weekly_flow)):
            await incr_metric(redis, "pair_flow_cap_rejections")
            logger.info(
                "pair_flow_cap_rejected",
                opportunity_id=opp.id,
                pair_id=opp.pair_id,
                window_flow=float(recent_flow),
                opening_flow=float(opening_flow),
                limit=settings.max_pair_weekly_flow,
            )
            # A capped pair stays capped for up to the window length; feed
            # the cooldown so detection stops re-creating its opportunities
            # instead of looping detect->optimize->reject for days.
            if await record_frozen_rejection(redis, opp.pair_id):
                logger.warning(
                    "pair_flow_cap_cooldown_started",
                    pair_id=opp.pair_id,
                    opportunity_id=opp.id,
                    cooldown_seconds=settings.frozen_pair_cooldown_seconds,
                )
            return None

    return ValidatedExecutionBundle(
        opportunity_id=opp.id,
        pair_id=opp.pair_id,
        estimated_profit=float(opp.estimated_profit or 0),
        kelly_fraction=kelly_fraction,
        current_prices=current_prices,
        legs=validated_legs,
    )


