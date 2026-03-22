"""Tests proving the execution lock serializes concurrent portfolio mutations.

Verifies that simultaneous simulate_opportunity, settle_resolved_markets,
and snapshot_portfolio calls cannot interleave against the shared portfolio.
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.simulator.pipeline import SimulatorPipeline
from services.simulator.portfolio import Portfolio


def _mock_session_factory():
    """Create a mock async session factory."""
    session = AsyncMock()
    session.add = MagicMock()
    factory = AsyncMock()
    factory.__aenter__ = AsyncMock(return_value=session)
    factory.__aexit__ = AsyncMock(return_value=False)

    def create():
        return factory
    return create, session


def _make_opportunity(opp_id=1, status="optimized", pair_id=1, trades=None):
    opp = MagicMock()
    opp.id = opp_id
    opp.status = status
    opp.pair_id = pair_id
    opp.optimal_trades = trades or {
        "trades": [
            {
                "market": "A",
                "outcome": "Yes",
                "side": "BUY",
                "edge": 0.05,
                "market_price": 0.55,
                "fair_price": 0.60,
                "venue": "polymarket",
            },
        ],
        "estimated_profit": 0.04,
    }
    opp.timestamp = MagicMock()
    opp.pending_at = None
    return opp


def _make_snapshot():
    snap = MagicMock()
    snap.prices = {"Yes": 0.55, "No": 0.45}
    snap.order_book = None
    snap.midpoints = None
    return snap


def _make_market(market_id=1, venue="polymarket", resolved_outcome=None):
    m = MagicMock()
    m.id = market_id
    m.venue = venue
    m.resolved_outcome = resolved_outcome
    return m


def _make_pair(pair_id=1, market_a_id=1, market_b_id=2):
    pair = MagicMock()
    pair.id = pair_id
    pair.market_a_id = market_a_id
    pair.market_b_id = market_b_id
    return pair


class TestExecutionLockSerializes:
    """Prove that concurrent portfolio-mutating calls are serialized."""

    @pytest.mark.asyncio
    async def test_concurrent_opportunities_are_serialized(self):
        """Two opportunities launched concurrently must not interleave.

        We inject a sleep into the first opportunity's execution path and
        verify that the second opportunity waits for it to complete before
        starting — i.e., the execution order log shows no interleaving.
        """
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        execution_log: list[str] = []

        # Two distinct opportunities
        opp_a = _make_opportunity(opp_id=1)
        opp_b = _make_opportunity(opp_id=2)
        pair = _make_pair()
        market_a = _make_market(1)
        market_b = _make_market(2)

        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair, Market
            if model == ArbitrageOpportunity:
                return opp_a if id_ == 1 else opp_b
            if model == MarketPair:
                return pair
            if model == Market:
                return market_a if id_ == 1 else market_b
            return None
        session.get = AsyncMock(side_effect=mock_get)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=_make_snapshot())
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )

        # Monkey-patch _simulate_opportunity_inner to log entry/exit with a
        # yield point (sleep) in between so interleaving would be visible.
        original = pipeline._simulate_opportunity_inner

        async def instrumented(opp_id):
            execution_log.append(f"start-{opp_id}")
            await asyncio.sleep(0.05)  # yield point where interleaving could happen
            result = await original(opp_id)
            execution_log.append(f"end-{opp_id}")
            return result

        pipeline._simulate_opportunity_inner = instrumented

        # Launch both concurrently
        results = await asyncio.gather(
            pipeline.simulate_opportunity(1),
            pipeline.simulate_opportunity(2),
        )

        # Both should complete (not be skipped — different IDs)
        assert all(r["status"] != "skipped" for r in results)

        # The execution log must show serialized order: start-X, end-X,
        # start-Y, end-Y — never start-X, start-Y (interleaved).
        assert len(execution_log) == 4
        # First two entries must be a matching start/end pair
        assert execution_log[0].startswith("start-")
        assert execution_log[1].startswith("end-")
        first_id = execution_log[0].split("-")[1]
        assert execution_log[1] == f"end-{first_id}"
        # Second pair
        assert execution_log[2].startswith("start-")
        assert execution_log[3].startswith("end-")
        second_id = execution_log[2].split("-")[1]
        assert execution_log[3] == f"end-{second_id}"
        # Both IDs were executed
        assert {first_id, second_id} == {"1", "2"}

    @pytest.mark.asyncio
    async def test_settlement_waits_for_opportunity(self):
        """settle_resolved_markets must wait if simulate_opportunity holds the lock."""
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        # Set up a position for settlement
        portfolio.execute_trade(1, "Yes", "BUY", 50, 0.50, 0.0)

        execution_log: list[str] = []

        opp = _make_opportunity(opp_id=1)
        pair = _make_pair()
        market_a = _make_market(1)
        market_b = _make_market(2)

        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair, Market
            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            if model == Market:
                return market_a if id_ == 1 else market_b
            return None
        session.get = AsyncMock(side_effect=mock_get)

        # Session.execute needs to return different things for different queries.
        # For simulate: price snapshot; for settle: resolved markets list.
        resolved_market = _make_market(1, resolved_outcome="Yes")
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[resolved_market])
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=_make_snapshot())
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )

        # Instrument both paths
        original_sim = pipeline._simulate_opportunity_inner
        original_settle = pipeline._settle_resolved_markets_inner

        async def instrumented_sim(opp_id):
            execution_log.append("sim-start")
            await asyncio.sleep(0.05)
            result = await original_sim(opp_id)
            execution_log.append("sim-end")
            return result

        async def instrumented_settle():
            execution_log.append("settle-start")
            result = await original_settle()
            execution_log.append("settle-end")
            return result

        pipeline._simulate_opportunity_inner = instrumented_sim
        pipeline._settle_resolved_markets_inner = instrumented_settle

        # Launch both concurrently — simulate first (grabs lock), settle waits
        await asyncio.gather(
            pipeline.simulate_opportunity(1),
            pipeline.settle_resolved_markets(),
        )

        # Must be serialized: one fully completes before the other starts
        assert len(execution_log) == 4
        assert execution_log[0].endswith("-start")
        assert execution_log[1].endswith("-end")
        first_op = execution_log[0].split("-")[0]
        assert execution_log[1] == f"{first_op}-end"

    @pytest.mark.asyncio
    async def test_snapshot_waits_for_opportunity(self):
        """snapshot_portfolio must wait if simulate_opportunity holds the lock."""
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        execution_log: list[str] = []

        opp = _make_opportunity(opp_id=1)
        pair = _make_pair()
        market_a = _make_market(1)
        market_b = _make_market(2)

        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair, Market
            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            if model == Market:
                return market_a if id_ == 1 else market_b
            return None
        session.get = AsyncMock(side_effect=mock_get)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=_make_snapshot())
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )

        original_sim = pipeline._simulate_opportunity_inner
        original_snap = pipeline._snapshot_portfolio_inner

        async def instrumented_sim(opp_id):
            execution_log.append("sim-start")
            await asyncio.sleep(0.05)
            result = await original_sim(opp_id)
            execution_log.append("sim-end")
            return result

        async def instrumented_snap():
            execution_log.append("snap-start")
            result = await original_snap()
            execution_log.append("snap-end")
            return result

        pipeline._simulate_opportunity_inner = instrumented_sim
        pipeline._snapshot_portfolio_inner = instrumented_snap

        await asyncio.gather(
            pipeline.simulate_opportunity(1),
            pipeline.snapshot_portfolio(),
        )

        assert len(execution_log) == 4
        assert execution_log[0].endswith("-start")
        assert execution_log[1].endswith("-end")
        first_op = execution_log[0].split("-")[0]
        assert execution_log[1] == f"{first_op}-end"
