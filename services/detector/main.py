import asyncio

import openai
import structlog

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import get_redis, subscribe, CHANNEL_MARKET_UPDATED
from shared.logging import setup_logging
from services.detector.pipeline import DetectionPipeline

logger = structlog.get_logger()


async def main() -> None:
    setup_logging(settings.log_level)

    await init_db()

    openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    redis = await get_redis()

    pipeline = DetectionPipeline(
        session_factory=SessionFactory,
        openai_client=openai_client,
        redis=redis,
        similarity_threshold=settings.similarity_threshold,
        similarity_top_k=settings.similarity_top_k,
        batch_size=settings.detector_batch_size,
        classifier_model=settings.classifier_model,
    )

    logger.info(
        "detector_started",
        threshold=settings.similarity_threshold,
        top_k=settings.similarity_top_k,
        interval=settings.detection_interval_seconds,
    )

    # Run detection on two triggers:
    # 1. Periodically on a timer
    # 2. Reactively when markets are updated
    await asyncio.gather(
        _periodic_loop(pipeline, settings.detection_interval_seconds),
        _event_loop(pipeline, redis),
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


if __name__ == "__main__":
    asyncio.run(main())
