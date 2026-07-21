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

    assert portfolio.cash == Decimal("998.00")
    assert portfolio.positions["10:Yes"] == Decimal("5")
    assert portfolio.cost_basis["10:Yes"] == Decimal("2.00")
    assert portfolio.total_trades == 1
    assert any("paper_trades" in query for query in session.execute_queries)


@pytest.mark.asyncio
async def test_restore_portfolio_purge_resets_counters():
    """After PURGE rows, counters should be zeroed for the post-purge baseline."""
    trades = [
        SimpleNamespace(
            market_id=10,
            outcome="Yes",
            side="BUY",
            size=Decimal("5"),
            vwap_price=Decimal("0.40"),
            fees=Decimal("0"),
        ),
        SimpleNamespace(
            market_id=10,
            outcome="Yes",
            side="PURGE",
            size=Decimal("5"),
            vwap_price=Decimal("0.50"),
            fees=Decimal("0"),
        ),
        SimpleNamespace(
            market_id=20,
            outcome="Yes",
            side="BUY",
            size=Decimal("3"),
            vwap_price=Decimal("0.30"),
            fees=Decimal("0"),
        ),
    ]
    session = FakeSession(trades)

    portfolio = await restore_portfolio(
        FakeSessionFactory(session),
        initial_capital=1000.0,
        source="paper",
    )

    assert portfolio.cash == Decimal("999.60")
    assert portfolio.positions == {"20:Yes": Decimal("3")}
    assert portfolio.total_trades == 1
    assert portfolio.settled_trades == 0
    assert portfolio.winning_trades == 0
    assert portfolio.realized_pnl == Decimal("0")


@pytest.mark.asyncio
async def test_restore_portfolio_fresh_start_with_no_trades():
    session = FakeSession([])

    portfolio = await restore_portfolio(
        FakeSessionFactory(session),
        initial_capital=5000.0,
        source="paper",
    )

    assert portfolio.cash == Decimal("5000.0")
    assert portfolio.positions == {}
    assert portfolio.total_trades == 0


def _trade(side: str, size: float, price: float, fees: float = 0.0):
    return SimpleNamespace(
        market_id=1,
        outcome="Yes",
        side=side,
        size=size,
        vwap_price=price,
        fees=fees,
    )


@pytest.mark.asyncio
async def test_replay_reproduces_long_exit_realized_pnl():
    """A SELL closing a long must contribute realized PnL during replay,
    mirroring the live pipeline (execute_trade itself never touches
    realized_pnl, so replay used to drop all exit PnL on every restart)."""
    trades = [
        _trade("BUY", 10, 0.40, fees=0.10),
        _trade("SELL", 10, 0.55, fees=0.10),
    ]
    session = FakeSession(trades)
    portfolio = await restore_portfolio(FakeSessionFactory(session), 1000.0)

    # avg_entry 0.40 → (0.55 - 0.40) * 10 - 0.10 exit fees = 1.40
    assert portfolio.realized_pnl == Decimal("1.4")
    assert not portfolio.positions  # flat after the round trip


@pytest.mark.asyncio
async def test_replay_reproduces_short_cover_realized_pnl():
    """A BUY covering a short realizes (avg_credit - cover_price) * size."""
    trades = [
        _trade("SELL", 10, 0.60, fees=0.05),   # open short, credit basis 5.95
        _trade("BUY", 10, 0.45, fees=0.05),    # cover
    ]
    session = FakeSession(trades)
    portfolio = await restore_portfolio(FakeSessionFactory(session), 1000.0)

    # avg credit 0.595 → (0.595 - 0.45) * 10 - 0.05 exit fees = 1.40
    assert portfolio.realized_pnl == Decimal("1.4")
    assert not portfolio.positions


@pytest.mark.asyncio
async def test_replay_entry_only_has_no_realized_pnl():
    """Entries must not produce realized PnL."""
    trades = [_trade("BUY", 10, 0.40, fees=0.10)]
    session = FakeSession(trades)
    portfolio = await restore_portfolio(FakeSessionFactory(session), 1000.0)

    assert portfolio.realized_pnl == Decimal("0")
    assert portfolio.positions["1:Yes"] == Decimal("10")
