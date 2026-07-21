"""Tests for circuit breaker safety mechanism."""

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.circuit_breaker import CircuitBreaker


def _make_cb(**kwargs):
    """Create CircuitBreaker with mock Redis."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.mget = AsyncMock(return_value=(None, None))
    defaults = dict(
        max_daily_loss=500.0,
        max_position_per_market=200.0,
        max_drawdown_pct=10.0,
        max_consecutive_errors=5,
        cooldown_seconds=300,
    )
    defaults.update(kwargs)
    return CircuitBreaker(redis=redis, **defaults)


def _make_portfolio(cash=10000.0, positions=None, cost_basis=None, initial=10000.0):
    """Create a mock portfolio."""
    p = MagicMock()
    p.cash = Decimal(str(cash))
    p.initial_capital = Decimal(str(initial))
    p.positions = positions or {}
    p.cost_basis = cost_basis or {}
    p.total_value = MagicMock(return_value=cash)
    return p


class TestIsTripped:
    def test_initially_not_tripped(self):
        cb = _make_cb()
        assert cb.is_tripped is False

    def test_tripped_after_record_error(self):
        cb = _make_cb(max_consecutive_errors=3)
        cb.record_error()
        cb.record_error()
        cb.record_error()
        assert cb.is_tripped is True

    def test_auto_reset_after_cooldown(self):
        cb = _make_cb(cooldown_seconds=0)
        cb.record_error()
        cb.record_error()
        cb.record_error()
        cb.record_error()
        cb.record_error()
        # Cooldown is 0 seconds, so should auto-reset
        assert cb.is_tripped is False


class TestRecordError:
    def test_below_threshold_not_tripped(self):
        cb = _make_cb(max_consecutive_errors=5)
        for _ in range(4):
            cb.record_error()
        assert cb.is_tripped is False

    def test_at_threshold_trips(self):
        cb = _make_cb(max_consecutive_errors=5)
        for _ in range(5):
            cb.record_error()
        assert cb.is_tripped is True
        assert cb._trip_reason == "consecutive_errors"


class TestRecordSuccess:
    def test_resets_error_count(self):
        cb = _make_cb(max_consecutive_errors=5)
        cb.record_error()
        cb.record_error()
        cb.record_success()
        cb.record_error()
        cb.record_error()
        assert cb.is_tripped is False


class TestRecordLoss:
    @pytest.mark.asyncio
    async def test_tracks_daily_loss(self):
        cb = _make_cb()
        await cb.record_loss(100.0)
        await cb.record_loss(200.0)
        assert cb._daily_loss == 300.0

    @pytest.mark.asyncio
    async def test_ignores_negative(self):
        cb = _make_cb()
        await cb.record_loss(-50.0)
        assert cb._daily_loss == 0.0


class TestPreTradeCheck:
    @pytest.mark.asyncio
    async def test_allowed_normal(self):
        cb = _make_cb()
        portfolio = _make_portfolio()
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=50, trade_side="BUY", outcome="Yes"
        )
        assert allowed is True
        assert reason == "ok"

    @pytest.mark.asyncio
    async def test_blocked_when_tripped(self):
        cb = _make_cb(max_consecutive_errors=1)
        cb.record_error()
        portfolio = _make_portfolio()
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=50, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert "circuit_breaker_tripped" in reason

    @pytest.mark.asyncio
    async def test_blocked_kill_switch(self):
        cb = _make_cb()
        cb.redis.get = AsyncMock(return_value="1")
        portfolio = _make_portfolio()
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=50, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert reason == "manual_kill_switch"

    @pytest.mark.asyncio
    async def test_blocked_daily_loss(self):
        cb = _make_cb(max_daily_loss=100.0)
        await cb.record_loss(100.0)
        portfolio = _make_portfolio()
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=50, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert reason == "max_daily_loss"

    @pytest.mark.asyncio
    async def test_blocked_max_position(self):
        cb = _make_cb(max_position_per_market=50.0)
        portfolio = _make_portfolio()
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=100, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert reason == "max_position_per_market"

    @pytest.mark.asyncio
    async def test_blocked_drawdown(self):
        cb = _make_cb(max_drawdown_pct=5.0)
        # Portfolio lost 10%: value = 9000 on 10000 initial
        portfolio = _make_portfolio(cash=9000.0, initial=10000.0)
        portfolio.total_value = MagicMock(return_value=9000.0)
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=50, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert reason == "max_drawdown"

    @pytest.mark.asyncio
    async def test_closing_position_allowed(self):
        """Selling into an existing long should not trigger position cap."""
        cb = _make_cb(max_position_per_market=100.0)
        portfolio = _make_portfolio(
            positions={"1:Yes": Decimal("80")},
        )
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=50, trade_side="SELL", outcome="Yes"
        )
        assert allowed is True

    @pytest.mark.asyncio
    async def test_new_outcome_position_cap(self):
        """Buying a new outcome key not yet in positions should still be checked."""
        cb = _make_cb(max_position_per_market=50.0)
        # Market 1 has an existing position for "No", but "Yes" is new
        portfolio = _make_portfolio(
            positions={"1:No": Decimal("30")},
        )
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=40, trade_side="BUY", outcome="Yes"
        )
        # post_market_exposure = 30 (No) + 40 (new Yes) = 70 > 50
        assert allowed is False
        assert reason == "max_position_per_market"


class TestPositionCapLocalRejection:
    """Regression: max_position_per_market must be a local rejection,
    not a global circuit breaker trip.  Changed 2026-03-22."""

    @pytest.mark.asyncio
    async def test_cap_breach_does_not_trip_global_breaker(self):
        """Oversize rejection should NOT set _tripped or cooldown state."""
        cb = _make_cb(max_position_per_market=50.0)
        portfolio = _make_portfolio()

        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=100, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert reason == "max_position_per_market"
        # Critical: breaker itself must NOT be tripped
        assert cb._tripped is False
        assert cb._trip_reason is None

    @pytest.mark.asyncio
    async def test_other_market_trades_after_cap_breach(self):
        """Market A breaches cap → market B should still be allowed."""
        cb = _make_cb(max_position_per_market=50.0)
        portfolio = _make_portfolio(
            positions={"1:Yes": Decimal("40")},
        )

        # Market 1 breaches cap (40 existing + 20 new = 60 > 50)
        allowed_a, _ = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=20, trade_side="BUY", outcome="Yes"
        )
        assert allowed_a is False

        # Market 2 should still trade fine
        allowed_b, reason_b = await cb.pre_trade_check(
            portfolio, market_id=2, trade_size=30, trade_side="BUY", outcome="Yes"
        )
        assert allowed_b is True
        assert reason_b == "ok"


class TestResetDaily:
    @pytest.mark.asyncio
    async def test_daily_reset_on_utc_day_rollover(self):
        cb = _make_cb()
        await cb.record_loss(200.0)
        assert cb._daily_loss == 200.0
        cb._day = "19700101"  # force a rollover
        cb._reset_daily()
        assert cb._daily_loss == 0.0

    @pytest.mark.asyncio
    async def test_no_reset_within_same_utc_day(self):
        cb = _make_cb()
        await cb.record_loss(200.0)
        cb._reset_daily()
        assert cb._daily_loss == 200.0


class TestRedisDurability:
    """Daily loss and trip state must survive a restart (new CB instance)."""

    def _fake_redis(self):
        import fakeredis

        return fakeredis.FakeAsyncRedis(decode_responses=True)

    @pytest.mark.asyncio
    async def test_daily_loss_survives_restart(self):
        redis = self._fake_redis()
        cb1 = CircuitBreaker(redis=redis, max_daily_loss=100.0)
        await cb1.record_loss(60.0)
        await cb1.record_loss(50.0)

        cb2 = CircuitBreaker(redis=redis, max_daily_loss=100.0)  # "restarted"
        portfolio = _make_portfolio()
        allowed, reason = await cb2.pre_trade_check(
            portfolio, market_id=1, trade_size=10, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert reason == "max_daily_loss"

    @pytest.mark.asyncio
    async def test_trip_survives_restart_and_expires(self):
        redis = self._fake_redis()
        cb1 = CircuitBreaker(redis=redis, cooldown_seconds=300)
        await cb1._trip("max_daily_loss", daily_loss=600.0)

        cb2 = CircuitBreaker(redis=redis, cooldown_seconds=300)
        portfolio = _make_portfolio()
        allowed, reason = await cb2.pre_trade_check(
            portfolio, market_id=1, trade_size=10, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert reason == "circuit_breaker_tripped:max_daily_loss"
        # key TTL mirrors the cooldown so expiry = auto-reset across restarts
        assert 0 < await redis.ttl(cb1._trip_key) <= 300

    @pytest.mark.asyncio
    async def test_scoped_keys_isolate_paper_and_live(self):
        # Regression: unscoped keys let $60 of routine paper losses trip a
        # live breaker whose daily limit is $10, and cross-adopt trips.
        redis = self._fake_redis()
        paper = CircuitBreaker(redis=redis, max_daily_loss=500.0, scope="paper")
        live = CircuitBreaker(redis=redis, max_daily_loss=10.0, scope="live")
        await paper.record_loss(60.0)

        portfolio = _make_portfolio()
        allowed, reason = await live.pre_trade_check(
            portfolio, market_id=1, trade_size=1, trade_side="BUY", outcome="Yes"
        )
        assert allowed is True
        assert live._daily_loss == 0.0

        await paper._trip("max_drawdown")
        allowed, _ = await live.pre_trade_check(
            portfolio, market_id=1, trade_size=1, trade_side="BUY", outcome="Yes"
        )
        assert allowed is True

    @pytest.mark.asyncio
    async def test_redis_down_falls_back_to_memory(self):
        cb = _make_cb(max_daily_loss=100.0)
        from redis.exceptions import RedisError

        cb.redis.mget = AsyncMock(side_effect=RedisError("down"))
        cb.redis.incrbyfloat = AsyncMock(side_effect=RedisError("down"))
        await cb.record_loss(150.0)  # memory still accumulates
        portfolio = _make_portfolio()
        allowed, reason = await cb.pre_trade_check(
            portfolio, market_id=1, trade_size=10, trade_side="BUY", outcome="Yes"
        )
        assert allowed is False
        assert reason == "max_daily_loss"
