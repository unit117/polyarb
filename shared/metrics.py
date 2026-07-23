"""Lightweight operational counters in Redis, daily-bucketed.

Phase 5 of the remediation plan: every safety mechanism shipped in phases
2-4 (cooldowns, flow cap, startup grace, retry policy, partial-row guard,
trade tape) previously emitted only log lines — recurrence of a flaw was
invisible until someone read logs. These counters make them queryable via
the dashboard's /metrics/observability endpoint.

Design: one Redis hash per UTC day (polyarb:metrics:{YYYYMMDD}), fields
incremented in place, 8-day TTL. Fail-open like frozen_cooldown — metrics
must never break the pipeline they observe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from redis.exceptions import RedisError

logger = structlog.get_logger()

METRICS_KEY = "polyarb:metrics:{day}"
METRICS_TTL = 8 * 86400


def _day(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).strftime("%Y%m%d")


async def incr_metric(redis, name: str, by: int = 1) -> None:
    """Increment today's counter `name` (fail-open)."""
    if redis is None:
        return
    try:
        key = METRICS_KEY.format(day=_day())
        await redis.hincrby(key, name, by)
        await redis.expire(key, METRICS_TTL)
    except Exception as exc:  # noqa: BLE001 — metrics must never break the pipeline
        logger.debug("metric_incr_failed", name=name, error=str(exc))


async def set_gauge(redis, name: str, value: float) -> None:
    """Set today's gauge `name` to the latest value (fail-open)."""
    if redis is None:
        return
    try:
        key = METRICS_KEY.format(day=_day())
        await redis.hset(key, name, value)
        await redis.expire(key, METRICS_TTL)
    except Exception as exc:  # noqa: BLE001 — metrics must never break the pipeline
        logger.debug("metric_gauge_failed", name=name, error=str(exc))


async def get_metrics(redis, days: int = 7) -> dict[str, dict[str, float]]:
    """Counters for the last `days` UTC days: {YYYYMMDD: {name: value}}."""
    out: dict[str, dict[str, float]] = {}
    if redis is None:
        return out
    now = datetime.now(timezone.utc)
    for offset in range(days):
        day = _day(now - timedelta(days=offset))
        try:
            raw = await redis.hgetall(METRICS_KEY.format(day=day))
        except Exception:  # noqa: BLE001
            continue
        if not raw:
            continue
        fields: dict[str, float] = {}
        for k, v in raw.items():
            name = k.decode() if isinstance(k, bytes) else str(k)
            try:
                val = float(v.decode() if isinstance(v, bytes) else v)
            except (ValueError, TypeError):
                continue
            fields[name] = int(val) if val == int(val) else val
        out[day] = fields
    return out
