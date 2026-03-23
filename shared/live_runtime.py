from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from shared.events import (
    CHANNEL_LIVE_STATUS,
    REDIS_LIVE_KILL_SWITCH_KEY,
    REDIS_LIVE_STATUS_KEY,
    publish,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.lower() in {"1", "true", "yes", "on"})


async def get_live_runtime_status(redis: aioredis.Redis) -> dict[str, Any]:
    raw = await redis.get(REDIS_LIVE_STATUS_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def set_live_runtime_status(
    redis: aioredis.Redis,
    payload: dict[str, Any],
) -> dict[str, Any]:
    status = dict(payload)
    status["updated_at"] = _utc_now_iso()
    await redis.set(REDIS_LIVE_STATUS_KEY, json.dumps(status))
    await publish(redis, CHANNEL_LIVE_STATUS, status)
    return status


async def is_live_kill_switch_enabled(redis: aioredis.Redis) -> bool:
    return _is_truthy(await redis.get(REDIS_LIVE_KILL_SWITCH_KEY))


async def set_live_kill_switch(redis: aioredis.Redis, enabled: bool) -> dict[str, Any]:
    if enabled:
        await redis.set(REDIS_LIVE_KILL_SWITCH_KEY, "1")
    else:
        await redis.delete(REDIS_LIVE_KILL_SWITCH_KEY)

    status = await get_live_runtime_status(redis)
    status["kill_switch"] = enabled
    if enabled:
        status["active"] = False
    return await set_live_runtime_status(redis, status)
