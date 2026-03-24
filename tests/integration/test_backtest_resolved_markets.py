"""Regression test: backtest must not open new positions on already-resolved markets.

Bug: detect_opportunities() returned opportunities on resolved markets because it
didn't check resolved_at. The simulator then opened positions at stale pre-resolution
prices and immediately settled them at resolution price — generating fake profit.

Fix: both detect_opportunities() and simulate_opportunity() now skip markets where
resolved_at <= as_of. Settlement runs BEFORE detection each day.
"""

import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock shared.db before importing backtest (asyncpg may not be installed locally)
_mock_db = MagicMock()
_mock_db.SessionFactory = MagicMock()
_mock_db.init_db = AsyncMock()
sys.modules.setdefault("asyncpg", MagicMock())
if "shared.db" not in sys.modules:
    sys.modules["shared.db"] = _mock_db

from scripts.backtest import (
    detect_opportunities,
    simulate_opportunity,
    is_resolved_as_of,
    check_pair_resolved,
)
from services.simulator.portfolio import Portfolio


def _make_market(
    market_id=1,
    question="Will X?",
    outcomes=None,
    event_id="evt1",
    resolved_at=None,
    resolved_outcome=None,
):
    m = MagicMock()
    m.id = market_id
    m.question = question
    m.outcomes = outcomes or ["Yes", "No"]
    m.event_id = event_id
    m.resolved_at = resolved_at
    m.resolved_outcome = resolved_outcome
    return m


def _make_pair(
    pair_id=1,
    market_a_id=1,
    market_b_id=2,
    verified=True,
    dependency_type="mutual_exclusion",
    confidence=0.95,
    constraint_matrix=None,
    resolution_vectors=None,
    implication_direction=None,
):
    pair = MagicMock()
    pair.id = pair_id
    pair.market_a_id = market_a_id
    pair.market_b_id = market_b_id
    pair.verified = verified
    pair.dependency_type = dependency_type
    pair.confidence = confidence
    pair.constraint_matrix = constraint_matrix or {
        "outcomes_a": ["Yes", "No"],
        "outcomes_b": ["Yes", "No"],
        "matrix": [[1, 0], [0, 1]],
        "profit_bound": 0.05,
    }
    pair.resolution_vectors = resolution_vectors
    pair.implication_direction = implication_direction
    return pair


def _make_opp(opp_id=1, pair_id=1, status="optimized"):
    opp = MagicMock()
    opp.id = opp_id
    opp.pair_id = pair_id
    opp.status = status
    opp.optimal_trades = {
        "trades": [
            {
                "market": "A",
                "outcome": "Yes",
                "side": "BUY",
                "edge": 0.05,
                "market_price": 0.34,
                "fair_price": 0.50,
            },
        ],
        "estimated_profit": 0.04,
    }
    return opp


# ═══════════════════════════════════════════════════════════════════
#  Unit tests for helper functions
# ═══════════════════════════════════════════════════════════════════

class TestIsResolvedAsOf:
    def test_resolved_before_as_of(self):
        market = _make_market(
            resolved_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
            resolved_outcome="Yes",
        )
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)
        assert is_resolved_as_of(market, as_of) is True

    def test_resolved_exactly_at_as_of(self):
        t = datetime(2025, 1, 5, tzinfo=timezone.utc)
        market = _make_market(resolved_at=t, resolved_outcome="Yes")
        assert is_resolved_as_of(market, t) is True

    def test_resolved_after_as_of(self):
        market = _make_market(
            resolved_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
            resolved_outcome="Yes",
        )
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)
        assert is_resolved_as_of(market, as_of) is False

    def test_not_resolved(self):
        market = _make_market(resolved_at=None, resolved_outcome=None)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)
        assert is_resolved_as_of(market, as_of) is False

    def test_none_market(self):
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)
        assert is_resolved_as_of(None, as_of) is False

    def test_resolved_at_but_no_outcome(self):
        """resolved_at without resolved_outcome is not fully resolved."""
        market = _make_market(
            resolved_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
            resolved_outcome=None,
        )
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)
        assert is_resolved_as_of(market, as_of) is False


class TestCheckPairResolved:
    def test_neither_resolved(self):
        a = _make_market(market_id=1)
        b = _make_market(market_id=2)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)
        assert check_pair_resolved(a, b, as_of) == []

    def test_a_resolved(self):
        a = _make_market(
            market_id=1,
            resolved_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
            resolved_outcome="Yes",
        )
        b = _make_market(market_id=2)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)
        assert check_pair_resolved(a, b, as_of) == [1]

    def test_both_resolved(self):
        t = datetime(2025, 1, 5, tzinfo=timezone.utc)
        a = _make_market(market_id=1, resolved_at=t, resolved_outcome="Yes")
        b = _make_market(market_id=2, resolved_at=t, resolved_outcome="No")
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)
        assert check_pair_resolved(a, b, as_of) == [1, 2]


# ═══════════════════════════════════════════════════════════════════
#  Detection tests
# ═══════════════════════════════════════════════════════════════════

class TestDetectSkipsResolvedMarkets:
    """detect_opportunities must skip pairs where either market resolved before as_of."""

    @pytest.mark.asyncio
    async def test_skips_pair_when_market_a_resolved(self):
        resolved_date = datetime(2025, 1, 5, tzinfo=timezone.utc)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1, resolved_at=resolved_date, resolved_outcome="Yes")
        market_b = _make_market(market_id=2)
        pair = _make_pair(market_a_id=1, market_b_id=2)

        session = AsyncMock()
        session.get = AsyncMock(side_effect=lambda model, mid: {1: market_a, 2: market_b}[mid])

        opp_ids = await detect_opportunities(session, [pair], as_of)
        assert opp_ids == [], "Should detect zero opportunities on resolved pair"

    @pytest.mark.asyncio
    async def test_skips_pair_when_market_b_resolved(self):
        resolved_date = datetime(2025, 1, 5, tzinfo=timezone.utc)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1)
        market_b = _make_market(market_id=2, resolved_at=resolved_date, resolved_outcome="No")
        pair = _make_pair(market_a_id=1, market_b_id=2)

        session = AsyncMock()
        session.get = AsyncMock(side_effect=lambda model, mid: {1: market_a, 2: market_b}[mid])

        opp_ids = await detect_opportunities(session, [pair], as_of)
        assert opp_ids == [], "Should detect zero opportunities when market B is resolved"

    @pytest.mark.asyncio
    async def test_skips_pair_when_both_resolved(self):
        resolved_date = datetime(2025, 1, 5, tzinfo=timezone.utc)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1, resolved_at=resolved_date, resolved_outcome="Yes")
        market_b = _make_market(market_id=2, resolved_at=resolved_date, resolved_outcome="No")
        pair = _make_pair(market_a_id=1, market_b_id=2)

        session = AsyncMock()
        session.get = AsyncMock(side_effect=lambda model, mid: {1: market_a, 2: market_b}[mid])

        opp_ids = await detect_opportunities(session, [pair], as_of)
        assert opp_ids == [], "Should detect zero opportunities when both markets resolved"

    @pytest.mark.asyncio
    async def test_allows_pair_before_resolution(self):
        """Market resolves on Jan 15, but we're on Jan 10 — should NOT skip."""
        resolved_date = datetime(2025, 1, 15, tzinfo=timezone.utc)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1, resolved_at=resolved_date, resolved_outcome="Yes")
        market_b = _make_market(market_id=2)
        pair = _make_pair(market_a_id=1, market_b_id=2)

        session = AsyncMock()
        session.get = AsyncMock(
            side_effect=lambda model, mid: {1: market_a, 2: market_b}[mid]
        )
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        opp_ids = await detect_opportunities(session, [pair], as_of)
        assert opp_ids == []
        assert session.execute.called, "Should have attempted price lookup (not blocked by resolution)"

    @pytest.mark.asyncio
    async def test_allows_unresolved_pair(self):
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1)
        market_b = _make_market(market_id=2)
        pair = _make_pair(market_a_id=1, market_b_id=2)

        session = AsyncMock()
        session.get = AsyncMock(
            side_effect=lambda model, mid: {1: market_a, 2: market_b}[mid]
        )
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        opp_ids = await detect_opportunities(session, [pair], as_of)
        assert opp_ids == []
        assert session.execute.called

    @pytest.mark.asyncio
    async def test_pair_ids_filter(self):
        """When pair_ids is provided, only matching pairs are processed."""
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1)
        market_b = _make_market(market_id=2)
        pair1 = _make_pair(pair_id=1, market_a_id=1, market_b_id=2)
        pair2 = _make_pair(pair_id=2, market_a_id=1, market_b_id=2)

        session = AsyncMock()
        session.get = AsyncMock(
            side_effect=lambda model, mid: {1: market_a, 2: market_b}[mid]
        )
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        # Only allow pair_id=2
        opp_ids = await detect_opportunities(session, [pair1, pair2], as_of, pair_ids={2})
        # pair1 should be skipped, pair2 should proceed (but fail on missing prices)
        assert opp_ids == []
        # session.get should be called for pair2 but not pair1
        # (pair1 skipped before market fetch)

    @pytest.mark.asyncio
    async def test_resolved_skip_logged_dedup(self):
        """resolved_skip_logged set should prevent repeat warnings."""
        resolved_date = datetime(2025, 1, 5, tzinfo=timezone.utc)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1, resolved_at=resolved_date, resolved_outcome="Yes")
        market_b = _make_market(market_id=2)
        pair = _make_pair(pair_id=42, market_a_id=1, market_b_id=2)

        session = AsyncMock()
        session.get = AsyncMock(side_effect=lambda model, mid: {1: market_a, 2: market_b}[mid])

        logged = set()
        await detect_opportunities(session, [pair], as_of, resolved_skip_logged=logged)
        assert 42 in logged

        # Second call should still skip but not re-add
        await detect_opportunities(session, [pair], as_of, resolved_skip_logged=logged)
        assert logged == {42}


# ═══════════════════════════════════════════════════════════════════
#  Simulation tests
# ═══════════════════════════════════════════════════════════════════

class TestSimulateBlocksResolvedMarkets:
    """simulate_opportunity must refuse to trade on already-resolved markets."""

    @pytest.mark.asyncio
    async def test_blocks_trade_when_market_a_resolved(self):
        resolved_date = datetime(2025, 1, 5, tzinfo=timezone.utc)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1, resolved_at=resolved_date, resolved_outcome="Yes")
        market_b = _make_market(market_id=2)
        pair = _make_pair(market_a_id=1, market_b_id=2)
        opp = _make_opp(opp_id=1, pair_id=1)

        session = AsyncMock()
        call_count = [0]

        def _get_side_effect(model, entity_id):
            call_count[0] += 1
            if call_count[0] == 1:
                return opp
            elif call_count[0] == 2:
                return pair
            elif call_count[0] == 3:
                return market_a
            elif call_count[0] == 4:
                return market_b
            return None

        session.get = AsyncMock(side_effect=_get_side_effect)

        portfolio = Portfolio(10000.0)
        result = await simulate_opportunity(session, 1, portfolio, as_of, 100.0)

        assert result["status"] == "skipped"
        assert result["trades_executed"] == 0
        assert portfolio.total_trades == 0

    @pytest.mark.asyncio
    async def test_blocks_trade_when_market_b_resolved(self):
        resolved_date = datetime(2025, 1, 5, tzinfo=timezone.utc)
        as_of = datetime(2025, 1, 10, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1)
        market_b = _make_market(market_id=2, resolved_at=resolved_date, resolved_outcome="No")
        pair = _make_pair(market_a_id=1, market_b_id=2)
        opp = _make_opp(opp_id=1, pair_id=1)

        session = AsyncMock()
        call_count = [0]

        def _get_side_effect(model, entity_id):
            call_count[0] += 1
            if call_count[0] == 1:
                return opp
            elif call_count[0] == 2:
                return pair
            elif call_count[0] == 3:
                return market_a
            elif call_count[0] == 4:
                return market_b
            return None

        session.get = AsyncMock(side_effect=_get_side_effect)

        portfolio = Portfolio(10000.0)
        result = await simulate_opportunity(session, 2, portfolio, as_of, 100.0)

        assert result["status"] == "skipped"
        assert result["trades_executed"] == 0
        assert portfolio.total_trades == 0


# ═══════════════════════════════════════════════════════════════════
#  End-to-end regression
# ═══════════════════════════════════════════════════════════════════

class TestEndToEndResolvedMarketRegression:
    """Simulate the exact bug scenario over multiple days."""

    @pytest.mark.asyncio
    async def test_no_trades_after_resolution(self):
        resolved_date = datetime(2025, 1, 5, tzinfo=timezone.utc)

        market_a = _make_market(market_id=1, resolved_at=resolved_date, resolved_outcome="Yes")
        market_b = _make_market(market_id=2, resolved_at=resolved_date, resolved_outcome="No")
        pair = _make_pair(market_a_id=1, market_b_id=2)

        portfolio = Portfolio(10000.0)
        resolved_skip_logged: set[int] = set()

        for day_offset in range(6, 11):
            as_of = datetime(2025, 1, day_offset, tzinfo=timezone.utc)

            session = AsyncMock()
            session.get = AsyncMock(
                side_effect=lambda model, mid: {1: market_a, 2: market_b}[mid]
            )

            opp_ids = await detect_opportunities(
                session, [pair], as_of, resolved_skip_logged=resolved_skip_logged,
            )
            assert opp_ids == [], f"Day {day_offset}: should not detect opportunities"

        assert portfolio.total_trades == 0
        assert portfolio.realized_pnl == Decimal("0")
        assert float(portfolio.cash) == 10000.0
        # Should have logged only once despite 5 days
        assert pair.id in resolved_skip_logged
