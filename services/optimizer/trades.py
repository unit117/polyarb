"""Convert optimization results to trade recommendations.

Compares the optimal distribution q* (from Frank-Wolfe) with current market
prices p to determine which outcomes are mispriced and what trades would
capture the arbitrage.
"""

import structlog
import numpy as np

from shared.config import venue_fee
from shared.schemas import MarketPriceComparison, OptimalTrades, TradeLeg
from services.optimizer.frank_wolfe import FWResult

logger = structlog.get_logger()

# Edges above this are almost certainly misclassified pairs, not real arb.
# A 20¢ edge on a liquid Polymarket binary is implausible.
MAX_EDGE = 0.20


def _price_comparison(p_vec, q_vec) -> MarketPriceComparison:
    return MarketPriceComparison(
        current=[round(float(x), 6) for x in p_vec],
        optimal=[round(float(x), 6) for x in q_vec],
    )


def _empty_result(
    theoretical_profit: float, p_a, q_a, p_b, q_b,
) -> OptimalTrades:
    return OptimalTrades(
        trades=[],
        estimated_profit=0.0,
        theoretical_profit=round(theoretical_profit, 6),
        market_a_prices=_price_comparison(p_a, q_a),
        market_b_prices=_price_comparison(p_b, q_b),
    )


def compute_trades(
    result: FWResult,
    outcomes_a: list[str],
    outcomes_b: list[str],
    theoretical_profit: float = 0.0,
    min_edge: float = 0.03,
    venue_a: str = "polymarket",
    venue_b: str = "polymarket",
    fee_rate_bps_a: int | None = None,
    fee_rate_bps_b: int | None = None,
) -> OptimalTrades:
    """Compute optimal trades from the FW result."""
    n_a = result.n_outcomes_a
    q = result.optimal_q
    p = result.market_prices

    q_a = q[:n_a]
    q_b = q[n_a:]
    p_a = p[:n_a]
    p_b = p[n_a:]

    trades: list[TradeLeg] = []

    # For each market, collect all candidate legs then keep only the
    # best-edge leg.  In binary markets BUY Yes and SELL No are mirrors
    # of the same mispricing — executing both pays double fees for the
    # same edge.
    for market_label, outcomes, q_vec, p_vec, venue, fee_bps in [
        ("A", outcomes_a, q_a, p_a, venue_a, fee_rate_bps_a),
        ("B", outcomes_b, q_b, p_b, venue_b, fee_rate_bps_b),
    ]:
        candidates: list[TradeLeg] = []
        for i, outcome in enumerate(outcomes):
            edge = float(q_vec[i] - p_vec[i])
            if abs(edge) > min_edge:
                candidates.append(TradeLeg(
                    market=market_label,
                    outcome=outcome,
                    outcome_index=i,
                    side="BUY" if edge > 0 else "SELL",
                    edge=round(abs(edge), 6),
                    market_price=round(float(p_vec[i]), 6),
                    fair_price=round(float(q_vec[i]), 6),
                    venue=venue,
                    fee_rate_bps=fee_bps,
                ))
        if candidates:
            if len(outcomes) <= 2:
                # Binary markets: BUY Yes and SELL No are mirrors — keep only
                # the best-edge leg to avoid paying double fees
                trades.append(max(candidates, key=lambda t: t.edge))
            else:
                # Multi-outcome markets: keep all legs to preserve hedge structure
                trades.extend(candidates)

    # Sanity cap: edges above MAX_EDGE are almost certainly misclassified
    # pairs, not real arbitrage.  Drop the entire opportunity.
    for t in trades:
        if t.edge > MAX_EDGE:
            logger.warning(
                "edge_sanity_cap_triggered",
                market=t.market,
                outcome=t.outcome,
                edge=t.edge,
            )
            return _empty_result(theoretical_profit, p_a, q_a, p_b, q_b)

    edge_a = max((t.edge for t in trades if t.market == "A"), default=0.0)
    edge_b = max((t.edge for t in trades if t.market == "B"), default=0.0)
    raw_edge = edge_a + edge_b

    # Estimated fees: per-leg using venue fee schedule at trade price
    est_fees = sum(
        venue_fee(t.venue, t.market_price, t.side,
                  fee_rate_bps=t.fee_rate_bps)
        for t in trades
    )

    # Estimated slippage cost: conservative 0.5% per leg (matches VWAP
    # midpoint fallback).  Without order book data at optimization time
    # this is the best proxy for execution cost.
    est_slippage = sum(t.market_price * 0.005 for t in trades)

    # Note: this is a per-unit edge proxy (not size-aware dollar PnL).
    # Downstream consumers (Kelly sizing, dashboard) should be aware of this.
    estimated_profit = max(raw_edge - est_fees - est_slippage, 0.0)

    # BT-008: Reject opportunities where net edge after fees+slippage is
    # too small to overcome execution friction. Minimum 0.5% net edge.
    if estimated_profit < 0.005:
        logger.info(
            "trade_below_min_profit",
            estimated_profit=round(estimated_profit, 6),
            raw_edge=round(raw_edge, 6),
            est_fees=round(est_fees, 6),
            est_slippage=round(est_slippage, 6),
        )
        return _empty_result(theoretical_profit, p_a, q_a, p_b, q_b)

    # BT-009: Payout proof — verify the trade bundle has non-negative
    # worst-case payoff across all feasible joint outcomes.
    feasibility = result.feasibility_matrix
    if feasibility and trades:
        worst_payoff = _worst_case_payoff(trades, outcomes_a, outcomes_b, feasibility)
        if worst_payoff < -0.01:  # Allow 1¢ tolerance for floating point
            logger.warning(
                "payout_proof_failed",
                worst_payoff=round(worst_payoff, 6),
                trades=len(trades),
            )
            return _empty_result(theoretical_profit, p_a, q_a, p_b, q_b)

    return OptimalTrades(
        trades=trades,
        estimated_profit=round(estimated_profit, 6),
        theoretical_profit=round(theoretical_profit, 6),
        market_a_prices=_price_comparison(p_a, q_a),
        market_b_prices=_price_comparison(p_b, q_b),
    )


def _worst_case_payoff(
    trades: list[TradeLeg],
    outcomes_a: list[str],
    outcomes_b: list[str],
    feasibility: list[list[int]],
) -> float:
    """Compute worst-case payoff across all feasible joint outcomes.

    For each feasible (outcome_a, outcome_b) combination, compute the
    net PnL of the trade bundle assuming that combination resolves.
    Returns the minimum payoff (worst case).
    """
    worst = float("inf")

    for i, oa in enumerate(outcomes_a):
        for j, ob in enumerate(outcomes_b):
            if not feasibility[i][j]:
                continue  # infeasible outcome — skip

            # Compute PnL for each trade leg under this resolution
            total_pnl = 0.0
            for t in trades:
                # Determine settlement: 1.0 if this outcome wins, 0.0 otherwise
                if t.market == "A":
                    settlement = 1.0 if t.outcome == oa else 0.0
                else:
                    settlement = 1.0 if t.outcome == ob else 0.0

                # Per-share PnL
                if t.side == "BUY":
                    # Paid price, receive settlement
                    pnl = settlement - t.market_price
                else:
                    # Received price, pay settlement
                    pnl = t.market_price - settlement

                total_pnl += pnl

            if total_pnl < worst:
                worst = total_pnl

    return worst if worst != float("inf") else 0.0
