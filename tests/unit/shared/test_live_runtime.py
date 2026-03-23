from __future__ import annotations

import pytest

from shared.live_runtime import (
    get_live_runtime_status,
    is_live_kill_switch_enabled,
    set_live_kill_switch,
    set_live_runtime_status,
)


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str):
        self.store[key] = value

    async def delete(self, key: str):
        self.store.pop(key, None)


@pytest.mark.asyncio
async def test_live_runtime_status_round_trip(monkeypatch):
    published: list[tuple[str, dict]] = []

    async def fake_publish(_redis, channel: str, payload: dict) -> None:
        published.append((channel, payload))

    monkeypatch.setattr("shared.live_runtime.publish", fake_publish)

    redis = FakeRedis()
    status = await set_live_runtime_status(
        redis,
        {
            "enabled": True,
            "dry_run": True,
            "active": True,
        },
    )

    stored = await get_live_runtime_status(redis)
    assert stored["enabled"] is True
    assert stored["dry_run"] is True
    assert stored["active"] is True
    assert "updated_at" in status
    assert published and published[0][0] == "polyarb:live_status"


@pytest.mark.asyncio
async def test_live_kill_switch_updates_status(monkeypatch):
    async def fake_publish(_redis, _channel: str, _payload: dict) -> None:
        return None

    monkeypatch.setattr("shared.live_runtime.publish", fake_publish)

    redis = FakeRedis()
    await set_live_runtime_status(
        redis,
        {
            "enabled": True,
            "dry_run": False,
            "active": True,
        },
    )

    status = await set_live_kill_switch(redis, True)
    assert await is_live_kill_switch_enabled(redis) is True
    assert status["kill_switch"] is True
    assert status["active"] is False

    status = await set_live_kill_switch(redis, False)
    assert await is_live_kill_switch_enabled(redis) is False
    assert status["kill_switch"] is False
