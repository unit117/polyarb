"""Detection pipeline: similarity -> classification -> constraint generation."""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import openai
import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.events import CHANNEL_PAIR_DETECTED, CHANNEL_ARBITRAGE_FOUND, publish_event
from shared.schemas import ArbitrageFoundEvent, PairDetectedEvent
from shared.lifecycle import IN_FLIGHT, OppStatus, transition
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PairClassificationCache,
    PriceSnapshot,
)
from shared.config import settings
from services.detector.similarity import find_similar_pairs, find_cross_venue_pairs
from services.detector.classifier import classify_pair
from services.detector.constraints import build_constraint_matrix, build_constraint_matrix_from_vectors
from services.detector.verification import verify_pair

logger = structlog.get_logger()


CLASSIFICATION_CACHE_VERSION = "llm-pair-v1"


@dataclass
class _CandidateResult:
    """Result of processing a single classified candidate."""
    pair_created: bool = False
    opportunity_created: bool = False
    events: list[tuple] = field(default_factory=list)


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

    # ------------------------------------------------------------------
    # Classification cache
    # ------------------------------------------------------------------

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

    async def _classify_with_cache(
        self,
        market_a_dict: dict,
        market_b_dict: dict,
        cached_classifications: dict[tuple[int, int], dict],
        cache_rows: list[dict],
    ) -> dict:
        """Classify a pair, using cache when available."""
        pair_key = _pair_key(market_a_dict["id"], market_b_dict["id"])
        classification = cached_classifications.get(pair_key)
        if classification is not None:
            return classification

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
        return classification

    # ------------------------------------------------------------------
    # Shared candidate processing (constrain -> verify -> persist)
    # ------------------------------------------------------------------

    async def _process_classified_candidate(
        self,
        session,
        market_a: Market,
        market_b: Market,
        classification: dict,
        prices_a: dict | None,
        prices_b: dict | None,
    ) -> _CandidateResult:
        """Build constraint matrix, verify pair, persist pair + opportunity.

        Shared by intra-venue detection and cross-venue detection.
        """
        result = _CandidateResult()
        market_a_dict = _market_to_dict(market_a)
        market_b_dict = _market_to_dict(market_b)

        # Build constraint matrix -- use vectors directly when available
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

        # Verify pair
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
            constraint_matrix=constraint.model_dump(),
            resolution_vectors=classification.get("valid_outcomes"),
            implication_direction=classification.get("implication_direction"),
            classification_source=classification.get("classification_source"),
            verified=verification["verified"],
        )
        session.add(pair)
        await session.flush()
        result.pair_created = True

        result.events.append((
            CHANNEL_PAIR_DETECTED,
            PairDetectedEvent(
                pair_id=pair.id,
                market_a_id=market_a.id,
                market_b_id=market_b.id,
                dependency_type=classification["dependency_type"],
                confidence=classification["confidence"],
            ),
        ))

        # If there's a theoretical profit on a verified pair, record an opportunity
        profit = constraint.profit_bound
        if profit > 0 and verification["verified"]:
            opp = ArbitrageOpportunity(
                pair_id=pair.id,
                type="rebalancing",
                theoretical_profit=Decimal(str(profit)),
                status=OppStatus.DETECTED,
                dependency_type=pair.dependency_type,
            )
            session.add(opp)
            await session.flush()
            result.opportunity_created = True

            result.events.append((
                CHANNEL_ARBITRAGE_FOUND,
                ArbitrageFoundEvent(
                    opportunity_id=opp.id,
                    pair_id=pair.id,
                    type="rebalancing",
                    theoretical_profit=float(profit),
                ),
            ))

        return result

    # ------------------------------------------------------------------
    # Shared pair refresh (rebuild constraint -> re-verify)
    # ------------------------------------------------------------------

    async def _refresh_pair_constraint(
        self,
        session,
        pair: MarketPair,
        prices_a: dict,
        prices_b: dict,
    ) -> tuple[float, bool]:
        """Rebuild constraint matrix and re-verify a pair with fresh prices.

        Updates pair.constraint_matrix in-place. If verification fails,
        sets pair.verified = False.

        Returns (profit_bound, verified).
        """
        constraint = pair.constraint_matrix or {}
        outcomes_a = constraint.get("outcomes_a", [])
        outcomes_b = constraint.get("outcomes_b", [])

        market_a_obj = await session.get(Market, pair.market_a_id)
        market_b_obj = await session.get(Market, pair.market_b_id)
        fresh_constraint = _rebuild_constraint_for_pair(
            pair, outcomes_a, outcomes_b, prices_a, prices_b,
            venue_a=getattr(market_a_obj, "venue", "polymarket"),
            venue_b=getattr(market_b_obj, "venue", "polymarket"),
        )

        pair.constraint_matrix = fresh_constraint.model_dump()

        market_a_dict = _market_to_dict(market_a_obj)
        market_b_dict = _market_to_dict(market_b_obj)
        re_verification = verify_pair(
            dependency_type=pair.dependency_type,
            market_a=market_a_dict,
            market_b=market_b_dict,
            prices_a=prices_a,
            prices_b=prices_b,
            confidence=pair.confidence,
            correlation=fresh_constraint.correlation,
            implication_direction=fresh_constraint.implication_direction,
        )
        if not re_verification["verified"]:
            pair.verified = False
            logger.info(
                "pair_unverified_on_rescan",
                pair_id=pair.id,
                reasons=re_verification["reasons"],
            )
            return 0.0, False

        return fresh_constraint.profit_bound, True

    # ------------------------------------------------------------------
    # Main detection cycle
    # ------------------------------------------------------------------

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
                session, candidates, markets_by_id,
            )
            cache_rows: list[dict] = []

            for candidate in candidates:
                market_a = markets_by_id.get(candidate["market_a_id"])
                market_b = markets_by_id.get(candidate["market_b_id"])
                if not market_a or not market_b:
                    continue

                market_a_dict = _market_to_dict(market_a)
                market_b_dict = _market_to_dict(market_b)

                classification = await self._classify_with_cache(
                    market_a_dict, market_b_dict,
                    cached_classifications, cache_rows,
                )

                if classification["dependency_type"] == "none":
                    continue

                # Structural pre-check: skip pairs that will inevitably
                # fail verification, saving price fetches and constraint builds.
                dep_type = classification["dependency_type"]
                if dep_type == "mutual_exclusion":
                    event_a = market_a_dict.get("event_id")
                    event_b = market_b_dict.get("event_id")
                    if not event_a and not event_b:
                        logger.info(
                            "skipped_structural_precheck",
                            market_a_id=market_a.id, market_b_id=market_b.id,
                            reason="mutual_exclusion_no_event_ids",
                        )
                        continue
                    outcomes_a = market_a_dict.get("outcomes", [])
                    outcomes_b = market_b_dict.get("outcomes", [])
                    if len(outcomes_a) != 2 or len(outcomes_b) != 2:
                        logger.info(
                            "skipped_structural_precheck",
                            market_a_id=market_a.id, market_b_id=market_b.id,
                            reason="mutual_exclusion_non_binary",
                        )
                        continue

                prices_a = await _get_latest_prices(session, market_a.id, settings.max_snapshot_age_seconds)
                prices_b = await _get_latest_prices(session, market_b.id, settings.max_snapshot_age_seconds)

                if not prices_a and not prices_b:
                    logger.info(
                        "skipped_no_price_data",
                        market_a_id=market_a.id, market_b_id=market_b.id,
                    )
                    continue

                if prices_a and prices_b and not _passes_uncertainty_filter(
                    prices_a, prices_b, market_a_dict["outcomes"], market_b_dict["outcomes"]
                ):
                    logger.info(
                        "uncertainty_filter_rejected",
                        market_a_id=market_a.id, market_b_id=market_b.id,
                    )
                    continue

                cr = await self._process_classified_candidate(
                    session, market_a, market_b, classification, prices_a, prices_b,
                )
                stats["pairs_created"] += int(cr.pair_created)
                stats["opportunities"] += int(cr.opportunity_created)
                deferred_events.extend(cr.events)

            await self._flush_classification_cache(session, cache_rows)
            await session.commit()

        for channel, payload in deferred_events:
            await publish_event(self.redis, channel, payload)

        # Cross-venue detection (Kalshi <-> Polymarket) if enabled
        if settings.kalshi_enabled:
            cross_stats = await self._detect_cross_venue()
            stats["cross_venue_candidates"] = cross_stats.get("candidates", 0)
            stats["pairs_created"] += cross_stats.get("pairs_created", 0)
            stats["opportunities"] += cross_stats.get("opportunities", 0)

        logger.info("detection_cycle_complete", **stats)

        rescan_stats = await self._rescan_existing_pairs()
        stats["rescanned"] = rescan_stats["opportunities"]

        return stats

    # ------------------------------------------------------------------
    # Cross-venue detection
    # ------------------------------------------------------------------

    async def _detect_cross_venue(self) -> dict:
        """Find and classify cross-venue pairs (Kalshi <-> Polymarket)."""
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
                session, candidates, markets_by_id,
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

                # High similarity -> auto-classify as cross_platform
                if similarity >= 0.95:
                    classification = {
                        "dependency_type": "cross_platform",
                        "confidence": 0.95,
                        "reasoning": f"Cross-venue match (similarity={similarity:.3f})",
                    }
                else:
                    classification = await self._classify_with_cache(
                        market_a_dict, market_b_dict,
                        cached_classifications, cache_rows,
                    )

                if classification["dependency_type"] == "none":
                    continue

                prices_a = await _get_latest_prices(session, market_a.id, settings.max_snapshot_age_seconds)
                prices_b = await _get_latest_prices(session, market_b.id, settings.max_snapshot_age_seconds)

                cr = await self._process_classified_candidate(
                    session, market_a, market_b, classification, prices_a, prices_b,
                )
                stats["pairs_created"] += int(cr.pair_created)
                stats["opportunities"] += int(cr.opportunity_created)
                deferred_events.extend(cr.events)

            await self._flush_classification_cache(session, cache_rows)
            await session.commit()

        for channel, payload in deferred_events:
            await publish_event(self.redis, channel, payload)

        if stats["pairs_created"] > 0:
            logger.info("cross_venue_detection_complete", **stats)
        return stats

    # ------------------------------------------------------------------
    # Rescan existing pairs
    # ------------------------------------------------------------------

    async def _rescan_existing_pairs(self) -> dict:
        """Re-evaluate existing pairs that have prices but no opportunities."""
        stats = {"opportunities": 0}
        deferred_events: list[dict] = []

        async with self._rescan_lock, self.session_factory() as session:
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

                if not (pair.constraint_matrix or {}).get("outcomes_a"):
                    continue

                profit, verified = await self._refresh_pair_constraint(
                    session, pair, prices_a, prices_b,
                )
                if not verified or profit <= 0:
                    continue

                opp = ArbitrageOpportunity(
                    pair_id=pair.id,
                    type="rebalancing",
                    theoretical_profit=Decimal(str(profit)),
                    status=OppStatus.DETECTED,
                    dependency_type=pair.dependency_type,
                )
                session.add(opp)
                try:
                    await session.flush()
                except IntegrityError:
                    await session.rollback()
                    logger.info("rescan_duplicate_skipped", pair_id=pair.id)
                    continue
                stats["opportunities"] += 1

                deferred_events.append(ArbitrageFoundEvent(
                    opportunity_id=opp.id,
                    pair_id=pair.id,
                    type="rebalancing",
                    theoretical_profit=float(profit),
                ))

            await session.commit()

        for payload in deferred_events:
            await publish_event(self.redis, CHANNEL_ARBITRAGE_FOUND, payload)

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
        - Has optimized/unconverged opp: refresh and reset to detected.
        - Has pending opp (simulator mid-execution): skip.
        - Has detected opp: just refresh the constraint matrix.
        """
        stats = {"opportunities": 0, "pairs_checked": 0, "refreshed": 0}
        deferred_events: list[dict] = []

        async with self._rescan_lock, self.session_factory() as session:
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
                        ArbitrageOpportunity.status.in_(list(IN_FLIGHT)),
                    )
                )
                in_flight_opps = {
                    opp.pair_id: opp for opp in opp_result.scalars().all()
                }
            else:
                in_flight_opps = {}

            for pair in pairs:
                if not pair.constraint_matrix:
                    continue

                prices_a = await _get_latest_prices(session, pair.market_a_id, settings.max_snapshot_age_seconds)
                prices_b = await _get_latest_prices(session, pair.market_b_id, settings.max_snapshot_age_seconds)
                if not prices_a or not prices_b:
                    continue

                profit, verified = await self._refresh_pair_constraint(
                    session, pair, prices_a, prices_b,
                )
                if not verified:
                    continue

                existing_opp = in_flight_opps.get(pair.id)
                if existing_opp:
                    # Don't touch pending opps -- simulator is mid-execution
                    if existing_opp.status == OppStatus.PENDING:
                        continue

                    # Mark expired when profit disappears
                    if profit <= 0 and not existing_opp.expired_at:
                        existing_opp.theoretical_profit = Decimal("0")
                        existing_opp.estimated_profit = Decimal("0")
                        existing_opp.optimal_trades = None
                        transition(existing_opp, OppStatus.EXPIRED)
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
                    if existing_opp.status in (OppStatus.OPTIMIZED, OppStatus.UNCONVERGED):
                        transition(existing_opp, OppStatus.DETECTED)
                        existing_opp.optimal_trades = None
                        existing_opp.fw_iterations = None
                        existing_opp.bregman_gap = None
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
                        status=OppStatus.DETECTED,
                        dependency_type=pair.dependency_type,
                    )
                    session.add(opp)
                    try:
                        await session.flush()
                    except IntegrityError:
                        await session.rollback()
                        logger.info("rescan_duplicate_skipped", pair_id=pair.id)
                        continue
                    stats["opportunities"] += 1

                    deferred_events.append(ArbitrageFoundEvent(
                        opportunity_id=opp.id,
                        pair_id=pair.id,
                        type="rebalancing",
                        theoretical_profit=float(profit),
                    ))

            await session.commit()

        for payload in deferred_events:
            await publish_event(self.redis, CHANNEL_ARBITRAGE_FOUND, payload)

        if stats["opportunities"] > 0 or stats["refreshed"] > 0:
            logger.info("snapshot_rescan_complete", **stats)
        return stats


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


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
    """Rebuild constraint matrix using vectors if available, else label-based."""
    constraint = pair.constraint_matrix or {}
    correlation = constraint.get("correlation")
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
    """Reject pairs where any binary market is near-certain (< floor or > ceil)."""
    floor = settings.uncertainty_price_floor
    ceil = settings.uncertainty_price_ceil

    for outcomes, prices in [(outcomes_a, prices_a), (outcomes_b, prices_b)]:
        if len(outcomes) > 2:
            continue
        for outcome in outcomes:
            try:
                p = float(prices.get(outcome, 0.5))
            except (TypeError, ValueError):
                continue
            if p < floor or p > ceil:
                return False
            complement = 1.0 - p
            if complement < floor or complement > ceil:
                return False
    return True


async def _get_latest_prices(session, market_id: int, max_age_seconds: int = 0) -> dict | None:
    """Fetch the most recent price snapshot for a market."""
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
