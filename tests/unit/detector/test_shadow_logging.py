from types import SimpleNamespace
from unittest.mock import patch

from services.detector.shadow_logging import (
    derive_silver_failure_signature,
    extract_order_book_summary,
    preview_trade_gates,
)


class TestExtractOrderBookSummary:
    def test_extracts_spread_and_visible_depth(self):
        summary = extract_order_book_summary(
            {
                "bids": [[0.44, 120], [0.43, 80]],
                "asks": [[0.46, 100], [0.47, 50]],
            }
        )

        assert summary["best_bid"] == 0.44
        assert summary["best_ask"] == 0.46
        assert summary["spread"] == 0.02
        assert summary["visible_depth"] == 350.0

    def test_handles_missing_order_book(self):
        summary = extract_order_book_summary(None)

        assert summary == {
            "best_bid": None,
            "best_ask": None,
            "spread": None,
            "visible_depth": None,
        }


class TestSilverFailureSignature:
    def test_matches_missing_event_id_failure(self):
        signature = derive_silver_failure_signature(
            ["mutual_exclusion: neither market has event_id — non-verifiable"]
        )

        assert signature == "mutual_exclusion_missing_event_id"

    def test_returns_none_for_other_failures(self):
        assert derive_silver_failure_signature(["low_confidence: 0.62 < 0.70"]) is None


class TestPreviewTradeGates:
    def test_short_circuits_unconstrained_conditional(self):
        preview = preview_trade_gates(
            {
                "type": "conditional",
                "outcomes_a": ["Yes", "No"],
                "outcomes_b": ["Yes", "No"],
                "matrix": [[1, 1], [1, 1]],
            },
            {"Yes": 0.55, "No": 0.45},
            {"Yes": 0.54, "No": 0.46},
            skip_conditional=True,
        )

        assert preview["status"] == "optimizer_rejected"
        assert preview["rejection_reason"] == "conditional_unconstrained"
        assert preview["would_trade"] is False

    def test_maps_optimizer_and_trade_preview(self):
        fw_result = SimpleNamespace(iterations=17, final_gap=0.0004)

        with patch(
            "services.detector.shadow_logging.optimize",
            return_value=fw_result,
        ) as mock_optimize, patch(
            "services.detector.shadow_logging.compute_trades",
            return_value={
                "trades": [{"market": "A"}],
                "estimated_profit": 0.018,
                "max_edge": 0.051,
            },
        ) as mock_compute_trades:
            preview = preview_trade_gates(
                {
                    "type": "partition",
                    "outcomes_a": ["Yes", "No"],
                    "outcomes_b": ["Yes", "No"],
                    "matrix": [[1, 0], [0, 1]],
                    "profit_bound": 0.04,
                },
                {"Yes": 0.60, "No": 0.40},
                {"Yes": 0.45, "No": 0.55},
                min_edge=0.03,
            )

        assert mock_optimize.called
        assert mock_compute_trades.called
        assert preview["status"] == "would_trade"
        assert preview["would_trade"] is True
        assert preview["trade_count"] == 1
        assert preview["estimated_profit"] == 0.018
        assert preview["max_edge"] == 0.051
