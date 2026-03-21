import json
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from shared.config import settings

CHANNEL_MARKET_UPDATED = "polyarb:market_updated"
CHANNEL_SNAPSHOT_CREATED = "polyarb:snapshot_created"
CHANNEL_PAIR_DETECTED = "polyarb:pair_detected"
CHANNEL_ARBITRAGE_FOUND = "polyarb:arbitrage_found"
CHANNEL_OPTIMIZATION_COMPLETE = "polyarb:optimization_complete"
CHANNEL_TRADE_EXECUTED = "polyarb:trade_executed"
CHANNEL_PORTFOLIO_UPDATED = "polyarb:portfolio_updated"
CHANNEL_MARKET_RESOLVED = "polyarb:market_resolved"


async def get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def publish(r: aioredis.Redis, channel: str, payload: dict) -> None:
    await r.publish(channel, json.dumps(payload))


async def subscribe(
    r: aioredis.Redis, channel: str
) -> AsyncGenerator[dict, None]:
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
