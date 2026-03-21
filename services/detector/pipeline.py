"""Detection pipeline: similarity → classification → constraint generation."""

from decimal import Decimal

import openai
import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.events import CHANNEL_PAIR_DETECTED, CHANNEL_ARBITRAGE_FOUND, publish
from shared.models import ArbitrageOpportunity, Market, MarketPair
from services.detector.similarity import find_similar_pairs
from services.detector.classifier import classify_pair
from services.detector.constraints import build_constraint_matrix
from services.detector.verification import verify_pair

logger = structlog.get_logger()


class DetectionPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        openai_client: openai.AsyncOpenAI,
        redis: aioredis.Redis,
        similarity_threshold: float,
        similarity_top_k: int,
        batch_size: int,
        classifier_model: str,
    ):
        self.session_factory = session_factory
        self.openai_client = openai_client
        self.redis = redis
        self.similarity_threshold = similarity_threshold
        self.similarity_top_k = similarity_top_k
        self.batch_size = batch_size
        self.classifier_model = classifier_model

    async def run_once(self) -> dict:
        """Execute one full detection cycle. Returns stats dict."""
        stats = {"candidates": 0, "pairs_created": 0, "opportunities": 0}

        async with self.session_factory() as session:
            # Step 1: Find similar market pairs via pgvector
            candidates = await find_similar_pairs(
                session,
                self.similarity_threshold,
                self.similarity_top_k,
                self.batch_size,
            )
            stats["candidates"] = len(candidates)

            if not candidates:
                logger.info("no_new_candidates")
                return stats

            # Load market data for all candidate IDs
            market_ids = set()
            for c in candidates:
                market_ids.add(c["market_a_id"])
                market_ids.add(c["market_b_id"])

            result = await session.execute(
                select(Market).where(Market.id.in_(market_ids))
            )
            markets_by_id = {m.id: m for m in result.scalars().all()}

            # Step 2 & 3: Classify each pair and generate constraints
            for candidate in candidates:
                market_a = markets_by_id.get(candidate["market_a_id"])
                market_b = markets_by_id.get(candidate["market_b_id"])
                if not market_a or not market_b:
                    continue

                market_a_dict = _market_to_dict(market_a)
                market_b_dict = _market_to_dict(market_b)

                # Classify dependency
                classification = await classify_pair(
                    self.openai_client,
                    self.classifier_model,
                    market_a_dict,
                    market_b_dict,
                )

                if classification["dependency_type"] == "none":
                    continue

                # Get latest prices for profit computation
                prices_a = await _get_latest_prices(session, market_a.id)
                prices_b = await _get_latest_prices(session, market_b.id)

                # Build constraint matrix
                constraint = build_constraint_matrix(
                    classification["dependency_type"],
                    market_a_dict["outcomes"],
                    market_b_dict["outcomes"],
                    prices_a,
                    prices_b,
                    correlation=classification.get("correlation"),
                )

                # Verify pair before persisting
                verification = verify_pair(
                    dependency_type=classification["dependency_type"],
                    market_a=market_a_dict,
                    market_b=market_b_dict,
                    prices_a=prices_a,
                    prices_b=prices_b,
                    confidence=classification["confidence"],
                    correlation=classification.get("correlation"),
                )

                # Persist market pair
                pair = MarketPair(
                    market_a_id=market_a.id,
                    market_b_id=market_b.id,
                    dependency_type=classification["dependency_type"],
                    confidence=classification["confidence"],
                    constraint_matrix=constraint,
                    verified=verification["verified"],
                )
                session.add(pair)
                await session.flush()
                stats["pairs_created"] += 1

                await publish(
                    self.redis,
                    CHANNEL_PAIR_DETECTED,
                    {
                        "pair_id": pair.id,
                        "market_a_id": market_a.id,
                        "market_b_id": market_b.id,
                        "dependency_type": classification["dependency_type"],
                        "confidence": classification["confidence"],
                    },
                )

                # If there's a theoretical profit on a verified pair, record an opportunity
                profit = constraint.get("profit_bound", 0.0)
                if profit > 0 and verification["verified"]:
                    opp = ArbitrageOpportunity(
                        pair_id=pair.id,
                        type="rebalancing",
                        theoretical_profit=Decimal(str(profit)),
                        status="detected",
                    )
                    session.add(opp)
                    await session.flush()
                    stats["opportunities"] += 1

                    await publish(
                        self.redis,
                        CHANNEL_ARBITRAGE_FOUND,
                        {
                            "opportunity_id": opp.id,
                            "pair_id": pair.id,
                            "type": "rebalancing",
                            "theoretical_profit": float(profit),
                        },
                    )

            await session.commit()

        logger.info("detection_cycle_complete", **stats)

        # Also rescan existing pairs that now have prices
        rescan_stats = await self._rescan_existing_pairs()
        stats["rescanned"] = rescan_stats["opportunities"]

        return stats

    async def _rescan_existing_pairs(self) -> dict:
        """Re-evaluate existing pairs that have prices but no opportunities."""
        stats = {"opportunities": 0}

        async with self.session_factory() as session:
            # Find pairs with no opportunities that now have price data
            from shared.models import PriceSnapshot

            result = await session.execute(
                select(MarketPair)
                .where(
                    ~MarketPair.id.in_(
                        select(ArbitrageOpportunity.pair_id).distinct()
                    )
                )
            )
            pairs = result.scalars().all()

            for pair in pairs:
                prices_a = await _get_latest_prices(session, pair.market_a_id)
                prices_b = await _get_latest_prices(session, pair.market_b_id)

                if not prices_a or not prices_b:
                    continue

                constraint = pair.constraint_matrix
                if not constraint:
                    continue

                outcomes_a = constraint.get("outcomes_a", [])
                outcomes_b = constraint.get("outcomes_b", [])

                # Recompute profit bound with actual prices
                from services.detector.constraints import build_constraint_matrix
                correlation = constraint.get("correlation")
                fresh_constraint = build_constraint_matrix(
                    pair.dependency_type, outcomes_a, outcomes_b, prices_a, prices_b,
                    correlation=correlation,
                )

                # Update stored constraint with fresh profit data
                pair.constraint_matrix = fresh_constraint

                profit = fresh_constraint.get("profit_bound", 0.0)

                # Create opportunity even if profit is 0 — let the optimizer decide
                opp = ArbitrageOpportunity(
                    pair_id=pair.id,
                    type="rebalancing",
                    theoretical_profit=Decimal(str(max(profit, 0.001))),
                    status="detected",
                )
                session.add(opp)
                await session.flush()
                stats["opportunities"] += 1

                await publish(
                    self.redis,
                    CHANNEL_ARBITRAGE_FOUND,
                    {
                        "opportunity_id": opp.id,
                        "pair_id": pair.id,
                        "type": "rebalancing",
                        "theoretical_profit": float(profit),
                    },
                )

            await session.commit()

        if stats["opportunities"] > 0:
            logger.info("rescan_complete", **stats)
        return stats


def _market_to_dict(market: Market) -> dict:
    return {
        "id": market.id,
        "event_id": market.event_id,
        "question": market.question,
        "description": market.description,
        "outcomes": market.outcomes if isinstance(market.outcomes, list) else [],
    }


async def _get_latest_prices(session, market_id: int) -> dict | None:
    """Fetch the most recent price snapshot for a market."""
    from shared.models import PriceSnapshot

    result = await session.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    return snapshot.prices if snapshot else None
