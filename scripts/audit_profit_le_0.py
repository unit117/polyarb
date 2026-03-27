"""Audit pairs that pass verification but die at profit_le_0.

Read-only.  For each covered, verified pair that yields profit_bound <= 0,
buckets by dependency type and reports the exact boundary margin:

  implication:          distance = |p_antecedent - p_consequent| (arb when > 0)
  mutual_exclusion:     distance = (p_a + p_b) - 1.0           (arb when > 0)
  negative conditional: same as mutual_exclusion
  partition:            distance = |sum(prices) - 1.0|          (arb when > 0)
  cross_platform:       distance = spread - fees               (arb when > 0)
  positive conditional: always 0 (no constraint, by design)

For each bucket, prints sampled pair details and a histogram of distances.

Usage:
    POSTGRES_DB=polyarb_backtest python -m scripts.audit_profit_le_0
"""

import asyncio
import sys
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from shared.db import engine

# Backtest eval dates (same as backtest.py)
EVAL_DATES = [
    datetime(2026, 2, 22, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 2, 23, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 2, 24, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 2, 25, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 2, 26, 23, 59, 59, tzinfo=timezone.utc),
]


def compute_boundary_distance(
    dep_type: str,
    correlation: str | None,
    imp_direction: str | None,
    prices_a: dict,
    prices_b: dict,
    outcomes_a: list,
    outcomes_b: list,
) -> tuple[float, str]:
    """Compute distance from the arbitrage boundary.

    Returns (distance, reason). Positive distance = in arb territory.
    Negative = correctly priced (no arb).
    """
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    if dep_type == "implication":
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0

        if imp_direction == "a_implies_b":
            # Arb when p_a > p_b (sell A, buy B)
            return round(p_a - p_b, 6), f"a_implies_b: p_a={p_a:.4f} p_b={p_b:.4f}"
        elif imp_direction == "b_implies_a":
            # Arb when p_b > p_a (sell B, buy A)
            return round(p_b - p_a, 6), f"b_implies_a: p_a={p_a:.4f} p_b={p_b:.4f}"
        else:
            return 0.0, f"no_direction: p_a={p_a:.4f} p_b={p_b:.4f}"

    if dep_type == "mutual_exclusion":
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        excess = (p_a + p_b) - 1.0
        return round(excess, 6), f"mutex: p_a={p_a:.4f} p_b={p_b:.4f} sum={p_a+p_b:.4f}"

    if dep_type == "conditional":
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        if correlation == "negative":
            excess = (p_a + p_b) - 1.0
            return round(excess, 6), f"neg_cond: p_a={p_a:.4f} p_b={p_b:.4f} sum={p_a+p_b:.4f}"
        else:
            return 0.0, f"pos_cond: p_a={p_a:.4f} p_b={p_b:.4f} (always 0)"

    if dep_type == "partition":
        total = sum(_f(prices_a.get(o, 0)) for o in outcomes_a) + sum(
            _f(prices_b.get(o, 0)) for o in outcomes_b
        )
        deviation = abs(total - 1.0)
        return round(deviation, 6), f"partition: sum={total:.4f}"

    if dep_type == "cross_platform":
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        spread = abs(p_a - p_b)
        # Approximate fees (Polymarket ~2% maker, Kalshi ~7% on winnings)
        fee_est = 0.02 + 0.07
        net = spread - fee_est
        return round(net, 6), f"cross: p_a={p_a:.4f} p_b={p_b:.4f} spread={spread:.4f}"

    return 0.0, f"unknown_type: {dep_type}"


async def main():
    async with engine.connect() as conn:
        # Load verified pairs with their constraint matrices
        pairs = (await conn.execute(text("""
            SELECT mp.id, mp.dependency_type, mp.implication_direction,
                   mp.constraint_matrix, mp.confidence,
                   mp.market_a_id, mp.market_b_id,
                   ma.question as q_a, mb.question as q_b,
                   ma.outcomes as out_a, mb.outcomes as out_b
            FROM market_pairs mp
            JOIN markets ma ON ma.id = mp.market_a_id
            JOIN markets mb ON mb.id = mp.market_b_id
            WHERE mp.verified = true
            ORDER BY mp.id
        """))).fetchall()

        print(f"Total verified pairs: {len(pairs)}")

        # Build price lookup: market_id → {date → prices_dict}
        # Use most recent snapshot <= eval_date for each market
        print("Loading price snapshots...")
        all_snaps = (await conn.execute(text("""
            SELECT market_id, timestamp, prices
            FROM price_snapshots
            WHERE timestamp <= :end_ts
            ORDER BY market_id, timestamp
        """), {"end_ts": EVAL_DATES[-1]})).fetchall()

        # market_id → list of (timestamp, prices) sorted by timestamp
        market_snaps = defaultdict(list)
        for s in all_snaps:
            market_snaps[s.market_id].append((s.timestamp, s.prices))

        print(f"Loaded {len(all_snaps)} snapshots for {len(market_snaps)} markets")

        def get_prices(market_id, as_of):
            """Replicate get_prices_at: most recent snapshot <= as_of."""
            snaps = market_snaps.get(market_id, [])
            best = None
            for ts, prices in snaps:
                ts_aware = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
                if ts_aware <= as_of:
                    best = prices
            return best

        # Categorize each pair × eval_date
        buckets = defaultdict(list)  # (dep_type, sub_reason) → list of dicts
        type_counts = Counter()
        total_profit_le_0 = 0
        total_no_prices = 0
        total_profit_gt_0 = 0

        for pair in pairs:
            constraint = pair.constraint_matrix or {}
            outcomes_a = constraint.get("outcomes_a", [])
            outcomes_b = constraint.get("outcomes_b", [])
            imp_direction = pair.implication_direction or constraint.get("implication_direction")
            correlation = constraint.get("correlation")

            if not outcomes_a:
                out_a = pair.out_a if isinstance(pair.out_a, list) else []
                if out_a:
                    outcomes_a = out_a
            if not outcomes_b:
                out_b = pair.out_b if isinstance(pair.out_b, list) else []
                if out_b:
                    outcomes_b = out_b

            for eval_dt in EVAL_DATES:
                prices_a = get_prices(pair.market_a_id, eval_dt)
                prices_b = get_prices(pair.market_b_id, eval_dt)

                if not prices_a or not prices_b:
                    total_no_prices += 1
                    continue

                dist, reason = compute_boundary_distance(
                    pair.dependency_type, correlation, imp_direction,
                    prices_a, prices_b, outcomes_a, outcomes_b,
                )

                if dist > 0.001:
                    total_profit_gt_0 += 1
                    continue

                total_profit_le_0 += 1

                # Sub-bucket by distance band
                if dist > -0.01:
                    band = "near_miss (0 to -1%)"
                elif dist > -0.05:
                    band = "mild (-1% to -5%)"
                elif dist > -0.15:
                    band = "moderate (-5% to -15%)"
                else:
                    band = "far (> -15%)"

                dep = pair.dependency_type
                if dep == "conditional":
                    dep = f"conditional_{correlation or 'unknown'}"

                key = (dep, band)
                type_counts[dep] += 1

                # Store detail for sampling
                buckets[key].append({
                    "pair_id": pair.id,
                    "market_a_id": pair.market_a_id,
                    "market_b_id": pair.market_b_id,
                    "q_a": (pair.q_a or "")[:80],
                    "q_b": (pair.q_b or "")[:80],
                    "dep_type": pair.dependency_type,
                    "direction": imp_direction,
                    "distance": dist,
                    "reason": reason,
                    "date": eval_dt.strftime("%Y-%m-%d"),
                })

        # ── Print results ─────────────────────────────────────────────
        print(f"\n{'=' * 80}")
        print(f"  profit_le_0 AUDIT  (Feb 22-27, 2026)")
        print(f"{'=' * 80}")
        print(f"  Total pair-day evaluations with prices:  {total_profit_le_0 + total_profit_gt_0}")
        print(f"  profit > 0 (detected):                   {total_profit_gt_0}")
        print(f"  profit <= 0 (rejected):                  {total_profit_le_0}")
        print(f"  no_prices (skipped):                     {total_no_prices}")
        print()

        # By dependency type
        print("BY DEPENDENCY TYPE:")
        print("-" * 60)
        for dep, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
            pct = 100 * cnt / max(total_profit_le_0, 1)
            print(f"  {dep:<30} {cnt:>6}  ({pct:5.1f}%)")
        print()

        # By (dep_type, band)
        print("BY DEPENDENCY TYPE × DISTANCE BAND:")
        print("-" * 80)
        for (dep, band), items in sorted(buckets.items(), key=lambda x: -len(x[1])):
            pct = 100 * len(items) / max(total_profit_le_0, 1)
            # Compute distance stats
            dists = [x["distance"] for x in items]
            avg_d = sum(dists) / len(dists) if dists else 0
            min_d = min(dists) if dists else 0
            max_d = max(dists) if dists else 0
            print(f"  {dep:>25} | {band:<25} {len(items):>6}  ({pct:5.1f}%)  "
                  f"dist: avg={avg_d:+.4f} min={min_d:+.4f} max={max_d:+.4f}")
        print()

        # Distance histogram across all types
        print("DISTANCE HISTOGRAM (all types):")
        print("-" * 60)
        all_dists = [x["distance"] for items in buckets.values() for x in items]
        if all_dists:
            hist_bins = [
                ("== 0.0 (structural zero)", lambda d: d == 0.0),
                ("> -0.005 (sub-0.5%)", lambda d: -0.005 < d <= 0.0),
                ("-0.005 to -0.01 (0.5-1%)", lambda d: -0.01 < d <= -0.005),
                ("-0.01 to -0.03 (1-3%)", lambda d: -0.03 < d <= -0.01),
                ("-0.03 to -0.05 (3-5%)", lambda d: -0.05 < d <= -0.03),
                ("-0.05 to -0.10 (5-10%)", lambda d: -0.10 < d <= -0.05),
                ("-0.10 to -0.20 (10-20%)", lambda d: -0.20 < d <= -0.10),
                ("-0.20 to -0.50 (20-50%)", lambda d: -0.50 < d <= -0.20),
                ("< -0.50 (> 50%)", lambda d: d <= -0.50),
            ]
            for label, pred in hist_bins:
                cnt = sum(1 for d in all_dists if pred(d))
                bar = "█" * (cnt // max(len(all_dists) // 40, 1))
                pct = 100 * cnt / len(all_dists)
                print(f"  {label:<30} {cnt:>6}  ({pct:5.1f}%)  {bar}")
        print()

        # Sample pairs per bucket
        print("SAMPLE PAIRS (up to 5 per bucket):")
        print("=" * 80)
        for (dep, band), items in sorted(buckets.items(), key=lambda x: -len(x[1])):
            print(f"\n  [{dep}] [{band}] — {len(items)} pair-day evals")
            print(f"  {'-' * 76}")
            # Show up to 5 unique pairs
            seen_pairs = set()
            shown = 0
            for x in sorted(items, key=lambda x: -x["distance"]):
                if x["pair_id"] in seen_pairs:
                    continue
                seen_pairs.add(x["pair_id"])
                print(f"    pair #{x['pair_id']}  dist={x['distance']:+.4f}  "
                      f"dir={x['direction'] or '-'}  [{x['date']}]")
                print(f"      A (#{x['market_a_id']}): {x['q_a']}")
                print(f"      B (#{x['market_b_id']}): {x['q_b']}")
                print(f"      {x['reason']}")
                shown += 1
                if shown >= 5:
                    break

        print(f"\n{'=' * 80}")


if __name__ == "__main__":
    asyncio.run(main())
