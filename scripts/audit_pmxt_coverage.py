"""PMXT coverage-density audit for the Feb 22-27, 2026 backtest window.

Read-only.  Buckets every no_prices outcome into concrete causes:
  1. no price history for market A
  2. no price history for market B
  3. both have history but timestamps never overlap the backtest window
  4. overlap exists but too sparse / too few usable points
  5. stale prices (only data before the backtest window)

Reports whether no_prices is concentrated in a few missing markets or
broadly sparse across the whole PMXT slice.

Usage:
    POSTGRES_DB=polyarb_backtest python -m scripts.audit_pmxt_coverage
"""
import asyncio
import sys
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from shared.db import engine

WINDOW_START = datetime(2026, 2, 22, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 2, 27, 23, 59, 59, tzinfo=timezone.utc)
# Backtest evaluates at 23:59:59 each day for 5 days (Feb 22-26)
EVAL_DATES = [
    datetime(2026, 2, 22, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 2, 23, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 2, 24, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 2, 25, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 2, 26, 23, 59, 59, tzinfo=timezone.utc),
]


async def main():
    async with engine.connect() as conn:
        # ── 1. Overall market and snapshot counts ────────────────────
        total_markets = (await conn.execute(text(
            "SELECT COUNT(*) FROM markets"
        ))).scalar()

        markets_in_pairs = (await conn.execute(text("""
            SELECT COUNT(DISTINCT m) FROM (
                SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                UNION
                SELECT market_b_id AS m FROM market_pairs WHERE verified = true
            ) x
        """))).scalar()

        markets_with_any_snap = (await conn.execute(text(
            "SELECT COUNT(DISTINCT market_id) FROM price_snapshots"
        ))).scalar()

        markets_with_window_snap = (await conn.execute(text("""
            SELECT COUNT(DISTINCT market_id) FROM price_snapshots
            WHERE timestamp >= :start
              AND timestamp <= :endts
        """), {"start": WINDOW_START, "endts": WINDOW_END})).scalar()

        total_snaps_in_window = (await conn.execute(text("""
            SELECT COUNT(*) FROM price_snapshots
            WHERE timestamp >= :start
              AND timestamp <= :endts
        """), {"start": WINDOW_START, "endts": WINDOW_END})).scalar()

        print("=" * 80)
        print("PMXT COVERAGE-DENSITY AUDIT  (Feb 22-27, 2026)")
        print("=" * 80)
        print(f"Total markets in DB:                  {total_markets:>7}")
        print(f"Markets in verified pairs:            {markets_in_pairs:>7}")
        print(f"Markets with ANY price snapshot:       {markets_with_any_snap:>7}")
        print(f"Markets with snapshot in window:       {markets_with_window_snap:>7}")
        print(f"Total snapshots in window:             {total_snaps_in_window:>7}")
        print(f"Coverage (window / in-pairs):          "
              f"{100 * markets_with_window_snap / max(markets_in_pairs, 1):.1f}%")
        print()

        # ── 2. Per-market snapshot density ───────────────────────────
        # For each market in verified pairs, count snapshots in window
        market_snap_counts = dict((await conn.execute(text("""
            SELECT ps.market_id, COUNT(*) as cnt
            FROM price_snapshots ps
            WHERE ps.market_id IN (
                SELECT DISTINCT m FROM (
                    SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                    UNION
                    SELECT market_b_id AS m FROM market_pairs WHERE verified = true
                ) x
            )
            AND ps.timestamp >= :start
            AND ps.timestamp <= :endts
            GROUP BY ps.market_id
        """), {"start": WINDOW_START, "endts": WINDOW_END})).fetchall())

        # Also get pre-window snapshots for staleness check
        market_latest_before = dict((await conn.execute(text("""
            SELECT ps.market_id, MAX(ps.timestamp) as latest
            FROM price_snapshots ps
            WHERE ps.market_id IN (
                SELECT DISTINCT m FROM (
                    SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                    UNION
                    SELECT market_b_id AS m FROM market_pairs WHERE verified = true
                ) x
            )
            AND ps.timestamp < :start
            GROUP BY ps.market_id
        """), {"start": WINDOW_START})).fetchall())

        # All markets in verified pairs
        all_pair_markets = set(r[0] for r in (await conn.execute(text("""
            SELECT DISTINCT m FROM (
                SELECT market_a_id AS m FROM market_pairs WHERE verified = true
                UNION
                SELECT market_b_id AS m FROM market_pairs WHERE verified = true
            ) x
        """))).fetchall())

        # Bucket markets
        has_window = set(market_snap_counts.keys())
        has_before = set(market_latest_before.keys())
        no_data_at_all = all_pair_markets - has_window - has_before
        stale_only = (has_before - has_window)  # has pre-window but not in-window
        in_window = has_window

        density_buckets = Counter()
        for mid in in_window:
            cnt = market_snap_counts[mid]
            if cnt >= 5:
                density_buckets["5+ snapshots (full)"] += 1
            elif cnt >= 3:
                density_buckets["3-4 snapshots"] += 1
            elif cnt >= 1:
                density_buckets["1-2 snapshots (sparse)"] += 1

        print("MARKET-LEVEL COVERAGE:")
        print("-" * 60)
        print(f"  No data at all:                      {len(no_data_at_all):>5}  "
              f"({100*len(no_data_at_all)/max(len(all_pair_markets),1):.1f}%)")
        print(f"  Stale only (pre-window):             {len(stale_only):>5}  "
              f"({100*len(stale_only)/max(len(all_pair_markets),1):.1f}%)")
        for bucket, cnt in sorted(density_buckets.items()):
            print(f"  In-window {bucket:<27} {cnt:>5}  "
                  f"({100*cnt/max(len(all_pair_markets),1):.1f}%)")
        print(f"  {'TOTAL':<39} {len(all_pair_markets):>5}")
        print()

        # ── 3. Pair-level no_prices simulation ──────────────────────
        # For each verified pair × each eval date, check if both markets
        # have a usable snapshot
        pairs = (await conn.execute(text("""
            SELECT id, market_a_id, market_b_id FROM market_pairs
            WHERE verified = true
        """))).fetchall()

        # Build lookup: market_id → set of dates with snapshots
        market_dates = defaultdict(set)
        date_rows = (await conn.execute(text("""
            SELECT market_id, timestamp::date as snap_date
            FROM price_snapshots
            WHERE timestamp <= :endts
        """), {"endts": WINDOW_END})).fetchall()
        for r in date_rows:
            market_dates[r[0]].add(str(r[1]))

        # Also track cumulative availability (any snapshot on or before eval date)
        # Since get_prices_at uses <= as_of, a snapshot from Feb 20 is valid on Feb 22
        market_has_any_before = defaultdict(set)
        for mid, dates in market_dates.items():
            for d in dates:
                market_has_any_before[mid].add(d)

        # For the actual check: does market_id have ANY snapshot with timestamp <= eval_date?
        # Simplify: if market has any snapshot in our DB at all before eval_date
        market_earliest = {}
        earliest_rows = (await conn.execute(text("""
            SELECT market_id, MIN(timestamp) as earliest
            FROM price_snapshots
            GROUP BY market_id
        """))).fetchall()
        for r in earliest_rows:
            market_earliest[r[0]] = r[1]

        # Simulate no_prices
        no_prices_reasons = Counter()
        no_prices_by_market = Counter()  # which markets cause the most blocks
        no_prices_pair_ct = Counter()    # which pairs are blocked most often
        total_evals = 0
        no_prices_total = 0

        for pair in pairs:
            for eval_dt in EVAL_DATES:
                total_evals += 1

                a_id, b_id = pair[1], pair[2]
                a_earliest = market_earliest.get(a_id)
                b_earliest = market_earliest.get(b_id)

                a_has = a_earliest is not None and a_earliest <= eval_dt
                b_has = b_earliest is not None and b_earliest <= eval_dt

                if a_has and b_has:
                    continue  # both have prices

                no_prices_total += 1

                if not a_has and not b_has:
                    if a_id not in market_earliest and b_id not in market_earliest:
                        reason = "both_no_data"
                    else:
                        reason = "both_stale_or_missing"
                elif not a_has:
                    if a_id not in market_earliest:
                        reason = "a_no_data"
                    else:
                        reason = "a_stale"
                    no_prices_by_market[a_id] += 1
                else:
                    if b_id not in market_earliest:
                        reason = "b_no_data"
                    else:
                        reason = "b_stale"
                    no_prices_by_market[b_id] += 1

                no_prices_reasons[reason] += 1
                no_prices_pair_ct[pair[0]] += 1

                # Track both markets for the "both" cases
                if reason.startswith("both"):
                    no_prices_by_market[a_id] += 1
                    no_prices_by_market[b_id] += 1

        print("PAIR-LEVEL no_prices SIMULATION:")
        print("-" * 60)
        print(f"  Total pair×day evaluations:          {total_evals:>7}")
        print(f"  no_prices outcomes:                  {no_prices_total:>7}")
        print(f"  Evaluations with prices:             {total_evals - no_prices_total:>7}")
        print()

        print("no_prices REASON BREAKDOWN:")
        print("-" * 60)
        for reason, cnt in no_prices_reasons.most_common():
            pct = 100 * cnt / max(no_prices_total, 1)
            print(f"  {reason:<35} {cnt:>7}  ({pct:5.1f}%)")
        print()

        # ── 4. Concentration analysis ───────────────────────────────
        # Are a few markets responsible for most blocks?
        print("CONCENTRATION: TOP 20 BLOCKING MARKETS:")
        print("-" * 80)

        top_blockers = no_prices_by_market.most_common(20)
        # Get market details
        if top_blockers:
            market_ids = [m for m, _ in top_blockers]
            details = {}
            for mid in market_ids:
                r = (await conn.execute(text(
                    "SELECT id, question, event_id, polymarket_id "
                    "FROM markets WHERE id = :id"
                ), {"id": mid})).first()
                if r:
                    details[mid] = r

            cumulative = 0
            for mid, cnt in top_blockers:
                cumulative += cnt
                d = details.get(mid)
                q = (d.question[:65] if d else "?")
                pct = 100 * cnt / max(no_prices_total, 1)
                cum_pct = 100 * cumulative / max(no_prices_total, 1)
                has_snaps = mid in market_earliest
                print(f"  #{mid:<6} blocks={cnt:>5} ({pct:4.1f}%, cum {cum_pct:5.1f}%)  "
                      f"snaps={'Y' if has_snaps else 'N'}  {q}")

        # How many markets cause 50%, 80%, 95% of blocks?
        print()
        sorted_blockers = sorted(no_prices_by_market.values(), reverse=True)
        cumsum = 0
        for threshold in [0.50, 0.80, 0.95]:
            for i, cnt in enumerate(sorted_blockers):
                cumsum += cnt
                if cumsum >= threshold * sum(sorted_blockers):
                    print(f"  {threshold*100:.0f}% of blocks caused by {i+1} markets "
                          f"(out of {len(sorted_blockers)} blocking)")
                    cumsum = 0
                    break

        # ── 5. Pair-level concentration ─────────────────────────────
        print()
        print("PAIR-LEVEL: how many pairs are always blocked?")
        always_blocked = sum(1 for cnt in no_prices_pair_ct.values() if cnt == len(EVAL_DATES))
        sometimes_blocked = sum(1 for cnt in no_prices_pair_ct.values() if 0 < cnt < len(EVAL_DATES))
        never_blocked = len(pairs) - len(no_prices_pair_ct)
        print(f"  Always blocked (all 5 days):         {always_blocked:>5}")
        print(f"  Sometimes blocked:                   {sometimes_blocked:>5}")
        print(f"  Never blocked:                       {never_blocked:>5}")
        print(f"  Total verified pairs:                {len(pairs):>5}")

        # ── 6. What would a targeted backfill buy? ──────────────────
        print()
        print("=" * 80)
        print("TARGETED BACKFILL IMPACT ESTIMATE:")
        print("=" * 80)

        # If we added price data for the top N blocking markets,
        # how many pair-day evals would we recover?
        for n_markets in [10, 25, 50, 100, 200, 500]:
            top_n = set(m for m, _ in no_prices_by_market.most_common(n_markets))
            recovered = 0
            for pair in pairs:
                for eval_dt in EVAL_DATES:
                    a_id, b_id = pair[1], pair[2]
                    a_earliest = market_earliest.get(a_id)
                    b_earliest = market_earliest.get(b_id)
                    a_has = a_earliest is not None and a_earliest <= eval_dt
                    b_has = b_earliest is not None and b_earliest <= eval_dt

                    if a_has and b_has:
                        continue  # already had prices

                    # Would adding top_n markets fix this?
                    a_fixed = a_has or a_id in top_n
                    b_fixed = b_has or b_id in top_n
                    if a_fixed and b_fixed:
                        recovered += 1

            pct = 100 * recovered / max(no_prices_total, 1)
            print(f"  Add top {n_markets:<4} markets → recover {recovered:>6} evals "
                  f"({pct:5.1f}% of no_prices)")

        print()


if __name__ == "__main__":
    asyncio.run(main())
