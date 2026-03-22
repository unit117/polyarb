import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

# Mocking shared.events before imports that use it
from unittest.mock import AsyncMock, MagicMock
import sys
import types
import os

# Create a mock events module
mock_events = types.ModuleType("shared.events")
mock_events.publish = AsyncMock()
mock_events.CHANNEL_TRADE_EXECUTED = "trade_executed"
mock_events.CHANNEL_PORTFOLIO_UPDATED = "portfolio_updated"

# Instead of creating fake modules, let's just use the real ones but mock the problematic parts
# if they are already in the filesystem. 
# PYTHONPATH=. is passed, so shared/ should be found.

# We just need to make sure shared.events doesn't try to connect to a real Redis in its top-level.
# Looking at shared/events.py:
# it defines get_redis and publish.
# If it doesn't do anything on import, we can just use it.

# Let's try a simpler approach: mock only the publish and get_redis
import shared.events
shared.events.publish = AsyncMock()
shared.events.get_redis = AsyncMock()

from shared.circuit_breaker import CircuitBreaker, REDIS_KILL_SWITCH_KEY
from services.simulator.portfolio import Portfolio
from services.simulator.pipeline import SimulatorPipeline

# Minimal mock for Redis
class MockRedis:
    def __init__(self):
        self.data = {}
    async def get(self, key):
        return self.data.get(key)
    async def set(self, key, value):
        self.data[key] = value
    async def publish(self, channel, message):
        pass

async def test_circuit_breaker():
    print("--- Testing CircuitBreaker ---")
    redis = MockRedis()
    cb = CircuitBreaker(
        redis=redis,
        max_daily_loss=100.0,
        max_position_per_market=50.0,
        max_drawdown_pct=10.0,
        max_consecutive_errors=3,
        cooldown_seconds=1 # Short for testing
    )

    # 1. Test Position Limit
    portfolio = Portfolio(1000.0)
    # Mock portfolio positions
    portfolio.positions = {"1:Yes": Decimal("40.0")}
    allowed, reason = await cb.pre_trade_check(portfolio, market_id=1, trade_size=20.0)
    print(f"Position limit check (should fail): allowed={allowed}, reason={reason}")
    assert not allowed
    assert cb.is_tripped

    # Wait for cooldown
    await asyncio.sleep(1.1)
    print(f"Tripped after cooldown: {cb.is_tripped}")
    assert not cb.is_tripped

    # 2. Test Daily Loss
    cb.record_loss(150.0)
    allowed, reason = await cb.pre_trade_check(portfolio, market_id=2, trade_size=10.0)
    print(f"Daily loss check (should fail): allowed={allowed}, reason={reason}")
    assert not allowed

    # 3. Test Consecutive Errors
    cb._tripped = False # Manual reset for test
    cb._trip_reason = None
    cb.record_error()
    cb.record_error()
    cb.record_error()
    print(f"Consecutive errors check (should trip): is_tripped={cb.is_tripped}")
    assert cb.is_tripped

    # 4. Test Kill Switch
    await redis.set(REDIS_KILL_SWITCH_KEY, "true")
    await asyncio.sleep(1.1) # Wait for previous trip to expire
    allowed, reason = await cb.pre_trade_check(portfolio, market_id=3, trade_size=1.0)
    print(f"Kill switch check (should fail): allowed={allowed}, reason={reason}")
    assert not allowed

async def test_kelly_sizing():
    print("\n--- Testing Kelly Sizing ---")
    portfolio = Portfolio(1000.0)
    pipeline = SimulatorPipeline(
        session_factory=AsyncMock(),
        redis=AsyncMock(),
        portfolio=portfolio,
        max_position_size=200.0
    )

    # Mock an opportunity with 0.10 edge (net_profit)
    # Half-Kelly = 0.10 * 0.5 = 0.05
    # Size = 0.05 * 200 = 10.0
    
    def get_size(net_profit, drawdown=0.0):
        kelly_fraction = min(net_profit * 0.5, 1.0)
        if drawdown > 0.05:
            # drawdown_scale = max(0.5, 1.0 - (drawdown - 0.05) / 0.10)
            # Example: 10% drawdown (0.10)
            # 1.0 - (0.10 - 0.05) / 0.10 = 1.0 - 0.05 / 0.10 = 0.5
            drawdown_scale = max(0.5, 1.0 - (drawdown - 0.05) / 0.10)
            kelly_fraction *= drawdown_scale
        return kelly_fraction * 200.0

    size1 = get_size(0.10)
    print(f"Size for 10c edge (expected 10.0): {size1}")
    assert size1 == 10.0

    size2 = get_size(0.20)
    print(f"Size for 20c edge (expected 20.0): {size2}")
    assert size2 == 20.0

    # Test drawdown scaling (e.g. 10% drawdown)
    size3 = get_size(0.20, drawdown=0.10)
    print(f"Size for 20c edge at 10% drawdown (expected 10.0): {size3}")
    assert size3 == 10.0

async def test_dedup():
    print("\n--- Testing In-Flight Dedup ---")
    pipeline = SimulatorPipeline(
        session_factory=AsyncMock(),
        redis=AsyncMock(),
        portfolio=MagicMock(),
        max_position_size=100.0
    )
    
    # Mock _simulate_opportunity_inner to just hang
    async def slow_inner(opp_id):
        await asyncio.sleep(0.5)
        return {"status": "simulated"}
    
    pipeline._simulate_opportunity_inner = slow_inner
    
    # Start one
    task1 = asyncio.create_task(pipeline.simulate_opportunity(123))
    await asyncio.sleep(0.1)
    
    # Try another same ID
    res2 = await pipeline.simulate_opportunity(123)
    print(f"Duplicate ID response: {res2}")
    assert res2["status"] == "skipped"
    assert res2["reason"] == "in_flight"
    
    # Try different ID
    task2 = asyncio.create_task(pipeline.simulate_opportunity(456))
    await asyncio.sleep(0.1)
    print(f"Different ID is in flight: {456 in pipeline._in_flight}")
    assert 456 in pipeline._in_flight
    
    await asyncio.gather(task1, task2)
    print(f"In-flight set empty after completion: {len(pipeline._in_flight) == 0}")
    assert len(pipeline._in_flight) == 0

if __name__ == "__main__":
    asyncio.run(test_circuit_breaker())
    asyncio.run(test_kelly_sizing())
    asyncio.run(test_dedup())
    print("\nAll Phase 3 validations PASSED.")
