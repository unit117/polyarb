from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import backtest
from services.simulator.portfolio import Portfolio


def _make_market(market_id: int, *, resolved_outcome=None, resolved_at=None):
    return SimpleNamespace(
        id=market_id,
        event_id=None,
        question=f"Market {market_id}",
        outcomes=["Yes", "No"],
        resolved_outcome=resolved_outcome,
        resolved_at=resolved_at,
    )


class TestResolvedMarketGuards:
    @pytest.mark.asyncio
    async def test_detect_opportunities_skips_pairs_with_resolved_leg(self, monkeypatch):
        as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
        pair = SimpleNamespace(
            id=1,
            verified=True,
            market_a_id=10,
            market_b_id=11,
            dependency_type="implication",
            confidence=0.9,
            implication_direction="a_implies_b",
            resolution_vectors=None,
            constraint_matrix={
                "outcomes_a": ["Yes", "No"],
                "outcomes_b": ["Yes", "No"],
                "correlation": None,
            },
        )
        market_a = _make_market(
            10,
            resolved_outcome="Yes",
            resolved_at=datetime(2026, 1, 9, tzinfo=timezone.utc),
        )
        market_b = _make_market(11)

        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.get = AsyncMock(side_effect=[market_a, market_b])

        get_prices_at = AsyncMock()
        monkeypatch.setattr(backtest, "get_prices_at", get_prices_at)

        resolved_skip_logged = set()
        opp_ids = await backtest.detect_opportunities(
            session,
            [pair],
            as_of,
            resolved_skip_logged=resolved_skip_logged,
        )

        assert opp_ids == []
        assert resolved_skip_logged == {pair.id}
        get_prices_at.assert_not_called()
        session.add.assert_not_called()
        session.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_simulate_opportunity_skips_when_leg_is_already_resolved(self, monkeypatch):
        as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
        opp = SimpleNamespace(
            id=7,
            status="optimized",
            pair_id=1,
            optimal_trades={
                "trades": [
                    {
                        "market": "A",
                        "outcome": "Yes",
                        "side": "BUY",
                        "market_price": 0.55,
                    }
                ],
                "estimated_profit": 0.04,
            },
        )
        pair = SimpleNamespace(id=1, market_a_id=10, market_b_id=11)
        market_a = _make_market(
            10,
            resolved_outcome="Yes",
            resolved_at=datetime(2026, 1, 9, tzinfo=timezone.utc),
        )
        market_b = _make_market(11)

        session = AsyncMock()
        session.add = MagicMock()

        async def mock_get(model, object_id):
            from shared.models import ArbitrageOpportunity, Market, MarketPair

            if model == ArbitrageOpportunity:
                return opp
            if model == MarketPair:
                return pair
            if model == Market:
                return market_a if object_id == 10 else market_b
            return None

        session.get = AsyncMock(side_effect=mock_get)

        get_snapshot_at = AsyncMock()
        monkeypatch.setattr(backtest, "get_snapshot_at", get_snapshot_at)

        portfolio = Portfolio(10000.0)
        resolved_skip_logged = set()
        result = await backtest.simulate_opportunity(
            session,
            7,
            portfolio,
            as_of,
            max_position_size=100.0,
            resolved_skip_logged=resolved_skip_logged,
        )

        assert result == {
            "status": "skipped",
            "reason": "resolved_market",
            "trades_executed": 0,
        }
        assert resolved_skip_logged == {pair.id}
        get_snapshot_at.assert_not_called()
        session.add.assert_not_called()
        assert portfolio.total_trades == 0
