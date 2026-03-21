import asyncio

import structlog

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import get_redis, subscribe, CHANNEL_ARBITRAGE_FOUND
from shared.logging import setup_logging
from services.optimizer.pipeline import OptimizerPipeline

logger = structlog.get_logger()


async def main() -> None:
    setup_logging(settings.log_level)

    await init_db()

    redis = await get_redis()

    pipeline = OptimizerPipeline(
        session_factory=SessionFactory,
        redis=redis,
        max_iterations=settings.fw_max_iterations,
        gap_tolerance=settings.fw_gap_tolerance,
        ip_timeout_ms=settings.fw_ip_timeout_ms,
        fee_rate=settings.fee_rate,
        min_edge=settings.optimizer_min_edge,
        skip_conditional=settings.optimizer_skip_conditional,
    )

    logger.info(
        "optimizer_started",
        max_iterations=settings.fw_max_iterations,
        gap_tolerance=settings.fw_gap_tolerance,
        ip_timeout_ms=settings.fw_ip_timeout_ms,
        min_edge=settings.optimizer_min_edge,
        skip_conditional=settings.optimizer_skip_conditional,
        interval=settings.optimizer_interval_seconds,
    )

    # Dual trigger: periodic sweep + reactive on new arbitrage detections
    await asyncio.gather(
        _periodic_loop(pipeline, settings.optimizer_interval_seconds),
        _event_loop(pipeline, redis),
    )


async def _periodic_loop(pipeline: OptimizerPipeline, interval: int) -> None:
    """Periodically sweep for unprocessed opportunities."""
    while True:
        try:
            await pipeline.process_pending()
        except Exception:
            logger.exception("periodic_optimization_error")
        await asyncio.sleep(interval)


async def _event_loop(pipeline: OptimizerPipeline, redis) -> None:
    """React to newly detected arbitrage opportunities."""
    async for event in subscribe(redis, CHANNEL_ARBITRAGE_FOUND):
        opp_id = event.get("opportunity_id")
        if opp_id:
            logger.info("triggered_by_detection", opportunity_id=opp_id)
            try:
                await pipeline.optimize_opportunity(opp_id)
            except Exception:
                logger.exception("event_optimization_error", opportunity_id=opp_id)


if __name__ == "__main__":
    asyncio.run(main())
