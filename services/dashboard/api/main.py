"""Dashboard API — FastAPI backend serving REST endpoints + WebSocket."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from shared.config import settings
from shared.db import init_db
from shared.events import get_redis
from shared.logging import setup_logging
from services.dashboard.api.routes import router

logger = structlog.get_logger()

# Connected WebSocket clients
ws_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    await init_db()
    app.state.redis = await get_redis()
    # Start Redis subscriber for live updates
    task = asyncio.create_task(_redis_broadcaster(app.state.redis))
    logger.info("dashboard_started", port=settings.dashboard_port)
    yield
    task.cancel()
    await app.state.redis.aclose()


app = FastAPI(title="PolyArb Dashboard", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(ws)


async def _redis_broadcaster(r: aioredis.Redis):
    """Subscribe to all polyarb channels and broadcast to WebSocket clients."""
    pubsub = r.pubsub()
    await pubsub.psubscribe("polyarb:*")
    try:
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                payload = json.dumps({
                    "channel": message["channel"],
                    "data": json.loads(message["data"]),
                })
                dead = set()
                for ws in ws_clients:
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        dead.add(ws)
                ws_clients -= dead
    finally:
        await pubsub.punsubscribe("polyarb:*")
        await pubsub.aclose()


# Serve Knowledge Base if it exists (must be before "/" catch-all)
docs_dir = Path(__file__).parent.parent / "docs" / "dist"
if docs_dir.exists():
    app.mount("/docs", StaticFiles(directory=str(docs_dir), html=True), name="docs")

# Serve React static build if it exists
static_dir = Path(__file__).parent.parent / "web" / "dist"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
