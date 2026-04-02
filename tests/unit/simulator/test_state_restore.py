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
    def __init__(self, trades):
        self.trades = trades
        self.execute_queries: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
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
async def test_restore_portfolio_rebuilds_state_from_trades():
    """Restore must rebuild all portfolio state purely from the trade ledger."""
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
    session = FakeSession(trades)

    portfolio = await restore_portfolio(
        FakeSessionFactory(session),
        initial_capital=1000.0,
        source="live",
    )

    # Cash = 1000 - (5 * 0.40 + 0 fees) = 998
    assert portfolio.cash == Decimal("998")
    assert portfolio.positions["10:Yes"] == Decimal("5")
    assert portfolio.cost_basis["10:Yes"] == Decimal("2.00")
    assert portfolio.total_trades == 1
    # Verify the query filters by source
    assert any("paper_trades" in query for query in session.execute_queries)


@pytest.mark.asyncio
async def test_restore_portfolio_purge_resets_counters():
    """After PURGE rows, counters should be zeroed for the post-purge baseline."""
    trades = [
        # Pre-purge trade
        SimpleNamespace(
            market_id=10, outcome="Yes", side="BUY",
            size=Decimal("5"), vwap_price=Decimal("0.40"), fees=Decimal("0"),
        ),
        # Purge at mark-to-market
        SimpleNamespace(
            market_id=10, outcome="Yes", side="PURGE",
            size=Decimal("5"), vwap_price=Decimal("0.50"), fees=Decimal("0"),
        ),
        # Post-purge trade
        SimpleNamespace(
            market_id=20, outcome="Yes", side="BUY",
            size=Decimal("3"), vwap_price=Decimal("0.30"), fees=Decimal("0"),
        ),
    ]
    session = FakeSession(trades)

    portfolio = await restore_portfolio(
        FakeSessionFactory(session),
        initial_capital=1000.0,
        source="paper",
    )

    # After purge: cash got the close_position payout (5 * 0.50 = 2.50),
    # then counters were reset, then BUY 3 @ 0.30 costs 0.90.
    # Purge close: cash was 998 + 2.50 = 1000.50 (from 0.10 profit).
    # Counter reset keeps cash as-is, zeros realized_pnl/counters.
    # Post-purge BUY: cash = 1000.50 - 0.90 = 999.60
    assert portfolio.cash == Decimal("1000.50") - Decimal("0.90")
    assert portfolio.positions == {"20:Yes": Decimal("3")}
    assert portfolio.total_trades == 1  # Only post-purge trade
    assert portfolio.realized_pnl == Decimal("0")


@pytest.mark.asyncio
async def test_restore_portfolio_fresh_start_with_no_trades():
    """No trades → fresh portfolio at initial capital."""
    session = FakeSession([])

    portfolio = await restore_portfolio(
        FakeSessionFactory(session),
        initial_capital=5000.0,
        source="paper",
    )

    assert portfolio.cash == Decimal("5000")
    assert portfolio.positions == {}
    assert portfolio.total_trades == 0
