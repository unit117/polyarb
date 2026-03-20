import asyncio

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import get_redis
from shared.logging import setup_logging
from services.ingestor.clob_client import ClobClient
from services.ingestor.embedder import Embedder
from services.ingestor.gamma_client import GammaClient
from services.ingestor.polling import MarketPoller


async def main() -> None:
    setup_logging(settings.log_level)

    await init_db()

    gamma = GammaClient(settings.gamma_api_base, settings.rate_limit_rps)
    clob = ClobClient(settings.clob_api_base, settings.rate_limit_rps)
    embedder = Embedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    redis = await get_redis()

    poller = MarketPoller(
        gamma=gamma,
        clob=clob,
        embedder=embedder,
        session_factory=SessionFactory,
        redis=redis,
        poll_interval=settings.poll_interval_seconds,
        fetch_order_books=settings.fetch_order_books,
        max_snapshot_markets=settings.max_snapshot_markets,
    )

    try:
        await poller.run()
    finally:
        await gamma.close()
        await clob.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
