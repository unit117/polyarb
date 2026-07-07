"""Export a curated V4 gold-set candidate file for manual labeling.

This keeps the existing eval JSON schema used by eval_classifier.py while
adding review metadata: family tags, shared-keyword counts, and selection
reasons. The exporter prefers resolved, verified pairs from families called
out in the V4 plan and fills the hard-negative bucket with semantically
similar non-persisted market pairs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

sys.path.insert(0, ".")

from shared.db import SessionFactory, init_db
from shared.models import Market, MarketPair

EVAL_DATA_DIR = Path(__file__).parent / "eval_data"
LABELED_PAIRS_V4_PATH = EVAL_DATA_DIR / "labeled_pairs_v4.json"

PREFERRED_DEP_TYPES = (
    "implication",
    "mutual_exclusion",
    "partition",
    "conditional",
)
TARGET_COUNTS = {
    "implication": 45,
    "mutual_exclusion": 35,
    "partition": 25,
    "conditional": 25,
    "none": 40,
}
SAFE_NONE_FAMILIES = {
    "other",
    "same_team_nearby_match_negative",
}
STRUCTURED_NEGATIVE_FAMILIES = {
    "ai_model_horizon_negative",
    "event_timing_negative",
    "geopolitical_window_negative",
    "intraday_direction_negative",
    "scalar_threshold_negative",
    "social_post_window_negative",
    "sports_ou_ladder_negative",
    "sports_spread_ladder_negative",
    "weather_temp_ladder_negative",
}
FAMILY_BOOST = {
    "crypto_threshold_ladder": 3.0,
    "fed_rate_cut_ladder": 3.0,
    "date_window_nesting": 2.8,
    "winner_duplicate": 2.6,
    "weather_temp_ladder_negative": 2.4,
    "sports_ou_ladder_negative": 2.2,
    "sports_spread_ladder_negative": 2.0,
    "social_post_window_negative": 2.2,
    "ai_model_horizon_negative": 2.0,
    "event_timing_negative": 1.8,
    "intraday_direction_negative": 1.8,
    "scalar_threshold_negative": 1.8,
    "geopolitical_window_negative": 1.8,
    "sports_winner_vs_game": 2.0,
    "sports_ou_btts": 1.8,
    "same_team_nearby_match_negative": 2.2,
    "other": 0.0,
}
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "vs",
    "will",
    "with",
    "yes",
    "no",
    "other",
}
ENTITY_STOPWORDS = STOPWORDS | {
    "above",
    "advance",
    "after",
    "before",
    "below",
    "both",
    "cuts",
    "game",
    "games",
    "goals",
    "group",
    "handicap",
    "map",
    "maps",
    "match",
    "matches",
    "over",
    "qualify",
    "reach",
    "score",
    "scored",
    "semifinal",
    "series",
    "spread",
    "team",
    "teams",
    "under",
    "win",
    "winner",
    "wins",
}
MONTH_TOKENS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}
HARD_NEGATIVE_SIGNATURE_STOPWORDS = MONTH_TOKENS | {
    "best",
    "end",
    "finals",
    "game",
    "games",
    "model",
    "post",
    "price",
    "season",
    "series",
    "winner",
    "winners",
}
HARD_NEGATIVE_SIGNATURE_CAP = 6
HARD_NEGATIVE_POOL_MULTIPLIER = 12


def _normalize_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _keyword_tokens(text: str | None, *, entity_mode: bool = False) -> set[str]:
    stopwords = ENTITY_STOPWORDS if entity_mode else STOPWORDS
    tokens = re.findall(r"[a-z0-9]+", _normalize_text(text))
    return {token for token in tokens if len(token) >= 3 and token not in stopwords}


def _shared_keywords(question_a: str, question_b: str) -> list[str]:
    shared = _keyword_tokens(question_a) & _keyword_tokens(question_b)
    return sorted(shared)


def _shared_entities(question_a: str, question_b: str) -> list[str]:
    shared = _keyword_tokens(question_a, entity_mode=True) & _keyword_tokens(
        question_b, entity_mode=True
    )
    return sorted(shared)


def _hard_negative_signature(record: dict) -> tuple[str, ...]:
    tokens = [
        token
        for token in record.get("shared_entities", [])
        if not token.isdigit() and token not in HARD_NEGATIVE_SIGNATURE_STOPWORDS
    ]
    if tokens:
        return tuple(tokens[:3])

    fallback_tokens = [
        token
        for token in record.get("shared_keywords", [])
        if not token.isdigit() and token not in HARD_NEGATIVE_SIGNATURE_STOPWORDS
    ]
    if fallback_tokens:
        return tuple(fallback_tokens[:3])

    return (str(record.get("market_a_id")), str(record.get("market_b_id")))


def _has_meaningful_text(question: str | None, description: str | None) -> bool:
    question_text = _normalize_text(question)
    if len(question_text) < 12:
        return False
    if len(_keyword_tokens(question_text)) < 3:
        return False
    if description and len(_normalize_text(description)) >= 40:
        return True
    return len(question_text) >= 24


def _is_obvious_duplicate(
    question_a: str,
    question_b: str,
    outcomes_a: list[str],
    outcomes_b: list[str],
) -> bool:
    return _normalize_text(question_a) == _normalize_text(question_b) and list(
        outcomes_a or []
    ) == list(outcomes_b or [])


def _market_shape(question: str, description: str = "") -> str:
    # Family tagging should follow the market question itself; descriptions often
    # contain boilerplate resolution dates that distort the semantic shape.
    text = _normalize_text(question)
    crypto_asset = re.search(r"\bbitcoin\b|\bbtc\b|\bethereum\b|\beth\b|\bsolana\b|\bxrp\b", text)
    crypto_threshold_context = re.search(
        r"\$|\bprice\b|\babove\b|\bbelow\b|\bbetween\b|\bgreater than\b|\bless than\b|\breach\b",
        text,
    )
    if "both teams to score" in text:
        return "sports_btts"
    if re.search(r"\bo/u\b|over\/under|:\s*o/u\s*\d", text):
        return "sports_ou"
    if re.search(r"\bhighest temperature\b|\btemperature\b.+\b\d+\s*°?[cf]\b", text):
        return "weather_temp"
    if re.search(r"\bpost\b|\btweets?\b|truth social", text):
        return "social_posts"
    if re.search(r"\bbest ai model\b|\btop ai model\b", text):
        return "ai_model_horizon"
    if re.search(r"\bmilitary action\b|\bstrike\b|\bairstrike\b|\bconduct military action\b", text):
        return "geo_action"
    if re.search(
        r"\bapproval rating\b|\bhit\b.*\$?\d|\bsettle at\b|\bbetween\b.+\b\d|\bupper bound\b|\bfdv\b|\bflu hospitalization rate\b",
        text,
    ):
        return "scalar_threshold"
    if re.search(r"\bspread\b|\bhandicap\b", text):
        return "sports_spread"
    if re.search(r"\bmap\b|\bgame\b|\bset\b|\bbest of\b|\bbo[1357]\b|\bseries\b", text):
        return "sports_map_game"
    if re.search(r"\bfed\b|\bfomc\b|rate cut|rate hike|basis point|\bbps\b|official cash rate|\bocr\b", text):
        return "fed_rate"
    winner_like = re.search(
        r"\bwin\b|\bwinner\b|\bqualify\b|\badvance\b|\bsemifinal\b|\bnominee\b|\bleader\b|\bnext\b.+\bmayor\b",
        text,
    )
    reach_like = re.search(r"\breach\b", text) and not re.search(r"\$|\bprice\b", text)
    if winner_like or reach_like:
        return "winner_like"
    if re.search(r"\bby\b.+\b20\d{2}\b|\bbefore\b.+\b20\d{2}\b|\bon or before\b", text):
        return "date_window"
    if crypto_asset and crypto_threshold_context:
        return "crypto_threshold"
    return "other"


def classify_pair_family(
    question_a: str,
    question_b: str,
    description_a: str = "",
    description_b: str = "",
    dep_type: str = "",
) -> str:
    """Heuristic family tag for manual review and stratified sampling."""
    shape_a = _market_shape(question_a, description_a)
    shape_b = _market_shape(question_b, description_b)
    shared_entities = _shared_entities(question_a, question_b)
    shared_keywords = _shared_keywords(question_a, question_b)

    if {shape_a, shape_b} == {"sports_ou", "sports_btts"}:
        return "sports_ou_btts"
    if {shape_a, shape_b} & {"crypto_threshold"} == {"crypto_threshold"}:
        return "crypto_threshold_ladder"
    if {shape_a, shape_b} & {"fed_rate"} == {"fed_rate"}:
        return "fed_rate_cut_ladder"
    if shape_a == shape_b == "date_window" and len(shared_keywords) >= 3:
        return "date_window_nesting"
    if (
        "sports_map_game" in {shape_a, shape_b}
        and ("winner_like" in {shape_a, shape_b} or "sports_spread" in {shape_a, shape_b})
        and len(shared_entities) >= 2
    ):
        return "sports_winner_vs_game"
    if shape_a == shape_b == "winner_like" and len(shared_keywords) >= 4:
        return "winner_duplicate"
    if dep_type in {"none", "none_candidate"}:
        if shape_a == shape_b == "weather_temp":
            return "weather_temp_ladder_negative"
        if shape_a == shape_b == "sports_ou":
            return "sports_ou_ladder_negative"
        if shape_a == shape_b == "sports_spread":
            return "sports_spread_ladder_negative"
        if shape_a == shape_b == "social_posts":
            return "social_post_window_negative"
        if shape_a == shape_b == "ai_model_horizon":
            return "ai_model_horizon_negative"
        if shape_a == shape_b == "geo_action":
            return "geopolitical_window_negative"
        if shape_a == shape_b == "scalar_threshold":
            return "scalar_threshold_negative"
        if "launch a token" in _normalize_text(question_a) and "launch a token" in _normalize_text(question_b):
            return "event_timing_negative"
        if "up or down" in _normalize_text(question_a) and "up or down" in _normalize_text(question_b):
            return "intraday_direction_negative"
    if dep_type in {"none", "none_candidate"} and len(shared_entities) >= 2:
        return "same_team_nearby_match_negative"
    return "other"


def should_exclude_pair(
    question_a: str,
    question_b: str,
    description_a: str,
    description_b: str,
    outcomes_a: list[str],
    outcomes_b: list[str],
) -> bool:
    """Drop malformed or trivial pairs that waste labeling effort."""
    if not _has_meaningful_text(question_a, description_a):
        return True
    if not _has_meaningful_text(question_b, description_b):
        return True
    if _is_obvious_duplicate(question_a, question_b, outcomes_a, outcomes_b):
        return True
    return False


def _candidate_score(record: dict) -> float:
    family = record["pair_family"]
    score = FAMILY_BOOST.get(family, 0.0)
    score += float(record.get("current_confidence", 0.0))
    score += min(len(record.get("shared_keywords", [])), 5) * 0.15
    if record.get("verified"):
        # Prefer verified rows when available, but still allow resolved fallbacks.
        score += 5.0
    if record.get("selection_bucket") == "hard_negative":
        score += float(record.get("semantic_similarity", 0.0))
    return score


def _selection_reason(family: str, bucket: str, extra: str = "") -> str:
    detail = f"{bucket}:{family}"
    if extra:
        detail = f"{detail}:{extra}"
    return detail


def _is_safe_none_family(family: str) -> bool:
    """Conservative allowlist for V4 hard-negative export.

    Manual review of the completed V4 gold set showed that the explicit
    "negative" ladder/window families were almost never true `none` pairs.
    Keep tagging them for diagnostics, but do not admit them into the
    hard-negative none bucket until they have a safer routing.
    """
    return family in SAFE_NONE_FAMILIES


def _build_record(
    *,
    pair_id: int | None,
    market_a: Market,
    market_b: Market,
    current_dependency_type: str,
    current_confidence: float,
    verified: bool,
    pair_family: str,
    selection_bucket: str,
    selection_reason: str,
    semantic_similarity: float | None = None,
) -> dict:
    shared_keywords = _shared_keywords(market_a.question, market_b.question)
    shared_entities = _shared_entities(market_a.question, market_b.question)
    return {
        "pair_id": pair_id,
        "market_a_id": market_a.id,
        "market_b_id": market_b.id,
        "question_a": market_a.question,
        "question_b": market_b.question,
        "description_a": market_a.description or "",
        "description_b": market_b.description or "",
        "outcomes_a": market_a.outcomes if isinstance(market_a.outcomes, list) else [],
        "outcomes_b": market_b.outcomes if isinstance(market_b.outcomes, list) else [],
        "event_id_a": market_a.event_id,
        "event_id_b": market_b.event_id,
        "current_dependency_type": current_dependency_type,
        "current_confidence": round(current_confidence, 4),
        "verified": verified,
        "resolved_outcome_a": market_a.resolved_outcome,
        "resolved_outcome_b": market_b.resolved_outcome,
        "resolved_at_a": market_a.resolved_at.isoformat() if market_a.resolved_at else "",
        "resolved_at_b": market_b.resolved_at.isoformat() if market_b.resolved_at else "",
        "pair_family": pair_family,
        "shared_keywords": shared_keywords,
        "shared_entities": shared_entities,
        "selection_bucket": selection_bucket,
        "selection_reason": selection_reason,
        "semantic_similarity": round(semantic_similarity, 4) if semantic_similarity is not None else None,
        "manual_family_tag": "",
        "ground_truth_type": "",
        "correct": None,
        "notes": "",
    }


def _select_balanced(
    candidates: list[dict],
    target: int,
    family_cap: int,
    signature_cap: int | None = None,
    preselected: list[dict] | None = None,
) -> list[dict]:
    selected: list[dict] = list(preselected or [])
    seen_pair_ids: set[int | None] = set()
    family_counts: Counter[str] = Counter()
    signature_counts: Counter[tuple[str, ...]] = Counter()

    for candidate in selected:
        pair_key = (
            candidate.get("pair_id")
            if candidate.get("pair_id") is not None
            else (candidate["market_a_id"], candidate["market_b_id"])
        )
        seen_pair_ids.add(pair_key)
        family_counts[candidate["pair_family"]] += 1
        if signature_cap and candidate.get("selection_bucket") == "hard_negative":
            signature_counts[_hard_negative_signature(candidate)] += 1

    ranked = sorted(candidates, key=_candidate_score, reverse=True)

    for relaxed in (False, True):
        for candidate in ranked:
            if len(selected) >= target:
                break
            pair_key = (
                candidate.get("pair_id")
                if candidate.get("pair_id") is not None
                else (candidate["market_a_id"], candidate["market_b_id"])
            )
            if pair_key in seen_pair_ids:
                continue
            family = candidate["pair_family"]
            if not relaxed and family_counts[family] >= family_cap:
                continue
            signature: tuple[str, ...] | None = None
            if (
                signature_cap
                and candidate.get("selection_bucket") == "hard_negative"
            ):
                signature = _hard_negative_signature(candidate)
                if signature_counts[signature] >= signature_cap:
                    continue
            selected.append(candidate)
            seen_pair_ids.add(pair_key)
            family_counts[family] += 1
            if signature is not None:
                signature_counts[signature] += 1
        if len(selected) >= target:
            break

    return selected


def _seed_family_coverage(candidates: list[dict], target: int) -> list[dict]:
    grouped: defaultdict[str, list[dict]] = defaultdict(list)
    for candidate in sorted(candidates, key=_candidate_score, reverse=True):
        grouped[candidate["pair_family"]].append(candidate)

    seeded: list[dict] = []
    for family, family_rows in sorted(
        grouped.items(),
        key=lambda item: (len(item[1]), -_candidate_score(item[1][0]), item[0]),
    ):
        if len(seeded) >= target:
            break
        seeded.append(family_rows[0])

    return seeded


async def _load_persisted_candidates() -> dict[str, list[dict]]:
    market_a = aliased(Market)
    market_b = aliased(Market)
    grouped: dict[str, list[dict]] = defaultdict(list)

    async with SessionFactory() as session:
        result = await session.execute(
            select(MarketPair, market_a, market_b)
            .join(market_a, market_a.id == MarketPair.market_a_id)
            .join(market_b, market_b.id == MarketPair.market_b_id)
            .where(MarketPair.dependency_type.in_(PREFERRED_DEP_TYPES))
            .where(market_a.resolved_outcome.isnot(None))
            .where(market_a.resolved_at.isnot(None))
            .where(market_b.resolved_outcome.isnot(None))
            .where(market_b.resolved_at.isnot(None))
        )

        for pair, db_market_a, db_market_b in result.all():
            outcomes_a = db_market_a.outcomes if isinstance(db_market_a.outcomes, list) else []
            outcomes_b = db_market_b.outcomes if isinstance(db_market_b.outcomes, list) else []
            if should_exclude_pair(
                db_market_a.question,
                db_market_b.question,
                db_market_a.description or "",
                db_market_b.description or "",
                outcomes_a,
                outcomes_b,
            ):
                continue

            family = classify_pair_family(
                db_market_a.question,
                db_market_b.question,
                db_market_a.description or "",
                db_market_b.description or "",
                dep_type=pair.dependency_type,
            )
            selection_bucket = (
                "resolved_verified" if pair.verified else "resolved_unverified"
            )
            record = _build_record(
                pair_id=pair.id,
                market_a=db_market_a,
                market_b=db_market_b,
                current_dependency_type=pair.dependency_type,
                current_confidence=float(pair.confidence or 0.0),
                verified=pair.verified,
                pair_family=family,
                selection_bucket=selection_bucket,
                selection_reason=_selection_reason(family, selection_bucket),
            )
            grouped[pair.dependency_type].append(record)

    return grouped


async def _load_none_candidates(
    *,
    target: int,
    sample_markets: int,
) -> list[dict]:
    async with SessionFactory() as session:
        existing_result = await session.execute(
            select(MarketPair.market_a_id, MarketPair.market_b_id)
        )
        existing_pairs = {
            (min(a_id, b_id), max(a_id, b_id))
            for a_id, b_id in existing_result.all()
        }

        market_result = await session.execute(
            select(Market)
            .where(Market.embedding.isnot(None))
            .where(Market.resolved_outcome.isnot(None))
            .where(Market.resolved_at.isnot(None))
            .order_by(Market.volume.desc().nullslast(), Market.id.asc())
            .limit(sample_markets)
        )
        markets = [
            market
            for market in market_result.scalars().all()
            if _has_meaningful_text(market.question, market.description)
        ]

    scored: list[tuple[float, Market, Market, str]] = []
    for idx, market_a in enumerate(markets):
        vec_a = np.array(market_a.embedding, dtype=np.float32)
        norm_a = np.linalg.norm(vec_a)
        if norm_a == 0:
            continue
        for market_b in markets[idx + 1:]:
            key = (min(market_a.id, market_b.id), max(market_a.id, market_b.id))
            if key in existing_pairs:
                continue

            vec_b = np.array(market_b.embedding, dtype=np.float32)
            norm_b = np.linalg.norm(vec_b)
            if norm_b == 0:
                continue

            similarity = float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
            if similarity < 0.84:
                continue

            family = classify_pair_family(
                market_a.question,
                market_b.question,
                market_a.description or "",
                market_b.description or "",
                dep_type="none_candidate",
            )
            if not _is_safe_none_family(family):
                continue

            shared_entities = _shared_entities(market_a.question, market_b.question)
            if family == "other" and len(shared_entities) < 2:
                continue

            scored.append((similarity, market_a, market_b, family))

    scored.sort(key=lambda row: row[0], reverse=True)
    candidates: list[dict] = []
    seen_markets: set[tuple[int, int]] = set()
    candidate_pool_target = max(target * HARD_NEGATIVE_POOL_MULTIPLIER, target * 3)
    for similarity, market_a, market_b, family in scored:
        if len(candidates) >= candidate_pool_target:
            break
        pair_key = (min(market_a.id, market_b.id), max(market_a.id, market_b.id))
        if pair_key in seen_markets:
            continue
        seen_markets.add(pair_key)
        candidates.append(
            _build_record(
                pair_id=None,
                market_a=market_a,
                market_b=market_b,
                current_dependency_type="none_candidate",
                current_confidence=0.0,
                verified=False,
                pair_family=family,
                selection_bucket="hard_negative",
                selection_reason=_selection_reason(
                    family,
                    "hard_negative",
                    f"sim={similarity:.3f}",
                ),
                semantic_similarity=similarity,
            )
        )

    return candidates


async def export_goldset_v4(
    *,
    output_path: Path,
    family_cap: int,
    sample_markets: int,
) -> list[dict]:
    await init_db()

    persisted = await _load_persisted_candidates()
    selected: list[dict] = []
    stats = Counter()
    family_stats = Counter()

    for dep_type in PREFERRED_DEP_TYPES:
        dep_candidates = persisted.get(dep_type, [])
        dep_selected = _select_balanced(
            dep_candidates,
            target=TARGET_COUNTS[dep_type],
            family_cap=family_cap,
        )
        selected.extend(dep_selected)
        stats[dep_type] += len(dep_selected)
        family_stats.update(row["pair_family"] for row in dep_selected)

    none_candidates = await _load_none_candidates(
        target=TARGET_COUNTS["none"],
        sample_markets=sample_markets,
    )
    none_selected = _select_balanced(
        none_candidates,
        target=TARGET_COUNTS["none"],
        family_cap=family_cap,
        signature_cap=HARD_NEGATIVE_SIGNATURE_CAP,
        preselected=_seed_family_coverage(none_candidates, TARGET_COUNTS["none"]),
    )
    if len(none_selected) < TARGET_COUNTS["none"]:
        print(
            "WARNING: safe hard-negative none candidates underfilled "
            f"({len(none_selected)}/{TARGET_COUNTS['none']})."
        )
    for row in none_selected:
        row["current_dependency_type"] = "none"
    selected.extend(none_selected)
    stats["none"] += len(none_selected)
    family_stats.update(row["pair_family"] for row in none_selected)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(selected, indent=2))

    print(f"Exported {len(selected)} gold-set candidates to {output_path}")
    print(f"Type counts: {dict(stats)}")
    print(f"Family counts: {dict(family_stats)}")

    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Export V4 gold-set candidate pairs")
    parser.add_argument(
        "--output",
        default=str(LABELED_PAIRS_V4_PATH),
        help="Output JSON path (default: scripts/eval_data/labeled_pairs_v4.json)",
    )
    parser.add_argument(
        "--family-cap",
        type=int,
        default=12,
        help="Maximum pairs per family before relaxed fill-in",
    )
    parser.add_argument(
        "--sample-markets",
        type=int,
        default=2500,
        help="Resolved embedded markets to scan for hard negatives",
    )
    args = parser.parse_args()

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    asyncio.run(
        export_goldset_v4(
            output_path=output_path,
            family_cap=args.family_cap,
            sample_markets=args.sample_markets,
        )
    )


if __name__ == "__main__":
    main()
