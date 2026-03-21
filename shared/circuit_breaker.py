"""Circuit breaker for trading safety.

Trips on: max daily loss, max position per market, max drawdown,
consecutive errors, or manual kill switch via Redis.
Auto-resets after a configurable cooldown period.
"""

import time

import redis.asyncio as aioredis
import structlog

from shared.events import publish

logger = structlog.get_logger()

CHANNEL_CB_TRIPPED = "polyarb:circuit_breaker_tripped"
REDIS_KILL_SWITCH_KEY = "polyarb:kill_switch"


class CircuitBreaker:
    def __init__(
        self,
        redis: aioredis.Redis,
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
        self._trip_reason: str | None = None
        self._trip_time: float = 0.0
        self._consecutive_errors = 0
        self._daily_loss = 0.0
        self._day_start: float = time.time()

    def _reset_daily(self) -> None:
        """Reset daily counters if a new day has started."""
        now = time.time()
        # Reset every 24 hours from the last reset
        if now - self._day_start >= 86400:
            self._daily_loss = 0.0
            self._day_start = now

    @property
    def is_tripped(self) -> bool:
        """Check if circuit breaker is tripped (respecting cooldown auto-reset)."""
        if not self._tripped:
            return False
        # Auto-reset after cooldown
        if time.time() - self._trip_time >= self.cooldown_seconds:
            logger.info(
                "circuit_breaker_auto_reset",
                was_tripped_for=self._trip_reason,
                cooldown_seconds=self.cooldown_seconds,
            )
            self._tripped = False
            self._trip_reason = None
            self._consecutive_errors = 0
            return False
        return True

    async def _trip(self, reason: str, **details) -> None:
        self._tripped = True
        self._trip_reason = reason
        self._trip_time = time.time()
        logger.warning("circuit_breaker_tripped", reason=reason, **details)
        await publish(
            self.redis,
            CHANNEL_CB_TRIPPED,
            {"reason": reason, "timestamp": self._trip_time, **details},
        )

    async def check_kill_switch(self) -> bool:
        """Check Redis for manual kill switch."""
        val = await self.redis.get(REDIS_KILL_SWITCH_KEY)
        if val and val.lower() in ("1", "true", "yes"):
            if not self._tripped or self._trip_reason != "manual_kill_switch":
                await self._trip("manual_kill_switch")
            return True
        return False

    async def pre_trade_check(
        self,
        portfolio,
        market_id: int,
        trade_size: float,
        trade_side: str,
        outcome: str,
        current_prices: dict[str, float] | None = None,
    ) -> tuple[bool, str]:
        """Run all checks before executing a trade.

        Returns (allowed, reason). If allowed is False, the trade should be skipped.
        """
        # Check cooldown state
        if self.is_tripped:
            return False, f"circuit_breaker_tripped:{self._trip_reason}"

        # Manual kill switch
        if await self.check_kill_switch():
            return False, "manual_kill_switch"

        self._reset_daily()

        # Check max daily loss
        if self._daily_loss >= self.max_daily_loss:
            await self._trip(
                "max_daily_loss",
                daily_loss=self._daily_loss,
                limit=self.max_daily_loss,
            )
            return False, "max_daily_loss"

        # Check max position per market — but allow trades that reduce exposure
        key = f"{market_id}:{outcome}"
        existing = float(portfolio.positions.get(key, 0))
        is_reducing = (
            (trade_side == "SELL" and existing > 0)
            or (trade_side == "BUY" and existing < 0)
        )
        if not is_reducing:
            market_exposure = sum(
                abs(float(shares))
                for k, shares in portfolio.positions.items()
                if k.startswith(f"{market_id}:")
            )
            if market_exposure + trade_size > self.max_position_per_market:
                await self._trip(
                    "max_position_per_market",
                    market_id=market_id,
                    current_exposure=market_exposure,
                    trade_size=trade_size,
                    limit=self.max_position_per_market,
                )
                return False, "max_position_per_market"

        # Check max drawdown (include position value via current_prices)
        total_value = portfolio.total_value(current_prices)
        initial = float(portfolio.initial_capital)
        drawdown_pct = ((initial - total_value) / initial) * 100.0
        if drawdown_pct >= self.max_drawdown_pct:
            await self._trip(
                "max_drawdown",
                drawdown_pct=round(drawdown_pct, 2),
                limit=self.max_drawdown_pct,
            )
            return False, "max_drawdown"

        return True, "ok"

    def record_error(self) -> None:
        """Record a consecutive error. Trips if threshold exceeded."""
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.max_consecutive_errors:
            # Can't await here, so set tripped directly
            self._tripped = True
            self._trip_reason = "consecutive_errors"
            self._trip_time = time.time()
            logger.warning(
                "circuit_breaker_tripped",
                reason="consecutive_errors",
                count=self._consecutive_errors,
                limit=self.max_consecutive_errors,
            )

    def record_success(self) -> None:
        """Reset consecutive error counter on success."""
        self._consecutive_errors = 0

    def record_loss(self, amount: float) -> None:
        """Track daily realized loss for the daily loss limit."""
        if amount > 0:
            self._daily_loss += amount
