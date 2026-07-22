"""Tests for WS trade capture and the midpoint-fold gate (Phase 4)."""

from datetime import timezone
from unittest.mock import MagicMock

import pytest

from services.ingestor.ws_client import ClobWebSocket
from shared.config import settings


def _ws() -> ClobWebSocket:
    ws = ClobWebSocket(
        redis=MagicMock(),
        session_factory=MagicMock(),
        ws_url="wss://test",
    )
    ws._token_map = {"tok1": (7, "Yes")}
    return ws


def _trade_msg(**overrides):
    msg = {
        "asset_id": "tok1",
        "price": "0.42",
        "size": "12.5",
        "side": "buy",
        "fee_rate_bps": "0",
        "timestamp": "1784700000000",  # epoch millis
    }
    msg.update(overrides)
    return msg


class TestTradeCapture:
    def test_full_record_buffered(self):
        ws = _ws()
        ws._handle_last_trade(_trade_msg())
        assert len(ws._pending_trades) == 1
        row = ws._pending_trades[0]
        assert row["market_id"] == 7
        assert row["token_id"] == "tok1"
        assert row["outcome"] == "Yes"
        assert row["price"] == "0.42"
        assert row["size"] == "12.5"
        assert row["side"] == "BUY"
        assert row["fee_rate_bps"] == 0
        assert row["event_ts"].tzinfo == timezone.utc
        assert row["event_ts"].year == 2026

    def test_missing_optional_fields_tolerated(self):
        ws = _ws()
        ws._handle_last_trade(
            _trade_msg(size=None, side=None, fee_rate_bps=None, timestamp="garbage")
        )
        row = ws._pending_trades[0]
        assert row["size"] is None
        assert row["side"] is None
        assert row["fee_rate_bps"] is None
        assert row["event_ts"] is None

    def test_unknown_token_ignored(self):
        ws = _ws()
        ws._handle_last_trade(_trade_msg(asset_id="unknown"))
        assert ws._pending_trades == []

    def test_capture_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "capture_ws_trades", False)
        ws = _ws()
        ws._handle_last_trade(_trade_msg())
        assert ws._pending_trades == []
        # fold still happens (default true)
        assert 7 in ws._pending_snapshots


class TestFoldGate:
    def test_fold_enabled_updates_price_buffer(self):
        ws = _ws()
        ws._handle_last_trade(_trade_msg())
        assert ws._pending_snapshots[7]["prices"]["Yes"] == "0.42"

    def test_fold_disabled_captures_trade_only(self, monkeypatch):
        monkeypatch.setattr(settings, "fold_trade_prices_into_midpoints", False)
        ws = _ws()
        ws._handle_last_trade(_trade_msg())
        assert len(ws._pending_trades) == 1
        assert 7 not in ws._pending_snapshots
