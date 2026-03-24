"""Tests for V4 silver dataset curator — noisy sports filter (pure function)."""

import sys
from unittest.mock import MagicMock, AsyncMock

# Mock asyncpg and shared.db before importing the curator
sys.modules.setdefault("asyncpg", MagicMock())
_mock_db = MagicMock()
_mock_db.SessionFactory = MagicMock()
_mock_db.init_db = AsyncMock()
if "shared.db" not in sys.modules:
    sys.modules["shared.db"] = _mock_db

from scripts.curate_silver_dataset import _is_noisy_sports


class TestIsNoisySports:
    def test_over_under(self):
        assert _is_noisy_sports("O/U 2.5 goals in the match")

    def test_btts(self):
        assert _is_noisy_sports("Both teams to score in Liverpool vs Arsenal")

    def test_btts_abbreviation(self):
        assert _is_noisy_sports("BTTS - Liverpool vs Arsenal")

    def test_spread(self):
        assert _is_noisy_sports("Lakers -3.5 spread against Celtics")

    def test_handicap(self):
        assert _is_noisy_sports("Arsenal handicap -1 against Chelsea")

    def test_over_under_words(self):
        assert _is_noisy_sports("Over/under 215.5 points in the NBA game")

    def test_over_standalone(self):
        assert _is_noisy_sports("Over 2.5 goals in the match")

    def test_under_standalone(self):
        assert _is_noisy_sports("Under 3.5 goals in the match")

    def test_not_noisy_winner(self):
        assert not _is_noisy_sports("Will the Lakers win the championship?")

    def test_not_noisy_crypto(self):
        assert not _is_noisy_sports("Will Bitcoin reach $100k by December?")

    def test_not_noisy_politics(self):
        assert not _is_noisy_sports("Will the Senate pass the bill?")

    def test_case_insensitive(self):
        assert _is_noisy_sports("OVER/UNDER 2.5 goals")
        assert _is_noisy_sports("Spread: Lakers -5.5")
