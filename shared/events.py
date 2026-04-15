import json
from collections.abc import AsyncGenerator
from typing import TypeVar

import redis.asyncio as aioredis
from pydantic import BaseModel

from shared.config import settings

T = TypeVar("T", bound=BaseModel)

# Channel payload schemas (all payloads are JSON dicts):
#
# MARKET_UPDATED:        {action: "sync", count: int}
# SNAPSHOT_CREATED:      {count: int, source: "websocket"|"polling", market_ids: [int]}
# PAIR_DETECTED:         {pair_id, market_a_id, market_b_id, dependency_type, confidence}
# ARBITRAGE_FOUND:       {opportunity_id, pair_id, type, theoretical_profit}
# OPTIMIZATION_COMPLETE: {opportunity_id, pair_id, status, iterations, bregman_gap,
#                         estimated_profit, n_trades, converged}
# TRADE_EXECUTED:        {trade_id, opportunity_id, market_id, outcome, side,
#                         size, vwap_price, slippage}
# PORTFOLIO_UPDATED:     {cash, positions, total_value, realized_pnl, unrealized_pnl,
#                         total_trades, settled_trades, winning_trades}
# MARKET_RESOLVED:       {market_id, resolved_outcome, source, price?}
# LIVE_STATUS:           {enabled, dry_run, active, kill_switch, last_heartbeat, ...}

CHANNEL_MARKET_UPDATED = "polyarb:market_updated"
CHANNEL_SNAPSHOT_CREATED = "polyarb:snapshot_created"
CHANNEL_PAIR_DETECTED = "polyarb:pair_detected"
CHANNEL_ARBITRAGE_FOUND = "polyarb:arbitrage_found"
CHANNEL_OPTIMIZATION_COMPLETE = "polyarb:optimization_complete"
CHANNEL_TRADE_EXECUTED = "polyarb:trade_executed"
CHANNEL_PORTFOLIO_UPDATED = "polyarb:portfolio_updated"
CHANNEL_MARKET_RESOLVED = "polyarb:market_resolved"
CHANNEL_LIVE_STATUS = "polyarb:live_status"

REDIS_LIVE_STATUS_KEY = "polyarb:live_status"
REDIS_LIVE_KILL_SWITCH_KEY = "polyarb:live_kill_switch"


async def get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def publish(r: aioredis.Redis, channel: str, payload: dict) -> None:
    await r.publish(channel, json.dumps(payload))


async def publish_event(r: aioredis.Redis, channel: str, event: BaseModel) -> None:
    """Typed publish — serializes a Pydantic model to the channel."""
    await r.publish(channel, event.model_dump_json())


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


async def subscribe_typed(
    r: aioredis.Redis, channel: str, model: type[T]
) -> AsyncGenerator[T, None]:
    """Typed subscribe — validates each message into a Pydantic model."""
    async for raw in subscribe(r, channel):
        yield model.model_validate(raw)
