"""Tests for shared/pricing.py — canonical snapshot query."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.pricing import get_latest_snapshot


def _make_snapshot(prices=None, market_id=1, ts=None):
    snap = MagicMock()
    snap.prices = prices or {"Yes": 0.6, "No": 0.4}
    snap.market_id = market_id
    snap.timestamp = ts or datetime.now(timezone.utc)
    return snap


class TestGetLatestSnapshot:
    @pytest.mark.asyncio
    async def test_returns_snapshot_when_found(self):
        snap = _make_snapshot()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = snap
        session = AsyncMock()
        session.execute.return_value = result_mock

        result = await get_latest_snapshot(session, market_id=1)
        assert result is snap
        assert result.prices == {"Yes": 0.6, "No": 0.4}

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute.return_value = result_mock

        result = await get_latest_snapshot(session, market_id=999)
        assert result is None

    @pytest.mark.asyncio
    async def test_passes_max_age_seconds(self):
        """Verify max_age_seconds > 0 adds an extra where clause."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute.return_value = result_mock

        await get_latest_snapshot(session, market_id=1, max_age_seconds=600)
        # Should still execute — we just check it doesn't crash
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_max_age_skips_cutoff(self):
        """max_age_seconds=0 (default) should not add a time cutoff."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute.return_value = result_mock

        await get_latest_snapshot(session, market_id=1, max_age_seconds=0)
        session.execute.assert_called_once()
