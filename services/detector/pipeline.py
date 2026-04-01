"""Detection pipeline: similarity → classification → constraint generation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import openai
import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.events import CHANNEL_PAIR_DETECTED, CHANNEL_ARBITRAGE_FOUND, publish
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PriceSnapshot,
    ShadowCandidateLog,
)
from shared.config import settings
from services.detector.similarity import find_similar_pairs, find_cross_venue_pairs
from services.detector.classifier import classify_pair
from services.detector.constraints import build_constraint_matrix, build_constraint_matrix_from_vectors
from services.detector.shadow_logging import (
    derive_silver_failure_signature,
    extract_order_book_summary,
    preview_trade_gates,
)
from services.detector.verification import verify_pair

logger = structlog.get_logger()


async def _invalidate_open_opportunities_for_pair(session, pair_id: int) -> int:
    """Skip stale opportunities when a pair fails re-verification."""
    result = await session.execute(
        update(ArbitrageOpportunity)
        .where(
            ArbitrageOpportunity.pair_id == pair_id,
            ArbitrageOpportunity.status.in_(("detected", "optimized", "unconverged")),
        )
        .values(status="skipped")
        .returning(ArbitrageOpportunity.id)
    )
    invalidated = [row[0] for row in result.fetchall()]
    if invalidated:
        logger.info(
            "invalidated_stale_opportunities",
            pair_id=pair_id,
            count=len(invalidated),
            opportunity_ids=invalidated,
        )
    return len(invalidated)


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

    async def _log_shadow_candidate(
        self,
        session,
        *,
        pipeline_source: str,
        similarity: float | None,
        market_a: Market,
        market_b: Market,
        snapshot_a: PriceSnapshot | None,
        snapshot_b: PriceSnapshot | None,
        classification: dict,
        decision_outcome: str,
        verification: dict | None = None,
        constraint: dict | None = None,
        pair_id: int | None = None,
        opportunity_id: int | None = None,
    ) -> None:
        if not _bool_setting("shadow_logging_enabled", False):
            return

        prices_a = snapshot_a.prices if snapshot_a else None
        prices_b = snapshot_b.prices if snapshot_b else None
        summary_a = extract_order_book_summary(snapshot_a.order_book if snapshot_a else None)
        summary_b = extract_order_book_summary(snapshot_b.order_book if snapshot_b else None)
        verification_reasons = verification.get("reasons") if verification else None
        silver_failure_signature = derive_silver_failure_signature(verification_reasons)

        profit = None
        passed_to_optimization = False
        preview_status = None
        preview_estimated_profit = None
        preview_trade_count = None
        preview_max_edge = None
        preview_rejection_reason = None
        would_trade = False

        if constraint:
            raw_profit = constraint.get("profit_bound")
            if raw_profit is not None:
                profit = Decimal(str(raw_profit))

        if verification and verification.get("verified") and profit and profit > 0:
            passed_to_optimization = True
            if _bool_setting("shadow_logging_optimizer_preview", True):
                preview = preview_trade_gates(
                    constraint,
                    prices_a,
                    prices_b,
                    venue_a=getattr(market_a, "venue", "polymarket"),
                    venue_b=getattr(market_b, "venue", "polymarket"),
                    min_edge=settings.optimizer_min_edge,
                    max_iterations=settings.fw_max_iterations,
                    gap_tolerance=settings.fw_gap_tolerance,
                    ip_timeout_ms=settings.fw_ip_timeout_ms,
                    skip_conditional=settings.optimizer_skip_conditional,
                )
                preview_status = preview.get("status")
                if preview.get("estimated_profit") is not None:
                    preview_estimated_profit = Decimal(
                        str(preview["estimated_profit"])
                    )
                preview_trade_count = preview.get("trade_count")
                preview_max_edge = preview.get("max_edge")
                preview_rejection_reason = preview.get("rejection_reason")
                would_trade = bool(preview.get("would_trade"))
                if would_trade:
                    decision_outcome = "would_trade"
                elif decision_outcome == "detected":
                    decision_outcome = "optimizer_rejected"

        session.add(
            ShadowCandidateLog(
                pipeline_source=pipeline_source,
                decision_outcome=decision_outcome,
                similarity=similarity,
                pair_id=pair_id,
                opportunity_id=opportunity_id,
                market_a_id=market_a.id,
                market_b_id=market_b.id,
                market_a_event_id=market_a.event_id,
                market_b_event_id=market_b.event_id,
                market_a_question=market_a.question,
                market_b_question=market_b.question,
                market_a_outcomes=market_a.outcomes if isinstance(market_a.outcomes, list) else None,
                market_b_outcomes=market_b.outcomes if isinstance(market_b.outcomes, list) else None,
                market_a_venue=getattr(market_a, "venue", "polymarket"),
                market_b_venue=getattr(market_b, "venue", "polymarket"),
                market_a_liquidity=market_a.liquidity,
                market_b_liquidity=market_b.liquidity,
                market_a_volume=market_a.volume,
                market_b_volume=market_b.volume,
                snapshot_a_timestamp=snapshot_a.timestamp if snapshot_a else None,
                snapshot_b_timestamp=snapshot_b.timestamp if snapshot_b else None,
                prices_a=prices_a,
                prices_b=prices_b,
                market_a_best_bid=summary_a["best_bid"],
                market_a_best_ask=summary_a["best_ask"],
                market_a_spread=summary_a["spread"],
                market_a_visible_depth=summary_a["visible_depth"],
                market_b_best_bid=summary_b["best_bid"],
                market_b_best_ask=summary_b["best_ask"],
                market_b_spread=summary_b["spread"],
                market_b_visible_depth=summary_b["visible_depth"],
                dependency_type=classification.get("dependency_type"),
                implication_direction=classification.get("implication_direction"),
                classification_source=classification.get("classification_source"),
                classifier_model=self.classifier_model,
                classifier_prompt_adapter=self.classifier_prompt_adapter,
                classifier_confidence=classification.get("confidence"),
                classification_reasoning=classification.get("reasoning"),
                verification_passed=(
                    verification.get("verified") if verification is not None else None
                ),
                verification_reasons=verification_reasons,
                silver_failure_signature=silver_failure_signature,
                profit_bound=profit,
                passed_to_optimization=passed_to_optimization,
                optimizer_preview_status=preview_status,
                optimizer_preview_estimated_profit=preview_estimated_profit,
                optimizer_preview_trade_count=preview_trade_count,
                optimizer_preview_max_edge=preview_max_edge,
                optimizer_preview_rejection_reason=preview_rejection_reason,
                would_trade=would_trade,
            )
        )

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
                    prompt_adapter=self.classifier_prompt_adapter,
                )

                if classification["dependency_type"] == "none":
                    if _bool_setting("shadow_logging_enabled", False):
                        snapshot_a = await _get_latest_snapshot(
                            session, market_a.id, settings.max_snapshot_age_seconds
                        )
                        snapshot_b = await _get_latest_snapshot(
                            session, market_b.id, settings.max_snapshot_age_seconds
                        )
                        await self._log_shadow_candidate(
                            session,
                            pipeline_source="similarity",
                            similarity=candidate.get("similarity"),
                            market_a=market_a,
                            market_b=market_b,
                            snapshot_a=snapshot_a,
                            snapshot_b=snapshot_b,
                            classification=classification,
                            decision_outcome="classified_none",
                        )
                    continue

                snapshot_a = await _get_latest_snapshot(
                    session, market_a.id, settings.max_snapshot_age_seconds
                )
                snapshot_b = await _get_latest_snapshot(
                    session, market_b.id, settings.max_snapshot_age_seconds
                )
                prices_a = snapshot_a.prices if snapshot_a else None
                prices_b = snapshot_b.prices if snapshot_b else None

                # Uncertainty filter: skip near-resolved markets
                if prices_a and prices_b and not _passes_uncertainty_filter(
                    prices_a, prices_b, market_a_dict["outcomes"], market_b_dict["outcomes"]
                ):
                    logger.info(
                        "uncertainty_filter_rejected",
                        market_a_id=market_a.id,
                        market_b_id=market_b.id,
                    )
                    await self._log_shadow_candidate(
                        session,
                        pipeline_source="similarity",
                        similarity=candidate.get("similarity"),
                        market_a=market_a,
                        market_b=market_b,
                        snapshot_a=snapshot_a,
                        snapshot_b=snapshot_b,
                        classification=classification,
                        decision_outcome="uncertainty_filtered",
                    )
                    continue

                # Build constraint matrix — use vectors directly when available
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
                opp = None
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

                decision_outcome = "detected"
                if not verification["verified"]:
                    decision_outcome = "verification_failed"
                elif profit <= 0:
                    decision_outcome = "profit_non_positive"

                await self._log_shadow_candidate(
                    session,
                    pipeline_source="similarity",
                    similarity=candidate.get("similarity"),
                    market_a=market_a,
                    market_b=market_b,
                    snapshot_a=snapshot_a,
                    snapshot_b=snapshot_b,
                    classification=classification,
                    verification=verification,
                    constraint=constraint,
                    decision_outcome=decision_outcome,
                    pair_id=pair.id,
                    opportunity_id=opp.id if opp else None,
                )

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

            for candidate in candidates:
                market_a = markets_by_id.get(candidate["market_a_id"])
                market_b = markets_by_id.get(candidate["market_b_id"])
                if not market_a or not market_b:
                    continue

                market_a_dict = _market_to_dict(market_a)
                market_b_dict = _market_to_dict(market_b)
                similarity = candidate["similarity"]

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
                    classification = await classify_pair(
                        self.openai_client,
                        self.classifier_model,
                        market_a_dict,
                        market_b_dict,
                        prompt_adapter=self.classifier_prompt_adapter,
                    )

                if classification["dependency_type"] == "none":
                    if _bool_setting("shadow_logging_enabled", False):
                        snapshot_a = await _get_latest_snapshot(
                            session, market_a.id, settings.max_snapshot_age_seconds
                        )
                        snapshot_b = await _get_latest_snapshot(
                            session, market_b.id, settings.max_snapshot_age_seconds
                        )
                        await self._log_shadow_candidate(
                            session,
                            pipeline_source="cross_venue",
                            similarity=similarity,
                            market_a=market_a,
                            market_b=market_b,
                            snapshot_a=snapshot_a,
                            snapshot_b=snapshot_b,
                            classification=classification,
                            decision_outcome="classified_none",
                        )
                    continue

                snapshot_a = await _get_latest_snapshot(
                    session, market_a.id, settings.max_snapshot_age_seconds
                )
                snapshot_b = await _get_latest_snapshot(
                    session, market_b.id, settings.max_snapshot_age_seconds
                )
                prices_a = snapshot_a.prices if snapshot_a else None
                prices_b = snapshot_b.prices if snapshot_b else None

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
                opp = None
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

                decision_outcome = "detected"
                if not verification["verified"]:
                    decision_outcome = "verification_failed"
                elif profit <= 0:
                    decision_outcome = "profit_non_positive"

                await self._log_shadow_candidate(
                    session,
                    pipeline_source="cross_venue",
                    similarity=similarity,
                    market_a=market_a,
                    market_b=market_b,
                    snapshot_a=snapshot_a,
                    snapshot_b=snapshot_b,
                    classification=classification,
                    verification=verification,
                    constraint=constraint,
                    decision_outcome=decision_outcome,
                    pair_id=pair.id,
                    opportunity_id=opp.id if opp else None,
                )

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
                    await _invalidate_open_opportunities_for_pair(session, pair.id)
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
                    await _invalidate_open_opportunities_for_pair(session, pair.id)
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


async def _get_latest_snapshot(
    session,
    market_id: int,
    max_age_seconds: int = 0,
) -> PriceSnapshot | None:
    """Fetch the most recent price snapshot row for a market."""
    from datetime import timedelta

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
    return result.scalar_one_or_none()


async def _get_latest_prices(session, market_id: int, max_age_seconds: int = 0) -> dict | None:
    """Fetch the most recent price payload for a market."""
    snapshot = await _get_latest_snapshot(session, market_id, max_age_seconds)
    return snapshot.prices if snapshot else None


def _bool_setting(name: str, default: bool) -> bool:
    value = getattr(settings, name, default)
    return value if isinstance(value, bool) else default
