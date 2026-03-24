"""Classifier evaluation harness.

Pulls classified pairs from the DB, exports for manual labeling, and scores
accuracy with multi-model comparison support.

Usage:
    # Step 1: Export pairs for labeling
    python -m scripts.eval_classifier export --n 200

    # Step 2: After hand-labeling scripts/eval_data/labeled_pairs.json, evaluate
    python -m scripts.eval_classifier eval

    # Optional: summarize label-transition and family-level failure modes
    python -m scripts.eval_classifier analyze --data-file scripts/eval_data/labeled_pairs_v4.json

    # Step 3: Compare models (resolution vectors vs label-based)
    python -m scripts.eval_classifier eval --model gpt-4.1-mini --compare minimax/minimax-m2.7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openai
import structlog

from shared.config import settings
from shared.db import init_db, SessionFactory

logger = structlog.get_logger()

EVAL_DATA_DIR = Path(__file__).parent / "eval_data"
LABELED_PAIRS_PATH = EVAL_DATA_DIR / "labeled_pairs.json"


def _resolve_data_file(path_str: str | None) -> Path:
    """Resolve a CLI-provided dataset path relative to the current working dir."""
    if not path_str:
        return LABELED_PAIRS_PATH
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _normalize_current_type(pair: dict) -> str:
    current = pair.get("current_dependency_type", "")
    return "none" if current == "none_candidate" else current


def _load_labeled_pairs(data_file: Path) -> list[dict]:
    if not data_file.exists():
        print(f"ERROR: {data_file} not found. Run 'export' first.")
        sys.exit(1)

    pairs = json.loads(data_file.read_text())
    labeled = [p for p in pairs if p.get("ground_truth_type")]
    if not labeled:
        print("ERROR: No labeled pairs found. Fill in 'ground_truth_type' field.")
        sys.exit(1)
    return labeled


def _summarize_labeled_pairs(
    pairs: list[dict],
    *,
    examples_per_transition: int = 3,
) -> dict:
    summary = {
        "total": len(pairs),
        "correct": sum(1 for p in pairs if p.get("correct") is True),
        "current_counts": Counter(),
        "ground_truth_counts": Counter(),
        "confusion": Counter(),
        "family_totals": Counter(),
        "family_wrong": Counter(),
        "family_transitions": defaultdict(Counter),
        "transition_examples": defaultdict(list),
    }

    for pair in pairs:
        current = _normalize_current_type(pair)
        ground_truth = pair.get("ground_truth_type", "")
        family = pair.get("pair_family") or "<none>"

        summary["current_counts"][current] += 1
        summary["ground_truth_counts"][ground_truth] += 1
        summary["family_totals"][family] += 1

        if current == ground_truth:
            continue

        transition = (current, ground_truth)
        summary["confusion"][transition] += 1
        summary["family_wrong"][family] += 1
        summary["family_transitions"][family][transition] += 1

        examples = summary["transition_examples"][transition]
        if len(examples) < examples_per_transition:
            examples.append({
                "pair_family": family,
                "question_a": pair.get("question_a", ""),
                "question_b": pair.get("question_b", ""),
                "notes": pair.get("notes", ""),
            })

    return summary


def _print_analysis(
    summary: dict,
    *,
    top_transitions: int,
    top_families: int,
) -> None:
    total = summary["total"]
    correct = summary["correct"]
    accuracy = (correct / total * 100) if total else 0.0

    print("# Classifier Dataset Analysis")
    print("")
    print(f"- Total labeled pairs: {total}")
    print(f"- Current-system accuracy: {correct}/{total} ({accuracy:.1f}%)")
    print("")

    print("## Current Label Counts")
    for dep_type, count in sorted(summary["current_counts"].items()):
        print(f"- {dep_type}: {count}")
    print("")

    print("## Ground Truth Counts")
    for dep_type, count in sorted(summary["ground_truth_counts"].items()):
        print(f"- {dep_type}: {count}")
    print("")

    print("## Largest Label Transitions")
    for (current, ground_truth), count in summary["confusion"].most_common(top_transitions):
        print(f"- {current} -> {ground_truth}: {count}")
    print("")

    print("## Worst Families")
    family_rows = sorted(
        summary["family_totals"].items(),
        key=lambda item: (
            summary["family_wrong"][item[0]] / item[1] if item[1] else 0.0,
            summary["family_wrong"][item[0]],
            item[1],
            item[0],
        ),
        reverse=True,
    )
    for family, total_rows in family_rows[:top_families]:
        wrong = summary["family_wrong"][family]
        error_rate = (wrong / total_rows * 100) if total_rows else 0.0
        transitions = ", ".join(
            f"{current}->{ground_truth}:{count}"
            for (current, ground_truth), count in summary["family_transitions"][family].most_common(3)
        ) or "all correct"
        print(f"- {family}: {wrong}/{total_rows} wrong ({error_rate:.1f}%) [{transitions}]")
    print("")

    print("## Sample Disagreements")
    for (current, ground_truth), count in summary["confusion"].most_common(top_transitions):
        print(f"### {current} -> {ground_truth} ({count})")
        for example in summary["transition_examples"][(current, ground_truth)]:
            print(
                f"- [{example['pair_family']}] "
                f"{example['question_a']} || {example['question_b']}"
            )
            if example["notes"]:
                print(f"  note: {example['notes']}")
        print("")


async def export_pairs(n: int = 200, output_path: Path = LABELED_PAIRS_PATH) -> None:
    """Export N classified pairs from the DB for manual labeling.

    Stratified sampling: over-sample independent-but-semantically-similar pairs
    (the confusion class that matters most — independent pairs misclassified as ME).
    """
    await init_db()

    from sqlalchemy import select, func
    from shared.models import MarketPair, Market

    async with SessionFactory() as session:
        # Get counts per dependency type
        count_query = (
            select(MarketPair.dependency_type, func.count())
            .group_by(MarketPair.dependency_type)
        )
        counts = dict((await session.execute(count_query)).all())
        total = sum(counts.values())
        print(f"DB pair counts: {counts} (total: {total})")

        # Stratified sampling: at least 40% from each type present,
        # but over-sample ME and independent pairs
        type_allocations = {}
        dep_types = list(counts.keys())
        base_per_type = max(1, n // max(len(dep_types), 1))

        for dt in dep_types:
            available = counts.get(dt, 0)
            # Over-sample ME — the confusion class
            if dt == "mutual_exclusion":
                alloc = min(available, max(base_per_type, n // 3))
            elif dt == "none":
                alloc = min(available, max(base_per_type, n // 4))
            else:
                alloc = min(available, base_per_type)
            type_allocations[dt] = alloc

        # If under budget, distribute remainder
        remaining = n - sum(type_allocations.values())
        for dt in dep_types:
            if remaining <= 0:
                break
            available = counts.get(dt, 0) - type_allocations.get(dt, 0)
            add = min(remaining, available)
            type_allocations[dt] = type_allocations.get(dt, 0) + add
            remaining -= add

        print(f"Sampling allocations: {type_allocations}")

        # Fetch pairs per type
        pairs_data = []
        for dt, alloc in type_allocations.items():
            if alloc <= 0:
                continue
            query = (
                select(MarketPair)
                .where(MarketPair.dependency_type == dt)
                .order_by(func.random())
                .limit(alloc)
            )
            result = await session.execute(query)
            db_pairs = result.scalars().all()

            for pair in db_pairs:
                market_a = await session.get(Market, pair.market_a_id)
                market_b = await session.get(Market, pair.market_b_id)
                if not market_a or not market_b:
                    continue

                pairs_data.append({
                    "pair_id": pair.id,
                    "market_a_id": pair.market_a_id,
                    "market_b_id": pair.market_b_id,
                    "question_a": market_a.question,
                    "question_b": market_b.question,
                    "description_a": market_a.description or "",
                    "description_b": market_b.description or "",
                    "outcomes_a": market_a.outcomes if isinstance(market_a.outcomes, list) else [],
                    "outcomes_b": market_b.outcomes if isinstance(market_b.outcomes, list) else [],
                    "event_id_a": market_a.event_id,
                    "event_id_b": market_b.event_id,
                    "current_dependency_type": pair.dependency_type,
                    "current_confidence": float(pair.confidence) if pair.confidence else 0.0,
                    "verified": pair.verified,
                    # To be filled by hand:
                    "ground_truth_type": "",
                    "correct": None,
                    "notes": "",
                })

        # Generate independent-pair candidates: sample semantically SIMILAR
        # market pairs NOT persisted as MarketPair rows. These are the hard
        # negative class — pairs the detector considered but discarded.
        # Use cosine similarity on embeddings to find near-miss pairs.
        n_independent = max(80, n // 3)
        existing_pair_keys = set()
        for p in pairs_data:
            existing_pair_keys.add((p["market_a_id"], p["market_b_id"]))
            existing_pair_keys.add((p["market_b_id"], p["market_a_id"]))

        # Fetch random markets with embeddings
        import numpy as np

        market_query = (
            select(Market)
            .where(Market.embedding.isnot(None))
            .order_by(func.random())
            .limit(500)
        )
        market_result = await session.execute(market_query)
        markets = market_result.scalars().all()

        # Compute cosine similarities and keep the most similar non-persisted pairs
        scored_candidates = []
        seen = set()
        for i, m_a in enumerate(markets):
            if m_a.embedding is None:
                continue
            vec_a = np.array(m_a.embedding, dtype=np.float32)
            norm_a = np.linalg.norm(vec_a)
            if norm_a == 0:
                continue
            for m_b in markets[i + 1:]:
                if m_b.embedding is None:
                    continue
                key = (min(m_a.id, m_b.id), max(m_a.id, m_b.id))
                if key in seen or key in existing_pair_keys:
                    continue
                seen.add(key)

                vec_b = np.array(m_b.embedding, dtype=np.float32)
                norm_b = np.linalg.norm(vec_b)
                if norm_b == 0:
                    continue
                similarity = float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
                scored_candidates.append((similarity, m_a, m_b))

        # Sort by similarity descending — take the most similar pairs
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        independent_candidates = []
        for similarity, m_a, m_b in scored_candidates:
            if len(independent_candidates) >= n_independent:
                break

            # Skip if already a persisted pair
            pair_check = await session.execute(
                select(MarketPair.id).where(
                    ((MarketPair.market_a_id == m_a.id) & (MarketPair.market_b_id == m_b.id))
                    | ((MarketPair.market_a_id == m_b.id) & (MarketPair.market_b_id == m_a.id))
                ).limit(1)
            )
            if pair_check.scalar_one_or_none() is not None:
                continue

            independent_candidates.append({
                "pair_id": None,
                "market_a_id": m_a.id,
                "market_b_id": m_b.id,
                "question_a": m_a.question,
                "question_b": m_b.question,
                "description_a": m_a.description or "",
                "description_b": m_b.description or "",
                "outcomes_a": m_a.outcomes if isinstance(m_a.outcomes, list) else [],
                "outcomes_b": m_b.outcomes if isinstance(m_b.outcomes, list) else [],
                "event_id_a": m_a.event_id,
                "event_id_b": m_b.event_id,
                "current_dependency_type": "none_candidate",
                "current_confidence": 0.0,
                "verified": False,
                "ground_truth_type": "",
                "correct": None,
                "notes": f"cosine_similarity={similarity:.3f}",
            })

        pairs_data.extend(independent_candidates)
        print(f"Added {len(independent_candidates)} independent-pair candidates")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(pairs_data, indent=2))
    print(f"\nExported {len(pairs_data)} pairs to {output_path}")
    print("Next: hand-label 'ground_truth_type' and 'correct' fields, then run 'eval'")


def _infer_classification_source(pair: dict) -> str:
    """Infer whether a pair was classified by rule-based or LLM by replaying rules.

    All rule-based checks are synchronous functions — call them directly to
    avoid nesting event loops (this runs inside asyncio.run already).
    """
    from services.detector.classifier import (
        _check_same_event,
        _check_outcome_subset,
        _check_crypto_time_intervals,
        _check_milestone_threshold_markets,
        _check_price_threshold_markets,
        _check_ranking_markets,
        _check_over_under_markets,
    )

    market_a = {
        "question": pair["question_a"],
        "description": pair.get("description_a", ""),
        "outcomes": pair.get("outcomes_a", []),
        "event_id": pair.get("event_id_a"),
    }
    market_b = {
        "question": pair["question_b"],
        "description": pair.get("description_b", ""),
        "outcomes": pair.get("outcomes_b", []),
        "event_id": pair.get("event_id_b"),
    }

    for check in (
        _check_same_event,
        _check_outcome_subset,
        _check_crypto_time_intervals,
        _check_milestone_threshold_markets,
        _check_price_threshold_markets,
        _check_ranking_markets,
        _check_over_under_markets,
    ):
        result = check(market_a, market_b)
        if result and result.get("dependency_type") == pair["current_dependency_type"]:
            return "rule_based"
    return "llm"


async def _classify_with_model(
    client: openai.AsyncOpenAI,
    model: str,
    pair: dict,
    use_vectors: bool = True,
    prompt_adapter: str = "auto",
) -> dict:
    """Classify a single pair with a given model. Returns classification dict."""
    from services.detector.classifier import (
        classify_llm_resolution,
        classify_llm,
    )

    market_a = {
        "question": pair["question_a"],
        "description": pair.get("description_a", ""),
        "outcomes": pair.get("outcomes_a", ["Yes", "No"]),
    }
    market_b = {
        "question": pair["question_b"],
        "description": pair.get("description_b", ""),
        "outcomes": pair.get("outcomes_b", ["Yes", "No"]),
    }

    if use_vectors:
        result = await classify_llm_resolution(
            client,
            model,
            market_a,
            market_b,
            prompt_adapter=prompt_adapter,
        )
        if result:
            return result

    # Fallback to label-based
    result = await classify_llm(
        client,
        model,
        market_a,
        market_b,
        prompt_adapter=prompt_adapter,
    )
    result["classification_source"] = "llm_label"
    return result


async def evaluate(
    model: str = "",
    compare_model: str = "",
    compare_base_url: str = "",
    use_vectors: bool = True,
    prompt_adapter: str = "auto",
    compare_prompt_adapter: str = "auto",
    data_file: Path = LABELED_PAIRS_PATH,
    base_url: str = "",
    api_key: str = "",
    summary_json: str = "",
) -> None:
    """Evaluate classifier accuracy against hand-labeled ground truth."""
    labeled = _load_labeled_pairs(data_file)

    print(f"Evaluating {len(labeled)} labeled pairs")

    # Score current classifications
    _score_classifications(labeled, "Current System")

    # If a model is specified, re-classify and score
    if model:
        _api_key = api_key or settings.openrouter_api_key or settings.openai_api_key
        _base_url = base_url or settings.classifier_base_url or None
        client = openai.AsyncOpenAI(
            api_key=_api_key,
            **({"base_url": _base_url} if _base_url else {}),
        )

        print(
            f"\n--- Re-classifying with {model} "
            f"(vectors={use_vectors}, prompt_adapter={prompt_adapter}) ---"
        )
        for p in labeled:
            result = await _classify_with_model(
                client,
                model,
                p,
                use_vectors,
                prompt_adapter=prompt_adapter,
            )
            p[f"reclassified_{model}"] = result.get("dependency_type", "none")
            p[f"reclassified_{model}_source"] = result.get("classification_source", "")

        metrics = _score_reclassifications(labeled, model)

        if summary_json:
            Path(summary_json).write_text(json.dumps(metrics, indent=2))
            print(f"\nSummary written to {summary_json}")

    # Shadow comparison model
    if compare_model:
        compare_key = settings.openrouter_api_key or settings.openai_api_key
        compare_client = openai.AsyncOpenAI(
            api_key=compare_key,
            **({"base_url": compare_base_url} if compare_base_url else {}),
        )

        print(
            f"\n--- Shadow comparison with {compare_model} "
            f"(prompt_adapter={compare_prompt_adapter}) ---"
        )
        for p in labeled:
            result = await _classify_with_model(
                compare_client,
                compare_model,
                p,
                use_vectors,
                prompt_adapter=compare_prompt_adapter,
            )
            p[f"shadow_{compare_model}"] = result.get("dependency_type", "none")

        _score_reclassifications(labeled, compare_model, prefix="shadow_")


def analyze(
    *,
    data_file: Path = LABELED_PAIRS_PATH,
    top_transitions: int = 10,
    top_families: int = 10,
    examples_per_transition: int = 3,
) -> None:
    """Analyze labeled-pair failure modes by transition and family."""
    labeled = _load_labeled_pairs(data_file)
    summary = _summarize_labeled_pairs(
        labeled,
        examples_per_transition=examples_per_transition,
    )
    _print_analysis(
        summary,
        top_transitions=top_transitions,
        top_families=top_families,
    )


def _score_classifications(pairs: list[dict], label: str) -> None:
    """Score current system classifications against ground truth."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    # Overall accuracy
    correct = sum(1 for p in pairs if p.get("correct") is True)
    total = len(pairs)
    print(f"Overall accuracy: {correct}/{total} ({correct/total*100:.1f}%)")

    # Break down by inferred source
    by_source = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in pairs:
        source = _infer_classification_source(p)
        by_source[source]["total"] += 1
        if p.get("correct") is True:
            by_source[source]["correct"] += 1

    print("\nBy classification source:")
    for source, stats in sorted(by_source.items()):
        acc = stats["correct"] / stats["total"] * 100 if stats["total"] else 0
        print(f"  {source}: {stats['correct']}/{stats['total']} ({acc:.1f}%)")

    # Per-type precision/recall
    dep_types = set(p.get("ground_truth_type", "") for p in pairs) | set(
        _normalize_current_type(p) for p in pairs
    )
    dep_types.discard("")

    print("\nPer-type metrics:")
    print(f"  {'Type':<20} {'Prec':>6} {'Rec':>6} {'F1':>6} {'TP':>4} {'FP':>4} {'FN':>4}")
    print(f"  {'-'*56}")

    total_fp_independent = 0
    for dt in sorted(dep_types):
        tp = sum(1 for p in pairs
                 if _normalize_current_type(p) == dt and p["ground_truth_type"] == dt)
        fp = sum(1 for p in pairs
                 if _normalize_current_type(p) == dt and p["ground_truth_type"] != dt)
        fn = sum(1 for p in pairs
                 if _normalize_current_type(p) != dt and p["ground_truth_type"] == dt)

        prec = tp / (tp + fp) if (tp + fp) else 0
        rec = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0

        print(f"  {dt:<20} {prec:>6.1%} {rec:>6.1%} {f1:>6.1%} {tp:>4} {fp:>4} {fn:>4}")

        # Track FP on independent pairs (primary KPI)
        if dt != "none":
            fp_indep = sum(1 for p in pairs
                          if _normalize_current_type(p) == dt
                          and p["ground_truth_type"] == "none")
            total_fp_independent += fp_indep

    indep_total = sum(1 for p in pairs if p["ground_truth_type"] == "none")
    fpr = total_fp_independent / indep_total * 100 if indep_total else 0
    print(f"\n  ** Independent-pair FPR: {total_fp_independent}/{indep_total} ({fpr:.1f}%) **")

    # Macro F1
    f1_scores = []
    for dt in sorted(dep_types):
        tp = sum(1 for p in pairs
                 if _normalize_current_type(p) == dt and p["ground_truth_type"] == dt)
        fp = sum(1 for p in pairs
                 if _normalize_current_type(p) == dt and p["ground_truth_type"] != dt)
        fn = sum(1 for p in pairs
                 if _normalize_current_type(p) != dt and p["ground_truth_type"] == dt)
        prec = tp / (tp + fp) if (tp + fp) else 0
        rec = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
        f1_scores.append(f1)
    macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0
    print(f"\n  ** Macro F1: {macro_f1:.3f} **")

    # Confusion matrix
    all_types = sorted(dep_types)
    print(f"\nConfusion Matrix (rows=predicted, cols=ground_truth):")
    header = f"  {'':>20}" + "".join(f"{t:>12}" for t in all_types)
    print(header)
    for pred in all_types:
        row = f"  {pred:>20}"
        for truth in all_types:
            count = sum(1 for p in pairs
                        if _normalize_current_type(p) == pred and p["ground_truth_type"] == truth)
            row += f"{count:>12}"
        print(row)

    # Per-family breakdown (if pair_family field exists)
    families = set(p.get("pair_family", "") for p in pairs)
    families.discard("")
    if families:
        print(f"\nPer-family accuracy:")
        print(f"  {'Family':<30} {'Correct':>8} {'Total':>6} {'Acc':>7}")
        print(f"  {'-'*53}")
        for fam in sorted(families):
            fam_pairs = [p for p in pairs if p.get("pair_family") == fam]
            fam_correct = sum(1 for p in fam_pairs if p.get("correct") is True)
            fam_total = len(fam_pairs)
            fam_acc = fam_correct / fam_total * 100 if fam_total else 0
            print(f"  {fam:<30} {fam_correct:>8} {fam_total:>6} {fam_acc:>6.1f}%")


def _score_reclassifications(
    pairs: list[dict], model: str, prefix: str = "reclassified_"
) -> dict:
    """Score reclassified results against ground truth with full metrics.

    Returns dict with accuracy_pct, correct, total, macro_f1, fpr_pct.
    """
    key = f"{prefix}{model}"
    correct = sum(1 for p in pairs if p.get(key) == p.get("ground_truth_type"))
    total = len(pairs)
    print(f"\n{model} accuracy: {correct}/{total} ({correct/total*100:.1f}%)")

    # Per-type precision/recall/F1
    dep_types = set(p.get("ground_truth_type", "") for p in pairs) | set(
        p.get(key, "") for p in pairs
    )
    dep_types.discard("")

    print(f"\n  {'Type':<20} {'Prec':>6} {'Rec':>6} {'F1':>6} {'TP':>4} {'FP':>4} {'FN':>4}")
    print(f"  {'-'*56}")

    f1_scores = []
    for dt in sorted(dep_types):
        tp = sum(1 for p in pairs if p.get(key) == dt and p["ground_truth_type"] == dt)
        fp = sum(1 for p in pairs if p.get(key) == dt and p["ground_truth_type"] != dt)
        fn = sum(1 for p in pairs if p.get(key) != dt and p["ground_truth_type"] == dt)
        prec = tp / (tp + fp) if (tp + fp) else 0
        rec = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
        f1_scores.append(f1)
        print(f"  {dt:<20} {prec:>6.1%} {rec:>6.1%} {f1:>6.1%} {tp:>4} {fp:>4} {fn:>4}")

    macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0
    print(f"\n  ** Macro F1: {macro_f1:.3f} **")

    # FPR on independent pairs
    fp_indep = sum(1 for p in pairs
                   if p.get(key, "none") != "none"
                   and p.get("ground_truth_type") == "none")
    indep_total = sum(1 for p in pairs if p["ground_truth_type"] == "none")
    fpr = fp_indep / indep_total * 100 if indep_total else 0
    print(f"  ** Independent-pair FPR: {fp_indep}/{indep_total} ({fpr:.1f}%) **")

    # Confusion matrix
    all_types = sorted(dep_types)
    print(f"\n  Confusion Matrix (rows=predicted, cols=ground_truth):")
    header = f"  {'':>20}" + "".join(f"{t:>12}" for t in all_types)
    print(header)
    for pred in all_types:
        row = f"  {pred:>20}"
        for truth in all_types:
            count = sum(1 for p in pairs if p.get(key) == pred and p["ground_truth_type"] == truth)
            row += f"{count:>12}"
        print(row)

    # Per-family breakdown
    families = set(p.get("pair_family", "") for p in pairs)
    families.discard("")
    if families:
        print(f"\n  Per-family accuracy:")
        print(f"  {'Family':<30} {'Correct':>8} {'Total':>6} {'Acc':>7}")
        print(f"  {'-'*53}")
        for fam in sorted(families):
            fam_pairs = [p for p in pairs if p.get("pair_family") == fam]
            fam_correct = sum(1 for p in fam_pairs if p.get(key) == p.get("ground_truth_type"))
            fam_total = len(fam_pairs)
            fam_acc = fam_correct / fam_total * 100 if fam_total else 0
            print(f"  {fam:<30} {fam_correct:>8} {fam_total:>6} {fam_acc:>6.1f}%")

    return {
        "model": model,
        "correct": correct,
        "total": total,
        "accuracy_pct": round(correct / total * 100, 1) if total else 0,
        "macro_f1": round(macro_f1, 3),
        "fpr_pct": round(fpr, 1),
    }


async def autolabel(
    model: str = "gpt-4.1-mini",
    use_vectors: bool = True,
    prompt_adapter: str = "auto",
    data_file: Path = LABELED_PAIRS_PATH,
) -> None:
    """Auto-label pairs using the full 3-tier classify_pair pipeline.

    Runs rule-based → resolution vectors → LLM fallback on each pair and
    fills in ground_truth_type with the result. Also records the source and
    reasoning for review. Marks 'correct' = True when auto-label matches
    current_dependency_type.

    This is NOT true ground truth — it's the new classifier's opinion.
    Review disagreements manually to produce real ground truth.
    """
    if not data_file.exists():
        print(f"ERROR: {data_file} not found. Run 'export' first.")
        sys.exit(1)

    pairs = json.loads(data_file.read_text())
    print(
        f"Auto-labeling {len(pairs)} pairs with {model} "
        f"(vectors={use_vectors}, prompt_adapter={prompt_adapter})"
    )

    from services.detector.classifier import classify_pair

    api_key = settings.openrouter_api_key or settings.openai_api_key
    base_url = settings.classifier_base_url or None
    client = openai.AsyncOpenAI(
        api_key=api_key,
        **({"base_url": base_url} if base_url else {}),
    )

    changed = 0
    errors = 0
    by_source = defaultdict(int)

    for i, p in enumerate(pairs):
        market_a = {
            "id": p.get("market_a_id"),
            "event_id": p.get("event_id_a"),
            "question": p["question_a"],
            "description": p.get("description_a", ""),
            "outcomes": p.get("outcomes_a", ["Yes", "No"]),
        }
        market_b = {
            "id": p.get("market_b_id"),
            "event_id": p.get("event_id_b"),
            "question": p["question_b"],
            "description": p.get("description_b", ""),
            "outcomes": p.get("outcomes_b", ["Yes", "No"]),
        }

        try:
            result = await classify_pair(
                client,
                model,
                market_a,
                market_b,
                prompt_adapter=prompt_adapter,
            )
            label = result.get("dependency_type", "none")
            source = result.get("classification_source", "unknown")
            reasoning = result.get("reasoning", "")

            p["ground_truth_type"] = label
            p["autolabel_source"] = source
            p["autolabel_reasoning"] = reasoning[:200]
            p["autolabel_confidence"] = result.get("confidence", 0.0)

            current = p.get("current_dependency_type", "")
            if current == "none_candidate":
                current = "none"
            p["correct"] = (current == label)
            if current != label:
                changed += 1
            by_source[source] += 1

        except Exception as e:
            errors += 1
            p["ground_truth_type"] = ""
            p["autolabel_error"] = str(e)[:100]
            logger.exception("autolabel_error", pair_index=i)

        if (i + 1) % 20 == 0:
            print(f"  Progress: {i+1}/{len(pairs)} ({changed} changed, {errors} errors)")

    # Save results
    data_file.write_text(json.dumps(pairs, indent=2))

    print(f"\nAuto-labeling complete:")
    print(f"  Total: {len(pairs)}")
    print(f"  Changed from current: {changed} ({changed/len(pairs)*100:.1f}%)")
    print(f"  Errors: {errors}")
    print(f"  By source: {dict(by_source)}")
    print(f"\nSaved to {data_file}")
    print("Review disagreements manually, then run 'eval' to score.")


def main():
    parser = argparse.ArgumentParser(description="Classifier eval harness")
    sub = parser.add_subparsers(dest="command")

    export_p = sub.add_parser("export", help="Export pairs for labeling")
    export_p.add_argument("--n", type=int, default=200, help="Number of pairs to export")
    export_p.add_argument(
        "--data-file",
        default="",
        help="Output JSON path (default: scripts/eval_data/labeled_pairs.json)",
    )

    eval_p = sub.add_parser("eval", help="Evaluate against labeled pairs")
    eval_p.add_argument("--model", default="", help="Model to re-classify with")
    eval_p.add_argument("--base-url", default="", help="Base URL for primary model API")
    eval_p.add_argument("--api-key", default="", help="API key for primary model")
    eval_p.add_argument("--compare", default="", help="Shadow comparison model")
    eval_p.add_argument("--compare-base-url", default="", help="Base URL for comparison model")
    eval_p.add_argument("--no-vectors", action="store_true", help="Disable resolution vectors")
    eval_p.add_argument(
        "--prompt-adapter",
        choices=["auto", "openai_generic", "claude_xml"],
        default="auto",
        help="Prompt adapter for the primary model",
    )
    eval_p.add_argument(
        "--compare-prompt-adapter",
        choices=["auto", "openai_generic", "claude_xml"],
        default="auto",
        help="Prompt adapter for the comparison model",
    )
    eval_p.add_argument(
        "--data-file",
        default="",
        help="Input JSON path (default: scripts/eval_data/labeled_pairs.json)",
    )
    eval_p.add_argument(
        "--summary-json",
        default="",
        help="Write machine-readable accuracy JSON to this path",
    )

    auto_p = sub.add_parser("autolabel", help="Auto-label pairs using 3-tier pipeline")
    auto_p.add_argument("--model", default="gpt-4.1-mini", help="Model to classify with")
    auto_p.add_argument("--no-vectors", action="store_true", help="Disable resolution vectors")
    auto_p.add_argument(
        "--prompt-adapter",
        choices=["auto", "openai_generic", "claude_xml"],
        default="auto",
        help="Prompt adapter for the autolabel model",
    )
    auto_p.add_argument(
        "--data-file",
        default="",
        help="Input JSON path (default: scripts/eval_data/labeled_pairs.json)",
    )

    analyze_p = sub.add_parser("analyze", help="Analyze labeled-pair failure modes")
    analyze_p.add_argument(
        "--data-file",
        default="",
        help="Input JSON path (default: scripts/eval_data/labeled_pairs.json)",
    )
    analyze_p.add_argument(
        "--top-transitions",
        type=int,
        default=10,
        help="How many label transitions to print",
    )
    analyze_p.add_argument(
        "--top-families",
        type=int,
        default=10,
        help="How many families to print",
    )
    analyze_p.add_argument(
        "--examples-per-transition",
        type=int,
        default=3,
        help="How many example disagreements to show per transition",
    )

    args = parser.parse_args()

    if args.command == "export":
        asyncio.run(export_pairs(args.n, output_path=_resolve_data_file(args.data_file)))
    elif args.command == "eval":
        asyncio.run(evaluate(
            model=args.model,
            compare_model=args.compare,
            compare_base_url=args.compare_base_url,
            use_vectors=not args.no_vectors,
            prompt_adapter=args.prompt_adapter,
            compare_prompt_adapter=args.compare_prompt_adapter,
            data_file=_resolve_data_file(args.data_file),
            base_url=args.base_url,
            api_key=args.api_key,
            summary_json=args.summary_json,
        ))
    elif args.command == "autolabel":
        asyncio.run(autolabel(
            model=args.model,
            use_vectors=not args.no_vectors,
            prompt_adapter=args.prompt_adapter,
            data_file=_resolve_data_file(args.data_file),
        ))
    elif args.command == "analyze":
        analyze(
            data_file=_resolve_data_file(args.data_file),
            top_transitions=args.top_transitions,
            top_families=args.top_families,
            examples_per_transition=args.examples_per_transition,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
