"""Tests for the Phase-5 daily-bucketed Redis metrics."""

import pytest

from shared.metrics import get_metrics, incr_metric, set_gauge


def _fake_redis():
    import fakeredis

    return fakeredis.FakeAsyncRedis(decode_responses=True)


class TestMetrics:
    @pytest.mark.asyncio
    async def test_incr_and_read_back(self):
        redis = _fake_redis()
        await incr_metric(redis, "cooldowns_started")
        await incr_metric(redis, "cooldowns_started", by=2)
        await set_gauge(redis, "poll_cycle_seconds", 12.5)
        out = await get_metrics(redis, days=1)
        assert len(out) == 1
        (day_fields,) = out.values()
        assert day_fields["cooldowns_started"] == 3
        assert day_fields["poll_cycle_seconds"] == 12.5

    @pytest.mark.asyncio
    async def test_none_redis_is_noop(self):
        await incr_metric(None, "x")
        await set_gauge(None, "x", 1)
        assert await get_metrics(None) == {}

    @pytest.mark.asyncio
    async def test_redis_error_fail_open(self):
        from unittest.mock import AsyncMock

        from redis.exceptions import RedisError

        redis = AsyncMock()
        redis.hincrby = AsyncMock(side_effect=RedisError("down"))
        redis.hgetall = AsyncMock(side_effect=RedisError("down"))
        await incr_metric(redis, "x")  # must not raise
        assert await get_metrics(redis, days=2) == {}
