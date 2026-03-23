from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.models import LiveFill, LiveOrder, Market, PaperTrade, PortfolioSnapshot
from services.simulator.live_coordinator import LiveTradingCoordinator
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
