from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, func, select

from shared.config import settings
from shared.live_runtime import (
    get_live_runtime_status,
    is_live_kill_switch_enabled,
)
from shared.models import LiveFill, LiveOrder, PortfolioSnapshot


def live_configured() -> bool:
    return settings.live_trading_dry_run or bool(
        settings.live_trading_private_key
    )


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def live_runtime_is_fresh(runtime: dict) -> bool:
    heartbeat = parse_timestamp(runtime.get("last_heartbeat"))
    if not heartbeat:
        return False
    max_age = max(90, settings.live_status_heartbeat_seconds * 3)
    return (datetime.now(timezone.utc) - heartbeat).total_seconds() <= max_age


async def build_live_status(redis, session_factory) -> dict:
    runtime = await get_live_runtime_status(redis)
    kill_switch = await is_live_kill_switch_enabled(redis)
    runtime_fresh = live_runtime_is_fresh(runtime)
    active = bool(
        settings.live_trading_enabled
        and runtime.get("active")
        and runtime_fresh
        and not kill_switch
    )

    async with session_factory() as session:
        order_count = await session.scalar(select(func.count()).select_from(LiveOrder))
        fill_count = await session.scalar(select(func.count()).select_from(LiveFill))
        latest_portfolio = await session.scalar(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.source == "live")
            .order_by(desc(PortfolioSnapshot.timestamp))
            .limit(1)
        )

    portfolio = None
    if latest_portfolio:
        portfolio = {
            "cash": float(latest_portfolio.cash),
            "total_value": float(latest_portfolio.total_value),
            "realized_pnl": float(latest_portfolio.realized_pnl),
            "unrealized_pnl": float(latest_portfolio.unrealized_pnl),
            "timestamp": latest_portfolio.timestamp.isoformat(),
            "total_positions": len(latest_portfolio.positions or {}),
        }

    return {
        "configured": live_configured(),
        "enabled": settings.live_trading_enabled,
        "dry_run": settings.live_trading_dry_run,
        "active": active,
        "kill_switch": kill_switch,
        "runtime_fresh": runtime_fresh,
        "bankroll": settings.live_trading_bankroll,
        "max_position_size": settings.live_trading_max_position_size,
        "min_edge": settings.live_trading_min_edge,
        "order_count": order_count or 0,
        "fill_count": fill_count or 0,
        "portfolio": portfolio,
        "runtime": runtime,
    }
