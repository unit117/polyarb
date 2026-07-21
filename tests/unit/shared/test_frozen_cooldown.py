"""Tests for the frozen-pair cooldown (shared/frozen_cooldown.py)."""

import pytest
from redis.exceptions import RedisError

from shared.config import settings
from shared.frozen_cooldown import (
    COOLDOWN_KEY,
    REJECT_COUNT_KEY,
    cooled_pair_ids,
    is_pair_cooled,
    record_frozen_rejection,
)


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key, ttl):
        self.ttls[key] = ttl
        return True

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def mget(self, keys):
        return [self.store.get(k) for k in keys]


class BrokenRedis:
    """Every operation raises, to exercise the fail-open paths."""

    async def incr(self, key):
        raise RedisError("down")

    async def exists(self, key):
        raise RedisError("down")

    async def mget(self, keys):
        raise RedisError("down")


class TestRecordFrozenRejection:
    @pytest.mark.asyncio
    async def test_below_threshold_no_cooldown(self):
        r = FakeRedis()
        for _ in range(settings.frozen_pair_reject_threshold - 1):
            assert await record_frozen_rejection(r, 42) is False
        assert not await is_pair_cooled(r, 42)

    @pytest.mark.asyncio
    async def test_threshold_starts_cooldown_exactly_once(self):
        r = FakeRedis()
        results = [
            await record_frozen_rejection(r, 42)
            for _ in range(settings.frozen_pair_reject_threshold + 2)
        ]
        # Only the rejection that crossed the threshold reports "newly started"
        assert results.count(True) == 1
        assert results[settings.frozen_pair_reject_threshold - 1] is True
        assert await is_pair_cooled(r, 42)
        # Cooldown key carries the configured TTL
        key = COOLDOWN_KEY.format(pair_id=42)
        assert r.ttls[key] == settings.frozen_pair_cooldown_seconds

    @pytest.mark.asyncio
    async def test_count_window_expiry_set_on_first_increment(self):
        r = FakeRedis()
        await record_frozen_rejection(r, 7)
        key = REJECT_COUNT_KEY.format(pair_id=7)
        assert r.ttls[key] == settings.frozen_pair_reject_window_seconds

    @pytest.mark.asyncio
    async def test_pairs_are_independent(self):
        r = FakeRedis()
        for _ in range(settings.frozen_pair_reject_threshold):
            await record_frozen_rejection(r, 1)
        assert await is_pair_cooled(r, 1)
        assert not await is_pair_cooled(r, 2)

    @pytest.mark.asyncio
    async def test_none_redis_or_pair_is_noop(self):
        assert await record_frozen_rejection(None, 42) is False
        assert await record_frozen_rejection(FakeRedis(), None) is False


class TestFailOpen:
    @pytest.mark.asyncio
    async def test_redis_errors_never_raise(self):
        r = BrokenRedis()
        assert await record_frozen_rejection(r, 42) is False
        assert await is_pair_cooled(r, 42) is False
        assert await cooled_pair_ids(r, [1, 2, 3]) == set()


class TestCooledPairIds:
    @pytest.mark.asyncio
    async def test_returns_only_cooled_subset(self):
        r = FakeRedis()
        for _ in range(settings.frozen_pair_reject_threshold):
            await record_frozen_rejection(r, 10)
            await record_frozen_rejection(r, 30)
        assert await cooled_pair_ids(r, [10, 20, 30, None]) == {10, 30}

    @pytest.mark.asyncio
    async def test_empty_input(self):
        assert await cooled_pair_ids(FakeRedis(), []) == set()
        assert await cooled_pair_ids(None, [1]) == set()
