"""Tests for trade computation from optimization results."""

import numpy as np
import pytest

from services.optimizer.frank_wolfe import FWResult
from shared.config import settings
from services.optimizer.trades import compute_trades


def _make_fw_result(q, p, n_a=2, n_b=2):
    return FWResult(
        optimal_q=np.array(q),
        market_prices=np.array(p),
        iterations=10,
        final_gap=0.0001,
        converged=True,
        kl_div=0.01,
        n_outcomes_a=n_a,
        n_outcomes_b=n_b,
    )


class TestComputeTrades:
    def test_simple_arb_generates_trades(self):
        # q differs from p enough to generate trades
        result = compute_trades(
            _make_fw_result(
                q=[0.55, 0.45, 0.60, 0.40],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
            min_edge=0.03,
        )
        assert len(result["trades"]) >= 1

    def test_no_trades_below_min_edge(self):
        result = compute_trades(
            _make_fw_result(
                q=[0.51, 0.49, 0.51, 0.49],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
            min_edge=0.03,
        )
        assert len(result["trades"]) == 0

    def test_buy_when_underpriced(self):
        result = compute_trades(
            _make_fw_result(
                q=[0.65, 0.35, 0.50, 0.50],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
            min_edge=0.03,
        )
        trades = result["trades"]
        a_trades = [t for t in trades if t["market"] == "A"]
        assert len(a_trades) == 1
        assert a_trades[0]["side"] == "BUY"
        assert a_trades[0]["outcome"] == "Yes"

    def test_sell_when_overpriced(self):
        result = compute_trades(
            _make_fw_result(
                q=[0.35, 0.65, 0.50, 0.50],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
            min_edge=0.03,
        )
        trades = result["trades"]
        a_trades = [t for t in trades if t["market"] == "A"]
        assert len(a_trades) == 1
        assert a_trades[0]["side"] == "SELL"

    def test_one_leg_per_market(self):
        # Both outcomes have large edges, but only best is kept
        result = compute_trades(
            _make_fw_result(
                q=[0.70, 0.30, 0.70, 0.30],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
            min_edge=0.03,
        )
        a_count = sum(1 for t in result["trades"] if t["market"] == "A")
        b_count = sum(1 for t in result["trades"] if t["market"] == "B")
        assert a_count <= 1
        assert b_count <= 1

    def test_sanity_cap_drops_all_trades(self):
        # Edge > settings.max_edge_sanity should return empty trades
        result = compute_trades(
            _make_fw_result(
                q=[0.80, 0.20, 0.50, 0.50],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
            min_edge=0.03,
        )
        # Edge = 0.30 > max_edge_sanity (0.20)
        assert result["trades"] == []
        assert result["estimated_profit"] == 0.0

    def test_estimated_profit_accounts_for_fees(self):
        result = compute_trades(
            _make_fw_result(
                q=[0.55, 0.45, 0.55, 0.45],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
            min_edge=0.03,
        )
        # Profit should be less than raw edge due to fees
        if result["trades"]:
            raw_edge = sum(t["edge"] for t in result["trades"])
            assert result["estimated_profit"] <= raw_edge

    def test_price_output_structure(self):
        result = compute_trades(
            _make_fw_result(
                q=[0.55, 0.45, 0.55, 0.45],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
        )
        assert "market_a_prices" in result
        assert "current" in result["market_a_prices"]
        assert "optimal" in result["market_a_prices"]
        assert len(result["market_a_prices"]["current"]) == 2

    def test_cross_venue_fees(self):
        result = compute_trades(
            _make_fw_result(
                q=[0.55, 0.45, 0.55, 0.45],
                p=[0.50, 0.50, 0.50, 0.50],
            ),
            outcomes_a=["Yes", "No"],
            outcomes_b=["Yes", "No"],
            venue_a="polymarket",
            venue_b="kalshi",
            min_edge=0.03,
        )
        # Should not error with different venues
        assert "estimated_profit" in result
