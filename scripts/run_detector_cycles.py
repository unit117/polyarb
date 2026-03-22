"""Run repeated detector cycles against backtest DB until pair growth plateaus.

Designed for E1: increases the resolved-pair sample size for embedding audit
by running the detector pipeline in a loop against the backtest database
(which has 5000 dataset markets with embeddings).

Each cycle picks a random batch of markets and searches for similar pairs
via pgvector. Running multiple cycles covers more of the 5000-market space
than a single cycle's batch_size allows.

Usage:
    python -m scripts.run_detector_cycles \
        --max-cycles 50 --plateau-threshold 3

    # In Docker (pointed at backtest DB):
    docker compose run --rm -e POSTGRES_DB=polyarb_backtest dataset-bootstrap \
        python -m scripts.run_detector_cycles --max-cycles 50
"""

import argparse
import asyncio
import sys

import openai
import structlog

sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.models import MarketPair
from services.detector.pipeline import DetectionPipeline

log = structlog.get_logger()


async def count_pairs() -> int:
    """Count total market pairs in the database."""
    from sqlalchemy import func, select

    async with SessionFactory() as session:
        result = await session.execute(select(func.count(MarketPair.id)))
        return result.scalar() or 0


async def main():
    parser = argparse.ArgumentParser(
        description="Run detector cycles to build pair coverage"
    )
    parser.add_argument(
        "--max-cycles", type=int, default=50,
        help="Maximum number of detection cycles to run (default: 50)",
    )
    parser.add_argument(
        "--plateau-threshold", type=int, default=3,
        help="Stop after N consecutive cycles with zero new pairs (default: 3)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=200,
        help="Markets per cycle batch (default: 200)",
    )
    parser.add_argument(
        "--similarity-threshold", type=float, default=None,
        help="Override similarity threshold (default: use settings)",
    )
    args = parser.parse_args()

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
    await init_db()

    # Need a real Redis connection for the pipeline (it publishes events)
    from shared.events import get_redis
    redis = await get_redis()

    openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    threshold = args.similarity_threshold or settings.similarity_threshold

    pipeline = DetectionPipeline(
        session_factory=SessionFactory,
        openai_client=openai_client,
        redis=redis,
        similarity_threshold=threshold,
        similarity_top_k=settings.similarity_top_k,
        batch_size=args.batch_size,
        classifier_model=settings.classifier_model,
    )

    initial_pairs = await count_pairs()
    log.info("detector_cycles_start",
             initial_pairs=initial_pairs,
             max_cycles=args.max_cycles,
             batch_size=args.batch_size,
             threshold=threshold)

    plateau_count = 0

    for cycle in range(1, args.max_cycles + 1):
        before = await count_pairs()

        try:
            stats = await pipeline.run_once()
        except Exception:
            log.exception("cycle_error", cycle=cycle)
            continue

        after = await count_pairs()
        new_pairs = after - before

        log.info("cycle_complete",
                 cycle=cycle,
                 new_pairs=new_pairs,
                 total_pairs=after,
                 candidates=stats.get("candidates", 0),
                 pairs_created=stats.get("pairs_created", 0))

        if new_pairs == 0:
            plateau_count += 1
            if plateau_count >= args.plateau_threshold:
                log.info("plateau_reached",
                         consecutive_zero=plateau_count,
                         total_pairs=after)
                break
        else:
            plateau_count = 0

    final_pairs = await count_pairs()
    log.info("detector_cycles_complete",
             total_cycles=min(cycle, args.max_cycles),
             initial_pairs=initial_pairs,
             final_pairs=final_pairs,
             new_pairs_found=final_pairs - initial_pairs)

    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
