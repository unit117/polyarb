from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from shared.models import LiveFill, LiveOrder, PaperTrade
from services.simulator.live_reconciler import (
    ReconciledFill,
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


def test_normalize_submitted_to_rejected_does_not_write_fills():
    """submitted→rejected: status='rejected', no fills extracted from rejected order."""
    order = make_live_order()

    # Venue reports REJECTED with no matched trades
    status = normalize_live_order_status(
        {"status": "REJECTED", "size_matched": "0"},
        requested_size=5.0,
        confirmed_fills=[],
        current_status="submitted",
    )
    assert status == "rejected"

    # No confirmed trades on a rejected order → no fills extracted
    trades_with_no_confirm = [
        {
            "id": "trade-99",
            "status": "MATCHED",
            "taker_order_id": "ord-1",
            "price": "0.60",
            "size": "5.0",
            "timestamp": "2026-03-23T12:00:00Z",
        },
    ]
    fills = extract_reconciled_fills(order, trades_with_no_confirm)
    assert fills == []


def test_normalize_submitted_to_cancelled_does_not_write_fills():
    """submitted→cancelled: no confirmed fills for a cancelled order."""
    order = make_live_order()

    status = normalize_live_order_status(
        {"status": "CANCELED", "size_matched": "0"},
        requested_size=5.0,
        confirmed_fills=[],
        current_status="submitted",
    )
    assert status == "cancelled"

    # Empty trade list → no fills
    fills = extract_reconciled_fills(order, [])
    assert fills == []


def test_normalize_submitted_to_filled_full_transition():
    """submitted→filled full transition with confirmed fills."""
    order = make_live_order()

    trades = [
        {
            "id": "fill-1",
            "status": "CONFIRMED",
            "taker_order_id": "ord-1",
            "price": "0.60",
            "size": "5.0",
            "timestamp": "2026-03-23T12:00:00Z",
        },
    ]
    fills = extract_reconciled_fills(order, trades)
    assert len(fills) == 1

    status = normalize_live_order_status(
        {"status": "LIVE", "size_matched": "5"},
        requested_size=5.0,
        confirmed_fills=fills,
        current_status="submitted",
    )
    assert status == "filled"


def test_normalize_submitted_partially_filled_then_filled():
    """submitted→partially_filled→filled two-step transition."""
    # Step 1: partial fill
    partial_fills = [
        ReconciledFill(
            venue_fill_id="fill-1", fill_size=2.0, fill_price=0.60,
            fees=0.01, filled_at=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
        ),
    ]
    status1 = normalize_live_order_status(
        {"status": "LIVE", "size_matched": "2"},
        requested_size=5.0,
        confirmed_fills=partial_fills,
        current_status="submitted",
    )
    assert status1 == "partially_filled"

    # Step 2: remaining fill arrives
    all_fills = partial_fills + [
        ReconciledFill(
            venue_fill_id="fill-2", fill_size=3.0, fill_price=0.61,
            fees=0.01, filled_at=datetime(2026, 3, 23, 12, 1, tzinfo=timezone.utc),
        ),
    ]
    status2 = normalize_live_order_status(
        {"status": "LIVE", "size_matched": "5"},
        requested_size=5.0,
        confirmed_fills=all_fills,
        current_status="partially_filled",
    )
    assert status2 == "filled"


@pytest.mark.asyncio
async def test_duplicate_venue_fill_id_is_skipped(monkeypatch):
    """Duplicate venue_fill_id should be skipped by apply_reconciliation (idempotency).

    This tests the dedup logic in LiveTradingCoordinator.apply_reconciliation
    which checks existing venue_fill_ids before recording new fills.
    """
    import pytest
    from services.simulator.live_coordinator import LiveTradingCoordinator
    from services.simulator.portfolio import Portfolio

    async def fake_set_runtime_status(_redis, payload):
        return payload

    monkeypatch.setattr(
        "services.simulator.live_coordinator.set_live_runtime_status",
        fake_set_runtime_status,
    )

    class _FakeRedis:
        async def get(self, _key):
            return None
        async def publish(self, _c, _v):
            return None
        async def set(self, _k, _v):
            return None
        async def delete(self, _k):
            return None

    class _FakeVenueAdapter:
        ready = True

    class _ReconSession:
        def __init__(self, live_order, existing_fill_ids):
            self._live_order = live_order
            self._existing_fill_ids = existing_fill_ids
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, _cls, oid):
            return self._live_order if self._live_order.id == oid else None

        async def execute(self, _q):
            class R:
                def __init__(self, ids):
                    self._ids = ids
                def fetchall(self):
                    return [(i,) for i in self._ids]
            return R(self._existing_fill_ids)

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            pass

        async def commit(self):
            pass

    class _SessionFactory:
        def __init__(self, sessions):
            self._sessions = list(sessions)
        def __call__(self):
            return self._sessions.pop(0)

    live_order = LiveOrder(
        id=1, opportunity_id=100, market_id=1, outcome="Yes",
        token_id="tok_yes", side="BUY", requested_size=Decimal("10"),
        requested_price=Decimal("0.40"), status="submitted",
        dry_run=False, venue_order_id="ord-1",
    )

    # "trade-dup" already recorded
    session = _ReconSession(live_order, existing_fill_ids=["trade-dup"])

    coordinator = LiveTradingCoordinator(
        session_factory=_SessionFactory([session]),
        redis=_FakeRedis(),
        portfolio=Portfolio(1000.0),
        venue_adapter=_FakeVenueAdapter(),
        circuit_breaker=None,
        dry_run=False,
    )

    fills = [
        ReconciledFill(
            venue_fill_id="trade-dup",  # duplicate — should be skipped
            fill_size=5.0, fill_price=0.41, fees=0.01,
            filled_at=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
        ),
        ReconciledFill(
            venue_fill_id="trade-new",  # new — should be applied
            fill_size=5.0, fill_price=0.42, fees=0.01,
            filled_at=datetime(2026, 3, 23, 12, 1, tzinfo=timezone.utc),
        ),
    ]

    # Avoid needing extra sessions for snapshot
    async def _noop():
        pass

    coordinator._snapshot_portfolio_locked = _noop

    result = await coordinator.apply_reconciliation(1, status="filled", fills=fills)

    assert result["fills_applied"] == 1  # only trade-new applied
    live_fills = [o for o in session.added if isinstance(o, LiveFill)]
    assert len(live_fills) == 1
    assert live_fills[0].venue_fill_id == "trade-new"
