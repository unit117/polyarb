"""One-time script: rebuild constraint matrices for all existing pairs.

Re-generates constraint matrices using the latest logic in constraints.py,
fixing stale matrices that were built before bug fixes (Bug #11).
Also re-classifies pairs using rule-based checks where applicable.

Usage (on NAS):
    docker compose run --rm detector python -m scripts.rebuild_constraints
"""

import asyncio

import openai
import structlog
from sqlalchemy import select

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.logging import setup_logging
from shared.models import Market, MarketPair, PriceSnapshot
from services.detector.classifier import classify_rule_based
from services.detector.constraints import build_constraint_matrix
from services.detector.verification import verify_pair

logger = structlog.get_logger()


async def _get_latest_prices(session, market_id: int) -> dict | None:
    result = await session.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    return snapshot.prices if snapshot else None


async def main() -> None:
    setup_logging(settings.log_level)
    await init_db()

    stats = {"total": 0, "reclassified": 0, "rebuilt": 0, "unverified": 0}

    async with SessionFactory() as session:
        result = await session.execute(select(MarketPair))
        pairs = result.scalars().all()
        stats["total"] = len(pairs)

        # Pre-load all referenced markets
        market_ids = set()
        for p in pairs:
            market_ids.add(p.market_a_id)
            market_ids.add(p.market_b_id)

        result = await session.execute(
            select(Market).where(Market.id.in_(market_ids))
        )
        markets_by_id = {m.id: m for m in result.scalars().all()}

        for pair in pairs:
            market_a = markets_by_id.get(pair.market_a_id)
            market_b = markets_by_id.get(pair.market_b_id)
            if not market_a or not market_b:
                continue

            market_a_dict = {
                "id": market_a.id,
                "event_id": market_a.event_id,
                "question": market_a.question,
                "description": market_a.description,
                "outcomes": market_a.outcomes if isinstance(market_a.outcomes, list) else [],
            }
            market_b_dict = {
                "id": market_b.id,
                "event_id": market_b.event_id,
                "question": market_b.question,
                "description": market_b.description,
                "outcomes": market_b.outcomes if isinstance(market_b.outcomes, list) else [],
            }

            # Try rule-based reclassification (catches Top-N, crypto time intervals, etc.)
            rule_result = await classify_rule_based(market_a_dict, market_b_dict)
            if rule_result and rule_result["dependency_type"] != pair.dependency_type:
                old_type = pair.dependency_type
                pair.dependency_type = rule_result["dependency_type"]
                pair.confidence = rule_result["confidence"]
                stats["reclassified"] += 1
                logger.info(
                    "pair_reclassified",
                    pair_id=pair.id,
                    old_type=old_type,
                    new_type=rule_result["dependency_type"],
                    reasoning=rule_result.get("reasoning", ""),
                )

            prices_a = await _get_latest_prices(session, pair.market_a_id)
            prices_b = await _get_latest_prices(session, pair.market_b_id)

            correlation = (
                rule_result.get("correlation")
                if rule_result
                else (pair.constraint_matrix or {}).get("correlation")
            )

            # Rebuild constraint matrix with latest logic
            fresh_constraint = build_constraint_matrix(
                pair.dependency_type,
                market_a_dict["outcomes"],
                market_b_dict["outcomes"],
                prices_a,
                prices_b,
                correlation=correlation,
            )
            pair.constraint_matrix = fresh_constraint
            stats["rebuilt"] += 1

            # Re-verify
            verification = verify_pair(
                dependency_type=pair.dependency_type,
                market_a=market_a_dict,
                market_b=market_b_dict,
                prices_a=prices_a,
                prices_b=prices_b,
                confidence=pair.confidence,
                correlation=correlation,
            )
            pair.verified = verification["verified"]
            if not verification["verified"]:
                stats["unverified"] += 1

        await session.commit()

    logger.info(
        "rebuild_complete",
        total=stats["total"],
        reclassified=stats["reclassified"],
        rebuilt=stats["rebuilt"],
        unverified=stats["unverified"],
    )


if __name__ == "__main__":
    asyncio.run(main())
