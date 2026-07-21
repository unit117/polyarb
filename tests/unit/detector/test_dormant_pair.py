"""Tests for the detector dormant-pair filter (_is_pair_dormant)."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.config import settings
from services.detector.pipeline import DetectionPipeline


def _pipeline():
    return DetectionPipeline(
        session_factory=MagicMock(),
        openai_client=MagicMock(),
        redis=MagicMock(),
        similarity_threshold=0.82,
        similarity_top_k=10,
        batch_size=100,
        classifier_model="gpt-4.1-mini",
    )


def _session_returning(profit_rows):
    """session.execute(...).all() yields single-column (estimated_profit,) rows."""
    result_mock = MagicMock()
    result_mock.all.return_value = [(p,) for p in profit_rows]
    session = AsyncMock()
    session.execute.return_value = result_mock
    return session


class TestIsPairDormant:
    @pytest.mark.asyncio
    async def test_all_zero_profit_is_dormant(self):
        session = _session_returning([Decimal("0")] * 5)
        assert await _pipeline()._is_pair_dormant(session, 30730) is True

    @pytest.mark.asyncio
    async def test_any_nonzero_profit_not_dormant(self):
        session = _session_returning(
            [Decimal("0"), Decimal("0"), Decimal("0.02"), Decimal("0"), Decimal("0")]
        )
        assert await _pipeline()._is_pair_dormant(session, 30730) is False

    @pytest.mark.asyncio
    async def test_too_few_evaluations_not_dormant(self):
        # Fewer than dormant_pair_min_evaluations rows in the window — can't judge.
        session = _session_returning([Decimal("0"), Decimal("0")])
        assert await _pipeline()._is_pair_dormant(session, 30730) is False

    @pytest.mark.asyncio
    async def test_none_profit_treated_as_zero(self):
        session = _session_returning([None, None, Decimal("0"), Decimal("0"), Decimal("0")])
        assert await _pipeline()._is_pair_dormant(session, 30730) is True

    @pytest.mark.asyncio
    async def test_disabled_flag_short_circuits(self, monkeypatch):
        monkeypatch.setattr(settings, "dormant_pair_enabled", False)
        session = _session_returning([Decimal("0")] * 5)
        assert await _pipeline()._is_pair_dormant(session, 30730) is False
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_null_profit_counts_as_zero(self):
        # Opps expired by the optimizer's stale sweep while still DETECTED
        # never get a profit written; they must count toward dormancy
        # instead of hiding it (the pre-fix SQL filtered NULLs out).
        session = _session_returning([None, Decimal("0"), None, None, Decimal("0")])
        assert await _pipeline()._is_pair_dormant(session, 30730) is True
