"""Shared fixtures for PolyArb test suite."""

import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path so `services.*` and `shared.*` imports work
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Prevent pydantic-settings from loading the real .env file during tests
os.environ.setdefault("POLYARB_ENV_FILE", "/dev/null")


@pytest.fixture
def sample_binary_market():
    """Factory for a binary prediction market dict."""
    def _make(
        market_id=1,
        question="Will X happen?",
        outcomes=None,
        event_id=None,
        venue="polymarket",
        description="",
    ):
        return {
            "id": market_id,
            "question": question,
            "outcomes": outcomes or ["Yes", "No"],
            "event_id": event_id,
            "venue": venue,
            "description": description,
        }
    return _make


@pytest.fixture
def sample_prices():
    """Factory for price dicts."""
    def _make(yes_price=0.60, no_price=0.40):
        return {"Yes": yes_price, "No": no_price}
    return _make


@pytest.fixture
def sample_order_book():
    """Factory for order book dicts."""
    def _make(asks=None, bids=None):
        return {
            "asks": asks or [[0.61, 100], [0.62, 200], [0.63, 150]],
            "bids": bids or [[0.59, 100], [0.58, 200], [0.57, 150]],
        }
    return _make
