from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.models import LiveOrder
from shared.config import venue_fee

logger = structlog.get_logger()

TERMINAL_STATUSES = {"dry_run", "filled", "cancelled", "rejected", "expired", "settled"}
NONTERMINAL_STATUSES = {"submitted", "partially_filled"}
CONFIRMED_TRADE_STATUSES = {"confirmed"}


@dataclass(frozen=True)
class ReconciledFill:
    venue_fill_id: str | None
    fill_size: float
    fill_price: float
    fees: float
    filled_at: datetime


class LiveOrderReconciler:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        venue_adapter,
        coordinator,
        poll_interval_seconds: int = 5,
    ):
        self.session_factory = session_factory
        self.venue_adapter = venue_adapter
        self.coordinator = coordinator
        self.poll_interval_seconds = poll_interval_seconds

    async def loop_forever(self) -> None:
        while True:
            try:
                await self.reconcile_once()
            except Exception:
                logger.exception("live_reconciler_loop_error")
            await asyncio.sleep(self.poll_interval_seconds)

    async def reconcile_once(self) -> dict:
        async with self.session_factory() as session:
            result = await session.execute(
                select(LiveOrder)
                .where(
                    LiveOrder.dry_run == False,  # noqa: E712
                    LiveOrder.venue_order_id.isnot(None),
                    LiveOrder.status.in_(tuple(NONTERMINAL_STATUSES)),
                )
                .order_by(LiveOrder.submitted_at.asc())
                .limit(100)
            )
            orders = result.scalars().all()

        stats = {"processed": 0, "updated": 0, "fills": 0, "errors": 0}
        for order in orders:
            try:
                update = await self._reconcile_order(order)
                stats["processed"] += 1
                stats["updated"] += 1 if update["order_status_changed"] else 0
                stats["fills"] += update["fills_applied"]
            except Exception:
                logger.exception("live_reconciler_order_error", live_order_id=order.id)
                stats["errors"] += 1

        if stats["processed"] > 0:
            logger.info("live_reconciliation_complete", **stats)
        return stats

    async def _reconcile_order(self, live_order: LiveOrder) -> dict:
        venue_state = await self.venue_adapter.fetch_order_state(
            live_order.venue_order_id,
            token_id=live_order.token_id,
            submitted_at=live_order.submitted_at,
        )
        raw_order = venue_state.get("order")
        trades = venue_state.get("trades", [])

        fills = extract_reconciled_fills(
            live_order,
            trades,
        )
        new_status = normalize_live_order_status(
            raw_order,
            requested_size=float(live_order.requested_size),
            confirmed_fills=fills,
            current_status=live_order.status,
        )
        result = await self.coordinator.apply_reconciliation(
            live_order.id,
            status=new_status,
            fills=fills,
        )
        return {
            "fills_applied": result["fills_applied"],
            "order_status_changed": new_status != live_order.status,
        }


def normalize_live_order_status(
    raw_order: dict | None,
    *,
    requested_size: float,
    confirmed_fills: list[ReconciledFill],
    current_status: str,
) -> str:
    confirmed_size = sum(fill.fill_size for fill in confirmed_fills)
    raw_status = str((raw_order or {}).get("status") or "").strip().lower()
    matched_size = max(
        _coerce_float((raw_order or {}).get("size_matched")),
        confirmed_size,
    )
    size_limit = requested_size if requested_size > 0 else 0.0

    if raw_status in {"cancelled", "canceled"}:
        return "cancelled"
    if raw_status in {"rejected", "failed"}:
        return "rejected"
    if raw_status == "expired":
        return "expired"
    if size_limit > 0 and matched_size >= size_limit - 1e-9:
        return "filled"
    if matched_size > 0:
        return "partially_filled"
    if current_status in TERMINAL_STATUSES:
        return current_status
    return "submitted"


def extract_reconciled_fills(
    live_order: LiveOrder,
    trades: list[dict],
) -> list[ReconciledFill]:
    fills: list[ReconciledFill] = []
    for trade in trades:
        if not trade_matches_order(trade, live_order.venue_order_id):
            continue
        if str(trade.get("status") or "").strip().lower() not in CONFIRMED_TRADE_STATUSES:
            continue

        price = _coerce_float(trade.get("price"))
        size = _extract_trade_size(trade, live_order.venue_order_id)
        if size <= 0 or price <= 0:
            continue

        fills.append(
            ReconciledFill(
                venue_fill_id=extract_trade_id(trade),
                fill_size=size,
                fill_price=price,
                fees=venue_fee("polymarket", price, live_order.side) * size,
                filled_at=_coerce_timestamp(trade.get("last_update") or trade.get("timestamp")),
            )
        )
    return fills


def trade_matches_order(trade: dict, order_id: str | None) -> bool:
    if not order_id or not isinstance(trade, dict):
        return False
    if str(trade.get("taker_order_id") or "") == order_id:
        return True

    for maker_order in trade.get("maker_orders") or []:
        if not isinstance(maker_order, dict):
            continue
        maker_id = maker_order.get("order_id") or maker_order.get("orderID")
        if str(maker_id or "") == order_id:
            return True
    return False


def extract_trade_id(trade: dict) -> str | None:
    for key in ("id", "tradeID", "trade_id"):
        if trade.get(key):
            return str(trade[key])
    return None


def _extract_trade_size(trade: dict, order_id: str | None) -> float:
    if str(trade.get("taker_order_id") or "") == str(order_id or ""):
        return _coerce_float(trade.get("size"))

    for maker_order in trade.get("maker_orders") or []:
        if not isinstance(maker_order, dict):
            continue
        maker_id = maker_order.get("order_id") or maker_order.get("orderID")
        if str(maker_id or "") != str(order_id or ""):
            continue
        return _coerce_float(maker_order.get("matched_amount") or maker_order.get("maker_matched_amount"))

    return _coerce_float(trade.get("size"))


def _coerce_float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(Decimal(str(value)))
    except Exception:
        return 0.0


def _coerce_timestamp(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)
