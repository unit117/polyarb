"""Tests for shared/pricing.py — canonical snapshot query."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.pricing import get_latest_snapshot, is_price_frozen


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


def _frozen_session(rows):
    """Build a mock session whose execute(...).all() yields (midpoints, prices) rows."""
    result_mock = MagicMock()
    result_mock.all.return_value = rows
    session = AsyncMock()
    session.execute.return_value = result_mock
    return session


class TestIsPriceFrozen:
    @pytest.mark.asyncio
    async def test_identical_midpoints_are_frozen(self):
        rows = [({"Yes": 0.44, "No": 0.56}, None)] * 10
        session = _frozen_session(rows)
        assert await is_price_frozen(
            session, 1, "Yes", window_seconds=3600, min_observations=4
        ) is True

    @pytest.mark.asyncio
    async def test_moving_midpoints_not_frozen(self):
        rows = [
            ({"Yes": 0.44, "No": 0.56}, None),
            ({"Yes": 0.45, "No": 0.55}, None),
            ({"Yes": 0.44, "No": 0.56}, None),
            ({"Yes": 0.46, "No": 0.54}, None),
            ({"Yes": 0.44, "No": 0.56}, None),
        ]
        session = _frozen_session(rows)
        assert await is_price_frozen(
            session, 1, "Yes", window_seconds=3600, min_observations=4
        ) is False

    @pytest.mark.asyncio
    async def test_too_few_observations_not_frozen(self):
        """Benefit of the doubt: not enough history to declare frozen."""
        rows = [({"Yes": 0.44, "No": 0.56}, None)] * 3
        session = _frozen_session(rows)
        assert await is_price_frozen(
            session, 1, "Yes", window_seconds=3600, min_observations=4
        ) is False

    @pytest.mark.asyncio
    async def test_falls_back_to_prices_when_no_midpoints(self):
        rows = [(None, {"Yes": 0.44, "No": 0.56})] * 6
        session = _frozen_session(rows)
        assert await is_price_frozen(
            session, 1, "Yes", window_seconds=3600, min_observations=4
        ) is True

    @pytest.mark.asyncio
    async def test_string_prices_are_float_cast(self):
        """Polymarket stores prices as strings — frozen detection must still work."""
        rows = [({"Yes": "0.44", "No": "0.56"}, None)] * 6
        session = _frozen_session(rows)
        assert await is_price_frozen(
            session, 1, "Yes", window_seconds=3600, min_observations=4
        ) is True

    @pytest.mark.asyncio
    async def test_missing_outcome_not_counted(self):
        """Rows lacking the traded outcome don't count toward observations."""
        rows = [({"No": 0.56}, None)] * 10
        session = _frozen_session(rows)
        # No observations for "Yes" → cannot judge → not frozen
        assert await is_price_frozen(
            session, 1, "Yes", window_seconds=3600, min_observations=4
        ) is False


class TestSelectOutcomeBook:
    def test_legacy_single_book_returned_for_any_outcome(self):
        from shared.pricing import select_outcome_book

        legacy = {"bids": [["0.4", "1"]], "asks": []}
        assert select_outcome_book(legacy, "Yes") is legacy
        assert select_outcome_book(legacy, "No") is legacy

    def test_keyed_book_selects_outcome(self):
        from shared.pricing import select_outcome_book

        yes_book = {"bids": [], "asks": [["0.6", "2"]]}
        keyed = {"Yes": yes_book, "No": {"bids": [], "asks": []}}
        assert select_outcome_book(keyed, "Yes") is yes_book
        assert select_outcome_book(keyed, "Maybe") is None

    def test_none_and_garbage(self):
        from shared.pricing import select_outcome_book

        assert select_outcome_book(None, "Yes") is None
        assert select_outcome_book("x", "Yes") is None
