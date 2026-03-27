"""Pair-quality audit: sample and bucket rejected opportunities by failure mode.

Targets the polyarb_backtest DB (Feb 22-27 PMXT slice).  Reads only —
no writes.  Examines opportunities rejected by:

  - edge_sanity_cap      (stored in optimal_trades->'rejection_reason')
  - verification_fail    (pairs that reach detect but fail verify_pair)
  - payout_proof_failed  (worst-case payoff is negative)
  - below_min_profit     (edge dies after fees/slippage)
  - below_min_edge       (no leg exceeds min_edge)

For each sampled pair, prints: pair id, market ids, questions,
dependency type, implication direction, verification reasons,
max edge, payout proof result, and a human-readable failure bucket.

Usage:
    POSTGRES_DB=polyarb_backtest python -m scripts.audit_pair_quality [--limit 20]
"""
import asyncio
import json
import sys
import os
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from shared.db import engine
from services.detector.verification import verify_pair
from services.detector.constraints import (
    build_constraint_matrix,
    build_constraint_matrix_from_vectors,
)
from services.optimizer.frank_wolfe import optimize
from services.optimizer.trades import compute_trades

# ────────────────────────────────────────────────────────────────────
#  SQL queries
# ────────────────────────────────────────────────────────────────────

# Opportunities that were optimized but had a rejection_reason in optimal_trades
REJECTED_OPPS_QUERY = """
SELECT
    ao.id AS opp_id,
    ao.pair_id,
    ao.theoretical_profit,
    ao.estimated_profit,
    ao.optimal_trades->>'rejection_reason' AS rejection_reason,
    ao.optimal_trades->>'max_edge' AS max_edge,
    ao.dependency_type AS opp_dep_type,
    ao.status,
    ao.timestamp,
    mp.dependency_type,
    mp.confidence,
    mp.verified,
    mp.implication_direction,
    mp.constraint_matrix,
    mp.resolution_vectors,
    mp.classification_source,
    ma.id AS market_a_id,
    mb.id AS market_b_id,
    ma.question AS q_a,
    mb.question AS q_b,
    ma.event_id AS event_a,
    mb.event_id AS event_b,
    ma.outcomes AS outcomes_a,
    mb.outcomes AS outcomes_b,
    ao.optimal_trades
FROM arbitrage_opportunities ao
JOIN market_pairs mp ON mp.id = ao.pair_id
JOIN markets ma ON ma.id = mp.market_a_id
JOIN markets mb ON mb.id = mp.market_b_id
WHERE ao.optimal_trades->>'rejection_reason' IS NOT NULL
ORDER BY ao.optimal_trades->>'rejection_reason', ao.id
"""

# Pairs that are verified=false (never even got to optimizer)
UNVERIFIED_PAIRS_QUERY = """
SELECT
    mp.id AS pair_id,
    mp.dependency_type,
    mp.confidence,
    mp.implication_direction,
    mp.constraint_matrix,
    mp.resolution_vectors,
    mp.classification_source,
    ma.id AS market_a_id,
    mb.id AS market_b_id,
    ma.question AS q_a,
    mb.question AS q_b,
    ma.event_id AS event_a,
    mb.event_id AS event_b,
    ma.outcomes AS outcomes_a,
    mb.outcomes AS outcomes_b
FROM market_pairs mp
JOIN markets ma ON ma.id = mp.market_a_id
JOIN markets mb ON mb.id = mp.market_b_id
WHERE NOT mp.verified
ORDER BY mp.id
"""

# Summary counts
SUMMARY_QUERY = """
SELECT
    ao.optimal_trades->>'rejection_reason' AS reason,
    COUNT(*) AS cnt
FROM arbitrage_opportunities ao
WHERE ao.optimal_trades->>'rejection_reason' IS NOT NULL
GROUP BY ao.optimal_trades->>'rejection_reason'
ORDER BY cnt DESC
"""

TOTAL_OPPS_QUERY = """
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN optimal_trades->>'rejection_reason' IS NOT NULL THEN 1 ELSE 0 END) AS rejected,
    SUM(CASE WHEN optimal_trades IS NOT NULL
              AND optimal_trades->>'rejection_reason' IS NULL
              AND jsonb_array_length(optimal_trades->'trades') > 0
         THEN 1 ELSE 0 END) AS executable
FROM arbitrage_opportunities
"""


# ────────────────────────────────────────────────────────────────────
#  Failure-mode bucketing
# ────────────────────────────────────────────────────────────────────

def bucket_edge_sanity(row) -> str:
    """Sub-classify edge_sanity_cap rejects."""
    dep = row.dependency_type
    max_edge = float(row.max_edge or 0)
    ot = row.optimal_trades or {}
    prices_a = ot.get("market_a_prices", {})
    prices_b = ot.get("market_b_prices", {})

    # Same event but different dependency → likely wrong label
    if row.event_a and row.event_b and row.event_a == row.event_b:
        return "same_event_wrong_dep"

    # Implication with wrong direction
    if dep == "implication" and not row.implication_direction:
        return "implication_no_direction"

    # Mutual exclusion with same question
    if dep == "mutual_exclusion":
        if row.q_a and row.q_b and row.q_a.strip() == row.q_b.strip():
            return "same_question_mutual_excl"
        return "mutual_excl_large_edge"

    if dep == "conditional":
        # Check if this is really an implication mislabeled as conditional.
        # Pattern: one market has very low Yes price (rare event), the other
        # has higher price.  The conditional constraint's divergence threshold
        # marks an outcome infeasible, then FW pushes the cheaper market to 0
        # creating a huge phantom edge.
        cur_a = prices_a.get("current", [0.5, 0.5])
        cur_b = prices_b.get("current", [0.5, 0.5])
        opt_a = prices_a.get("optimal", cur_a)
        opt_b = prices_b.get("optimal", cur_b)

        # FW pushed one side to 0.0 or 1.0 — phantom arb from loose constraint
        has_extreme_optimal = (
            any(abs(v) < 0.001 or abs(v - 1.0) < 0.001 for v in opt_a)
            or any(abs(v) < 0.001 or abs(v - 1.0) < 0.001 for v in opt_b)
        )

        # Check if one side is rare (P(Yes) < 0.15)
        p_a_yes = cur_a[0] if cur_a else 0.5
        p_b_yes = cur_b[0] if cur_b else 0.5
        one_rare = min(p_a_yes, p_b_yes) < 0.15

        if has_extreme_optimal and one_rare:
            return "conditional_implication_mislabel"
        elif has_extreme_optimal:
            return "conditional_loose_constraint"
        elif max_edge > 0.50:
            return "conditional_correlated_not_arb"
        else:
            return "conditional_other"

    if max_edge > 0.50:
        return f"correlated_not_arb_{dep}"

    return f"large_edge_{dep}"


def bucket_verification_reasons(reasons: list[str]) -> str:
    """Pick the most informative verification failure reason."""
    if not reasons:
        return "unknown"
    # Priority: structural > price > confidence
    for r in reasons:
        if "different event_ids" in r:
            return "different_event_ids"
        if "identical questions" in r:
            return "identical_questions"
        if "non-binary" in r:
            return "non_binary_markets"
        if "no shared event_id" in r:
            return "no_shared_event"
        if "neither market has event_id" in r:
            return "no_event_id"
        if "price sum" in r:
            return "price_sum_violation"
        if "violates" in r:
            return "implication_price_violation"
        if "P(A)+P(B)" in r:
            return "mutual_excl_price_violation"
        if "low_confidence" in r:
            return "low_confidence"
    return reasons[0][:40]


# ────────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────────

async def main():
    limit = 20
    if len(sys.argv) > 1 and sys.argv[1] == "--limit":
        limit = int(sys.argv[2])

    async with engine.connect() as conn:
        # ── Overall summary ──────────────────────────────────────────
        totals = (await conn.execute(text(TOTAL_OPPS_QUERY))).first()
        print("=" * 80)
        print("PAIR-QUALITY AUDIT  (polyarb_backtest)")
        print("=" * 80)
        print(f"Total opportunities: {totals.total}")
        print(f"  Executable (has trades): {totals.executable}")
        print(f"  Rejected (has reason):   {totals.rejected}")
        print()

        # ── Rejection breakdown ──────────────────────────────────────
        print("REJECTION REASON BREAKDOWN:")
        print("-" * 50)
        summary_rows = (await conn.execute(text(SUMMARY_QUERY))).fetchall()
        for r in summary_rows:
            pct = 100 * r.cnt / max(totals.rejected, 1)
            bar = "█" * int(pct / 2)
            print(f"  {r.reason:<25} {r.cnt:>5}  ({pct:5.1f}%)  {bar}")
        print()

        # ── Edge sanity cap deep-dive ────────────────────────────────
        print("=" * 80)
        print("EDGE SANITY CAP — SAMPLED PAIRS")
        print("=" * 80)

        esc_rows = (await conn.execute(text(
            REJECTED_OPPS_QUERY.replace(
                "ORDER BY ao.optimal_trades->>'rejection_reason', ao.id",
                "ORDER BY ao.id"
            ) + f" LIMIT {limit * 3}"
        ))).fetchall()

        esc_only = [r for r in esc_rows if r.rejection_reason == "edge_sanity_cap"]
        esc_buckets = Counter()

        for r in esc_only[:limit]:
            bucket = bucket_edge_sanity(r)
            esc_buckets[bucket] += 1
            _print_pair_detail(r, bucket)

        # Count all edge_sanity_cap rows for bucketing
        all_esc = [r for r in (await conn.execute(text(
            REJECTED_OPPS_QUERY
        ))).fetchall() if r.rejection_reason == "edge_sanity_cap"]
        esc_all_buckets = Counter()
        for r in all_esc:
            esc_all_buckets[bucket_edge_sanity(r)] += 1

        print(f"\nEDGE SANITY CAP — FAILURE BUCKETS (all {len(all_esc)}):")
        print("-" * 60)
        for bucket, cnt in esc_all_buckets.most_common():
            pct = 100 * cnt / max(len(all_esc), 1)
            print(f"  {bucket:<40} {cnt:>5}  ({pct:5.1f}%)")

        # ── Payout proof failures ────────────────────────────────────
        ppf = [r for r in esc_rows if r.rejection_reason == "payout_proof_failed"]
        if ppf:
            print()
            print("=" * 80)
            print("PAYOUT PROOF FAILURES — SAMPLED PAIRS")
            print("=" * 80)
            ppf_buckets = Counter()
            for r in ppf[:limit]:
                bucket = f"{r.dependency_type}_payout_fail"
                ppf_buckets[bucket] += 1
                _print_pair_detail(r, bucket)

        # ── Below min profit ─────────────────────────────────────────
        bmp = [r for r in esc_rows if r.rejection_reason == "below_min_profit"]
        if bmp:
            print()
            print("=" * 80)
            print(f"BELOW MIN PROFIT — {len(bmp)} sampled")
            print("=" * 80)
            for r in bmp[:min(5, limit)]:
                ot = r.optimal_trades or {}
                print(f"  opp #{r.opp_id}  pair #{r.pair_id}  "
                      f"dep={r.dependency_type}  "
                      f"raw_edge={ot.get('raw_edge', '?')}  "
                      f"fees={ot.get('est_fees', '?')}  "
                      f"slippage={ot.get('est_slippage', '?')}  "
                      f"max_edge={r.max_edge}")

        # ── Unverified pairs (verification_fail in backtest) ─────────
        print()
        print("=" * 80)
        print("UNVERIFIED PAIRS — RE-VERIFICATION AUDIT")
        print("=" * 80)

        uv_rows = (await conn.execute(text(UNVERIFIED_PAIRS_QUERY))).fetchall()
        print(f"Total unverified pairs: {len(uv_rows)}")

        uv_buckets = Counter()
        uv_dep_buckets = Counter()
        uv_samples = defaultdict(list)

        for r in uv_rows:
            # Re-run verification to get reasons
            outcomes_a = r.outcomes_a if isinstance(r.outcomes_a, list) else []
            outcomes_b = r.outcomes_b if isinstance(r.outcomes_b, list) else []
            market_a_dict = {
                "event_id": r.event_a,
                "question": r.q_a,
                "outcomes": outcomes_a,
            }
            market_b_dict = {
                "event_id": r.event_b,
                "question": r.q_b,
                "outcomes": outcomes_b,
            }
            constraint = r.constraint_matrix or {}
            imp_dir = r.implication_direction or constraint.get("implication_direction")
            result = verify_pair(
                dependency_type=r.dependency_type,
                market_a=market_a_dict,
                market_b=market_b_dict,
                prices_a=None,  # no prices — just structural
                prices_b=None,
                confidence=r.confidence,
                correlation=constraint.get("correlation"),
                implication_direction=imp_dir,
            )
            reasons = result.get("reasons", [])
            bucket = bucket_verification_reasons(reasons)
            uv_buckets[bucket] += 1
            uv_dep_buckets[(r.dependency_type, bucket)] += 1
            if len(uv_samples[bucket]) < 3:
                uv_samples[bucket].append((r, reasons))

        print(f"\nVERIFICATION FAILURE BUCKETS:")
        print("-" * 60)
        for bucket, cnt in uv_buckets.most_common():
            pct = 100 * cnt / max(len(uv_rows), 1)
            print(f"  {bucket:<40} {cnt:>5}  ({pct:5.1f}%)")

        print(f"\nBY DEPENDENCY TYPE × FAILURE:")
        print("-" * 70)
        for (dep, bucket), cnt in uv_dep_buckets.most_common(20):
            print(f"  {dep:<20} {bucket:<35} {cnt:>5}")

        # Print samples for top buckets
        top_buckets = [b for b, _ in uv_buckets.most_common(5)]
        for bucket in top_buckets:
            samples = uv_samples[bucket]
            if not samples:
                continue
            print(f"\n  SAMPLES — {bucket}:")
            for r, reasons in samples:
                print(f"    pair #{r.pair_id}  dep={r.dependency_type}  "
                      f"conf={r.confidence:.2f}  "
                      f"src={r.classification_source or '?'}")
                print(f"      A (#{r.market_a_id}): {(r.q_a or '')[:70]}")
                print(f"      B (#{r.market_b_id}): {(r.q_b or '')[:70]}")
                print(f"      event_a={r.event_a}  event_b={r.event_b}")
                print(f"      reasons: {reasons}")

        # ── Grand summary ────────────────────────────────────────────
        print()
        print("=" * 80)
        print("GRAND SUMMARY — FAILURE MODE DOMINANCE")
        print("=" * 80)

        total_bad = totals.rejected + len(uv_rows)
        print(f"Total rejected opps + unverified pairs: {total_bad}")
        print()

        # Merge all buckets for ranking
        all_buckets = Counter()
        for b, c in esc_all_buckets.items():
            all_buckets[f"esc: {b}"] += c
        for b, c in uv_buckets.items():
            all_buckets[f"verif: {b}"] += c
        # Add other rejection reasons
        for r in summary_rows:
            if r.reason != "edge_sanity_cap":
                all_buckets[f"opt: {r.reason}"] += r.cnt

        print(f"{'FAILURE MODE':<50} {'COUNT':>6} {'% OF BAD':>8}")
        print("-" * 70)
        for bucket, cnt in all_buckets.most_common(20):
            pct = 100 * cnt / max(total_bad, 1)
            print(f"  {bucket:<48} {cnt:>6}  {pct:5.1f}%")

        print()
        print("CHEAPEST NEXT FIX CANDIDATES:")
        print("-" * 50)
        top3 = all_buckets.most_common(3)
        for i, (bucket, cnt) in enumerate(top3, 1):
            pct = 100 * cnt / max(total_bad, 1)
            if "verif:" in bucket:
                fix = "→ classifier/labeling quality"
            elif "esc:" in bucket and "correlated" in bucket:
                fix = "→ classifier: correlated != arbitrageable"
            elif "esc:" in bucket and "wrong_dep" in bucket:
                fix = "→ classifier: dependency type accuracy"
            elif "opt:" in bucket and "min_profit" in bucket:
                fix = "→ PMXT coverage / spread density"
            elif "opt:" in bucket and "min_edge" in bucket:
                fix = "→ PMXT coverage / spread density"
            else:
                fix = "→ investigate further"
            print(f"  {i}. {bucket} ({cnt}, {pct:.0f}%) {fix}")

        print()


def _print_pair_detail(r, bucket: str):
    """Print detailed info for one rejected opportunity."""
    ot = r.optimal_trades or {}
    prices_a = ot.get("market_a_prices", {})
    prices_b = ot.get("market_b_prices", {})

    print(f"\n  opp #{r.opp_id}  pair #{r.pair_id}  [{bucket}]")
    print(f"    dep_type:   {r.dependency_type}  "
          f"impl_dir: {r.implication_direction or 'n/a'}  "
          f"conf: {r.confidence:.2f}  "
          f"src: {r.classification_source or '?'}")
    print(f"    A (#{r.market_a_id}): {(r.q_a or '')[:75]}")
    print(f"    B (#{r.market_b_id}): {(r.q_b or '')[:75]}")
    print(f"    event_a={r.event_a}  event_b={r.event_b}")
    print(f"    max_edge={r.max_edge}  "
          f"theo_profit={r.theoretical_profit}  "
          f"status={r.status}")
    if prices_a:
        print(f"    prices_a: cur={prices_a.get('current')} "
              f"opt={prices_a.get('optimal')}")
    if prices_b:
        print(f"    prices_b: cur={prices_b.get('current')} "
              f"opt={prices_b.get('optimal')}")


if __name__ == "__main__":
    asyncio.run(main())
