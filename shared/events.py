import json
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from shared.config import settings

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
