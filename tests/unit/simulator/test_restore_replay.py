"""Regression tests for _restore_portfolio cost-basis replay.

Verifies that the replay logic in main.py produces the same cost_basis
as Portfolio.execute_trade for short covers, long-to-short flips, and
mixed sequences.
"""
from decimal import Decimal

import pytest

from services.simulator.portfolio import Portfolio


def replay_cost_basis(trades: list[dict]) -> dict[str, Decimal]:
    """Pure-function equivalent of the _restore_portfolio replay loop.

    Each trade dict has keys: market_id, outcome, side, size, vwap_price.
    Returns the reconstructed cost_basis dict.
    """
    cost_basis: dict[str, Decimal] = {}
    replay_positions: dict[str, Decimal] = {}

    for t in trades:
        key = f"{t['market_id']}:{t['outcome']}"
        size_d = Decimal(str(t["size"]))
        price_d = Decimal(str(t["vwap_price"]))

        if t["side"] in ("SETTLE", "PURGE"):
            cost_basis.pop(key, None)
            replay_positions.pop(key, None)
        elif t["side"] == "BUY":
            current = replay_positions.get(key, Decimal("0"))
            if current < 0:
                cover_size = min(size_d, abs(current))
                remainder = size_d - cover_size
                if key in cost_basis and current != 0:
                    avg_credit = cost_basis[key] / abs(current)
                    cost_basis[key] -= cover_size * avg_credit
                new_pos = current + size_d
                if new_pos == 0:
                    cost_basis.pop(key, None)
                elif new_pos > 0:
                    cost_basis[key] = remainder * price_d
            else:
                cost_basis[key] = cost_basis.get(key, Decimal("0")) + size_d * price_d
            replay_positions[key] = replay_positions.get(key, Decimal("0")) + size_d
        elif t["side"] == "SELL":
            current = replay_positions.get(key, Decimal("0"))
            if current > 0:
                close_size = min(size_d, current)
                remainder = size_d - close_size
                if key in cost_basis and current > 0:
                    avg_entry = cost_basis[key] / current
                    cost_basis[key] -= close_size * avg_entry
                new_pos = current - size_d
                if new_pos == 0:
                    cost_basis.pop(key, None)
                elif new_pos < 0:
                    cost_basis[key] = remainder * price_d
            elif current <= 0:
                cost_basis[key] = cost_basis.get(key, Decimal("0")) + size_d * price_d
            replay_positions[key] = current - size_d

    return cost_basis


def execute_trades(trades: list[dict]) -> dict[str, Decimal]:
    """Run trades through Portfolio.execute_trade and return cost_basis."""
    p = Portfolio(1_000_000)  # large capital to avoid margin limits
    for t in trades:
        p.execute_trade(
            t["market_id"], t["outcome"], t["side"],
            t["size"], t["vwap_price"], 0.0,
        )
    return dict(p.cost_basis)


class TestReplayMatchesExecute:
    """Replay must produce the same cost_basis as execute_trade."""

    def test_short_then_partial_cover(self):
        """P1 repro: SELL 10@0.60 then BUY 4@0.40 — cover reduces short basis."""
        trades = [
            {"market_id": 1, "outcome": "Yes", "side": "SELL", "size": 10, "vwap_price": 0.60},
            {"market_id": 1, "outcome": "Yes", "side": "BUY", "size": 4, "vwap_price": 0.40},
        ]
        replay = replay_cost_basis(trades)
        live = execute_trades(trades)
        for key in set(list(replay.keys()) + list(live.keys())):
            assert float(replay.get(key, 0)) == pytest.approx(
                float(live.get(key, 0)), abs=0.01
            ), f"Mismatch on {key}: replay={replay.get(key)} live={live.get(key)}"

    def test_long_then_flip_to_short(self):
        """P1 repro: BUY 10@0.50 then SELL 15@0.60 — flips to short."""
        trades = [
            {"market_id": 1, "outcome": "Yes", "side": "BUY", "size": 10, "vwap_price": 0.50},
            {"market_id": 1, "outcome": "Yes", "side": "SELL", "size": 15, "vwap_price": 0.60},
        ]
        replay = replay_cost_basis(trades)
        live = execute_trades(trades)
        for key in set(list(replay.keys()) + list(live.keys())):
            assert float(replay.get(key, 0)) == pytest.approx(
                float(live.get(key, 0)), abs=0.01
            ), f"Mismatch on {key}: replay={replay.get(key)} live={live.get(key)}"

    def test_short_then_full_cover(self):
        """SELL 10@0.60 then BUY 10@0.40 — fully covers, basis cleared."""
        trades = [
            {"market_id": 1, "outcome": "Yes", "side": "SELL", "size": 10, "vwap_price": 0.60},
            {"market_id": 1, "outcome": "Yes", "side": "BUY", "size": 10, "vwap_price": 0.40},
        ]
        replay = replay_cost_basis(trades)
        live = execute_trades(trades)
        assert "1:Yes" not in replay
        assert "1:Yes" not in live

    def test_short_then_flip_to_long(self):
        """SELL 5@0.70 then BUY 12@0.50 — flips to long, basis = remainder * price."""
        trades = [
            {"market_id": 1, "outcome": "Yes", "side": "SELL", "size": 5, "vwap_price": 0.70},
            {"market_id": 1, "outcome": "Yes", "side": "BUY", "size": 12, "vwap_price": 0.50},
        ]
        replay = replay_cost_basis(trades)
        live = execute_trades(trades)
        for key in set(list(replay.keys()) + list(live.keys())):
            assert float(replay.get(key, 0)) == pytest.approx(
                float(live.get(key, 0)), abs=0.01
            ), f"Mismatch on {key}: replay={replay.get(key)} live={live.get(key)}"

    def test_mixed_multi_position_sequence(self):
        """Complex sequence across two positions."""
        trades = [
            {"market_id": 1, "outcome": "Yes", "side": "BUY", "size": 20, "vwap_price": 0.45},
            {"market_id": 2, "outcome": "No", "side": "SELL", "size": 15, "vwap_price": 0.55},
            {"market_id": 1, "outcome": "Yes", "side": "SELL", "size": 25, "vwap_price": 0.50},  # flip
            {"market_id": 2, "outcome": "No", "side": "BUY", "size": 20, "vwap_price": 0.48},  # flip
            {"market_id": 1, "outcome": "Yes", "side": "BUY", "size": 10, "vwap_price": 0.42},  # partial cover
        ]
        replay = replay_cost_basis(trades)
        live = execute_trades(trades)
        for key in set(list(replay.keys()) + list(live.keys())):
            assert float(replay.get(key, 0)) == pytest.approx(
                float(live.get(key, 0)), abs=0.01
            ), f"Mismatch on {key}: replay={replay.get(key)} live={live.get(key)}"

    def test_settle_clears_basis(self):
        """SETTLE clears both cost_basis and replay position."""
        trades = [
            {"market_id": 1, "outcome": "Yes", "side": "BUY", "size": 10, "vwap_price": 0.50},
            {"market_id": 1, "outcome": "Yes", "side": "SETTLE", "size": 10, "vwap_price": 1.0},
        ]
        replay = replay_cost_basis(trades)
        assert "1:Yes" not in replay
