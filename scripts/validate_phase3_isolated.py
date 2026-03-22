import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

# --- COPIED CLASSES FROM SOURCE ---

class CircuitBreaker:
    def __init__(
        self,
        redis,
        max_daily_loss: float = 500.0,
        max_position_per_market: float = 200.0,
        max_drawdown_pct: float = 10.0,
        max_consecutive_errors: int = 5,
        cooldown_seconds: int = 300,
    ):
        self.redis = redis
        self.max_daily_loss = max_daily_loss
        self.max_position_per_market = max_position_per_market
        self.max_drawdown_pct = max_drawdown_pct
        self.max_consecutive_errors = max_consecutive_errors
        self.cooldown_seconds = cooldown_seconds

        self._tripped = False
        self._trip_reason = None
        self._trip_time = 0.0
        self._consecutive_errors = 0
        self._daily_loss = 0.0
        self._day_start = time.time()

    def _reset_daily(self):
        now = time.time()
        if now - self._day_start >= 86400:
            self._daily_loss = 0.0
            self._day_start = now

    @property
    def is_tripped(self):
        if not self._tripped:
            return False
        if time.time() - self._trip_time >= self.cooldown_seconds:
            self._tripped = False
            self._trip_reason = None
            self._consecutive_errors = 0
            return False
        return True

    async def _trip(self, reason, **details):
        self._tripped = True
        self._trip_reason = reason
        self._trip_time = time.time()

    async def check_kill_switch(self):
        val = await self.redis.get("polyarb:kill_switch")
        if val and str(val).lower() in ("1", "true", "yes"):
            if not self._tripped or self._trip_reason != "manual_kill_switch":
                await self._trip("manual_kill_switch")
            return True
        return False

    async def pre_trade_check(self, portfolio, market_id: int, trade_size: float):
        if self.is_tripped:
            return False, f"circuit_breaker_tripped:{self._trip_reason}"
        if await self.check_kill_switch():
            return False, "manual_kill_switch"
        self._reset_daily()
        if self._daily_loss >= self.max_daily_loss:
            await self._trip("max_daily_loss")
            return False, "max_daily_loss"
        market_exposure = sum(abs(float(shares)) for key, shares in portfolio.positions.items() if key.startswith(f"{market_id}:"))
        if market_exposure + trade_size > self.max_position_per_market:
            await self._trip("max_position_per_market")
            return False, "max_position_per_market"
        total_value = portfolio.total_value()
        initial = float(portfolio.initial_capital)
        drawdown_pct = ((initial - total_value) / initial) * 100.0
        if drawdown_pct >= self.max_drawdown_pct:
            await self._trip("max_drawdown")
            return False, "max_drawdown"
        return True, "ok"

    def record_error(self):
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.max_consecutive_errors:
            self._tripped = True
            self._trip_reason = "consecutive_errors"
            self._trip_time = time.time()

    def record_success(self):
        self._consecutive_errors = 0

    def record_loss(self, amount: float):
        if amount > 0:
            self._daily_loss += amount

class Portfolio:
    def __init__(self, initial_capital: float):
        self.initial_capital = Decimal(str(initial_capital))
        self.cash = Decimal(str(initial_capital))
        self.positions = {}
    def total_value(self):
        return float(self.cash) # Simplified for test

# --- MOCK REDIS ---
class MockRedis:
    def __init__(self):
        self.data = {}
    async def get(self, key):
        return self.data.get(key)
    async def set(self, key, value):
        self.data[key] = value

# --- TEST SUITE ---
async def test_circuit_breaker():
    print("--- Testing CircuitBreaker ---")
    redis = MockRedis()
    cb = CircuitBreaker(
        redis=redis,
        max_daily_loss=100.0,
        max_position_per_market=50.0,
        max_drawdown_pct=10.0,
        max_consecutive_errors=3,
        cooldown_seconds=1
    )

    portfolio = Portfolio(1000.0)
    portfolio.positions = {"1:Yes": Decimal("40.0")}
    
    # 1. Position Limit
    allowed, reason = await cb.pre_trade_check(portfolio, market_id=1, trade_size=20.0)
    print(f"Position limit check (should fail): allowed={allowed}, reason={reason}")
    assert not allowed
    assert cb.is_tripped

    # Cooldown
    await asyncio.sleep(1.1)
    assert not cb.is_tripped

    # 2. Daily Loss
    cb.record_loss(150.0)
    allowed, reason = await cb.pre_trade_check(portfolio, market_id=2, trade_size=10.0)
    print(f"Daily loss check (should fail): allowed={allowed}, reason={reason}")
    assert not allowed

    # 3. Consecutive Errors
    cb._tripped = False
    cb._trip_reason = None
    cb.record_error(); cb.record_error(); cb.record_error()
    print(f"Consecutive errors check: is_tripped={cb.is_tripped}")
    assert cb.is_tripped

    # 4. Kill Switch
    await redis.set("polyarb:kill_switch", "true")
    await asyncio.sleep(1.1)
    allowed, reason = await cb.pre_trade_check(portfolio, market_id=3, trade_size=1.0)
    print(f"Kill switch check: allowed={allowed}, reason={reason}")
    assert not allowed

def test_kelly_sizing():
    print("\n--- Testing Kelly Sizing (Logic Check) ---")
    max_position_size = 200.0
    def get_size(net_profit, total_value=1000.0, initial_capital=1000.0):
        # Kelly logic from services/simulator/pipeline.py
        kelly_fraction = min(net_profit * 0.5, 1.0)
        drawdown = 1.0 - (total_value / float(initial_capital))
        if drawdown > 0.05:
            drawdown_scale = max(0.5, 1.0 - (drawdown - 0.05) / 0.10)
            kelly_fraction *= drawdown_scale
        return kelly_fraction * max_position_size

    s1 = get_size(0.10)
    print(f"Size for 10c edge (expected 10.0): {s1}")
    assert abs(s1 - 10.0) < 1e-9

    s2 = get_size(0.20)
    print(f"Size for 20c edge (expected 20.0): {s2}")
    assert abs(s2 - 20.0) < 1e-9

    s3 = get_size(0.20, total_value=900.0) # 10% drawdown
    print(f"Size for 20c edge at 10% drawdown (expected 10.0): {s3}")
    assert abs(s3 - 10.0) < 1e-9

async def test_dedup():
    print("\n--- Testing In-Flight Dedup (Logic Check) ---")
    _in_flight = set()
    async def simulate_opportunity(opp_id):
        if opp_id in _in_flight:
            return {"status": "skipped", "reason": "in_flight"}
        _in_flight.add(opp_id)
        try:
            await asyncio.sleep(0.5)
            return {"status": "simulated"}
        finally:
            _in_flight.discard(opp_id)

    task1 = asyncio.create_task(simulate_opportunity(123))
    await asyncio.sleep(0.1)
    res2 = await simulate_opportunity(123)
    print(f"Duplicate ID response: {res2}")
    assert res2["status"] == "skipped"
    
    await task1
    assert 123 not in _in_flight
    print("Deduplication logic works.")

if __name__ == "__main__":
    asyncio.run(test_circuit_breaker())
    test_kelly_sizing()
    asyncio.run(test_dedup())
    print("\nAll Phase 3 logic validations PASSED.")
