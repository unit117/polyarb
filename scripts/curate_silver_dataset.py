"""V4 silver dataset curator: export a curated pair manifest for backtesting.

Queries the backtest DB for resolved, verified pairs and applies quality
filters to produce a pair-ID list suitable for --pair-file in backtest.py.

Filters:
- Both markets resolved within the backtest window
- Verified pairs only
- Dependency type in {implication, mutual_exclusion, partition} by default
  (conditional can be included with --include-conditional)
- Excludes noisy sports correlation patterns (O/U, BTTS, spread, handicap)
  unless --include-noisy-sports is set
- Requires meaningful question text on both sides

Output: JSON file with pair IDs and metadata, or plain text (one ID per line).

Usage:
    python -m scripts.curate_silver_dataset --output silver_pairs.json
    python -m scripts.curate_silver_dataset --output silver_pairs.txt --format text
    # Then run backtest with:
    python -m scripts.backtest --pair-file silver_pairs.json --authoritative
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import aliased

sys.path.insert(0, ".")

from shared.db import SessionFactory, init_db
from shared.models import Market, MarketPair
from scripts.export_goldset_v4 import (
    classify_pair_family as classify_family,
    _has_meaningful_text as has_meaningful_text,
    _is_obvious_duplicate as is_obvious_duplicate,
    _shared_keywords as shared_keywords,
)


# Noisy sports patterns — these produce high-volume but unreliable pairs
_NOISY_SPORTS_RE = re.compile(
    r"\bover\b|\bunder\b|\bo/u\b|over\/under|both teams to score|\bbtts\b"
    r"|\bspread\b|\bhandicap\b",
    re.IGNORECASE,
)


def _is_noisy_sports(question: str) -> bool:
    return bool(_NOISY_SPORTS_RE.search(question))


async def curate_silver(
    output: Path,
    fmt: str = "json",
    include_conditional: bool = False,
    include_noisy_sports: bool = False,
    min_shared_keywords: int = 0,
) -> list[dict]:
    """Query DB and apply silver filters. Returns list of pair records."""
    await init_db()

    dep_types = ["implication", "mutual_exclusion", "partition"]
    if include_conditional:
        dep_types.append("conditional")

    MarketA = aliased(Market)
    MarketB = aliased(Market)

    async with SessionFactory() as session:
        result = await session.execute(
            select(MarketPair, MarketA, MarketB)
            .join(MarketA, MarketA.id == MarketPair.market_a_id)
            .join(MarketB, MarketB.id == MarketPair.market_b_id)
            .where(MarketPair.verified == True)  # noqa: E712
            .where(MarketPair.dependency_type.in_(dep_types))
            .where(MarketA.resolved_outcome.isnot(None))
            .where(MarketA.resolved_at.isnot(None))
            .where(MarketB.resolved_outcome.isnot(None))
            .where(MarketB.resolved_at.isnot(None))
        )

        pairs_data: list[dict] = []
        skip_counts: Counter = Counter()

        for pair, mkt_a, mkt_b in result.all():
            # Text quality
            if not has_meaningful_text(mkt_a.question, mkt_a.description):
                skip_counts["bad_text"] += 1
                continue
            if not has_meaningful_text(mkt_b.question, mkt_b.description):
                skip_counts["bad_text"] += 1
                continue

            # Duplicate check
            out_a = mkt_a.outcomes if isinstance(mkt_a.outcomes, list) else []
            out_b = mkt_b.outcomes if isinstance(mkt_b.outcomes, list) else []
            if is_obvious_duplicate(mkt_a.question, mkt_b.question, out_a, out_b):
                skip_counts["duplicate"] += 1
                continue

            # Noisy sports filter
            if not include_noisy_sports:
                if _is_noisy_sports(mkt_a.question) or _is_noisy_sports(mkt_b.question):
                    skip_counts["noisy_sports"] += 1
                    continue

            # Keyword overlap filter
            if min_shared_keywords > 0:
                kw = shared_keywords(mkt_a.question, mkt_b.question)
                if len(kw) < min_shared_keywords:
                    skip_counts["low_keyword_overlap"] += 1
                    continue

            family = classify_family(
                mkt_a.question, mkt_b.question,
                mkt_a.description or "", mkt_b.description or "",
                dep_type=pair.dependency_type,
            )

            pairs_data.append({
                "pair_id": pair.id,
                "dependency_type": pair.dependency_type,
                "confidence": float(pair.confidence or 0),
                "family": family,
                "question_a": mkt_a.question,
                "question_b": mkt_b.question,
                "market_a_id": mkt_a.id,
                "market_b_id": mkt_b.id,
            })

    # Write output
    output.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "text":
        output.write_text("\n".join(str(p["pair_id"]) for p in pairs_data) + "\n")
    else:
        output.write_text(json.dumps(pairs_data, indent=2))

    # Stats
    type_counts = Counter(p["dependency_type"] for p in pairs_data)
    family_counts = Counter(p["family"] for p in pairs_data)

    print(f"Silver dataset: {len(pairs_data)} pairs → {output}")
    print(f"Type counts: {dict(type_counts)}")
    print(f"Family counts: {dict(family_counts)}")
    if skip_counts:
        print(f"Skipped: {dict(skip_counts)}")

    return pairs_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate V4 silver pair dataset")
    parser.add_argument(
        "--output", "-o",
        default="scripts/eval_data/silver_pairs_v4.json",
        help="Output file path",
    )
    parser.add_argument(
        "--format", dest="fmt",
        choices=["json", "text"],
        default="json",
        help="Output format: json (with metadata) or text (IDs only)",
    )
    parser.add_argument(
        "--include-conditional",
        action="store_true",
        help="Include conditional pairs (excluded by default)",
    )
    parser.add_argument(
        "--include-noisy-sports",
        action="store_true",
        help="Include O/U, BTTS, spread, handicap pairs",
    )
    parser.add_argument(
        "--min-shared-keywords",
        type=int, default=0,
        help="Minimum shared keywords between pair questions",
    )
    args = parser.parse_args()

    output = Path(args.output)
    if not output.is_absolute():
        output = Path.cwd() / output

    asyncio.run(curate_silver(
        output,
        fmt=args.fmt,
        include_conditional=args.include_conditional,
        include_noisy_sports=args.include_noisy_sports,
        min_shared_keywords=args.min_shared_keywords,
    ))


if __name__ == "__main__":
    main()
