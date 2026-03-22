"""Embedding accuracy audit — measures whether pgvector similarity
actually correlates with pair quality.

Run inside any service container:
    python -m scripts.audit_embeddings

Outputs a report with:
1. Similarity score vs verification rate (do higher scores = better pairs?)
2. False negative check (same event_id pairs missed by embeddings)
3. Rule-based vs LLM classification breakdown
4. Embedding ROI: how many LLM calls are wasted on junk candidates
"""

import asyncio
import structlog
from sqlalchemy import select, func, text, case, and_

from shared.db import init_db, SessionFactory
from shared.models import Market, MarketPair, ArbitrageOpportunity, PaperTrade

logger = structlog.get_logger()


async def run_audit():
    await init_db()

    async with SessionFactory() as session:
        # ── 1. Confidence bucket vs verification rate ──────────────
        # (confidence here is classifier confidence, not embedding similarity)
        # We need to check if similarity score is stored anywhere
        print("\n" + "=" * 70)
        print("EMBEDDING & CLASSIFICATION ACCURACY AUDIT")
        print("=" * 70)

        # Total pair stats
        total = await session.scalar(select(func.count(MarketPair.id)))
        verified = await session.scalar(
            select(func.count(MarketPair.id)).where(MarketPair.verified == True)
        )
        print(f"\nTotal pairs: {total}")
        print(f"Verified pairs: {verified} ({100*verified/total:.1f}%)")
        print(f"Unverified pairs: {total - verified} ({100*(total-verified)/total:.1f}%)")

        # ── 2. By dependency type ──────────────────────────────────
        print("\n--- By Dependency Type ---")
        rows = (await session.execute(
            select(
                MarketPair.dependency_type,
                func.count(MarketPair.id).label("total"),
                func.sum(case((MarketPair.verified == True, 1), else_=0)).label("verified"),
                func.avg(MarketPair.confidence).label("avg_confidence"),
            ).group_by(MarketPair.dependency_type)
        )).all()
        for r in rows:
            v_pct = 100 * r.verified / r.total if r.total else 0
            print(f"  {r.dependency_type:20s}  total={r.total:5d}  "
                  f"verified={r.verified:5d} ({v_pct:5.1f}%)  "
                  f"avg_conf={r.avg_confidence:.3f}")

        # ── 3. Confidence bucket analysis ──────────────────────────
        print("\n--- Classifier Confidence vs Verification Rate ---")
        rows = (await session.execute(text("""
            SELECT
                CASE
                    WHEN confidence >= 0.95 THEN '0.95-1.00'
                    WHEN confidence >= 0.90 THEN '0.90-0.95'
                    WHEN confidence >= 0.85 THEN '0.85-0.90'
                    WHEN confidence >= 0.80 THEN '0.80-0.85'
                    WHEN confidence >= 0.70 THEN '0.70-0.80'
                    ELSE '< 0.70'
                END as bucket,
                COUNT(*) as total,
                SUM(CASE WHEN verified THEN 1 ELSE 0 END) as verified_cnt
            FROM market_pairs
            GROUP BY 1
            ORDER BY 1
        """))).all()
        for r in rows:
            v_pct = 100 * r.verified_cnt / r.total if r.total else 0
            print(f"  {r.bucket:12s}  total={r.total:5d}  "
                  f"verified={r.verified_cnt:5d} ({v_pct:5.1f}%)")

        # ── 4. Same event_id pairs — are embeddings finding them? ──
        print("\n--- Same Event ID Analysis ---")
        same_event = (await session.execute(text("""
            SELECT COUNT(*) as cnt
            FROM market_pairs mp
            JOIN markets ma ON mp.market_a_id = ma.id
            JOIN markets mb ON mp.market_b_id = mb.id
            WHERE ma.event_id IS NOT NULL
              AND ma.event_id = mb.event_id
        """))).scalar()
        print(f"  Pairs sharing event_id: {same_event}")

        # How many same-event_id market combinations exist but aren't paired?
        missed = (await session.execute(text("""
            SELECT COUNT(*) as cnt FROM (
                SELECT ma.id as a_id, mb.id as b_id
                FROM markets ma
                JOIN markets mb ON ma.event_id = mb.event_id
                    AND ma.id < mb.id
                    AND ma.active = true AND mb.active = true
                WHERE ma.event_id IS NOT NULL
                EXCEPT
                SELECT market_a_id, market_b_id FROM market_pairs
            ) missed
        """))).scalar()
        print(f"  Same-event_id pairs NOT in market_pairs (missed): {missed}")
        if missed and missed > 0:
            print(f"  ⚠️  Embeddings are missing {missed} obvious same-event pairs!")

        # ── 5. Cosine similarity distribution for existing pairs ───
        # Recompute similarity from stored embeddings
        print("\n--- Embedding Similarity for Existing Pairs (sample) ---")
        sim_rows = (await session.execute(text("""
            SELECT
                mp.dependency_type,
                mp.verified,
                1 - (ma.embedding <=> mb.embedding) as cosine_sim
            FROM market_pairs mp
            JOIN markets ma ON mp.market_a_id = ma.id
            JOIN markets mb ON mp.market_b_id = mb.id
            WHERE ma.embedding IS NOT NULL AND mb.embedding IS NOT NULL
            ORDER BY mp.id DESC
            LIMIT 1000
        """))).all()

        if sim_rows:
            from collections import defaultdict
            buckets = defaultdict(lambda: {"verified": 0, "unverified": 0})
            for r in sim_rows:
                sim = float(r.cosine_sim)
                if sim >= 0.95:
                    b = "0.95-1.00"
                elif sim >= 0.90:
                    b = "0.90-0.95"
                elif sim >= 0.85:
                    b = "0.85-0.90"
                elif sim >= 0.82:
                    b = "0.82-0.85"
                else:
                    b = "< 0.82"
                key = "verified" if r.verified else "unverified"
                buckets[b][key] += 1

            print(f"  {'Sim Bucket':12s}  {'Verified':>10s}  {'Unverified':>10s}  {'Verif %':>8s}")
            for b in ["0.95-1.00", "0.90-0.95", "0.85-0.90", "0.82-0.85", "< 0.82"]:
                if b in buckets:
                    v = buckets[b]["verified"]
                    u = buckets[b]["unverified"]
                    pct = 100 * v / (v + u) if (v + u) > 0 else 0
                    print(f"  {b:12s}  {v:10d}  {u:10d}  {pct:7.1f}%")
        else:
            print("  (no embedding data available)")

        # ── 6. Opportunity funnel ──────────────────────────────────
        print("\n--- Opportunity Pipeline Funnel ---")
        funnel = (await session.execute(text("""
            SELECT
                status,
                COUNT(*) as cnt,
                ROUND(AVG(estimated_profit::numeric), 4) as avg_profit,
                SUM(CASE WHEN estimated_profit > 0 THEN 1 ELSE 0 END) as profitable
            FROM arbitrage_opportunities
            GROUP BY status
            ORDER BY status
        """))).all()
        for r in funnel:
            print(f"  {r.status:15s}  count={r.cnt:5d}  "
                  f"avg_profit=${r.avg_profit or 0:.4f}  "
                  f"profitable={r.profitable}")

        # ── 7. Trade outcomes by dependency type ───────────────────
        print("\n--- Trade Outcomes by Dependency Type ---")
        trade_rows = (await session.execute(text("""
            SELECT
                mp.dependency_type,
                mp.verified,
                COUNT(pt.id) as trade_count,
                ROUND(SUM(
                    CASE WHEN pt.side = 'SETTLE' THEN
                        CASE WHEN pt.entry_price = 1.0 THEN pt.size * 1.0 - pt.fees
                             ELSE -pt.size * pt.entry_price END
                    ELSE 0 END
                )::numeric, 2) as settlement_pnl
            FROM paper_trades pt
            LEFT JOIN arbitrage_opportunities ao ON pt.opportunity_id = ao.id
            LEFT JOIN market_pairs mp ON ao.pair_id = mp.id
            GROUP BY mp.dependency_type, mp.verified
            ORDER BY 1, 2
        """))).all()
        for r in trade_rows:
            print(f"  {str(r.dependency_type):20s}  verified={str(r.verified):5s}  "
                  f"trades={r.trade_count:5d}  settle_pnl=${r.settlement_pnl or 0}")

        # ── 8. Outcome-based dependency validation (E1c) ─────────────
        # For pairs where both markets have resolved_outcome, check whether
        # the predicted dependency type matches the actual outcome combination.
        print("\n--- Outcome-Based Dependency Validation ---")
        outcome_rows = (await session.execute(text("""
            SELECT
                mp.id as pair_id,
                mp.dependency_type,
                mp.constraint_matrix,
                mp.confidence,
                mp.verified,
                ma.question as q_a,
                mb.question as q_b,
                ma.resolved_outcome as outcome_a,
                mb.resolved_outcome as outcome_b,
                1 - (ma.embedding <=> mb.embedding) as cosine_sim
            FROM market_pairs mp
            JOIN markets ma ON mp.market_a_id = ma.id
            JOIN markets mb ON mp.market_b_id = mb.id
            WHERE ma.resolved_outcome IS NOT NULL
              AND mb.resolved_outcome IS NOT NULL
              AND ma.embedding IS NOT NULL
              AND mb.embedding IS NOT NULL
        """))).all()

        if outcome_rows:
            print(f"  Pairs with both markets resolved: {len(outcome_rows)}")

            from collections import defaultdict
            dep_stats = defaultdict(lambda: {
                "total": 0, "consistent": 0, "inconsistent": 0,
                "sim_sum": 0.0, "examples": [],
            })

            for r in outcome_rows:
                dep = r.dependency_type
                dep_stats[dep]["total"] += 1
                dep_stats[dep]["sim_sum"] += float(r.cosine_sim)

                # Check consistency of outcome vs predicted dependency
                consistent = _check_outcome_consistency(
                    dep, r.outcome_a, r.outcome_b, r.constraint_matrix,
                )
                if consistent is None:
                    # Can't determine — skip
                    continue
                if consistent:
                    dep_stats[dep]["consistent"] += 1
                else:
                    dep_stats[dep]["inconsistent"] += 1
                    if len(dep_stats[dep]["examples"]) < 3:
                        dep_stats[dep]["examples"].append({
                            "pair_id": r.pair_id,
                            "q_a": r.q_a[:60],
                            "q_b": r.q_b[:60],
                            "outcome_a": r.outcome_a,
                            "outcome_b": r.outcome_b,
                        })

            print(f"\n  {'Dep Type':20s}  {'Total':>6s}  {'Consistent':>10s}  "
                  f"{'Inconsistent':>12s}  {'Accuracy':>8s}  {'Avg Sim':>7s}")
            for dep in sorted(dep_stats.keys()):
                s = dep_stats[dep]
                checked = s["consistent"] + s["inconsistent"]
                acc = 100 * s["consistent"] / checked if checked > 0 else 0
                avg_sim = s["sim_sum"] / s["total"] if s["total"] > 0 else 0
                print(f"  {dep:20s}  {s['total']:6d}  {s['consistent']:10d}  "
                      f"{s['inconsistent']:12d}  {acc:7.1f}%  {avg_sim:7.3f}")

                # Show examples of inconsistencies
                for ex in s["examples"]:
                    print(f"    ⚠️  pair {ex['pair_id']}: "
                          f"{ex['q_a']}... [{ex['outcome_a']}] vs "
                          f"{ex['q_b']}... [{ex['outcome_b']}]")

            # Summary
            total_checked = sum(
                s["consistent"] + s["inconsistent"]
                for s in dep_stats.values()
            )
            total_consistent = sum(s["consistent"] for s in dep_stats.values())
            if total_checked > 0:
                overall = 100 * total_consistent / total_checked
                print(f"\n  Overall accuracy: {total_consistent}/{total_checked} "
                      f"({overall:.1f}%)")
        else:
            print("  (no resolved pairs found — run import_resolved_outcomes.py first)")

        print("\n" + "=" * 70)
        print("AUDIT COMPLETE")
        print("=" * 70)


def _check_outcome_consistency(
    dep_type: str,
    outcome_a: str,
    outcome_b: str,
    constraint_matrix: dict | None,
) -> bool | None:
    """Check if actual outcomes are consistent with predicted dependency.

    Returns True (consistent), False (inconsistent), or None (can't determine).
    """
    if not dep_type:
        return None

    oa = outcome_a.strip().lower()
    ob = outcome_b.strip().lower()

    if dep_type == "mutual_exclusion":
        # Both can't be "yes" — at most one wins
        if oa == "yes" and ob == "yes":
            return False
        return True

    elif dep_type == "implication":
        # A implies B: if A is yes, B must be yes
        if oa == "yes" and ob != "yes":
            return False
        return True

    elif dep_type == "partition":
        # Exactly one outcome wins across the partition
        # For binary: one yes, one no
        if oa == ob:
            # Both yes or both no — depends on partition structure
            # With 2-market partition, both "yes" or both "no" is wrong
            return False
        return True

    elif dep_type == "complement":
        # Opposite outcomes expected
        if oa == ob:
            return False
        return True

    elif dep_type == "conditional":
        # Conditional relationships are harder to validate from outcomes alone.
        # We can check if the constraint matrix allows the observed combination.
        if constraint_matrix and "matrix" in constraint_matrix:
            return _outcome_in_feasibility(
                outcome_a, outcome_b, constraint_matrix
            )
        return None

    elif dep_type == "cross_platform_equivalent":
        # Same market on different venues — should resolve the same way
        if oa != ob:
            return False
        return True

    return None


def _outcome_in_feasibility(
    outcome_a: str,
    outcome_b: str,
    constraint: dict,
) -> bool | None:
    """Check if the outcome combination is feasible per the constraint matrix."""
    outcomes_a = constraint.get("outcomes_a", [])
    outcomes_b = constraint.get("outcomes_b", [])
    matrix = constraint.get("matrix", [])

    if not outcomes_a or not outcomes_b or not matrix:
        return None

    # Find indices
    try:
        idx_a = next(
            i for i, o in enumerate(outcomes_a)
            if o.strip().lower() == outcome_a.strip().lower()
        )
        idx_b = next(
            i for i, o in enumerate(outcomes_b)
            if o.strip().lower() == outcome_b.strip().lower()
        )
    except StopIteration:
        return None  # outcome not in matrix

    # Check if this combination is marked feasible
    if idx_a < len(matrix) and idx_b < len(matrix[idx_a]):
        return matrix[idx_a][idx_b] == 1
    return None


if __name__ == "__main__":
    asyncio.run(run_audit())
