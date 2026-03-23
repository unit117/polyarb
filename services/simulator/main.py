import asyncio

import structlog

from shared.circuit_breaker import CircuitBreaker
from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.events import (
    CHANNEL_MARKET_RESOLVED,
    CHANNEL_OPTIMIZATION_COMPLETE,
    get_redis,
    subscribe,
)
from shared.live_runtime import set_live_runtime_status
from shared.logging import setup_logging
from services.simulator.live_coordinator import LiveTradingCoordinator
from services.simulator.live_executor import LiveExecutor
from services.simulator.live_reconciler import LiveOrderReconciler
from services.simulator.pipeline import SimulatorPipeline
from services.simulator.state import restore_portfolio

logger = structlog.get_logger()


def _build_circuit_breaker(
    redis,
    *,
    max_daily_loss: float,
    max_position_per_market: float,
) -> CircuitBreaker:
    return CircuitBreaker(
        redis=redis,
        max_daily_loss=max_daily_loss,
        max_position_per_market=max_position_per_market,
        max_drawdown_pct=settings.cb_max_drawdown_pct,
        max_consecutive_errors=settings.cb_max_consecutive_errors,
        cooldown_seconds=settings.cb_cooldown_seconds,
    )


async def main() -> None:
    setup_logging(settings.log_level)
    await init_db()

    redis = await get_redis()
    portfolio = await restore_portfolio(
        SessionFactory,
        settings.initial_capital,
        source="paper",
    )

    cb = _build_circuit_breaker(
        redis,
        max_daily_loss=settings.cb_max_daily_loss,
        max_position_per_market=settings.cb_max_position_per_market,
    )
    pipeline = SimulatorPipeline(
        session_factory=SessionFactory,
        redis=redis,
        portfolio=portfolio,
        max_position_size=settings.max_position_size,
        circuit_breaker=cb,
        source="paper",
    )

    live_coordinator = None
    if settings.live_trading_enabled:
        live_portfolio = await restore_portfolio(
            SessionFactory,
            settings.live_trading_bankroll,
            source="live",
        )
        live_cb = _build_circuit_breaker(
            redis,
            max_daily_loss=(
                settings.live_trading_bankroll
                * settings.live_trading_max_daily_loss_pct
                / 100.0
            ),
            max_position_per_market=settings.live_trading_max_position_size,
        )
        live_executor = LiveExecutor(
            private_key=settings.live_trading_private_key,
            chain_id=settings.live_trading_chain_id,
            dry_run=settings.live_trading_dry_run,
            host=settings.clob_api_base,
            signature_type=settings.live_trading_signature_type,
            funder=settings.live_trading_funder or None,
        )
        await live_executor.initialize()
        live_coordinator = LiveTradingCoordinator(
            session_factory=SessionFactory,
            redis=redis,
            portfolio=live_portfolio,
            venue_adapter=live_executor,
            circuit_breaker=live_cb,
            dry_run=settings.live_trading_dry_run,
        )
        await live_coordinator.publish_status()
    else:
        await set_live_runtime_status(
            redis,
            {
                "enabled": False,
                "dry_run": settings.live_trading_dry_run,
                "active": False,
                "adapter_ready": False,
                "kill_switch": False,
            },
        )

    logger.info(
        "simulator_started",
        initial_capital=settings.initial_capital,
        max_position=settings.max_position_size,
        restored_cash=float(portfolio.cash),
        restored_positions=len(portfolio.positions),
        circuit_breaker="enabled",
        live_enabled=settings.live_trading_enabled,
        live_dry_run=settings.live_trading_dry_run,
    )

    try:
        await pipeline.snapshot_portfolio()
        logger.info("initial_snapshot_created", source="paper")
    except Exception:
        logger.exception("initial_snapshot_error", source="paper")

    reconciler = None
    if live_coordinator:
        try:
            await live_coordinator.snapshot_portfolio()
            logger.info("initial_snapshot_created", source="live")
        except Exception:
            logger.exception("initial_snapshot_error", source="live")
        if not settings.live_trading_dry_run:
            reconciler = LiveOrderReconciler(
                session_factory=SessionFactory,
                venue_adapter=live_coordinator.venue_adapter,
                coordinator=live_coordinator,
                poll_interval_seconds=settings.live_reconcile_interval_seconds,
            )

    tasks = [
        _periodic_loop(pipeline, settings.simulator_interval_seconds, live_coordinator),
        _snapshot_loop(pipeline, 300),
        _event_loop(pipeline, redis, live_coordinator),
        _settlement_loop(pipeline, live_coordinator, settings.settlement_interval_seconds),
        _resolution_event_loop(pipeline, live_coordinator, redis),
    ]
    if live_coordinator:
        tasks.extend(
            [
                _live_snapshot_loop(
                    live_coordinator,
                    settings.live_snapshot_interval_seconds,
                ),
                _live_status_loop(
                    live_coordinator,
                    settings.live_status_heartbeat_seconds,
                ),
            ]
        )
    if reconciler:
        tasks.append(reconciler.loop_forever())

    await asyncio.gather(*tasks)


async def _periodic_loop(
    pipeline: SimulatorPipeline,
    interval: int,
    live_coordinator: LiveTradingCoordinator | None,
) -> None:
    while True:
        try:
            await pipeline.process_pending(live_coordinator=live_coordinator)
        except Exception:
            logger.exception("periodic_simulation_error")
            if pipeline.circuit_breaker:
                pipeline.circuit_breaker.record_error()
        await asyncio.sleep(interval)


async def _snapshot_loop(pipeline: SimulatorPipeline, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await pipeline.snapshot_portfolio()
        except Exception:
            logger.exception("snapshot_loop_error", source="paper")


async def _live_snapshot_loop(
    live_coordinator: LiveTradingCoordinator,
    interval: int,
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await live_coordinator.snapshot_portfolio()
        except Exception:
            logger.exception("snapshot_loop_error", source="live")


async def _live_status_loop(
    live_coordinator: LiveTradingCoordinator,
    interval: int,
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await live_coordinator.publish_status()
        except Exception:
            logger.exception("live_status_loop_error")


async def _event_loop(
    pipeline: SimulatorPipeline,
    redis,
    live_coordinator: LiveTradingCoordinator | None,
) -> None:
    async for event in subscribe(redis, CHANNEL_OPTIMIZATION_COMPLETE):
        opp_id = event.get("opportunity_id")
        if opp_id:
            logger.info("triggered_by_optimization", opportunity_id=opp_id)
            try:
                await pipeline.simulate_opportunity(
                    opp_id,
                    live_coordinator=live_coordinator,
                )
                await pipeline.snapshot_portfolio()
            except Exception:
                logger.exception("event_simulation_error", opportunity_id=opp_id)
                if pipeline.circuit_breaker:
                    pipeline.circuit_breaker.record_error()


async def _settlement_loop(
    pipeline: SimulatorPipeline,
    live_coordinator: LiveTradingCoordinator | None,
    interval: int,
) -> None:
    while True:
        try:
            await pipeline.settle_resolved_markets()
            if live_coordinator:
                await live_coordinator.settle_resolved_markets()
        except Exception:
            logger.exception("settlement_loop_error")
        await asyncio.sleep(interval)


async def _resolution_event_loop(
    pipeline: SimulatorPipeline,
    live_coordinator: LiveTradingCoordinator | None,
    redis,
) -> None:
    async for event in subscribe(redis, CHANNEL_MARKET_RESOLVED):
        market_id = event.get("market_id")
        if market_id:
            logger.info("triggered_by_resolution", market_id=market_id)
            try:
                await pipeline.settle_resolved_markets()
                if live_coordinator:
                    await live_coordinator.settle_resolved_markets()
            except Exception:
                logger.exception("resolution_settlement_error", market_id=market_id)


if __name__ == "__main__":
    asyncio.run(main())
