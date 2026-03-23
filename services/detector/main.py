import asyncio

import openai
import structlog

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import (
    get_redis,
    subscribe,
    CHANNEL_MARKET_UPDATED,
    CHANNEL_SNAPSHOT_CREATED,
)
from shared.logging import setup_logging
from services.detector.pipeline import DetectionPipeline

logger = structlog.get_logger()

# Debounce interval for snapshot-triggered rescans (seconds).
# Collects market IDs from WS snapshots and rescans in batch.
SNAPSHOT_RESCAN_INTERVAL = 10


async def main() -> None:
    setup_logging(settings.log_level)

    await init_db()

    # Build OpenAI client — use classifier_base_url if set (for OpenRouter),
    # otherwise direct OpenAI.
    if settings.classifier_base_url:
        api_key = settings.openrouter_api_key or settings.openai_api_key
        openai_client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=settings.classifier_base_url,
        )
        logger.info("classifier_client", provider="openrouter", base_url=settings.classifier_base_url)
    else:
        openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        logger.info("classifier_client", provider="openai_direct")

    redis = await get_redis()

    pipeline = DetectionPipeline(
        session_factory=SessionFactory,
        openai_client=openai_client,
        redis=redis,
        similarity_threshold=settings.similarity_threshold,
        similarity_top_k=settings.similarity_top_k,
        batch_size=settings.detector_batch_size,
        classifier_model=settings.classifier_model,
        classifier_prompt_adapter=settings.classifier_prompt_adapter,
    )

    logger.info(
        "detector_started",
        threshold=settings.similarity_threshold,
        top_k=settings.similarity_top_k,
        interval=settings.detection_interval_seconds,
        classifier_model=settings.classifier_model,
        classifier_prompt_adapter=settings.classifier_prompt_adapter,
    )

    # Run detection on three triggers:
    # 1. Periodically on a timer (full detection with pgvector search)
    # 2. Reactively when markets are synced (full detection)
    # 3. On price snapshots from WS (lightweight rescan of affected pairs only)
    await asyncio.gather(
        _periodic_loop(pipeline, settings.detection_interval_seconds),
        _event_loop(pipeline, redis),
        _snapshot_rescan_loop(pipeline, redis),
    )


async def _periodic_loop(pipeline: DetectionPipeline, interval: int) -> None:
    """Run detection on a fixed interval."""
    while True:
        try:
            await pipeline.run_once()
        except Exception:
            logger.exception("periodic_detection_error")
        await asyncio.sleep(interval)


async def _event_loop(pipeline: DetectionPipeline, redis) -> None:
    """Run detection when triggered by market sync events."""
    async for event in subscribe(redis, CHANNEL_MARKET_UPDATED):
        if event.get("action") == "sync":
            logger.info("triggered_by_market_sync", count=event.get("count"))
            try:
                await pipeline.run_once()
            except Exception:
                logger.exception("event_triggered_detection_error")


async def _snapshot_rescan_loop(pipeline: DetectionPipeline, redis) -> None:
    """Rescan pairs when WS price snapshots arrive.

    Debounces by collecting market IDs over SNAPSHOT_RESCAN_INTERVAL seconds,
    then triggers a single lightweight rescan for all affected pairs.
    """
    pending_market_ids: set[int] = set()

    # Two concurrent tasks: one collects, one drains
    async def _collect():
        async for event in subscribe(redis, CHANNEL_SNAPSHOT_CREATED):
            # React to snapshots from any source (WS or polling) so
            # graceful degradation rescans pairs even when WS is down.
            market_ids = event.get("market_ids", [])
            pending_market_ids.update(market_ids)

    async def _drain():
        while True:
            await asyncio.sleep(SNAPSHOT_RESCAN_INTERVAL)
            if not pending_market_ids:
                continue
            batch = pending_market_ids.copy()
            pending_market_ids.clear()
            try:
                await pipeline.rescan_by_market_ids(batch)
            except Exception:
                logger.exception("snapshot_rescan_error", market_count=len(batch))

    await asyncio.gather(_collect(), _drain())


if __name__ == "__main__":
    asyncio.run(main())
