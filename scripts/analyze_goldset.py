"""Gold set quality analyzer: validate and summarize a labeled pair dataset.

Reads a gold-set JSON (output from export_goldset_v4.py or hand-labeled) and
produces quality metrics, distribution checks, and labeling gap reports.

Usage:
    python -m scripts.analyze_goldset scripts/eval_data/labeled_pairs_v4.json
    python -m scripts.analyze_goldset --check-gate labeled_pairs_v4.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Target composition for gate checks
TARGET_COMPOSITION = {
    "implication": 45,
    "mutual_exclusion": 35,
    "partition": 25,
    "conditional": 25,
    "none": 40,
}


def load_dataset(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        print(f"ERROR: Expected list, got {type(data).__name__}", file=sys.stderr)
        sys.exit(1)
    return data


def analyze(records: list[dict]) -> dict:
    """Compute summary statistics for a gold set."""
    stats: dict = {}
    stats["total_pairs"] = len(records)

    # Dependency type distribution
    dep_types = Counter(r.get("current_dependency_type", "unknown") for r in records)
    stats["dep_type_counts"] = dict(dep_types)

    # Family distribution
    families = Counter(r.get("pair_family", "unknown") for r in records)
    stats["family_counts"] = dict(families)

    # Selection bucket distribution
    buckets = Counter(r.get("selection_bucket", "unknown") for r in records)
    stats["bucket_counts"] = dict(buckets)

    # Labeling status
    labeled = sum(1 for r in records if r.get("ground_truth_type"))
    unlabeled = len(records) - labeled
    stats["labeled"] = labeled
    stats["unlabeled"] = unlabeled
    stats["label_rate"] = round(labeled / max(len(records), 1), 3)

    # Ground truth distribution (for labeled records)
    gt_types = Counter(
        r["ground_truth_type"] for r in records if r.get("ground_truth_type")
    )
    stats["ground_truth_counts"] = dict(gt_types)

    # Correctness (where labeled)
    correct_counts = Counter()
    for r in records:
        if r.get("ground_truth_type"):
            is_correct = r.get("current_dependency_type") == r.get("ground_truth_type")
            correct_counts["correct" if is_correct else "incorrect"] += 1
    stats["correctness"] = dict(correct_counts)

    # Keyword overlap stats
    kw_lens = [len(r.get("shared_keywords", [])) for r in records]
    if kw_lens:
        stats["keyword_overlap_mean"] = round(sum(kw_lens) / len(kw_lens), 2)
        stats["keyword_overlap_max"] = max(kw_lens)
        stats["keyword_overlap_zero"] = sum(1 for k in kw_lens if k == 0)

    # Similarity stats (for records with semantic_similarity)
    sims = [r["semantic_similarity"] for r in records if r.get("semantic_similarity") is not None]
    if sims:
        stats["similarity_mean"] = round(sum(sims) / len(sims), 4)
        stats["similarity_min"] = round(min(sims), 4)
        stats["similarity_max"] = round(max(sims), 4)
        stats["similarity_count"] = len(sims)

    # Family key diversity
    family_keys = set()
    for r in records:
        if r.get("family_key_a"):
            family_keys.add(r["family_key_a"])
        if r.get("family_key_b"):
            family_keys.add(r["family_key_b"])
    stats["unique_family_keys"] = len(family_keys)

    # Unique markets involved
    market_ids = set()
    for r in records:
        if r.get("market_a_id"):
            market_ids.add(r["market_a_id"])
        if r.get("market_b_id"):
            market_ids.add(r["market_b_id"])
    stats["unique_markets"] = len(market_ids)

    return stats


def check_gate(stats: dict) -> bool:
    """Check Phase 2 gate criteria. Returns True if passed."""
    passed = True
    total = stats["total_pairs"]

    if total < 150:
        print(f"  GATE FAIL: {total} < 150 minimum pairs")
        passed = False
    else:
        print(f"  GATE PASS: {total} >= 150 pairs")

    dep_counts = stats["dep_type_counts"]
    for dt, target in TARGET_COMPOSITION.items():
        actual = dep_counts.get(dt, 0)
        min_required = max(target // 3, 5)
        if actual == 0:
            print(f"  GATE FAIL: 0 {dt} pairs (need >= {min_required})")
            passed = False
        elif actual < min_required:
            print(f"  GATE WARN: {actual} {dt} pairs (target {target}, min {min_required})")
        else:
            print(f"  GATE PASS: {actual} {dt} pairs")

    none_count = dep_counts.get("none", 0)
    if none_count < 30:
        print(f"  GATE FAIL: {none_count} < 30 'none' pairs (hard negatives)")
        passed = False

    return passed


def print_report(stats: dict, verbose: bool = False) -> None:
    """Print a formatted analysis report."""
    print(f"\n{'=' * 60}")
    print(f"  Gold Set Analysis: {stats['total_pairs']} pairs")
    print(f"{'=' * 60}")

    print(f"\nLabeling: {stats['labeled']}/{stats['total_pairs']} ({stats['label_rate']:.0%})")
    if stats.get("correctness"):
        c = stats["correctness"]
        total_labeled = sum(c.values())
        accuracy = c.get("correct", 0) / max(total_labeled, 1)
        print(f"Classifier accuracy on labeled: {accuracy:.1%} ({c.get('correct', 0)}/{total_labeled})")

    print(f"\nDependency types:")
    for dt, count in sorted(stats["dep_type_counts"].items(), key=lambda x: -x[1]):
        target = TARGET_COMPOSITION.get(dt, "?")
        print(f"  {dt:25s} {count:4d}  (target: {target})")

    print(f"\nFamily distribution:")
    for fam, count in sorted(stats["family_counts"].items(), key=lambda x: -x[1]):
        print(f"  {fam:25s} {count:4d}")

    if stats.get("ground_truth_counts"):
        print(f"\nGround truth labels:")
        for gt, count in sorted(stats["ground_truth_counts"].items(), key=lambda x: -x[1]):
            print(f"  {gt:25s} {count:4d}")

    if verbose:
        print(f"\nBucket distribution:")
        for bucket, count in sorted(stats["bucket_counts"].items(), key=lambda x: -x[1]):
            print(f"  {bucket:25s} {count:4d}")

        print(f"\nKeyword overlap: mean={stats.get('keyword_overlap_mean', 'N/A')}, "
              f"max={stats.get('keyword_overlap_max', 'N/A')}, "
              f"zero={stats.get('keyword_overlap_zero', 'N/A')}")

        if stats.get("similarity_count"):
            print(f"Semantic similarity: mean={stats['similarity_mean']}, "
                  f"range=[{stats['similarity_min']}, {stats['similarity_max']}], "
                  f"n={stats['similarity_count']}")

        print(f"Unique family keys: {stats['unique_family_keys']}")
        print(f"Unique markets: {stats['unique_markets']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a V4 gold set dataset")
    parser.add_argument("input", help="Path to gold set JSON file")
    parser.add_argument("--check-gate", action="store_true", help="Run Phase 2 gate checks")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed stats")
    parser.add_argument("--json", action="store_true", help="Output raw stats as JSON")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    records = load_dataset(path)
    stats = analyze(records)

    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print_report(stats, verbose=args.verbose)

    if args.check_gate:
        print(f"\n{'=' * 60}")
        print("  Gate Check")
        print(f"{'=' * 60}")
        passed = check_gate(stats)
        print(f"\n  {'PASSED' if passed else 'FAILED'}")
        sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
