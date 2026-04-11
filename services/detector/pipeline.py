"""Detection pipeline: similarity → classification → constraint generation."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

import openai
import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.events import CHANNEL_PAIR_DETECTED, CHANNEL_ARBITRAGE_FOUND, publish
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PairClassificationCache,
)
from shared.config import settings
from services.detector.similarity import find_similar_pairs, find_cross_venue_pairs
from services.detector.classifier import classify_pair
from services.detector.constraints import build_constraint_matrix, build_constraint_matrix_from_vectors
from services.detector.verification import verify_pair

logger = structlog.get_logger()


CLASSIFICATION_CACHE_VERSION = "llm-pair-v1"


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
        classifier_prompt_adapter: str = "auto",
    ):
        self.session_factory = session_factory
        self.openai_client = openai_client
        self.redis = redis
        self.similarity_threshold = similarity_threshold
        self.similarity_top_k = similarity_top_k
        self.batch_size = batch_size
        self.classifier_model = classifier_model
        self.classifier_prompt_adapter = classifier_prompt_adapter
        self._rescan_lock = asyncio.Lock()
        self._detection_lock = asyncio.Lock()

    async def _load_classification_cache(
        self,
        session,
        candidates: list[dict],
        markets_by_id: dict[int, Market],
    ) -> dict[tuple[int, int], dict]:
        if not candidates:
            return {}

        pair_keys = list({
            _pair_key(candidate["market_a_id"], candidate["market_b_id"])
            for candidate in candidates
        })
        result = await session.execute(
            select(PairClassificationCache).where(
                PairClassificationCache.classifier_model == self.classifier_model,
                PairClassificationCache.prompt_adapter == self.classifier_prompt_adapter,
                PairClassificationCache.cache_version == CLASSIFICATION_CACHE_VERSION,
                tuple_(
                    PairClassificationCache.market_a_id,
                    PairClassificationCache.market_b_id,
                ).in_(pair_keys),
            )
        )

        cached: dict[tuple[int, int], dict] = {}
        for row in result.scalars().all():
            market_a = markets_by_id.get(row.market_a_id)
            market_b = markets_by_id.get(row.market_b_id)
            if not market_a or not market_b:
                continue

            market_a_dict = _market_to_dict(market_a)
            market_b_dict = _market_to_dict(market_b)
            if (
                row.market_a_fingerprint != _market_fingerprint(market_a_dict)
                or row.market_b_fingerprint != _market_fingerprint(market_b_dict)
            ):
                continue

            classification = row.classification or {}
            if isinstance(classification, dict):
                cached[(row.market_a_id, row.market_b_id)] = classification

        return cached

    async def _flush_classification_cache(
        self,
        session,
        cache_rows: list[dict],
    ) -> None:
        if not cache_rows:
            return

        stmt = insert(PairClassificationCache).values(cache_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                "market_a_id",
                "market_b_id",
                "classifier_model",
                "prompt_adapter",
                "cache_version",
            ],
            set_={
                "market_a_fingerprint": stmt.excluded.market_a_fingerprint,
                "market_b_fingerprint": stmt.excluded.market_b_fingerprint,
                "classification": stmt.excluded.classification,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(stmt)

    async def run_once(self) -> dict:
        """Execute one full detection cycle. Returns stats dict.

        Serialized via _detection_lock so concurrent triggers (periodic +
        market-sync event) don't duplicate classification work or collide
        on the market_pairs unique index.
        """
        async with self._detection_lock:
            return await self._run_once_inner()

    async def _run_once_inner(self) -> dict:
        stats = {"candidates": 0, "pairs_created": 0, "opportunities": 0}
        deferred_events: list[tuple[str, dict]] = []

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
            cached_classifications = await self._load_classification_cache(
                session,
                candidates,
                markets_by_id,
            )
            cache_rows: list[dict] = []

            # Step 2 & 3: Classify each pair and generate constraints
            for candidate in candidates:
                market_a = markets_by_id.get(candidate["market_a_id"])
                market_b = markets_by_id.get(candidate["market_b_id"])
                if not market_a or not market_b:
                    continue

                market_a_dict = _market_to_dict(market_a)
                market_b_dict = _market_to_dict(market_b)
                pair_key = _pair_key(market_a.id, market_b.id)

                classification = cached_classifications.get(pair_key)
                if classification is None:
                    classification = await classify_pair(
                        self.openai_client,
                        self.classifier_model,
                        market_a_dict,
                        market_b_dict,
                        prompt_adapter=self.classifier_prompt_adapter,
                    )
                    cache_row = _build_cache_row(
                        market_a_dict,
                        market_b_dict,
                        classification,
                        classifier_model=self.classifier_model,
                        prompt_adapter=self.classifier_prompt_adapter,
                    )
                    if cache_row is not None:
                        cache_rows.append(cache_row)
                        cached_classifications[pair_key] = classification

                if classification["dependency_type"] == "none":
                    continue

                # Get latest prices for profit computation
                prices_a = await _get_latest_prices(session, market_a.id, settings.max_snapshot_age_seconds)
                prices_b = await _get_latest_prices(session, market_b.id, settings.max_snapshot_age_seconds)

                # Uncertainty filter: skip near-resolved markets
                if prices_a and prices_b and not _passes_uncertainty_filter(
                    prices_a, prices_b, market_a_dict["outcomes"], market_b_dict["outcomes"]
                ):
                    logger.info(
                        "uncertainty_filter_rejected",
                        market_a_id=market_a.id,
                        market_b_id=market_b.id,
                    )
                    continue

                # Build constraint matrix — use vectors directly when available
                fr_a = market_a_dict.get("fee_rate_bps")
                fr_b = market_b_dict.get("fee_rate_bps")
                if classification.get("valid_outcomes"):
                    constraint = build_constraint_matrix_from_vectors(
                        classification["valid_outcomes"],
                        market_a_dict["outcomes"],
                        market_b_dict["outcomes"],
                        dependency_type=classification["dependency_type"],
                        prices_a=prices_a,
                        prices_b=prices_b,
                        correlation=classification.get("correlation"),
                        implication_direction=classification.get("implication_direction"),
                        venue_a=market_a_dict.get("venue", "polymarket"),
                        venue_b=market_b_dict.get("venue", "polymarket"),
                        fee_rate_bps_a=fr_a,
                        fee_rate_bps_b=fr_b,
                    )
                else:
                    constraint = build_constraint_matrix(
                        classification["dependency_type"],
                        market_a_dict["outcomes"],
                        market_b_dict["outcomes"],
                        prices_a,
                        prices_b,
                        correlation=classification.get("correlation"),
                        venue_a=market_a_dict.get("venue", "polymarket"),
                        venue_b=market_b_dict.get("venue", "polymarket"),
                        implication_direction=classification.get("implication_direction"),
                        fee_rate_bps_a=fr_a,
                        fee_rate_bps_b=fr_b,
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
                    implication_direction=classification.get("implication_direction"),
                )

                # Persist market pair
                pair = MarketPair(
                    market_a_id=market_a.id,
                    market_b_id=market_b.id,
                    dependency_type=classification["dependency_type"],
                    confidence=classification["confidence"],
                    constraint_matrix=constraint,
                    resolution_vectors=classification.get("valid_outcomes"),
                    implication_direction=classification.get("implication_direction"),
                    classification_source=classification.get("classification_source"),
                    verified=verification["verified"],
                )
                session.add(pair)
                await session.flush()
                stats["pairs_created"] += 1

                deferred_events.append((
                    CHANNEL_PAIR_DETECTED,
                    {
                        "pair_id": pair.id,
                        "market_a_id": market_a.id,
                        "market_b_id": market_b.id,
                        "dependency_type": classification["dependency_type"],
                        "confidence": classification["confidence"],
                    },
                ))

                # If there's a theoretical profit on a verified pair, record an opportunity
                profit = constraint.get("profit_bound", 0.0)
                if profit > 0 and verification["verified"]:
                    opp = ArbitrageOpportunity(
                        pair_id=pair.id,
                        type="rebalancing",
                        theoretical_profit=Decimal(str(profit)),
                        status="detected",
                        dependency_type=pair.dependency_type,
                    )
                    session.add(opp)
                    await session.flush()
                    stats["opportunities"] += 1

                    deferred_events.append((
                        CHANNEL_ARBITRAGE_FOUND,
                        {
                            "opportunity_id": opp.id,
                            "pair_id": pair.id,
                            "type": "rebalancing",
                            "theoretical_profit": float(profit),
                        },
                    ))

            await self._flush_classification_cache(session, cache_rows)
            await session.commit()

        # Publish events after commit so downstream consumers can read the rows
        for channel, payload in deferred_events:
            await publish(self.redis, channel, payload)

        # Cross-venue detection (Kalshi ↔ Polymarket) if enabled
        if settings.kalshi_enabled:
            cross_stats = await self._detect_cross_venue()
            stats["cross_venue_candidates"] = cross_stats.get("candidates", 0)
            stats["pairs_created"] += cross_stats.get("pairs_created", 0)
            stats["opportunities"] += cross_stats.get("opportunities", 0)

        logger.info("detection_cycle_complete", **stats)

        # Also rescan existing pairs that now have prices
        rescan_stats = await self._rescan_existing_pairs()
        stats["rescanned"] = rescan_stats["opportunities"]

        return stats

    async def _detect_cross_venue(self) -> dict:
        """Find and classify cross-venue pairs (Kalshi ↔ Polymarket).

        Runs separately from intra-venue detection with its own session.
        Uses a higher similarity threshold (0.92) for auto-classification.
        """
        stats = {"candidates": 0, "pairs_created": 0, "opportunities": 0}
        deferred_events: list[tuple[str, dict]] = []

        async with self.session_factory() as session:
            candidates = await find_cross_venue_pairs(
                session,
                threshold=max(self.similarity_threshold, 0.82),
                top_k=self.similarity_top_k,
            )
            stats["candidates"] = len(candidates)

            if not candidates:
                return stats

            market_ids = set()
            for c in candidates:
                market_ids.add(c["market_a_id"])
                market_ids.add(c["market_b_id"])

            result = await session.execute(
                select(Market).where(Market.id.in_(market_ids))
            )
            markets_by_id = {m.id: m for m in result.scalars().all()}
            cached_classifications = await self._load_classification_cache(
                session,
                candidates,
                markets_by_id,
            )
            cache_rows: list[dict] = []

            for candidate in candidates:
                market_a = markets_by_id.get(candidate["market_a_id"])
                market_b = markets_by_id.get(candidate["market_b_id"])
                if not market_a or not market_b:
                    continue

                market_a_dict = _market_to_dict(market_a)
                market_b_dict = _market_to_dict(market_b)
                similarity = candidate["similarity"]
                pair_key = _pair_key(market_a.id, market_b.id)

                # High similarity → auto-classify as cross_platform
                # Moderate similarity → use LLM to verify
                # Threshold 0.95 to avoid matching markets with same topic
                # but different resolution criteria (dates, thresholds)
                if similarity >= 0.95:
                    classification = {
                        "dependency_type": "cross_platform",
                        "confidence": 0.95,
                        "reasoning": f"Cross-venue match (similarity={similarity:.3f})",
                    }
                else:
                    classification = cached_classifications.get(pair_key)
                    if classification is None:
                        classification = await classify_pair(
                            self.openai_client,
                            self.classifier_model,
                            market_a_dict,
                            market_b_dict,
                            prompt_adapter=self.classifier_prompt_adapter,
                        )
                        cache_row = _build_cache_row(
                            market_a_dict,
                            market_b_dict,
                            classification,
                            classifier_model=self.classifier_model,
                            prompt_adapter=self.classifier_prompt_adapter,
                        )
                        if cache_row is not None:
                            cache_rows.append(cache_row)
                            cached_classifications[pair_key] = classification

                if classification["dependency_type"] == "none":
                    continue

                prices_a = await _get_latest_prices(session, market_a.id, settings.max_snapshot_age_seconds)
                prices_b = await _get_latest_prices(session, market_b.id, settings.max_snapshot_age_seconds)

                fr_a = market_a_dict.get("fee_rate_bps")
                fr_b = market_b_dict.get("fee_rate_bps")
                if classification.get("valid_outcomes"):
                    constraint = build_constraint_matrix_from_vectors(
                        classification["valid_outcomes"],
                        market_a_dict["outcomes"],
                        market_b_dict["outcomes"],
                        dependency_type=classification["dependency_type"],
                        prices_a=prices_a,
                        prices_b=prices_b,
                        correlation=classification.get("correlation"),
                        implication_direction=classification.get("implication_direction"),
                        venue_a=market_a_dict.get("venue", "polymarket"),
                        venue_b=market_b_dict.get("venue", "polymarket"),
                        fee_rate_bps_a=fr_a,
                        fee_rate_bps_b=fr_b,
                    )
                else:
                    constraint = build_constraint_matrix(
                        classification["dependency_type"],
                        market_a_dict["outcomes"],
                        market_b_dict["outcomes"],
                        prices_a,
                        prices_b,
                        correlation=classification.get("correlation"),
                        venue_a=market_a_dict.get("venue", "polymarket"),
                        venue_b=market_b_dict.get("venue", "polymarket"),
                        implication_direction=classification.get("implication_direction"),
                        fee_rate_bps_a=fr_a,
                        fee_rate_bps_b=fr_b,
                    )

                verification = verify_pair(
                    dependency_type=classification["dependency_type"],
                    market_a=market_a_dict,
                    market_b=market_b_dict,
                    prices_a=prices_a,
                    prices_b=prices_b,
                    confidence=classification["confidence"],
                    correlation=classification.get("correlation"),
                    implication_direction=classification.get("implication_direction"),
                )

                pair = MarketPair(
                    market_a_id=market_a.id,
                    market_b_id=market_b.id,
                    dependency_type=classification["dependency_type"],
                    confidence=classification["confidence"],
                    constraint_matrix=constraint,
                    resolution_vectors=classification.get("valid_outcomes"),
                    implication_direction=classification.get("implication_direction"),
                    classification_source=classification.get("classification_source"),
                    verified=verification["verified"],
                )
                session.add(pair)
                await session.flush()
                stats["pairs_created"] += 1

                deferred_events.append((
                    CHANNEL_PAIR_DETECTED,
                    {
                        "pair_id": pair.id,
                        "market_a_id": market_a.id,
                        "market_b_id": market_b.id,
                        "dependency_type": classification["dependency_type"],
                        "confidence": classification["confidence"],
                    },
                ))

                profit = constraint.get("profit_bound", 0.0)
                if profit > 0 and verification["verified"]:
                    opp = ArbitrageOpportunity(
                        pair_id=pair.id,
                        type="rebalancing",
                        theoretical_profit=Decimal(str(profit)),
                        status="detected",
                        dependency_type=pair.dependency_type,
                    )
                    session.add(opp)
                    await session.flush()
                    stats["opportunities"] += 1

                    deferred_events.append((
                        CHANNEL_ARBITRAGE_FOUND,
                        {
                            "opportunity_id": opp.id,
                            "pair_id": pair.id,
                            "type": "rebalancing",
                            "theoretical_profit": float(profit),
                        },
                    ))

            await self._flush_classification_cache(session, cache_rows)
            await session.commit()

        for channel, payload in deferred_events:
            await publish(self.redis, channel, payload)

        if stats["pairs_created"] > 0:
            logger.info("cross_venue_detection_complete", **stats)
        return stats

    async def _rescan_existing_pairs(self) -> dict:
        """Re-evaluate existing pairs that have prices but no opportunities."""
        stats = {"opportunities": 0}
        deferred_events: list[dict] = []

        async with self._rescan_lock, self.session_factory() as session:
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
                if not pair.verified:
                    continue

                prices_a = await _get_latest_prices(session, pair.market_a_id, settings.max_snapshot_age_seconds)
                prices_b = await _get_latest_prices(session, pair.market_b_id, settings.max_snapshot_age_seconds)

                if not prices_a or not prices_b:
                    continue

                constraint = pair.constraint_matrix
                if not constraint:
                    continue

                outcomes_a = constraint.get("outcomes_a", [])
                outcomes_b = constraint.get("outcomes_b", [])

                # Recompute profit bound with actual prices
                market_a_obj = await session.get(Market, pair.market_a_id)
                market_b_obj = await session.get(Market, pair.market_b_id)
                fresh_constraint = _rebuild_constraint_for_pair(
                    pair, outcomes_a, outcomes_b, prices_a, prices_b,
                    venue_a=getattr(market_a_obj, "venue", "polymarket"),
                    venue_b=getattr(market_b_obj, "venue", "polymarket"),
                )

                # Update stored constraint with fresh profit data
                pair.constraint_matrix = fresh_constraint

                # Re-verify pair with fresh prices (BT-018)
                market_a_dict = _market_to_dict(market_a_obj)
                market_b_dict = _market_to_dict(market_b_obj)
                re_verification = verify_pair(
                    dependency_type=pair.dependency_type,
                    market_a=market_a_dict,
                    market_b=market_b_dict,
                    prices_a=prices_a,
                    prices_b=prices_b,
                    confidence=pair.confidence,
                    correlation=fresh_constraint.get("correlation"),
                    implication_direction=fresh_constraint.get("implication_direction"),
                )
                if not re_verification["verified"]:
                    pair.verified = False
                    logger.info("pair_unverified_on_rescan", pair_id=pair.id, reasons=re_verification["reasons"])
                    continue

                profit = fresh_constraint.get("profit_bound", 0.0)

                if profit <= 0:
                    continue

                opp = ArbitrageOpportunity(
                    pair_id=pair.id,
                    type="rebalancing",
                    theoretical_profit=Decimal(str(profit)),
                    status="detected",
                    dependency_type=pair.dependency_type,
                )
                session.add(opp)
                try:
                    await session.flush()
                except IntegrityError:
                    await session.rollback()
                    logger.info(
                        "rescan_duplicate_skipped", pair_id=pair.id
                    )
                    continue
                stats["opportunities"] += 1

                deferred_events.append({
                    "opportunity_id": opp.id,
                    "pair_id": pair.id,
                    "type": "rebalancing",
                    "theoretical_profit": float(profit),
                })

            await session.commit()

        # Publish after commit so optimizer can read the rows
        for payload in deferred_events:
            await publish(self.redis, CHANNEL_ARBITRAGE_FOUND, payload)

        if stats["opportunities"] > 0:
            logger.info("rescan_complete", **stats)
        return stats

    async def rescan_by_market_ids(self, market_ids: set[int]) -> dict:
        """Re-evaluate verified pairs involving specific markets with fresh prices.

        Lightweight: no pgvector search, no LLM classification. Only recomputes
        profit bounds for existing pairs where at least one market just got a
        price update.

        Two behaviours depending on whether the pair has an in-flight opportunity:
        - No in-flight opp: create a new detected opportunity if profit > 0.
        - Has optimized/unconverged opp (blocked by breaker, waiting for retry):
          refresh the pair's constraint matrix and reset the opp to detected so
          the optimizer re-plans with current prices instead of stale trades.
        - Has pending opp (simulator mid-execution): skip — don't pull the rug.
        - Has detected opp: just refresh the constraint matrix (optimizer hasn't
          run yet, it will read the updated matrix).
        """
        stats = {"opportunities": 0, "pairs_checked": 0, "refreshed": 0}
        deferred_events: list[dict] = []

        async with self._rescan_lock, self.session_factory() as session:
            # Fetch all verified pairs affected by these market IDs
            result = await session.execute(
                select(MarketPair)
                .where(
                    MarketPair.verified == True,  # noqa: E712
                    (MarketPair.market_a_id.in_(market_ids))
                    | (MarketPair.market_b_id.in_(market_ids)),
                )
            )
            pairs = result.scalars().all()
            stats["pairs_checked"] = len(pairs)

            # Load in-flight opportunities for these pairs in one query
            pair_ids = [p.id for p in pairs]
            if pair_ids:
                opp_result = await session.execute(
                    select(ArbitrageOpportunity)
                    .where(
                        ArbitrageOpportunity.pair_id.in_(pair_ids),
                        ArbitrageOpportunity.status.in_(
                            ["detected", "pending", "optimized", "unconverged"]
                        ),
                    )
                )
                in_flight_opps = {
                    opp.pair_id: opp for opp in opp_result.scalars().all()
                }
            else:
                in_flight_opps = {}

            for pair in pairs:
                constraint = pair.constraint_matrix
                if not constraint:
                    continue

                prices_a = await _get_latest_prices(session, pair.market_a_id, settings.max_snapshot_age_seconds)
                prices_b = await _get_latest_prices(session, pair.market_b_id, settings.max_snapshot_age_seconds)
                if not prices_a or not prices_b:
                    continue

                outcomes_a = constraint.get("outcomes_a", [])
                outcomes_b = constraint.get("outcomes_b", [])

                market_a_obj = await session.get(Market, pair.market_a_id)
                market_b_obj = await session.get(Market, pair.market_b_id)
                fresh_constraint = _rebuild_constraint_for_pair(
                    pair, outcomes_a, outcomes_b, prices_a, prices_b,
                    venue_a=getattr(market_a_obj, "venue", "polymarket"),
                    venue_b=getattr(market_b_obj, "venue", "polymarket"),
                )
                pair.constraint_matrix = fresh_constraint

                # Re-verify pair with fresh prices (BT-018)
                market_a_dict = _market_to_dict(market_a_obj)
                market_b_dict = _market_to_dict(market_b_obj)
                re_verification = verify_pair(
                    dependency_type=pair.dependency_type,
                    market_a=market_a_dict,
                    market_b=market_b_dict,
                    prices_a=prices_a,
                    prices_b=prices_b,
                    confidence=pair.confidence,
                    correlation=fresh_constraint.get("correlation"),
                    implication_direction=fresh_constraint.get("implication_direction"),
                )
                if not re_verification["verified"]:
                    pair.verified = False
                    logger.info("pair_unverified_on_rescan", pair_id=pair.id, reasons=re_verification["reasons"])
                    continue

                profit = fresh_constraint.get("profit_bound", 0.0)

                existing_opp = in_flight_opps.get(pair.id)
                if existing_opp:
                    # Don't touch pending opps — simulator is mid-execution
                    if existing_opp.status == "pending":
                        continue

                    # Mark expired when profit disappears (duration tracking)
                    if profit <= 0 and not existing_opp.expired_at:
                        existing_opp.expired_at = datetime.now(timezone.utc)
                        existing_opp.theoretical_profit = Decimal("0")
                        existing_opp.estimated_profit = Decimal("0")
                        existing_opp.optimal_trades = None
                        existing_opp.status = "expired"
                        stats["expired"] = stats.get("expired", 0) + 1
                        logger.info(
                            "opportunity_expired",
                            opportunity_id=existing_opp.id,
                            pair_id=pair.id,
                            duration_seconds=(
                                existing_opp.expired_at - existing_opp.timestamp
                            ).total_seconds(),
                        )
                        continue

                    # Refresh the existing opportunity with current profit
                    existing_opp.theoretical_profit = Decimal(
                        str(max(profit, 0))
                    )
                    # Reset optimized/unconverged back to detected so the
                    # optimizer re-plans with fresh prices instead of stale
                    # trades that may execute against moved markets.
                    if existing_opp.status in ("optimized", "unconverged"):
                        existing_opp.status = "detected"
                        existing_opp.optimal_trades = None
                        existing_opp.fw_iterations = None
                        existing_opp.bregman_gap = None
                        # Emit arb event so optimizer picks it up reactively
                        deferred_events.append({
                            "opportunity_id": existing_opp.id,
                            "pair_id": pair.id,
                            "type": "rebalancing",
                            "theoretical_profit": float(max(profit, 0)),
                        })
                    stats["refreshed"] += 1
                elif profit > 0:
                    opp = ArbitrageOpportunity(
                        pair_id=pair.id,
                        type="rebalancing",
                        theoretical_profit=Decimal(str(profit)),
                        status="detected",
                        dependency_type=pair.dependency_type,
                    )
                    session.add(opp)
                    try:
                        await session.flush()
                    except IntegrityError:
                        # Unique index violation — another loop already
                        # created an in-flight opp for this pair.  Roll
                        # back the failed INSERT and continue with the
                        # rest of the batch instead of aborting.
                        await session.rollback()
                        logger.info(
                            "rescan_duplicate_skipped", pair_id=pair.id
                        )
                        continue
                    stats["opportunities"] += 1

                    deferred_events.append({
                        "opportunity_id": opp.id,
                        "pair_id": pair.id,
                        "type": "rebalancing",
                        "theoretical_profit": float(profit),
                    })

            await session.commit()

        # Publish after commit so optimizer/simulator can read the rows
        for payload in deferred_events:
            await publish(self.redis, CHANNEL_ARBITRAGE_FOUND, payload)

        if stats["opportunities"] > 0 or stats["refreshed"] > 0:
            logger.info("snapshot_rescan_complete", **stats)
        return stats


def _market_to_dict(market: Market) -> dict:
    return {
        "id": market.id,
        "event_id": market.event_id,
        "question": market.question,
        "description": market.description,
        "outcomes": market.outcomes if isinstance(market.outcomes, list) else [],
        "venue": getattr(market, "venue", "polymarket"),
        "fee_rate_bps": getattr(market, "fee_rate_bps", None),
    }


def _pair_key(market_a_id: int, market_b_id: int) -> tuple[int, int]:
    return (min(market_a_id, market_b_id), max(market_a_id, market_b_id))


def _market_fingerprint(market: dict) -> str:
    payload = {
        "event_id": market.get("event_id"),
        "question": market.get("question"),
        "description": market.get("description"),
        "outcomes": list(market.get("outcomes") or []),
        "venue": market.get("venue", "polymarket"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_cache_row(
    market_a: dict,
    market_b: dict,
    classification: dict,
    *,
    classifier_model: str,
    prompt_adapter: str,
) -> dict | None:
    if classification.get("classification_source") not in {"llm_vector", "llm_label"}:
        return None

    market_a_id, market_b_id = _pair_key(market_a["id"], market_b["id"])
    canonical_a = market_a if market_a["id"] == market_a_id else market_b
    canonical_b = market_b if market_b["id"] == market_b_id else market_a

    return {
        "market_a_id": market_a_id,
        "market_b_id": market_b_id,
        "classifier_model": classifier_model,
        "prompt_adapter": prompt_adapter,
        "cache_version": CLASSIFICATION_CACHE_VERSION,
        "market_a_fingerprint": _market_fingerprint(canonical_a),
        "market_b_fingerprint": _market_fingerprint(canonical_b),
        "classification": classification,
    }


def _rebuild_constraint_for_pair(
    pair,
    outcomes_a,
    outcomes_b,
    prices_a,
    prices_b,
    venue_a="polymarket",
    venue_b="polymarket",
):
    """Rebuild constraint matrix using vectors if available, else label-based.

    Ensures rescan/refresh paths preserve the richer vector-derived matrix
    instead of falling back to the coarser heuristic builder.
    """
    constraint = pair.constraint_matrix or {}
    correlation = constraint.get("correlation")
    # Prefer the column value (set by rule-based classifier) over the
    # constraint JSON (which may be stale or null-defaulted to a_implies_b).
    imp_direction = pair.implication_direction or constraint.get("implication_direction")

    if pair.resolution_vectors:
        return build_constraint_matrix_from_vectors(
            pair.resolution_vectors,
            outcomes_a,
            outcomes_b,
            dependency_type=pair.dependency_type,
            prices_a=prices_a,
            prices_b=prices_b,
            correlation=correlation,
            implication_direction=imp_direction,
            venue_a=venue_a,
            venue_b=venue_b,
        )

    return build_constraint_matrix(
        pair.dependency_type,
        outcomes_a,
        outcomes_b,
        prices_a,
        prices_b,
        correlation=correlation,
        venue_a=venue_a,
        venue_b=venue_b,
        implication_direction=imp_direction,
    )


def _passes_uncertainty_filter(
    prices_a: dict, prices_b: dict,
    outcomes_a: list[str], outcomes_b: list[str],
) -> bool:
    """Reject pairs where any binary market is near-certain (< floor or > ceil).

    Near-resolved markets have sub-5-cent margins that get eaten by fees
    and slippage. Filter early to avoid wasting optimizer cycles.

    Only applies to binary markets (2 outcomes). Multi-outcome markets
    naturally have low-probability tails that are not indicative of
    near-resolution.
    """
    floor = settings.uncertainty_price_floor
    ceil = settings.uncertainty_price_ceil

    for outcomes, prices in [(outcomes_a, prices_a), (outcomes_b, prices_b)]:
        # Skip multi-outcome markets — low tails are normal pricing
        if len(outcomes) > 2:
            continue
        for outcome in outcomes:
            try:
                p = float(prices.get(outcome, 0.5))
            except (TypeError, ValueError):
                continue
            if p < floor or p > ceil:
                return False
            # Check implied complement for single-sided data
            complement = 1.0 - p
            if complement < floor or complement > ceil:
                return False
    return True


async def _get_latest_prices(session, market_id: int, max_age_seconds: int = 0) -> dict | None:
    """Fetch the most recent price snapshot for a market."""
    from datetime import timedelta
    from shared.models import PriceSnapshot

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
