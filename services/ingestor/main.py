import asyncio

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import get_redis
from shared.logging import setup_logging
from services.ingestor.clob_client import ClobClient
from services.ingestor.embedder import Embedder
from services.ingestor.gamma_client import GammaClient
from services.ingestor.polling import MarketPoller
from services.ingestor.ws_client import ClobWebSocket


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

    # When WS is enabled, slow polling to 5-minute reconciliation
    poll_interval = 300 if settings.ws_enabled else settings.poll_interval_seconds

    poller = MarketPoller(
        gamma=gamma,
        clob=clob,
        embedder=embedder,
        session_factory=SessionFactory,
        redis=redis,
        poll_interval=poll_interval,
        fetch_order_books=settings.fetch_order_books,
        max_snapshot_markets=settings.max_snapshot_markets,
    )

    ws_client = None
    if settings.ws_enabled:
        ws_client = ClobWebSocket(
            redis=redis,
            session_factory=SessionFactory,
            ws_url=settings.ws_clob_url,
            reconnect_base_delay=settings.ws_reconnect_base_delay,
            reconnect_max_delay=settings.ws_reconnect_max_delay,
            ping_interval=settings.ws_ping_interval,
            buffer_seconds=settings.ws_snapshot_buffer_seconds,
            resolution_threshold=settings.resolution_price_threshold,
            max_snapshot_markets=settings.max_snapshot_markets,
        )
        poller.set_ws_client(ws_client)

    try:
        if ws_client:
            # Start WS and polling concurrently — WS builds its own token map
            # from DB on startup, no need to wait for initial poll
            await asyncio.gather(
                ws_client.run(),
                poller.run(),
            )
        else:
            await poller.run()
    finally:
        if ws_client:
            await ws_client.close()
        await gamma.close()
        await clob.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
