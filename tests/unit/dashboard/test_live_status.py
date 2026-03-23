from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from services.dashboard.api.live_status import build_live_status


class FakeRedis:
    def __init__(self, store: dict[str, str]):
        self.store = store

    async def get(self, key: str):
        return self.store.get(key)


class FakeSession:
    def __init__(self, order_count, fill_count, portfolio):
        self._responses = [order_count, fill_count, portfolio]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def scalar(self, _query):
        return self._responses.pop(0)


class FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


@pytest.mark.asyncio
async def test_build_live_status_combines_runtime_and_db(monkeypatch):
    heartbeat = datetime.now(timezone.utc).isoformat()
    redis = FakeRedis(
        {
            "polyarb:live_status": json.dumps(
                {
                    "active": True,
                    "last_heartbeat": heartbeat,
                    "adapter_ready": True,
                }
            )
        }
    )
    portfolio = SimpleNamespace(
        cash=Decimal("100.0"),
        total_value=Decimal("100.0"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        timestamp=datetime.now(timezone.utc),
        positions={},
    )
    module = importlib.import_module("services.dashboard.api.live_status")
    monkeypatch.setattr(module.settings, "live_trading_enabled", True, raising=False)
    monkeypatch.setattr(module.settings, "live_trading_dry_run", True, raising=False)
    monkeypatch.setattr(module.settings, "live_status_heartbeat_seconds", 30, raising=False)

    status = await build_live_status(redis, FakeSessionFactory(FakeSession(3, 0, portfolio)))

    assert status["enabled"] is True
    assert status["active"] is True
    assert status["order_count"] == 3
    assert status["fill_count"] == 0
    assert status["portfolio"]["cash"] == 100.0
