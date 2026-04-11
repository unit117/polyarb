"""Optimizer pipeline: loads opportunities, runs Frank-Wolfe, persists results."""
from __future__ import annotations

from decimal import Decimal

import numpy as np
import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.config import settings
from shared.events import CHANNEL_OPTIMIZATION_COMPLETE, publish
from shared.models import ArbitrageOpportunity, Market, MarketPair, PriceSnapshot
from services.optimizer.frank_wolfe import optimize
from services.optimizer.trades import compute_trades

logger = structlog.get_logger()


class OptimizerPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        redis: aioredis.Redis,
        max_iterations: int,
        gap_tolerance: float,
        ip_timeout_ms: int,
        min_edge: float = 0.03,
        skip_conditional: bool = True,
    ):
        self.session_factory = session_factory
        self.redis = redis
        self.max_iterations = max_iterations
        self.gap_tolerance = gap_tolerance
        self.ip_timeout_ms = ip_timeout_ms
        self.min_edge = min_edge
        self.skip_conditional = skip_conditional

    async def optimize_opportunity(self, opportunity_id: int) -> dict:
        """Optimize a single detected arbitrage opportunity.

        Loads the opportunity and its market pair, runs Frank-Wolfe,
        and updates the DB with results.
        """
        async with self.session_factory() as session:
            # Load opportunity with its pair
            opp = await session.get(ArbitrageOpportunity, opportunity_id)
            if not opp:
                logger.warning("opportunity_not_found", id=opportunity_id)
                return {"status": "not_found"}

            if opp.status != "detected":
                logger.info("opportunity_already_processed", id=opportunity_id, status=opp.status)
                return {"status": "skipped", "reason": opp.status}

            pair = await session.get(MarketPair, opp.pair_id)
            if not pair or not pair.constraint_matrix:
                logger.warning("pair_missing_constraints", pair_id=opp.pair_id)
                return {"status": "no_constraints"}

            constraint = pair.constraint_matrix
            dep_type = constraint.get("type", "")
            outcomes_a = constraint.get("outcomes_a", [])
            outcomes_b = constraint.get("outcomes_b", [])
            feasibility = constraint.get("matrix", [])

            if not outcomes_a or not outcomes_b or not feasibility:
                logger.warning("invalid_constraint_matrix", pair_id=pair.id)
                return {"status": "invalid_constraints"}

            # Skip conditional pairs whose matrix is all-ones (unconstrained),
            # or when skip_conditional is forced — UNLESS the pair was classified
            # via resolution vectors and has a non-trivial matrix (at least one
            # infeasible cell), in which case evaluate it regardless.
            if dep_type == "conditional":
                is_unconstrained = all(
                    feasibility[i][j] == 1
                    for i in range(len(feasibility))
                    for j in range(len(feasibility[0]))
                ) if feasibility else True
                source = constraint.get("classification_source", "")
                vector_with_constraints = (
                    source == "llm_vector" and not is_unconstrained
                )
                if is_unconstrained or (
                    self.skip_conditional and not vector_with_constraints
                ):
                    opp.status = "skipped"
                    await session.commit()
                    logger.info(
                        "skipping_conditional_pair",
                        opportunity_id=opportunity_id,
                        reason="unconstrained" if is_unconstrained else "forced",
                    )
                    return {"status": "skipped", "reason": "conditional_unconstrained"}

            # Fetch latest prices — optimizer uses a looser staleness threshold
            # than the simulator since it's computing fair values, not executing.
            max_age = settings.optimizer_max_snapshot_age_seconds
            prices_a = await _get_latest_prices(session, pair.market_a_id, max_age)
            prices_b = await _get_latest_prices(session, pair.market_b_id, max_age)

            if prices_a is None or prices_b is None:
                logger.warning("missing_prices", pair_id=pair.id)
                return {"status": "no_prices"}

            # Build price vectors aligned with outcomes
            p_a = np.array([prices_a.get(o, 0.5) for o in outcomes_a], dtype=np.float64)
            p_b = np.array([prices_b.get(o, 0.5) for o in outcomes_b], dtype=np.float64)

            # Run Frank-Wolfe
            logger.info(
                "starting_optimization",
                opportunity_id=opportunity_id,
                pair_id=pair.id,
                n_outcomes=f"{len(outcomes_a)}x{len(outcomes_b)}",
            )

            result = optimize(
                prices_a=p_a,
                prices_b=p_b,
                feasibility_matrix=feasibility,
                max_iterations=self.max_iterations,
                gap_tolerance=self.gap_tolerance,
                ip_timeout_ms=self.ip_timeout_ms,
            )

            # Load market venues and fee rates for fee routing
            market_a = await session.get(Market, pair.market_a_id)
            market_b = await session.get(Market, pair.market_b_id)
            v_a = getattr(market_a, "venue", "polymarket") if market_a else "polymarket"
            v_b = getattr(market_b, "venue", "polymarket") if market_b else "polymarket"
            fr_a = getattr(market_a, "fee_rate_bps", None) if market_a else None
            fr_b = getattr(market_b, "fee_rate_bps", None) if market_b else None

            # Compute trades
            theoretical_profit = float(constraint.get("profit_bound", 0.0))
            trade_info = compute_trades(
                result,
                outcomes_a,
                outcomes_b,
                theoretical_profit=theoretical_profit,
                min_edge=self.min_edge,
                venue_a=v_a,
                venue_b=v_b,
                fee_rate_bps_a=fr_a,
                fee_rate_bps_b=fr_b,
            )

            # Update opportunity
            opp.fw_iterations = result.iterations
            opp.bregman_gap = result.final_gap
            opp.estimated_profit = Decimal(str(trade_info["estimated_profit"]))
            opp.optimal_trades = trade_info
            opp.status = "optimized" if result.converged else "unconverged"

            await session.commit()

            # Publish result
            await publish(
                self.redis,
                CHANNEL_OPTIMIZATION_COMPLETE,
                {
                    "opportunity_id": opp.id,
                    "pair_id": pair.id,
                    "status": opp.status,
                    "iterations": result.iterations,
                    "bregman_gap": result.final_gap,
                    "estimated_profit": trade_info["estimated_profit"],
                    "n_trades": len(trade_info["trades"]),
                    "converged": result.converged,
                },
            )

            logger.info(
                "optimization_complete",
                opportunity_id=opp.id,
                status=opp.status,
                iterations=result.iterations,
                gap=result.final_gap,
                estimated_profit=trade_info["estimated_profit"],
            )

            return {
                "status": opp.status,
                "iterations": result.iterations,
                "gap": result.final_gap,
                "estimated_profit": trade_info["estimated_profit"],
                "trades": len(trade_info["trades"]),
            }

    async def process_pending(self) -> dict:
        """Find and optimize all pending (detected) opportunities."""
        stats = {"processed": 0, "optimized": 0, "failed": 0}

        # Expire stale detected opportunities that will never get fresh prices
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update

        async with self.session_factory() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=settings.optimizer_max_snapshot_age_seconds
            )
            expired = await session.execute(
                update(ArbitrageOpportunity)
                .where(
                    ArbitrageOpportunity.status == "detected",
                    ArbitrageOpportunity.timestamp < cutoff,
                )
                .values(status="expired")
                .returning(ArbitrageOpportunity.id)
            )
            expired_ids = [row[0] for row in expired.fetchall()]
            if expired_ids:
                await session.commit()
                logger.info("expired_stale_detected", count=len(expired_ids))

        async with self.session_factory() as session:
            result = await session.execute(
                select(ArbitrageOpportunity.id)
                .where(ArbitrageOpportunity.status == "detected")
                .order_by(ArbitrageOpportunity.timestamp.desc())
                .limit(50)
            )
            opp_ids = [row[0] for row in result.fetchall()]

        for opp_id in opp_ids:
            try:
                result = await self.optimize_opportunity(opp_id)
                stats["processed"] += 1
                if result["status"] in ("optimized", "unconverged"):
                    stats["optimized"] += 1
                else:
                    stats["failed"] += 1
            except Exception:
                logger.exception("optimization_error", opportunity_id=opp_id)
                stats["failed"] += 1

        if stats["processed"] > 0:
            logger.info("batch_optimization_complete", **stats)
        return stats


async def _get_latest_prices(session, market_id: int, max_age_seconds: int = 0) -> dict | None:
    from datetime import datetime, timedelta, timezone

    query = (
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    if max_age_seconds > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        query = query.where(PriceSnapshot.timestamp >= cutoff)
    result = await session.execute(query)
    snapshot = result.scalar_one_or_none()
    return snapshot.prices if snapshot else None
