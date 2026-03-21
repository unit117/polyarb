"""Convert optimization results to trade recommendations.

Compares the optimal distribution q* (from Frank-Wolfe) with current market
prices p to determine which outcomes are mispriced and what trades would
capture the arbitrage.
"""

import numpy as np

from services.optimizer.frank_wolfe import FWResult


def compute_trades(
    result: FWResult,
    outcomes_a: list[str],
    outcomes_b: list[str],
    theoretical_profit: float = 0.0,
    fee_rate: float = 0.02,
    min_edge: float = 0.03,
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

    # Market A trades — only include the best edge per market (BUY the
    # underpriced outcome), not both sides of a binary complement.
    for i, outcome in enumerate(outcomes_a):
        edge = float(q_a[i] - p_a[i])
        if abs(edge) > min_edge:
            trades.append({
                "market": "A",
                "outcome": outcome,
                "outcome_index": i,
                "side": "BUY" if edge > 0 else "SELL",
                "edge": round(abs(edge), 6),
                "market_price": round(float(p_a[i]), 6),
                "fair_price": round(float(q_a[i]), 6),
            })

    # Market B trades
    for j, outcome in enumerate(outcomes_b):
        edge = float(q_b[j] - p_b[j])
        if abs(edge) > min_edge:
            trades.append({
                "market": "B",
                "outcome": outcome,
                "outcome_index": j,
                "side": "BUY" if edge > 0 else "SELL",
                "edge": round(abs(edge), 6),
                "market_price": round(float(p_b[j]), 6),
                "fair_price": round(float(q_b[j]), 6),
            })

    # For binary markets, each market contributes two edges that are
    # mirror images (BUY Yes = SELL No). Only count the max edge per
    # market to avoid double-counting the same mispricing.
    edge_a = max((t["edge"] for t in trades if t["market"] == "A"), default=0.0)
    edge_b = max((t["edge"] for t in trades if t["market"] == "B"), default=0.0)
    raw_edge = edge_a + edge_b

    # Estimated fees: two legs (buy + sell), each at ~midpoint price
    avg_price_a = float(np.mean(p_a)) if len(p_a) > 0 else 0.5
    avg_price_b = float(np.mean(p_b)) if len(p_b) > 0 else 0.5
    est_fees = (avg_price_a + avg_price_b) * fee_rate

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
