"""Frozen-pair cooldown shared between simulator, detector, and ingestor.

When the simulator repeatedly rejects a pair's opportunities because their
quoted prices are frozen (see shared.pricing.is_price_frozen), nothing
upstream learns about it: the detector re-creates the opportunity every
cycle (fresh-but-flat snapshots pass its recency checks) and the ingestor
keeps polling the pair's markets because they have "recent opportunities" —
a self-reinforcing loop that can spin every ~10s for days on a dead market.

The simulator records each frozen rejection here; once a pair crosses the
threshold within the rolling window, a cooldown key is set and (a) the
detector stops creating opportunities for the pair and (b) the ingestor
drops it from the opportunity-based poll-inclusion rule. The cooldown
expires on its own; a market that genuinely wakes up re-enters via WS
price updates regardless.

Redis failures are swallowed (fail-open): cooldown bookkeeping must never
block validation or detection.
"""

import structlog
from redis.exceptions import RedisError

from shared.config import settings
from shared.metrics import incr_metric

logger = structlog.get_logger()

REJECT_COUNT_KEY = "polyarb:frozen_reject_count:{pair_id}"
COOLDOWN_KEY = "polyarb:frozen_pair_cooldown:{pair_id}"


async def record_frozen_rejection(redis, pair_id: int) -> bool:
    """Count a frozen-price rejection; start the pair's cooldown at the threshold.

    Returns True only when this call newly started a cooldown (so the caller
    can log the transition exactly once).
    """
    if redis is None or pair_id is None:
        return False
    try:
        count_key = REJECT_COUNT_KEY.format(pair_id=pair_id)
        count = await redis.incr(count_key)
        await incr_metric(redis, "cooldown_rejections_recorded")
        if count == 1:
            await redis.expire(count_key, settings.frozen_pair_reject_window_seconds)
        if count < settings.frozen_pair_reject_threshold:
            return False
        newly_set = await redis.set(
            COOLDOWN_KEY.format(pair_id=pair_id),
            "1",
            ex=settings.frozen_pair_cooldown_seconds,
            nx=True,
        )
        if newly_set:
            await incr_metric(redis, "cooldowns_started")
        return bool(newly_set)
    except RedisError as exc:
        logger.debug("frozen_cooldown_record_failed", pair_id=pair_id, error=str(exc))
        return False


async def is_pair_cooled(redis, pair_id: int) -> bool:
    """Whether a pair is currently in frozen-price cooldown."""
    if redis is None or pair_id is None:
        return False
    try:
        return bool(await redis.exists(COOLDOWN_KEY.format(pair_id=pair_id)))
    except RedisError as exc:
        logger.debug("frozen_cooldown_check_failed", pair_id=pair_id, error=str(exc))
        return False


async def cooled_pair_ids(redis, pair_ids) -> set[int]:
    """Subset of pair_ids currently in cooldown (single MGET round-trip)."""
    ids = [pid for pid in pair_ids if pid is not None]
    if redis is None or not ids:
        return set()
    try:
        values = await redis.mget([COOLDOWN_KEY.format(pair_id=pid) for pid in ids])
        return {pid for pid, val in zip(ids, values) if val is not None}
    except RedisError as exc:
        logger.debug("frozen_cooldown_bulk_check_failed", error=str(exc))
        return set()
