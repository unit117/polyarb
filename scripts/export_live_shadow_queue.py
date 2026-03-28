"""Export live shadow candidate logs into a manual review queue JSONL."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from shared.db import SessionFactory, init_db
from shared.models import ShadowCandidateLog


async def export_shadow_queue(
    *,
    output_path: Path,
    days: int,
    limit: int,
    fetch_limit: int,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with SessionFactory() as session:
        result = await session.execute(
            select(ShadowCandidateLog)
            .where(ShadowCandidateLog.logged_at >= cutoff)
            .order_by(ShadowCandidateLog.logged_at.desc())
            .limit(fetch_limit)
        )
        rows = list(result.scalars().all())

    rows.sort(key=_review_priority, reverse=True)
    selected = rows[:limit]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in selected:
            f.write(json.dumps(_serialize_row(row), ensure_ascii=True))
            f.write("\n")

    summary = _summarize(rows)
    summary["selected"] = len(selected)
    summary["output"] = str(output_path)
    return summary


def _review_priority(row: ShadowCandidateLog) -> tuple:
    severity = {
        "verification_failed": 5,
        "optimizer_rejected": 4,
        "uncertainty_filtered": 3,
        "classified_none": 2,
        "profit_non_positive": 1,
        "would_trade": 0,
        "detected": 0,
    }
    return (
        1 if row.silver_failure_signature else 0,
        severity.get(row.decision_outcome, 0),
        1 if row.passed_to_optimization and not row.would_trade else 0,
        float(row.classifier_confidence or 0.0),
        row.logged_at,
    )


def _serialize_row(row: ShadowCandidateLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "logged_at": _json_value(row.logged_at),
        "pipeline_source": row.pipeline_source,
        "decision_outcome": row.decision_outcome,
        "similarity": row.similarity,
        "pair_id": row.pair_id,
        "opportunity_id": row.opportunity_id,
        "market_a_id": row.market_a_id,
        "market_b_id": row.market_b_id,
        "market_a_event_id": row.market_a_event_id,
        "market_b_event_id": row.market_b_event_id,
        "market_a_question": row.market_a_question,
        "market_b_question": row.market_b_question,
        "market_a_outcomes": row.market_a_outcomes,
        "market_b_outcomes": row.market_b_outcomes,
        "market_a_venue": row.market_a_venue,
        "market_b_venue": row.market_b_venue,
        "market_a_liquidity": _json_value(row.market_a_liquidity),
        "market_b_liquidity": _json_value(row.market_b_liquidity),
        "market_a_volume": _json_value(row.market_a_volume),
        "market_b_volume": _json_value(row.market_b_volume),
        "snapshot_a_timestamp": _json_value(row.snapshot_a_timestamp),
        "snapshot_b_timestamp": _json_value(row.snapshot_b_timestamp),
        "prices_a": row.prices_a,
        "prices_b": row.prices_b,
        "market_a_best_bid": row.market_a_best_bid,
        "market_a_best_ask": row.market_a_best_ask,
        "market_a_spread": row.market_a_spread,
        "market_a_visible_depth": row.market_a_visible_depth,
        "market_b_best_bid": row.market_b_best_bid,
        "market_b_best_ask": row.market_b_best_ask,
        "market_b_spread": row.market_b_spread,
        "market_b_visible_depth": row.market_b_visible_depth,
        "dependency_type": row.dependency_type,
        "implication_direction": row.implication_direction,
        "classification_source": row.classification_source,
        "classifier_model": row.classifier_model,
        "classifier_prompt_adapter": row.classifier_prompt_adapter,
        "classifier_confidence": row.classifier_confidence,
        "classification_reasoning": row.classification_reasoning,
        "verification_passed": row.verification_passed,
        "verification_reasons": row.verification_reasons,
        "silver_failure_signature": row.silver_failure_signature,
        "profit_bound": _json_value(row.profit_bound),
        "passed_to_optimization": row.passed_to_optimization,
        "optimizer_preview_status": row.optimizer_preview_status,
        "optimizer_preview_estimated_profit": _json_value(
            row.optimizer_preview_estimated_profit
        ),
        "optimizer_preview_trade_count": row.optimizer_preview_trade_count,
        "optimizer_preview_max_edge": row.optimizer_preview_max_edge,
        "optimizer_preview_rejection_reason": row.optimizer_preview_rejection_reason,
        "would_trade": row.would_trade,
    }


def _summarize(rows: list[ShadowCandidateLog]) -> dict[str, Any]:
    outcome_counts = Counter(row.decision_outcome for row in rows)
    silver_counts = Counter(row.silver_failure_signature for row in rows if row.silver_failure_signature)
    verification_reason_counts = Counter()
    optimizer_rejection_counts = Counter()

    passed_to_optimization = 0
    would_trade = 0
    for row in rows:
        if row.passed_to_optimization:
            passed_to_optimization += 1
        if row.would_trade:
            would_trade += 1
        for reason in row.verification_reasons or []:
            verification_reason_counts[reason] += 1
        if row.optimizer_preview_rejection_reason:
            optimizer_rejection_counts[row.optimizer_preview_rejection_reason] += 1

    return {
        "rows_considered": len(rows),
        "passed_to_optimization": passed_to_optimization,
        "would_trade": would_trade,
        "decision_outcomes": dict(outcome_counts.most_common()),
        "silver_failure_signatures": dict(silver_counts.most_common()),
        "top_verification_reasons": dict(verification_reason_counts.most_common(10)),
        "top_optimizer_rejections": dict(optimizer_rejection_counts.most_common(10)),
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return Path("reports") / f"live_shadow_review_queue_{stamp}.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export durable shadow candidate logs to review-friendly JSONL",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_output_path(),
        help="JSONL destination (default: reports/live_shadow_review_queue_YYYY-MM-DD.jsonl)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="How many recent days of logs to consider (default: 7)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="How many highest-signal rows to export (default: 200)",
    )
    parser.add_argument(
        "--fetch-limit",
        type=int,
        default=5000,
        help="Initial SQL fetch cap before review prioritization (default: 5000)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await init_db()
    summary = await export_shadow_queue(
        output_path=args.output,
        days=args.days,
        limit=args.limit,
        fetch_limit=args.fetch_limit,
    )

    print("LIVE SHADOW REVIEW QUEUE")
    print(f"  Considered rows:        {summary['rows_considered']}")
    print(f"  Exported rows:          {summary['selected']}")
    print(f"  Passed optimization:    {summary['passed_to_optimization']}")
    print(f"  Would trade:            {summary['would_trade']}")
    print(f"  Output:                 {summary['output']}")

    if summary["decision_outcomes"]:
        print("\nDecision outcomes:")
        for key, value in summary["decision_outcomes"].items():
            print(f"  {key:28s} {value}")

    if summary["silver_failure_signatures"]:
        print("\nSilver-like verification blockers:")
        for key, value in summary["silver_failure_signatures"].items():
            print(f"  {key:28s} {value}")

    if summary["top_verification_reasons"]:
        print("\nTop verification reasons:")
        for key, value in summary["top_verification_reasons"].items():
            print(f"  {key[:60]:60s} {value}")

    if summary["top_optimizer_rejections"]:
        print("\nTop optimizer rejections:")
        for key, value in summary["top_optimizer_rejections"].items():
            print(f"  {key:28s} {value}")


if __name__ == "__main__":
    asyncio.run(main())
