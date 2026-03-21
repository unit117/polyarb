"""Convert optimization results to trade recommendations.

Compares the optimal distribution q* (from Frank-Wolfe) with current market
prices p to determine which outcomes are mispriced and what trades would
capture the arbitrage.
"""

import structlog
import numpy as np

from shared.config import venue_fee
from services.optimizer.frank_wolfe import FWResult

logger = structlog.get_logger()

# Edges above this are almost certainly misclassified pairs, not real arb.
# A 20¢ edge on a liquid Polymarket binary is implausible.
MAX_EDGE = 0.20


def compute_trades(
    result: FWResult,
    outcomes_a: list[str],
    outcomes_b: list[str],
    theoretical_profit: float = 0.0,
    min_edge: float = 0.03,
    venue_a: str = "polymarket",
    venue_b: str = "polymarket",
) -> dict:
    """Compute optimal trades from the FW result.

    Returns a dict with:
    - trades: list of {market, outcome, side, size, edge}
    - estimated_profit: estimated profit from the rebalancing
    - market_a_prices: current vs optimal for market A
    - market_b_prices: current vs optimal for market B
    """
    n_a = result.n_outcomes_a
    q = result.optimal_q
    p = result.market_prices

    q_a = q[:n_a]
    q_b = q[n_a:]
    p_a = p[:n_a]
    p_b = p[n_a:]

    trades = []

    # For each market, collect all candidate legs then keep only the
    # best-edge leg.  In binary markets BUY Yes and SELL No are mirrors
    # of the same mispricing — executing both pays double fees for the
    # same edge.
    for market_label, outcomes, q_vec, p_vec, venue in [
        ("A", outcomes_a, q_a, p_a, venue_a),
        ("B", outcomes_b, q_b, p_b, venue_b),
    ]:
        candidates = []
        for i, outcome in enumerate(outcomes):
            edge = float(q_vec[i] - p_vec[i])
            if abs(edge) > min_edge:
                candidates.append({
                    "market": market_label,
                    "outcome": outcome,
                    "outcome_index": i,
                    "side": "BUY" if edge > 0 else "SELL",
                    "edge": round(abs(edge), 6),
                    "market_price": round(float(p_vec[i]), 6),
                    "fair_price": round(float(q_vec[i]), 6),
                    "venue": venue,
                })
        if candidates:
            # Keep only the single best leg per market
            trades.append(max(candidates, key=lambda t: t["edge"]))

    # Sanity cap: edges above MAX_EDGE are almost certainly misclassified
    # pairs, not real arbitrage.  Drop the entire opportunity.
    for t in trades:
        if t["edge"] > MAX_EDGE:
            logger.warning(
                "edge_sanity_cap_triggered",
                market=t["market"],
                outcome=t["outcome"],
                edge=t["edge"],
            )
            return {
                "trades": [],
                "estimated_profit": 0.0,
                "theoretical_profit": round(theoretical_profit, 6),
                "market_a_prices": {
                    "current": [round(float(x), 6) for x in p_a],
                    "optimal": [round(float(x), 6) for x in q_a],
                },
                "market_b_prices": {
                    "current": [round(float(x), 6) for x in p_b],
                    "optimal": [round(float(x), 6) for x in q_b],
                },
            }

    edge_a = max((t["edge"] for t in trades if t["market"] == "A"), default=0.0)
    edge_b = max((t["edge"] for t in trades if t["market"] == "B"), default=0.0)
    raw_edge = edge_a + edge_b

    # Estimated fees: per-leg using venue fee schedule at trade price
    est_fees = sum(
        venue_fee(t.get("venue", "polymarket"), t["market_price"], t["side"])
        for t in trades
    )

    estimated_profit = max(raw_edge - est_fees, 0.0)

    return {
        "trades": trades,
        "estimated_profit": round(estimated_profit, 6),
        "theoretical_profit": round(theoretical_profit, 6),
        "market_a_prices": {
            "current": [round(float(x), 6) for x in p_a],
            "optimal": [round(float(x), 6) for x in q_a],
        },
        "market_b_prices": {
            "current": [round(float(x), 6) for x in p_b],
            "optimal": [round(float(x), 6) for x in q_b],
        },
    }
