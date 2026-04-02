from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from shared.models import LiveFill, LiveOrder, Market, PaperTrade, PortfolioSnapshot
from services.simulator.live_coordinator import LiveTradingCoordinator, token_id_for_outcome
from services.simulator.live_reconciler import ReconciledFill
from services.simulator.pipeline import ValidatedExecutionBundle, ValidatedLeg
from services.simulator.portfolio import Portfolio


class FakeRedis:
    async def get(self, _key: str):
        return None

    async def publish(self, _channel: str, _value: str):
        return None

    async def set(self, _key: str, _value: str):
        return None

    async def delete(self, _key: str):
        return None


class FakeVenueAdapter:
    ready = True


class FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, markets=None):
        self.markets = markets or []
        self.added = []
        self._next_id = 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _query):
        return FakeExecuteResult(self.markets)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if isinstance(obj, LiveOrder) and getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    async def commit(self):
        return None


class FakeSessionFactory:
    def __init__(self, sessions):
        self.sessions = list(sessions)

    def __call__(self):
        return self.sessions.pop(0)


@pytest.mark.asyncio
async def test_live_settlement_writes_audit_rows_and_snapshot(monkeypatch):
    async def fake_set_runtime_status(_redis, payload):
        return payload

    monkeypatch.setattr("services.simulator.live_coordinator.set_live_runtime_status", fake_set_runtime_status)

    portfolio = Portfolio(1000.0)
    portfolio.execute_trade(1, "Yes", "BUY", 10, 0.40, 0.0)

    market = Market(
        id=1,
        polymarket_id="pm-1",
        venue="polymarket",
        question="Will X happen?",
        outcomes=["Yes", "No"],
        token_ids=["tok_yes", "tok_no"],
        active=True,
        resolved_outcome="Yes",
        resolved_at=datetime(2026, 3, 23, tzinfo=timezone.utc),
    )

    settle_session = FakeSession(markets=[market])
    snapshot_session = FakeSession()
    coordinator = LiveTradingCoordinator(
        session_factory=FakeSessionFactory([settle_session, snapshot_session]),
        redis=FakeRedis(),
        portfolio=portfolio,
        venue_adapter=FakeVenueAdapter(),
        circuit_breaker=None,
        dry_run=False,
    )

    stats = await coordinator.settle_resolved_markets()

    assert stats["settled"] == 1
    assert not portfolio.positions

    live_orders = [obj for obj in settle_session.added if isinstance(obj, LiveOrder)]
    live_fills = [obj for obj in settle_session.added if isinstance(obj, LiveFill)]
    paper_trades = [obj for obj in settle_session.added if isinstance(obj, PaperTrade)]
    snapshots = [obj for obj in snapshot_session.added if isinstance(obj, PortfolioSnapshot)]

    assert len(live_orders) == 1
    assert live_orders[0].status == "settled"
    assert len(live_fills) == 1
    assert live_fills[0].venue_fill_id.startswith("settlement:1:Yes:")
    assert len(paper_trades) == 1
    assert paper_trades[0].source == "live"
    assert len(snapshots) == 1
    assert snapshots[0].source == "live"


# ---------------------------------------------------------------------------
# Helpers for submission & reconciliation tests
# ---------------------------------------------------------------------------

def _make_market(market_id=1):
    return Market(
        id=market_id,
        polymarket_id=f"pm-{market_id}",
        venue="polymarket",
        question="Will X happen?",
        outcomes=["Yes", "No"],
        token_ids=["tok_yes", "tok_no"],
        active=True,
    )


def _make_bundle(market_id=1, opportunity_id=100):
    return ValidatedExecutionBundle(
        opportunity_id=opportunity_id,
        pair_id=1,
        estimated_profit=0.05,
        kelly_fraction=0.1,
        current_prices={f"{market_id}:Yes": 0.40},
        legs=[
            ValidatedLeg(
                market_id=market_id,
                outcome="Yes",
                side="BUY",
                size=10.0,
                entry_price=0.40,
                vwap_price=0.41,
                slippage=0.01,
                fees=0.02,
                fair_price=0.45,
                trade_venue="polymarket",
            ),
        ],
    )


class FakeRedisKillSwitchOn:
    """FakeRedis where the live kill switch is active."""

    async def get(self, key: str):
        if "kill_switch" in key:
            return "1"
        return None

    async def publish(self, _channel: str, _value: str):
        return None

    async def set(self, _key: str, _value: str):
        return None

    async def delete(self, _key: str):
        return None


class FakeVenueAdapterSubmit:
    """Venue adapter that records submit_order calls."""

    ready = True

    def __init__(self):
        self.calls = []

    async def submit_order(self, *, token_id, side, size, price):
        self.calls.append({"token_id": token_id, "side": side, "size": size, "price": price})
        return {"status": "submitted", "order": {"orderID": "venue-ord-123"}}


class FakeCircuitBreaker:
    """Circuit breaker that always blocks."""

    def __init__(self, allowed=True, reason=""):
        self._allowed = allowed
        self._reason = reason

    async def pre_trade_check(self, portfolio, market_id, trade_size, **kwargs):
        return (self._allowed, self._reason)

    def record_loss(self, amount):
        pass


class FakeReconSession:
    """Session that supports get() for apply_reconciliation tests."""

    def __init__(self, live_order=None, existing_fill_ids=None):
        self._live_order = live_order
        self._existing_fill_ids = existing_fill_ids or []
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, _model_class, obj_id):
        if self._live_order and self._live_order.id == obj_id:
            return self._live_order
        return None

    async def execute(self, _query):
        return _FetchAllResult(self._existing_fill_ids)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass


class _FetchAllResult:
    def __init__(self, fill_ids):
        self._fill_ids = fill_ids

    def fetchall(self):
        return [(fid,) for fid in self._fill_ids]


# ---------------------------------------------------------------------------
# token_id_for_outcome
# ---------------------------------------------------------------------------

def test_token_id_for_outcome_returns_correct_token():
    market = _make_market()
    assert token_id_for_outcome(market, "Yes") == "tok_yes"
    assert token_id_for_outcome(market, "No") == "tok_no"


def test_token_id_for_outcome_returns_none_on_missing():
    market = _make_market()
    assert token_id_for_outcome(market, "Maybe") is None

    empty = Market(
        id=2, polymarket_id="pm-2", venue="polymarket",
        question="Q?", outcomes=["Yes"], token_ids=[],
        active=True,
    )
    assert token_id_for_outcome(empty, "Yes") is None


# ---------------------------------------------------------------------------
# submit_validated_bundle — dry-run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_dry_run_writes_dry_run_status_no_venue_call(monkeypatch):
    async def fake_set_runtime_status(_redis, payload):
        return payload

    monkeypatch.setattr(
        "services.simulator.live_coordinator.set_live_runtime_status",
        fake_set_runtime_status,
    )

    market = _make_market()
    session = FakeSession(markets=[market])
    adapter = FakeVenueAdapterSubmit()

    coordinator = LiveTradingCoordinator(
        session_factory=FakeSessionFactory([session]),
        redis=FakeRedis(),
        portfolio=Portfolio(1000.0),
        venue_adapter=adapter,
        circuit_breaker=None,
        dry_run=True,
    )

    result = await coordinator.submit_validated_bundle(_make_bundle())

    assert result["status"] == "ok"
    assert result["orders_created"] == 1

    live_orders = [o for o in session.added if isinstance(o, LiveOrder)]
    assert len(live_orders) == 1
    assert live_orders[0].status == "dry_run"
    assert live_orders[0].dry_run is True
    assert live_orders[0].venue_order_id is None
    assert adapter.calls == []  # venue never called


# ---------------------------------------------------------------------------
# submit_validated_bundle — real submission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_real_calls_executor_writes_submitted(monkeypatch):
    async def fake_set_runtime_status(_redis, payload):
        return payload

    monkeypatch.setattr(
        "services.simulator.live_coordinator.set_live_runtime_status",
        fake_set_runtime_status,
    )

    market = _make_market()
    session = FakeSession(markets=[market])
    adapter = FakeVenueAdapterSubmit()

    coordinator = LiveTradingCoordinator(
        session_factory=FakeSessionFactory([session]),
        redis=FakeRedis(),
        portfolio=Portfolio(1000.0),
        venue_adapter=adapter,
        circuit_breaker=None,
        dry_run=False,
    )

    result = await coordinator.submit_validated_bundle(_make_bundle())

    assert result["status"] == "ok"
    assert result["orders_created"] == 1

    live_orders = [o for o in session.added if isinstance(o, LiveOrder)]
    assert len(live_orders) == 1
    assert live_orders[0].status == "submitted"
    assert live_orders[0].dry_run is False
    assert live_orders[0].venue_order_id == "venue-ord-123"
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["token_id"] == "tok_yes"


# ---------------------------------------------------------------------------
# submit_validated_bundle — kill switch blocks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kill_switch_blocks_submission(monkeypatch):
    async def fake_set_runtime_status(_redis, payload):
        return payload

    monkeypatch.setattr(
        "services.simulator.live_coordinator.set_live_runtime_status",
        fake_set_runtime_status,
    )

    coordinator = LiveTradingCoordinator(
        session_factory=FakeSessionFactory([]),
        redis=FakeRedisKillSwitchOn(),
        portfolio=Portfolio(1000.0),
        venue_adapter=FakeVenueAdapter(),
        circuit_breaker=None,
        dry_run=False,
    )

    result = await coordinator.submit_validated_bundle(_make_bundle())

    assert result["status"] == "blocked"
    assert result["reason"] == "live_kill_switch"


# ---------------------------------------------------------------------------
# submit_validated_bundle — circuit breaker blocks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_breaker_blocks_submission(monkeypatch):
    async def fake_set_runtime_status(_redis, payload):
        return payload

    monkeypatch.setattr(
        "services.simulator.live_coordinator.set_live_runtime_status",
        fake_set_runtime_status,
    )

    market = _make_market()
    session = FakeSession(markets=[market])
    breaker = FakeCircuitBreaker(allowed=False, reason="max_daily_loss")

    coordinator = LiveTradingCoordinator(
        session_factory=FakeSessionFactory([session]),
        redis=FakeRedis(),
        portfolio=Portfolio(1000.0),
        venue_adapter=FakeVenueAdapter(),
        circuit_breaker=breaker,
        dry_run=True,
    )

    result = await coordinator.submit_validated_bundle(_make_bundle())

    # Order is still created but with error logged; leg is skipped
    assert result["orders_created"] == 0
    assert "max_daily_loss" in result["errors"]


# ---------------------------------------------------------------------------
# apply_reconciliation — writes LiveFill + PaperTrade, updates portfolio
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_reconciliation_writes_fill_and_updates_portfolio(monkeypatch):
    async def fake_set_runtime_status(_redis, payload):
        return payload

    monkeypatch.setattr(
        "services.simulator.live_coordinator.set_live_runtime_status",
        fake_set_runtime_status,
    )

    live_order = LiveOrder(
        id=1,
        opportunity_id=100,
        market_id=1,
        outcome="Yes",
        token_id="tok_yes",
        side="BUY",
        requested_size=Decimal("10"),
        requested_price=Decimal("0.40"),
        status="submitted",
        dry_run=False,
        venue_order_id="ord-1",
    )

    class _PriceSession(FakeSession):
        async def scalar(self, _query):
            return None

    recon_session = FakeReconSession(live_order=live_order, existing_fill_ids=[])
    snapshot_prices_session = _PriceSession()  # _get_current_prices
    snapshot_write_session = FakeSession()     # _snapshot_portfolio_locked write

    portfolio = Portfolio(1000.0)

    coordinator = LiveTradingCoordinator(
        session_factory=FakeSessionFactory([recon_session, snapshot_prices_session, snapshot_write_session]),
        redis=FakeRedis(),
        portfolio=portfolio,
        venue_adapter=FakeVenueAdapter(),
        circuit_breaker=None,
        dry_run=False,
    )

    fills = [
        ReconciledFill(
            venue_fill_id="trade-1",
            fill_size=10.0,
            fill_price=0.41,
            fees=0.02,
            filled_at=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    result = await coordinator.apply_reconciliation(
        live_order.id,
        status="filled",
        fills=fills,
    )

    assert result["status"] == "ok"
    assert result["fills_applied"] == 1
    assert result["order_status"] == "filled"

    # LiveFill and PaperTrade written
    live_fills = [o for o in recon_session.added if isinstance(o, LiveFill)]
    paper_trades = [o for o in recon_session.added if isinstance(o, PaperTrade)]
    assert len(live_fills) == 1
    assert live_fills[0].venue_fill_id == "trade-1"
    assert len(paper_trades) == 1
    assert paper_trades[0].source == "live"

    # Portfolio was mutated (BUY 10 shares)
    assert "1:Yes" in portfolio.positions
    assert live_order.status == "filled"


@pytest.mark.asyncio
async def test_apply_reconciliation_persists_actual_clipped_fill(monkeypatch):
    async def fake_set_runtime_status(_redis, payload):
        return payload

    monkeypatch.setattr(
        "services.simulator.live_coordinator.set_live_runtime_status",
        fake_set_runtime_status,
    )

    live_order = LiveOrder(
        id=1,
        opportunity_id=100,
        market_id=1,
        outcome="Yes",
        token_id="tok_yes",
        side="BUY",
        requested_size=Decimal("10"),
        requested_price=Decimal("0.40"),
        status="submitted",
        dry_run=False,
        venue_order_id="ord-1",
    )

    class _PriceSession(FakeSession):
        async def scalar(self, _query):
            return None

    recon_session = FakeReconSession(live_order=live_order, existing_fill_ids=[])
    snapshot_prices_session = _PriceSession()
    snapshot_write_session = FakeSession()

    coordinator = LiveTradingCoordinator(
        session_factory=FakeSessionFactory(
            [recon_session, snapshot_prices_session, snapshot_write_session]
        ),
        redis=FakeRedis(),
        portfolio=Portfolio(1.0),
        venue_adapter=FakeVenueAdapter(),
        circuit_breaker=None,
        dry_run=False,
    )

    fills = [
        ReconciledFill(
            venue_fill_id="trade-1",
            fill_size=10.0,
            fill_price=0.41,
            fees=0.02,
            filled_at=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    result = await coordinator.apply_reconciliation(
        live_order.id,
        status="filled",
        fills=fills,
    )

    assert result["status"] == "ok"

    live_fills = [o for o in recon_session.added if isinstance(o, LiveFill)]
    paper_trades = [o for o in recon_session.added if isinstance(o, PaperTrade)]
    assert len(live_fills) == 1
    assert len(paper_trades) == 1
    assert live_fills[0].fill_size == paper_trades[0].size
    assert live_fills[0].fill_size < Decimal("10")
