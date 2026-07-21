"""Integration tests for the simulator pipeline with mocked DB/Redis."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.simulator.pipeline import SimulatorPipeline
from services.simulator.portfolio import Portfolio


def _mock_session_factory():
    """Create a mock async session factory.

    flush() assigns IDs to added objects like a real DB flush would — the
    typed TradeExecutedEvent requires an int trade_id.
    """
    session = AsyncMock()
    added_objects = []
    session.add = MagicMock(side_effect=added_objects.append)  # add() is sync

    async def mock_flush():
        for i, obj in enumerate(added_objects, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = i
    session.flush = AsyncMock(side_effect=mock_flush)
    factory = AsyncMock()
    factory.__aenter__ = AsyncMock(return_value=session)
    factory.__aexit__ = AsyncMock(return_value=False)

    def create():
        return factory
    return create, session


def _make_opportunity(
    opp_id=1, status="optimized", pair_id=1, trades=None,
):
    opp = MagicMock()
    opp.id = opp_id
    opp.status = status
    opp.pair_id = pair_id
    opp.optimal_trades = trades or {
        "trades": [
            {
                "market": "A",
                "outcome": "Yes",
                "outcome_index": 0,
                "side": "BUY",
                "edge": 0.05,
                "market_price": 0.55,
                "fair_price": 0.60,
                "venue": "polymarket",
            },
        ],
        "estimated_profit": 0.04,
        "theoretical_profit": 0.05,
        "market_a_prices": {"current": [0.55, 0.45], "optimal": [0.60, 0.40]},
        "market_b_prices": {"current": [0.50, 0.50], "optimal": [0.50, 0.50]},
    }
    opp.timestamp = MagicMock()
    return opp


def _make_pair(pair_id=1, market_a_id=1, market_b_id=2):
    pair = MagicMock()
    pair.id = pair_id
    pair.market_a_id = market_a_id
    pair.market_b_id = market_b_id
    return pair


def _make_market(market_id=1, venue="polymarket", resolved_outcome=None):
    m = MagicMock()
    m.id = market_id
    m.venue = venue
    m.resolved_outcome = resolved_outcome
    m.active = True
    m.fee_rate_bps = None
    return m


def _make_snapshot(prices=None, order_book=None, midpoints=None):
    from datetime import datetime, timedelta, timezone

    snap = MagicMock()
    snap.prices = prices or {"Yes": 0.55, "No": 0.45}
    snap.order_book = order_book
    snap.midpoints = midpoints
    # Post-boot timestamp so the startup-grace gate treats it as fresh
    snap.timestamp = datetime.now(timezone.utc) + timedelta(seconds=1)
    return snap


class TestSimulateOpportunity:
    @pytest.mark.asyncio
    async def test_executes_trade_successfully(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        opp = _make_opportunity()
        pair = _make_pair()
        market_a = _make_market(1)
        market_b = _make_market(2)

        get_calls = [0]
        async def mock_get(model, id_):
            from shared.models import ArbitrageOpportunity, MarketPair, Market
            get_calls[0] += 1
            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            if model == Market:
                return market_a if id_ == 1 else market_b
            return None
        session.get = AsyncMock(side_effect=mock_get)

        # Mock price snapshot query (returns no order book → midpoint fill)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=_make_snapshot())
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )

        result = await pipeline.simulate_opportunity(1)

        assert result["status"] == "simulated"
        assert result["trades_executed"] == 1
        assert result["cash_remaining"] < 10000.0
        assert portfolio.total_trades == 1

    @pytest.mark.asyncio
    async def test_skips_non_optimized(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        opp = _make_opportunity(status="detected")
        session.get = AsyncMock(return_value=opp)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )

        result = await pipeline.simulate_opportunity(1)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_skips_in_flight_duplicates(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )
        pipeline._in_flight.add(1)

        result = await pipeline.simulate_opportunity(1)
        assert result["status"] == "skipped"
        assert result["reason"] == "in_flight"

    @pytest.mark.asyncio
    async def test_empty_trades_expires_opportunity(self):
        """An opportunity with no trades is a dead end — expired, not retried."""
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        opp = _make_opportunity(trades={"trades": [], "estimated_profit": 0.0})
        session.get = AsyncMock(return_value=opp)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )

        result = await pipeline.simulate_opportunity(1)
        assert result["status"] == "expired"
        assert result["reason"] == "no_trades"
        assert opp.status == "expired"

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_trade(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        opp = _make_opportunity()
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

        # Circuit breaker that blocks everything
        cb = AsyncMock()
        cb.pre_trade_check = AsyncMock(return_value=(False, "max_daily_loss"))
        cb.record_success = MagicMock()

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
            circuit_breaker=cb,
        )

        result = await pipeline.simulate_opportunity(1)
        # All trades blocked → reverts to optimized
        assert result["status"] == "blocked"
        assert result["trades_executed"] == 0


class TestSettleResolvedMarkets:
    @pytest.mark.asyncio
    async def test_settles_winning_position(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        # Set up a long position
        portfolio.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        initial_cash = float(portfolio.cash)

        # Mock resolved market
        resolved_market = _make_market(1, resolved_outcome="Yes")
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[resolved_market])
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )

        result = await pipeline.settle_resolved_markets()

        assert result["settled"] == 1
        assert result["pnl_realized"] > 0  # Won: paid 50, received 100
        assert "1:Yes" not in portfolio.positions

    @pytest.mark.asyncio
    async def test_no_positions_skips(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        portfolio = Portfolio(10000.0)

        pipeline = SimulatorPipeline(
            session_factory=factory_fn,
            redis=redis,
            portfolio=portfolio,
            max_position_size=100.0,
        )

        result = await pipeline.settle_resolved_markets()
        assert result["settled"] == 0
