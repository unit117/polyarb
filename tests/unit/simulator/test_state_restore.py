from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from services.simulator.state import restore_portfolio


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalars(self._rows)


class FakeSession:
    def __init__(self, snapshot, trades):
        self.snapshot = snapshot
        self.trades = trades
        self.scalar_queries: list[str] = []
        self.execute_queries: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def scalar(self, query):
        sql = str(query)
        self.scalar_queries.append(sql)
        if "portfolio_snapshots" in sql:
            return self.snapshot
        if "count(*)" in sql and "paper_trades" in sql:
            return len(self.trades)
        return None

    async def execute(self, query):
        self.execute_queries.append(str(query))
        return FakeExecuteResult(self.trades)


class FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


@pytest.mark.asyncio
async def test_restore_portfolio_filters_snapshot_and_trade_queries_by_source():
    snapshot = SimpleNamespace(
        cash=Decimal("125.0"),
        realized_pnl=Decimal("5.0"),
        total_trades=1,
        settled_trades=0,
        winning_trades=1,
        positions={"10:Yes": 5.0},
    )
    trades = [
        SimpleNamespace(
            market_id=10,
            outcome="Yes",
            side="BUY",
            size=Decimal("5"),
            vwap_price=Decimal("0.40"),
            fees=Decimal("0"),
        )
    ]
    session = FakeSession(snapshot, trades)

    portfolio = await restore_portfolio(
        FakeSessionFactory(session),
        initial_capital=1000.0,
        source="live",
    )

    assert portfolio.cash == Decimal("125.0")
    assert portfolio.positions["10:Yes"] == Decimal("5.0")
    assert portfolio.cost_basis["10:Yes"] == Decimal("2.00")
    assert any("portfolio_snapshots.source" in query for query in session.scalar_queries)
    assert any("paper_trades.source" in query for query in session.execute_queries)
