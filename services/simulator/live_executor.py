"""Thin Polymarket venue adapter for live order submission and reconciliation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()


class LiveExecutor:
    """Submit and inspect real trades on Polymarket via the official SDK."""

    def __init__(
        self,
        private_key: str,
        chain_id: int,
        dry_run: bool = True,
        host: str = "https://clob.polymarket.com",
        signature_type: int = 0,
        funder: str | None = None,
    ):
        self.private_key = private_key
        self.chain_id = chain_id
        self.dry_run = dry_run
        self.host = host
        self.signature_type = signature_type
        self.funder = funder
        self.client = None
        self.ready = False
        self.account_address: str | None = None

    async def initialize(self) -> None:
        """Initialize the authenticated CLOB client."""
        if self.dry_run:
            self.ready = True
            logger.info(
                "live_executor_initialized",
                dry_run=True,
                submission_mode="dry_run",
            )
            return

        if not self.private_key:
            logger.warning(
                "live_executor_no_credentials",
                msg="Private key not set",
            )
            self.ready = False
            return

        try:
            from py_clob_client.client import ClobClient

            self.client = ClobClient(
                self.host,
                chain_id=self.chain_id,
                key=self.private_key,
                signature_type=self.signature_type,
                funder=self.funder or None,
            )
            creds = await asyncio.to_thread(self.client.create_or_derive_api_creds)
            await asyncio.to_thread(self.client.set_api_creds, creds)
            self.account_address = self.client.get_address()
            self.ready = True
            logger.info(
                "live_executor_initialized",
                dry_run=False,
                submission_mode="live",
                account_address=self.account_address,
            )
        except ImportError:
            logger.warning(
                "live_executor_missing_dependency",
                msg="Install py-clob-client: pip install py-clob-client",
            )
            self.ready = False
        except Exception:
            logger.exception("live_executor_init_failed")
            self.ready = False

    async def submit_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> dict:
        """Submit an immediate-or-cancel style order via the venue client."""
        trade_info = {
            "token_id": token_id,
            "side": side,
            "size": size,
            "price": price,
        }

        if not self.ready or not self.client:
            return {"status": "rejected", "reason": "client_not_initialized"}

        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY as CLOB_BUY, SELL as CLOB_SELL

            order_side = CLOB_BUY if side == "BUY" else CLOB_SELL
            amount = size * price if side == "BUY" else size
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                side=order_side,
                price=price,
                order_type=OrderType.FAK,
            )
            signed_order = await asyncio.to_thread(
                self.client.create_market_order,
                order_args,
            )
            order = await asyncio.to_thread(
                self.client.post_order,
                signed_order,
                OrderType.FAK,
            )

            logger.info("live_executor_order_submitted", order=order, **trade_info)
            return {
                "status": "submitted",
                "order": order,
                **trade_info,
            }
        except Exception as exc:
            logger.exception("live_executor_order_failed", error=str(exc), **trade_info)
            return {"status": "rejected", "reason": str(exc), **trade_info}

    async def fetch_order_state(
        self,
        order_id: str,
        *,
        token_id: str,
        submitted_at: datetime,
    ) -> dict:
        """Fetch the latest order and trade state for a submitted live order."""
        if not self.ready or not self.client:
            return {"order": None, "trades": []}

        order = None
        try:
            order = await asyncio.to_thread(self.client.get_order, order_id)
        except Exception:
            logger.exception("live_executor_get_order_failed", order_id=order_id)

        if not order:
            try:
                from py_clob_client.clob_types import OpenOrderParams

                open_orders = await asyncio.to_thread(
                    self.client.get_orders,
                    OpenOrderParams(id=order_id),
                )
                if open_orders:
                    order = open_orders[0]
            except Exception:
                logger.exception("live_executor_get_open_order_failed", order_id=order_id)

        trades = await self._fetch_related_trades(
            order_id=order_id,
            token_id=token_id,
            submitted_at=submitted_at,
            order=order,
        )
        return {"order": order, "trades": trades}

    async def _fetch_related_trades(
        self,
        *,
        order_id: str,
        token_id: str,
        submitted_at: datetime,
        order: dict | None,
    ) -> list[dict]:
        try:
            from py_clob_client.clob_types import TradeParams
        except Exception:
            return []

        trade_ids = _extract_trade_ids(order)
        trades: list[dict] = []

        if trade_ids:
            for trade_id in trade_ids:
                try:
                    rows = await asyncio.to_thread(
                        self.client.get_trades,
                        TradeParams(id=trade_id),
                    )
                    trades.extend(rows or [])
                except Exception:
                    logger.exception(
                        "live_executor_get_trade_failed",
                        order_id=order_id,
                        trade_id=trade_id,
                    )
            return trades

        after = int(submitted_at.replace(tzinfo=timezone.utc).timestamp()) - 60
        try:
            rows = await asyncio.to_thread(
                self.client.get_trades,
                TradeParams(asset_id=token_id, after=after),
            )
        except Exception:
            logger.exception(
                "live_executor_get_trades_failed",
                order_id=order_id,
                token_id=token_id,
            )
            return []

        return [row for row in rows or [] if _trade_matches_order(row, order_id)]


def _extract_trade_ids(order: dict | None) -> list[str]:
    if not isinstance(order, dict):
        return []
    trade_ids = order.get("associate_trades") or order.get("associated_trades") or []
    return [str(trade_id) for trade_id in trade_ids if trade_id is not None]


def _trade_matches_order(trade: dict, order_id: str) -> bool:
    if not isinstance(trade, dict):
        return False
    if str(trade.get("taker_order_id") or "") == order_id:
        return True

    maker_orders = trade.get("maker_orders") or []
    for maker_order in maker_orders:
        if not isinstance(maker_order, dict):
            continue
        if str(maker_order.get("order_id") or maker_order.get("orderID") or "") == order_id:
            return True
    return False
