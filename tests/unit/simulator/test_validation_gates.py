"""Tests for build_validated_bundle's execution gates.

Covers the Phase-2 remediation gates: zero-edge cooldown recording, the
post-restart startup grace, and the per-pair exposure-opening flow cap.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.simulator.validation as validation
from services.simulator.portfolio import Portfolio
from shared.config import settings


def _optimal(profit=0.05, side="BUY", fair=0.6):
    leg = dict(
        outcome="Yes",
        outcome_index=0,
        side=side,
        edge=0.1,
        market_price=0.5,
        fair_price=fair,
    )
    return dict(
        trades=[dict(market="A", **leg), dict(market="B", **leg)],
        estimated_profit=profit,
        theoretical_profit=profit,
        market_a_prices=dict(current=[0.5], optimal=[0.5]),
        market_b_prices=dict(current=[0.5], optimal=[0.5]),
    )


def _market(mid):
    return SimpleNamespace(
        id=mid, resolved_outcome=None, active=True, venue="polymarket", fee_rate_bps=0
    )


def _opp(profit=0.05, **optimal_kwargs):
    return SimpleNamespace(
        id=1,
        pair_id=42,
        estimated_profit=profit,
        optimal_trades=_optimal(profit=profit, **optimal_kwargs),
    )


@pytest.fixture
def world(monkeypatch):
    """Monkeypatch validation's collaborators to a controllable happy path."""
    now = datetime.now(timezone.utc)
    snapshot = SimpleNamespace(timestamp=now + timedelta(seconds=1), order_book=None)

    get_snapshot = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(validation, "get_latest_snapshot", get_snapshot)
    monkeypatch.setattr(validation, "is_price_frozen", AsyncMock(return_value=False))
    record_rejection = AsyncMock(return_value=False)
    monkeypatch.setattr(validation, "record_frozen_rejection", record_rejection)
    monkeypatch.setattr(
        validation,
        "compute_vwap",
        lambda ob, side, size, mid: {
            "filled_size": size,
            "vwap_price": mid,
            "slippage": 0.0,
        },
    )
    monkeypatch.setattr(validation, "_PROCESS_START", now)
    monkeypatch.setattr(settings, "simulator_startup_grace_seconds", 180)
    monkeypatch.setattr(settings, "max_pair_weekly_flow", 100.0)

    return SimpleNamespace(
        now=now,
        snapshot=snapshot,
        get_snapshot=get_snapshot,
        record_rejection=record_rejection,
        session=MagicMock(),
        redis=MagicMock(),
        portfolio=Portfolio(1000.0),
    )


async def _build(world, opp):
    return await validation.build_validated_bundle(
        world.session,
        opp,
        _market(101),
        _market(102),
        portfolio=world.portfolio,
        max_position_size=100.0,
        circuit_breaker=None,
        current_prices={},
        redis=world.redis,
    )


class TestZeroEdgeCooldown:
    @pytest.mark.asyncio
    async def test_zero_edge_records_rejection(self, world):
        assert await _build(world, _opp(profit=0.0)) is None
        world.record_rejection.assert_awaited_once_with(world.redis, 42)

    @pytest.mark.asyncio
    async def test_positive_edge_does_not_record(self, world):
        bundle = await _build(world, _opp(profit=0.05))
        assert bundle is not None
        world.record_rejection.assert_not_awaited()


class TestStartupGrace:
    @pytest.mark.asyncio
    async def test_blocks_preboot_snapshot_during_grace(self, world):
        world.snapshot.timestamp = world.now - timedelta(seconds=60)
        assert await _build(world, _opp()) is None

    @pytest.mark.asyncio
    async def test_allows_postboot_snapshot_during_grace(self, world):
        world.snapshot.timestamp = world.now + timedelta(seconds=5)
        bundle = await _build(world, _opp())
        assert bundle is not None
        assert len(bundle.legs) == 2

    @pytest.mark.asyncio
    async def test_disabled_grace_allows_preboot_snapshot(self, world, monkeypatch):
        monkeypatch.setattr(settings, "simulator_startup_grace_seconds", 0)
        world.snapshot.timestamp = world.now - timedelta(seconds=60)
        assert await _build(world, _opp()) is not None


class TestPairFlowCap:
    @pytest.mark.asyncio
    async def test_rejects_when_window_flow_exhausted(self, world):
        world.portfolio.record_pair_entry(42, 99.5, at=world.now)
        assert await _build(world, _opp()) is None

    @pytest.mark.asyncio
    async def test_allows_under_cap(self, world):
        world.portfolio.record_pair_entry(42, 50.0, at=world.now)
        assert await _build(world, _opp()) is not None

    @pytest.mark.asyncio
    async def test_exits_bypass_cap(self, world):
        # Long both legs; SELL legs are exits and open no new exposure,
        # so they must pass even with the pair's window flow exhausted.
        world.portfolio.positions = {
            "101:Yes": Decimal("50"),
            "102:Yes": Decimal("50"),
        }
        world.portfolio.record_pair_entry(42, 99.9, at=world.now)
        bundle = await _build(world, _opp(side="SELL", fair=0.4))
        assert bundle is not None

    @pytest.mark.asyncio
    async def test_disabled_cap_allows_everything(self, world, monkeypatch):
        monkeypatch.setattr(settings, "max_pair_weekly_flow", 0.0)
        world.portfolio.record_pair_entry(42, 5000.0, at=world.now)
        assert await _build(world, _opp()) is not None


class TestFlipAwareCap:
    @pytest.mark.asyncio
    async def test_flip_remainder_counts_toward_cap(self, world):
        # Position +1 long each market; SELL 2.5 closes 1 and opens a 1.5
        # short — the remainder must count as new exposure (whole-leg exit
        # classification let flips open unlimited uncapped exposure).
        world.portfolio.positions = {
            "101:Yes": Decimal("1"),
            "102:Yes": Decimal("1"),
        }
        world.portfolio.record_pair_entry(42, 99.9, at=world.now)
        assert await _build(world, _opp(side="SELL", fair=0.4)) is None


class TestPerOutcomeBookSelection:
    @pytest.mark.asyncio
    async def test_vwap_receives_selected_outcome_book(self, world, monkeypatch):
        yes_book = {"bids": [["0.49", "100"]], "asks": [["0.51", "100"]]}
        received = []
        monkeypatch.setattr(
            validation,
            "compute_vwap",
            lambda ob, side, size, mid: (
                received.append(ob),
                {"filled_size": size, "vwap_price": mid, "slippage": 0.0},
            )[1],
        )
        world.snapshot.order_book = {"Yes": yes_book, "No": {"bids": [], "asks": []}}
        bundle = await _build(world, _opp())
        assert bundle is not None
        assert received == [yes_book, yes_book]  # both legs trade "Yes"

    @pytest.mark.asyncio
    async def test_legacy_top_level_book_still_used(self, world, monkeypatch):
        legacy = {"bids": [["0.49", "100"]], "asks": [["0.51", "100"]]}
        received = []
        monkeypatch.setattr(
            validation,
            "compute_vwap",
            lambda ob, side, size, mid: (
                received.append(ob),
                {"filled_size": size, "vwap_price": mid, "slippage": 0.0},
            )[1],
        )
        world.snapshot.order_book = legacy
        assert await _build(world, _opp()) is not None
        assert received == [legacy, legacy]
