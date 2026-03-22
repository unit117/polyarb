"""Tests for VWAP execution simulation."""

import pytest

from services.simulator.vwap import compute_vwap


class TestComputeVWAP:
    def test_single_level_full_fill(self):
        book = {"asks": [[0.60, 200]], "bids": [[0.58, 200]]}
        result = compute_vwap(book, "BUY", 100, midpoint=0.59)
        assert result["vwap_price"] == pytest.approx(0.60)
        assert result["filled_size"] == pytest.approx(100.0)
        assert result["levels_consumed"] == 1
        assert result["partial_fill"] is False

    def test_multi_level_fill(self):
        book = {
            "asks": [[0.60, 50], [0.62, 100], [0.65, 100]],
            "bids": [],
        }
        result = compute_vwap(book, "BUY", 100, midpoint=0.59)
        # 50 @ 0.60 + 50 @ 0.62 = 30 + 31 = 61 / 100 = 0.61
        assert result["vwap_price"] == pytest.approx(0.61)
        assert result["levels_consumed"] == 2

    def test_partial_fill(self):
        book = {"asks": [[0.60, 30]], "bids": []}
        result = compute_vwap(book, "BUY", 100, midpoint=0.59)
        assert result["filled_size"] == pytest.approx(30.0)
        assert result["partial_fill"] is True

    def test_sell_uses_bids(self):
        book = {"asks": [], "bids": [[0.58, 200]]}
        result = compute_vwap(book, "SELL", 50, midpoint=0.59)
        assert result["vwap_price"] == pytest.approx(0.58)
        assert result["filled_size"] == pytest.approx(50.0)

    def test_no_order_book_falls_back_to_midpoint(self):
        result = compute_vwap(None, "BUY", 100, midpoint=0.50)
        assert result["vwap_price"] == pytest.approx(0.50 * 1.005, abs=0.001)
        assert result["slippage"] == 0.005
        assert result["levels_consumed"] == 0

    def test_empty_levels_falls_back(self):
        book = {"asks": [], "bids": []}
        result = compute_vwap(book, "BUY", 100, midpoint=0.50)
        assert result["levels_consumed"] == 0

    def test_slippage_calculation(self):
        book = {"asks": [[0.62, 200]], "bids": []}
        result = compute_vwap(book, "BUY", 50, midpoint=0.60)
        expected_slippage = abs(0.62 - 0.60) / 0.60
        assert result["slippage"] == pytest.approx(expected_slippage, abs=0.0001)

    def test_sell_midpoint_fallback(self):
        result = compute_vwap(None, "SELL", 100, midpoint=0.50)
        assert result["vwap_price"] == pytest.approx(0.50 * 0.995, abs=0.001)

    def test_dict_format_levels(self):
        """Test with dict-formatted order book levels."""
        book = {"asks": [{"price": 0.60, "size": 200}], "bids": []}
        result = compute_vwap(book, "BUY", 50, midpoint=0.59)
        assert result["vwap_price"] == pytest.approx(0.60)
