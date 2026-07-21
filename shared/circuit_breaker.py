"""Circuit breaker for trading safety.

Trips on: max daily loss, max position per market, max drawdown,
consecutive errors, or manual kill switch via Redis.
Auto-resets after a configurable cooldown period.

Daily-loss and trip state are mirrored to Redis so they survive service
restarts: before this, the in-memory accumulator reset on every boot, so a
loss cluster spanning a restart could never trip max_daily_loss, and a trip
was silently forgotten. Redis failures fall back to the in-memory state
(fail-open, consistent with shared.frozen_cooldown) — the breaker must
never block trading on Redis being down, only on real limits.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog
from redis.exceptions import RedisError

from shared.events import publish

logger = structlog.get_logger()

CHANNEL_CB_TRIPPED = "polyarb:circuit_breaker_tripped"
REDIS_KILL_SWITCH_KEY = "polyarb:kill_switch"  # intentionally global across books
REDIS_TRIP_KEY = "polyarb:cb:{scope}:trip"
REDIS_DAILY_LOSS_KEY = "polyarb:cb:{scope}:daily_loss:{day}"
DAILY_LOSS_KEY_TTL = 172800  # 2 days; the key is UTC-date-stamped


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _as_str(val) -> str | None:
    if val is None:
        return None
    return val.decode() if isinstance(val, (bytes, bytearray)) else str(val)


class CircuitBreaker:
    def __init__(
        self,
        redis: aioredis.Redis,
        max_daily_loss: float = 500.0,
        max_position_per_market: float = 200.0,
        max_drawdown_pct: float = 10.0,
        max_consecutive_errors: int = 5,
        cooldown_seconds: int = 300,
        scope: str = "paper",
    ):
        # The paper and live books run separate breakers with different
        # limits in the same process — their Redis state must not mix.
        self.redis = redis
        self.scope = scope
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
        self._day: str = _utc_day()

    @property
    def _trip_key(self) -> str:
        return REDIS_TRIP_KEY.format(scope=self.scope)

    def _loss_key(self, day: str) -> str:
        return REDIS_DAILY_LOSS_KEY.format(scope=self.scope, day=day)

    def _reset_daily(self) -> None:
        """Reset the in-memory daily counter when the UTC day rolls over."""
        today = _utc_day()
        if today != self._day:
            self._daily_loss = 0.0
            self._day = today

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
        try:
            # TTL doubles as the auto-reset across restarts: key gone = reset.
            await self.redis.set(self._trip_key, reason, ex=self.cooldown_seconds)
        except RedisError as exc:
            logger.debug("cb_trip_persist_failed", error=str(exc))
        try:
            await publish(
                self.redis,
                CHANNEL_CB_TRIPPED,
                {"reason": reason, "timestamp": self._trip_time, **details},
            )
        except RedisError as exc:
            logger.debug("cb_trip_publish_failed", error=str(exc))

    async def _refresh_from_redis(self) -> None:
        """Adopt Redis-persisted trip/daily-loss state (fail-open on errors).

        Redis is authoritative when reachable: it survives restarts and is
        shared across processes. In-memory state remains the fallback and
        still covers the sync-only paths (record_error).
        """
        try:
            trip_val, loss_val = await self.redis.mget(
                self._trip_key,
                self._loss_key(_utc_day()),
            )
        except RedisError as exc:
            logger.debug("cb_refresh_failed", error=str(exc))
            return
        reason = _as_str(trip_val)
        # is_tripped (not the raw flag) so a locally-expired trip is
        # normalized first — otherwise a fresh trip key written by another
        # process would be skipped and one trade could slip through.
        if reason is not None and not self.is_tripped:
            # A prior process (or pre-restart self) tripped; adopt it. The
            # remaining TTL is unknown, so anchor the memory cooldown now —
            # worst case the memory trip outlives the key by one cooldown.
            self._tripped = True
            self._trip_reason = reason
            self._trip_time = time.time()
        loss_str = _as_str(loss_val)
        if loss_str is not None:
            try:
                self._daily_loss = max(self._daily_loss, float(loss_str))
            except ValueError:
                pass

    async def check_kill_switch(self) -> bool:
        """Check Redis for manual kill switch (fail-open on Redis errors)."""
        try:
            val = await self.redis.get(REDIS_KILL_SWITCH_KEY)
        except RedisError as exc:
            logger.debug("cb_kill_switch_check_failed", error=str(exc))
            return False
        val = _as_str(val)
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
        self._reset_daily()
        await self._refresh_from_redis()

        # Check cooldown state
        if self.is_tripped:
            return False, f"circuit_breaker_tripped:{self._trip_reason}"

        # Manual kill switch
        if await self.check_kill_switch():
            return False, "manual_kill_switch"

        # Check max daily loss
        if self._daily_loss >= self.max_daily_loss:
            await self._trip(
                "max_daily_loss",
                daily_loss=self._daily_loss,
                limit=self.max_daily_loss,
            )
            return False, "max_daily_loss"

        # Check max position per market.
        # Compute what exposure will be AFTER the trade to correctly handle
        # trades that partially close and partially open (e.g. BUY 150
        # against a short of 100 → closes 100, opens 50 new long).
        key = f"{market_id}:{outcome}"
        existing = float(portfolio.positions.get(key, 0))

        if trade_side == "BUY":
            post_position = existing + trade_size
        else:
            post_position = existing - trade_size

        # Only check the cap if post-trade exposure is larger than current
        if abs(post_position) > abs(existing):
            # Sum all outcome positions for this market after the trade
            post_market_exposure = 0.0
            for k, shares in portfolio.positions.items():
                if not k.startswith(f"{market_id}:"):
                    continue
                if k == key:
                    post_market_exposure += abs(post_position)
                else:
                    post_market_exposure += abs(float(shares))
            # If key wasn't in positions yet, add it
            if key not in portfolio.positions:
                post_market_exposure += abs(post_position)

            if post_market_exposure > self.max_position_per_market:
                # Local rejection only — don't trip the global breaker.
                # Other markets can still trade; only this market is capped.
                logger.info(
                    "position_cap_rejected",
                    market_id=market_id,
                    post_market_exposure=post_market_exposure,
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
            # Can't await here, so set tripped directly (memory-only trip;
            # Redis persistence would need an event loop handle)
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

    async def record_loss(self, amount: float) -> None:
        """Track daily realized loss for the daily loss limit.

        Persisted to a UTC-date-stamped Redis key so the accumulator
        survives restarts; the date stamp anchors the reset to UTC
        midnight (a new day simply reads a fresh key).
        """
        if amount <= 0:
            return
        self._reset_daily()
        self._daily_loss += amount
        try:
            key = self._loss_key(self._day)
            await self.redis.incrbyfloat(key, amount)
            await self.redis.expire(key, DAILY_LOSS_KEY_TTL)
        except RedisError as exc:
            logger.debug("cb_loss_persist_failed", error=str(exc))
