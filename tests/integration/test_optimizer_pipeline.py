"""Integration tests for the optimizer pipeline with mocked DB/Redis."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from services.optimizer.pipeline import OptimizerPipeline


def _mock_session_factory():
    """Create a mock async session factory that yields a mock session."""
    session = AsyncMock()
    session.add = MagicMock()  # add() is sync
    factory = AsyncMock()
    factory.__aenter__ = AsyncMock(return_value=session)
    factory.__aexit__ = AsyncMock(return_value=False)

    def create():
        return factory
    return create, session


def _make_opportunity(opp_id=1, status="detected", pair_id=1, optimal_trades=None):
    opp = MagicMock()
    opp.id = opp_id
    opp.status = status
    opp.pair_id = pair_id
    opp.optimal_trades = optimal_trades
    opp.timestamp = MagicMock()
    return opp


def _make_pair(pair_id=1, market_a_id=1, market_b_id=2, dep_type="implication"):
    pair = MagicMock()
    pair.id = pair_id
    pair.market_a_id = market_a_id
    pair.market_b_id = market_b_id
    pair.dependency_type = dep_type
    pair.constraint_matrix = {
        "type": dep_type,
        "outcomes_a": ["Yes", "No"],
        "outcomes_b": ["Yes", "No"],
        "matrix": [[1, 0], [0, 1]],
        "profit_bound": 0.05,
    }
    return pair


def _make_market(market_id=1, venue="polymarket"):
    m = MagicMock()
    m.id = market_id
    m.venue = venue
    return m


def _make_price_snapshot(prices):
    snap = MagicMock()
    snap.prices = prices
    return snap


class TestOptimizeOpportunity:
    @pytest.mark.asyncio
    async def test_optimizes_detected_opportunity(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        opp = _make_opportunity()
        pair = _make_pair()
        market_a = _make_market(1, "polymarket")
        market_b = _make_market(2, "polymarket")
        snap_a = _make_price_snapshot({"Yes": 0.7, "No": 0.3})
        snap_b = _make_price_snapshot({"Yes": 0.5, "No": 0.5})

        # session.get returns different objects by type/id
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

        # Mock price query
        mock_result = MagicMock()
        call_count = [0]
        def scalar_side_effect():
            call_count[0] += 1
            return snap_a if call_count[0] % 2 == 1 else snap_b
        mock_result.scalar_one_or_none = scalar_side_effect
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
            min_edge=0.03,
            skip_conditional=True,
        )

        result = await pipeline.optimize_opportunity(1)

        assert result["status"] in ("optimized", "unconverged")
        assert result["iterations"] > 0
        assert "estimated_profit" in result

    @pytest.mark.asyncio
    async def test_skips_non_detected(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        opp = _make_opportunity(status="simulated")
        session.get = AsyncMock(return_value=opp)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        result = await pipeline.optimize_opportunity(1)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_returns_not_found(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        session.get = AsyncMock(return_value=None)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        result = await pipeline.optimize_opportunity(999)
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_skips_conditional_when_configured(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        opp = _make_opportunity()
        pair = _make_pair(dep_type="conditional")
        pair.constraint_matrix["type"] = "conditional"

        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair
            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            return None
        session.get = AsyncMock(side_effect=mock_get)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
            skip_conditional=True,
        )

        result = await pipeline.optimize_opportunity(1)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_no_constraints_returns_error(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        opp = _make_opportunity()
        pair = MagicMock()
        pair.id = 1
        pair.constraint_matrix = None

        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair
            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            return None
        session.get = AsyncMock(side_effect=mock_get)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        result = await pipeline.optimize_opportunity(1)
        assert result["status"] == "no_constraints"

    @pytest.mark.asyncio
    async def test_skips_detected_opportunity_when_pair_is_unverified(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        opp = _make_opportunity()
        pair = _make_pair()
        pair.verified = False

        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair
            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            return None

        session.get = AsyncMock(side_effect=mock_get)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        result = await pipeline.optimize_opportunity(1)

        assert result == {"status": "skipped", "reason": "pair_unverified"}
        assert opp.status == "skipped"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_invalid_constraint_matrix_returns_error(self):
        """Empty outcomes_a/b in constraint_matrix → invalid_constraints."""
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        opp = _make_opportunity()
        pair = MagicMock()
        pair.id = 1
        pair.market_a_id = 1
        pair.market_b_id = 2
        pair.dependency_type = "implication"
        # constraint_matrix present but has empty outcomes
        pair.constraint_matrix = {
            "type": "implication",
            "outcomes_a": [],
            "outcomes_b": [],
            "matrix": [],
        }

        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair
            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            return None
        session.get = AsyncMock(side_effect=mock_get)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        result = await pipeline.optimize_opportunity(1)
        assert result["status"] == "invalid_constraints"

    @pytest.mark.asyncio
    async def test_missing_prices_returns_no_prices(self):
        """When price snapshots are missing/stale → no_prices."""
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        opp = _make_opportunity()
        pair = _make_pair()

        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair
            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            return None
        session.get = AsyncMock(side_effect=mock_get)

        # Simulate no price snapshot found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        result = await pipeline.optimize_opportunity(1)
        assert result["status"] == "no_prices"


class TestProcessPending:
    @pytest.mark.asyncio
    async def test_empty_queue_returns_zero_stats(self):
        """No detected opportunities → zero processed."""
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        # No rows returned
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        stats = await pipeline.process_pending()
        assert stats["processed"] == 0
        assert stats["optimized"] == 0
        assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_processes_detected_opportunities(self):
        """process_pending optimizes detected opportunities and returns counts."""
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        opp = _make_opportunity()
        pair = _make_pair()
        market_a = _make_market(1, "polymarket")
        market_b = _make_market(2, "polymarket")
        snap_a = _make_price_snapshot({"Yes": 0.7, "No": 0.3})
        snap_b = _make_price_snapshot({"Yes": 0.5, "No": 0.5})

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

        # First execute returns opp IDs, subsequent return prices
        call_count = [0]
        def execute_side_effect(query):
            call_count[0] += 1
            if call_count[0] == 1:
                # Return list of opp IDs for process_pending query
                mock_rows = MagicMock()
                mock_rows.fetchall = MagicMock(return_value=[(1,)])
                return mock_rows
            else:
                # Return price snapshots for optimize_opportunity
                mock_snap_result = MagicMock()
                snap_call = [0]
                def scalar_fn():
                    snap_call[0] += 1
                    return snap_a if snap_call[0] % 2 == 1 else snap_b
                mock_snap_result.scalar_one_or_none = scalar_fn
                return mock_snap_result

        session.execute = AsyncMock(side_effect=execute_side_effect)

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        stats = await pipeline.process_pending()
        assert stats["processed"] == 1
        assert stats["optimized"] + stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_exception_counts_as_failed(self):
        """An exception inside optimize_opportunity is caught and counted as failed."""
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()

        call_count = [0]
        def execute_side_effect(query):
            call_count[0] += 1
            if call_count[0] == 1:
                mock_rows = MagicMock()
                mock_rows.fetchall = MagicMock(return_value=[(42,)])
                return mock_rows
            raise RuntimeError("DB error")

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.get = AsyncMock(side_effect=RuntimeError("DB error"))

        pipeline = OptimizerPipeline(
            session_factory=factory_fn,
            redis=redis,
            max_iterations=50,
            gap_tolerance=0.01,
            ip_timeout_ms=5000,
        )

        stats = await pipeline.process_pending()
        # processed is only incremented on success; exception goes to failed directly
        assert stats["processed"] == 0
        assert stats["failed"] == 1
