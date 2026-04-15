from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.circuit_breaker import CircuitBreaker
from shared.events import CHANNEL_PORTFOLIO_UPDATED, publish_event
from shared.schemas import PortfolioUpdatedEvent
from shared.lifecycle import OrderStatus, TradeStatus
from shared.live_runtime import (
    is_live_kill_switch_enabled,
    set_live_runtime_status,
)
from shared.models import LiveFill, LiveOrder, Market, PaperTrade, PortfolioSnapshot, PriceSnapshot
from services.simulator.portfolio import Portfolio

if TYPE_CHECKING:
    from services.simulator.live_executor import LiveExecutor
    from services.simulator.live_reconciler import ReconciledFill
    from services.simulator.validation import ValidatedExecutionBundle

logger = structlog.get_logger()


class LiveTradingCoordinator:
    """Persists live order intent and maintains separate live runtime state."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        redis: aioredis.Redis,
        portfolio: Portfolio,
        venue_adapter: LiveExecutor,
        circuit_breaker: CircuitBreaker | None = None,
        dry_run: bool = True,
    ):
        self.session_factory = session_factory
        self.redis = redis
        self.portfolio = portfolio
        self.venue_adapter = venue_adapter
        self.circuit_breaker = circuit_breaker
        self.dry_run = dry_run
        self._lock = asyncio.Lock()

    async def publish_status(
        self,
        *,
        last_submission_at: str | None = None,
        last_error: str | None = None,
    ) -> dict:
        kill_switch = await is_live_kill_switch_enabled(self.redis)
        status = {
            "enabled": True,
            "dry_run": self.dry_run,
            "active": not kill_switch and (self.dry_run or self.venue_adapter.ready),
            "kill_switch": kill_switch,
            "adapter_ready": self.venue_adapter.ready,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "open_positions": len(self.portfolio.positions),
            "cash": float(self.portfolio.cash),
        }
        if last_submission_at:
            status["last_submission_at"] = last_submission_at
        if last_error:
            status["last_error"] = last_error
        return await set_live_runtime_status(self.redis, status)

    async def submit_validated_bundle(self, bundle: ValidatedExecutionBundle) -> dict:
        async with self._lock:
            if await is_live_kill_switch_enabled(self.redis):
                await self.publish_status(last_error="live_kill_switch")
                return {"status": "blocked", "reason": "live_kill_switch"}

            if not self.dry_run and not self.venue_adapter.ready:
                await self.publish_status(last_error="venue_adapter_not_ready")
                return {"status": "blocked", "reason": "venue_adapter_not_ready"}

            async with self.session_factory() as session:
                result = await session.execute(
                    select(Market).where(Market.id.in_({leg.market_id for leg in bundle.legs}))
                )
                markets = {market.id: market for market in result.scalars().all()}

                created = 0
                errors: list[str] = []
                for leg in bundle.legs:
                    market = markets.get(leg.market_id)
                    if not market:
                        errors.append(f"market_missing:{leg.market_id}")
                        continue

                    token_id = token_id_for_outcome(market, leg.outcome)
                    if not token_id:
                        errors.append(f"token_missing:{leg.market_id}:{leg.outcome}")
                        continue

                    if self.circuit_breaker:
                        allowed, reason = await self.circuit_breaker.pre_trade_check(
                            self.portfolio,
                            leg.market_id,
                            leg.size,
                            trade_side=leg.side,
                            outcome=leg.outcome,
                            current_prices=bundle.current_prices,
                        )
                        if not allowed:
                            errors.append(reason)
                            continue

                    venue_order_id = None
                    status = OrderStatus.DRY_RUN if self.dry_run else OrderStatus.SUBMITTED
                    error = None

                    if not self.dry_run:
                        submit_result = await self.venue_adapter.submit_order(
                            token_id=token_id,
                            side=leg.side,
                            size=leg.size,
                            price=leg.vwap_price,
                        )
                        status = submit_result.get("status", OrderStatus.REJECTED)
                        if status == OrderStatus.SUBMITTED:
                            venue_order_id = extract_venue_order_id(
                                submit_result.get("order")
                            )
                        elif status != OrderStatus.SUBMITTED:
                            error = submit_result.get("reason")
                            errors.append(error or "submission_rejected")

                    session.add(
                        LiveOrder(
                            opportunity_id=bundle.opportunity_id,
                            market_id=leg.market_id,
                            outcome=leg.outcome,
                            token_id=token_id,
                            side=leg.side,
                            requested_size=Decimal(str(leg.size)),
                            requested_price=Decimal(str(leg.vwap_price)),
                            status=status,
                            dry_run=self.dry_run,
                            venue_order_id=venue_order_id,
                            error=error,
                        )
                    )
                    created += 1

                await session.commit()

            await self.publish_status(
                last_submission_at=datetime.now(timezone.utc).isoformat(),
                last_error=";".join(errors) if errors else None,
            )
            return {
                "status": "ok" if created > 0 else "blocked",
                "orders_created": created,
                "errors": errors,
            }

    async def apply_reconciliation(
        self,
        live_order_id: int,
        *,
        status: str,
        fills: list[ReconciledFill],
        error: str | None = None,
    ) -> dict:
        async with self._lock:
            async with self.session_factory() as session:
                live_order = await session.get(LiveOrder, live_order_id)
                if not live_order:
                    return {"status": "not_found", "fills_applied": 0}

                existing_fill_ids = await _existing_fill_ids(session, live_order.id)
                fills_applied = 0
                for fill in fills:
                    if fill.venue_fill_id and fill.venue_fill_id in existing_fill_ids:
                        continue

                    await self._record_fill(session, live_order, fill)
                    fills_applied += 1
                    if fill.venue_fill_id:
                        existing_fill_ids.add(fill.venue_fill_id)

                if status and live_order.status != status:
                    live_order.status = status
                if error:
                    live_order.error = error

                await session.commit()

            if fills_applied > 0:
                await self._snapshot_portfolio_locked()
            await self.publish_status(last_error=error)
            return {
                "status": "ok",
                "fills_applied": fills_applied,
                "order_status": status,
            }

    async def settle_resolved_markets(self) -> dict:
        async with self._lock:
            stats = {"settled": 0, "pnl_realized": 0.0}
            if not self.portfolio.positions:
                return stats

            position_market_ids = {
                int(key.split(":", 1)[0])
                for key in self.portfolio.positions
                if ":" in key
            }
            if not position_market_ids:
                return stats

            async with self.session_factory() as session:
                result = await session.execute(
                    select(Market).where(
                        Market.resolved_outcome.isnot(None),
                        Market.id.in_(position_market_ids),
                    )
                )
                markets = result.scalars().all()

                for market in markets:
                    for key in list(self.portfolio.positions.keys()):
                        if not key.startswith(f"{market.id}:"):
                            continue

                        position_outcome = key.split(":", 1)[1]
                        is_winner = position_outcome == market.resolved_outcome
                        settlement_price = 1.0 if is_winner else 0.0
                        close_result = self.portfolio.close_position(key, settlement_price)
                        if not close_result["closed"]:
                            continue

                        token_id = token_id_for_outcome(market, position_outcome)
                        live_order = LiveOrder(
                            opportunity_id=None,
                            market_id=market.id,
                            outcome=position_outcome,
                            token_id=token_id or f"settlement:{market.id}:{position_outcome}",
                            side="SETTLE",
                            requested_size=Decimal(str(abs(close_result["shares"]))),
                            requested_price=Decimal(str(settlement_price)),
                            status=OrderStatus.SETTLED,
                            dry_run=False,
                        )
                        session.add(live_order)
                        await session.flush()

                        settlement_fill_id = _settlement_fill_id(
                            market.id,
                            position_outcome,
                            market.resolved_at,
                        )
                        session.add(
                            LiveFill(
                                live_order_id=live_order.id,
                                market_id=market.id,
                                outcome=position_outcome,
                                side="SETTLE",
                                venue_fill_id=settlement_fill_id,
                                fill_size=Decimal(str(abs(close_result["shares"]))),
                                fill_price=Decimal(str(settlement_price)),
                                fees=Decimal("0"),
                            )
                        )
                        session.add(
                            PaperTrade(
                                opportunity_id=None,
                                market_id=market.id,
                                outcome=position_outcome,
                                side="SETTLE",
                                size=Decimal(str(abs(close_result["shares"]))),
                                entry_price=Decimal(str(settlement_price)),
                                vwap_price=Decimal(str(settlement_price)),
                                slippage=Decimal("0"),
                                fees=Decimal("0"),
                                status=TradeStatus.SETTLED,
                                source="live",
                                venue=getattr(market, "venue", "polymarket"),
                            )
                        )

                        stats["settled"] += 1
                        stats["pnl_realized"] += close_result["pnl"]
                        if self.circuit_breaker and close_result["pnl"] < 0:
                            self.circuit_breaker.record_loss(abs(close_result["pnl"]))

                await session.commit()

            if stats["settled"] > 0:
                await self._snapshot_portfolio_locked()
                await self.publish_status()
                logger.info("live_settlement_complete", **stats)

            return stats

    async def snapshot_portfolio(self) -> None:
        async with self._lock:
            await self._snapshot_portfolio_locked()
            await self.publish_status()

    async def _snapshot_portfolio_locked(self) -> None:
        current_prices = await self._get_current_prices()
        snap = self.portfolio.to_snapshot_dict(current_prices)

        async with self.session_factory() as session:
            session.add(
                PortfolioSnapshot(
                    cash=Decimal(str(snap["cash"])),
                    positions=snap["positions"],
                    cost_basis=snap.get("cost_basis"),
                    total_value=Decimal(str(snap["total_value"])),
                    realized_pnl=Decimal(str(snap["realized_pnl"])),
                    unrealized_pnl=Decimal(str(snap["unrealized_pnl"])),
                    total_trades=snap["total_trades"],
                    settled_trades=snap["settled_trades"],
                    winning_trades=snap["winning_trades"],
                    source="live",
                )
            )
            await session.commit()

        await publish_event(
            self.redis,
            CHANNEL_PORTFOLIO_UPDATED,
            PortfolioUpdatedEvent.model_validate(snap),
        )

    async def _record_fill(
        self,
        session,
        live_order: LiveOrder,
        fill: ReconciledFill,
    ) -> None:
        key = f"{live_order.market_id}:{live_order.outcome}"
        existing_position = self.portfolio.positions.get(key, Decimal("0"))
        is_exit = (
            (live_order.side == "SELL" and existing_position > 0)
            or (live_order.side == "BUY" and existing_position < 0)
        )
        pre_trade_cost = self.portfolio.cost_basis.get(key, Decimal("0"))

        result = self.portfolio.execute_trade(
            market_id=live_order.market_id,
            outcome=live_order.outcome,
            side=live_order.side,
            size=fill.fill_size,
            vwap_price=fill.fill_price,
            fees=fill.fees,
        )
        if not result["executed"]:
            raise RuntimeError(f"failed_to_apply_live_fill:{live_order.id}")

        actual_size = Decimal(str(result["size"]))
        actual_fees = Decimal(str(result["fees"]))

        if is_exit and existing_position != 0:
            close_size = min(abs(existing_position), actual_size)
            avg_entry = pre_trade_cost / abs(existing_position)
            exit_price = Decimal(str(fill.fill_price))
            exit_fees = (
                actual_fees * close_size / actual_size
                if actual_size > 0
                else Decimal("0")
            )

            if existing_position > 0:
                realized = (exit_price - avg_entry) * close_size - exit_fees
            else:
                realized = (avg_entry - exit_price) * close_size - exit_fees

            self.portfolio.realized_pnl += realized
            if self.circuit_breaker and realized < 0:
                self.circuit_breaker.record_loss(float(abs(realized)))

        session.add(
            LiveFill(
                live_order_id=live_order.id,
                market_id=live_order.market_id,
                outcome=live_order.outcome,
                side=live_order.side,
                venue_fill_id=fill.venue_fill_id,
                fill_size=actual_size,
                fill_price=Decimal(str(fill.fill_price)),
                fees=actual_fees,
                filled_at=fill.filled_at,
            )
        )
        session.add(
            PaperTrade(
                opportunity_id=live_order.opportunity_id,
                market_id=live_order.market_id,
                outcome=live_order.outcome,
                side=live_order.side,
                size=actual_size,
                entry_price=Decimal(str(live_order.requested_price)),
                vwap_price=Decimal(str(fill.fill_price)),
                slippage=Decimal(str(abs(fill.fill_price - float(live_order.requested_price)))),
                fees=actual_fees,
                status=TradeStatus.FILLED,
                source="live",
                venue="polymarket",
            )
        )

    async def _get_current_prices(self) -> dict[str, float]:
        prices: dict[str, float] = {}
        if not self.portfolio.positions:
            return prices

        # Collect market IDs
        market_ids: set[int] = set()
        for key in self.portfolio.positions:
            parts = key.split(":")
            if len(parts) == 2:
                market_ids.add(int(parts[0]))

        async with self.session_factory() as session:
            # Batch-query resolved markets
            resolved: dict[int, str] = {}
            if market_ids:
                result = await session.execute(
                    select(Market.id, Market.resolved_outcome).where(
                        Market.id.in_(market_ids),
                        Market.resolved_outcome.isnot(None),
                    )
                )
                for mid, res_outcome in result.all():
                    resolved[mid] = res_outcome

            for key in self.portfolio.positions:
                parts = key.split(":")
                if len(parts) != 2:
                    continue
                market_id = int(parts[0])
                outcome = parts[1]

                if market_id in resolved:
                    prices[key] = 1.0 if outcome == resolved[market_id] else 0.0
                    continue

                snapshot = await session.scalar(
                    select(PriceSnapshot)
                    .where(PriceSnapshot.market_id == market_id)
                    .order_by(PriceSnapshot.timestamp.desc())
                    .limit(1)
                )
                if snapshot and snapshot.midpoints:
                    price = snapshot.midpoints.get(outcome)
                    if price is not None:
                        prices[key] = float(price)
                elif snapshot and snapshot.prices:
                    price = snapshot.prices.get(outcome)
                    if price is not None:
                        prices[key] = float(price)
        return prices


async def _existing_fill_ids(session, live_order_id: int) -> set[str]:
    result = await session.execute(
        select(LiveFill.venue_fill_id).where(
            LiveFill.live_order_id == live_order_id,
            LiveFill.venue_fill_id.isnot(None),
        )
    )
    return {row[0] for row in result.fetchall() if row[0]}


def token_id_for_outcome(market: Market, outcome: str) -> str | None:
    outcomes = list(market.outcomes or [])
    token_ids = list(market.token_ids or [])
    try:
        index = outcomes.index(outcome)
    except ValueError:
        return None
    if index >= len(token_ids):
        return None
    return str(token_ids[index])


def extract_venue_order_id(order: object) -> str | None:
    if isinstance(order, dict):
        for key in ("orderID", "orderId", "id"):
            if order.get(key):
                return str(order[key])
    return None


def _settlement_fill_id(
    market_id: int,
    outcome: str,
    resolved_at: datetime | None,
) -> str:
    stamp = resolved_at.isoformat() if resolved_at else "unresolved"
    return f"settlement:{market_id}:{outcome}:{stamp}"
