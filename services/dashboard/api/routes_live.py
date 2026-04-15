"""Live trading control API routes."""
from __future__ import annotations

from fastapi import APIRouter, Request

from shared.db import SessionFactory
from shared.live_runtime import set_live_kill_switch
from services.dashboard.api.live_status import build_live_status

router = APIRouter()


@router.get("/live/status")
async def get_live_status(request: Request):
    """Live trading status."""
    return await build_live_status(request.app.state.redis, SessionFactory)


@router.post("/live/kill")
async def kill_live_trading(request: Request):
    """Emergency kill switch for live trading."""
    await set_live_kill_switch(request.app.state.redis, True)
    return {"status": "killed", "msg": "Live trading disabled"}


@router.post("/live/enable")
async def enable_live_trading(request: Request):
    """Re-enable live trading after kill switch."""
    await set_live_kill_switch(request.app.state.redis, False)
    return {"status": "enabled", "msg": "Live trading re-enabled"}
