from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from shared.models import LiveOrder
from services.simulator.live_reconciler import (
    extract_reconciled_fills,
    normalize_live_order_status,
)


def make_live_order() -> LiveOrder:
    return LiveOrder(
        id=1,
        opportunity_id=123,
        market_id=10,
        outcome="Yes",
        token_id="tok_yes",
        side="BUY",
        requested_size=Decimal("5"),
        requested_price=Decimal("0.60"),
        status="submitted",
        dry_run=False,
        venue_order_id="ord-1",
    )


def test_extract_reconciled_fills_uses_confirmed_matching_trades_only():
    order = make_live_order()
    trades = [
        {
            "id": "trade-1",
            "status": "CONFIRMED",
            "taker_order_id": "ord-1",
            "price": "0.61",
            "size": "2.5",
            "timestamp": "2026-03-23T12:00:00Z",
        },
        {
            "id": "trade-2",
            "status": "MATCHED",
            "taker_order_id": "ord-1",
            "price": "0.60",
            "size": "1.0",
            "timestamp": "2026-03-23T12:01:00Z",
        },
        {
            "id": "trade-3",
            "status": "CONFIRMED",
            "taker_order_id": "other-order",
            "price": "0.62",
            "size": "1.0",
            "timestamp": "2026-03-23T12:02:00Z",
        },
    ]

    fills = extract_reconciled_fills(order, trades)

    assert len(fills) == 1
    assert fills[0].venue_fill_id == "trade-1"
    assert fills[0].fill_size == 2.5
    assert fills[0].fill_price == 0.61


def test_normalize_live_order_status_handles_partial_and_terminal_states():
    partial = normalize_live_order_status(
        {"status": "LIVE", "size_matched": "2"},
        requested_size=5.0,
        confirmed_fills=[],
        current_status="submitted",
    )
    assert partial == "partially_filled"

    filled = normalize_live_order_status(
        {"status": "LIVE", "size_matched": "5"},
        requested_size=5.0,
        confirmed_fills=[],
        current_status="submitted",
    )
    assert filled == "filled"

    cancelled = normalize_live_order_status(
        {"status": "CANCELED", "size_matched": "0"},
        requested_size=5.0,
        confirmed_fills=[],
        current_status="submitted",
    )
    assert cancelled == "cancelled"
