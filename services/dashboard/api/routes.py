"""REST API routes for the dashboard — assembled from domain-specific modules."""
from fastapi import APIRouter

from services.dashboard.api.routes_portfolio import router as portfolio_router
from services.dashboard.api.routes_trading import router as trading_router
from services.dashboard.api.routes_metrics import router as metrics_router
from services.dashboard.api.routes_live import router as live_router

router = APIRouter()
router.include_router(portfolio_router)
router.include_router(trading_router)
router.include_router(metrics_router)
router.include_router(live_router)
