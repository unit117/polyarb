"""Quick accuracy audit: embedding similarity vs verification rate."""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from shared.db import engine


QUERY = """
WITH pair_stats AS (
    SELECT
        mp.id,
        mp.dependency_type,
        mp.confidence,
        mp.verified,
        mp.constraint_matrix->>'profit_bound' AS profit_bound,
        1 - (ma.embedding <=> mb.embedding) AS similarity,
        ma.question AS q_a,
        mb.question AS q_b
    FROM market_pairs mp
    JOIN markets ma ON ma.id = mp.market_a_id
    JOIN markets mb ON mb.id = mp.market_b_id
    WHERE ma.embedding IS NOT NULL AND mb.embedding IS NOT NULL
)
SELECT * FROM pair_stats ORDER BY similarity DESC
"""

SUMMARY_QUERY = """
WITH pair_stats AS (
    SELECT
        mp.dependency_type,
        mp.confidence,
        mp.verified,
        CAST(mp.constraint_matrix->>'profit_bound' AS float) AS profit_bound,
        1 - (ma.embedding <=> mb.embedding) AS similarity
    FROM market_pairs mp
    JOIN markets ma ON ma.id = mp.market_a_id
    JOIN markets mb ON mb.id = mp.market_b_id
    WHERE ma.embedding IS NOT NULL AND mb.embedding IS NOT NULL
)
SELECT
    dependency_type,
    COUNT(*) AS total,
    SUM(CASE WHEN verified THEN 1 ELSE 0 END) AS verified_ct,
    ROUND(100.0 * SUM(CASE WHEN verified THEN 1 ELSE 0 END) / COUNT(*), 1) AS verify_pct,
    ROUND(AVG(similarity)::numeric, 4) AS avg_sim,
    ROUND(AVG(CASE WHEN verified THEN similarity END)::numeric, 4) AS avg_sim_verified,
    ROUND(AVG(CASE WHEN NOT verified THEN similarity END)::numeric, 4) AS avg_sim_unverified,
    ROUND(AVG(confidence)::numeric, 4) AS avg_conf,
    ROUND(AVG(CASE WHEN verified THEN profit_bound END)::numeric, 4) AS avg_profit_verified
FROM pair_stats
GROUP BY dependency_type
ORDER BY total DESC
"""

BUCKET_QUERY = """
WITH pair_stats AS (
    SELECT
        mp.verified,
        1 - (ma.embedding <=> mb.embedding) AS similarity
    FROM market_pairs mp
    JOIN markets ma ON ma.id = mp.market_a_id
    JOIN markets mb ON mb.id = mp.market_b_id
    WHERE ma.embedding IS NOT NULL AND mb.embedding IS NOT NULL
)
SELECT
    CASE
        WHEN similarity >= 0.95 THEN '0.95-1.00'
        WHEN similarity >= 0.90 THEN '0.90-0.95'
        WHEN similarity >= 0.85 THEN '0.85-0.90'
        WHEN similarity >= 0.82 THEN '0.82-0.85'
        WHEN similarity >= 0.75 THEN '0.75-0.82'
        ELSE '<0.75'
    END AS sim_bucket,
    COUNT(*) AS total,
    SUM(CASE WHEN verified THEN 1 ELSE 0 END) AS verified_ct,
    ROUND(100.0 * SUM(CASE WHEN verified THEN 1 ELSE 0 END) / COUNT(*), 1) AS verify_pct
FROM pair_stats
GROUP BY sim_bucket
ORDER BY sim_bucket DESC
"""

FALSE_NEGATIVE_QUERY = """
-- High-similarity pairs that failed verification (potential false negatives)
SELECT
    mp.id,
    mp.dependency_type,
    mp.confidence,
    1 - (ma.embedding <=> mb.embedding) AS similarity,
    ma.question AS q_a,
    mb.question AS q_b
FROM market_pairs mp
JOIN markets ma ON ma.id = mp.market_a_id
JOIN markets mb ON mb.id = mp.market_b_id
WHERE ma.embedding IS NOT NULL AND mb.embedding IS NOT NULL
  AND NOT mp.verified
  AND 1 - (ma.embedding <=> mb.embedding) >= 0.92
ORDER BY 1 - (ma.embedding <=> mb.embedding) DESC
LIMIT 10
"""

LOW_SIM_VERIFIED_QUERY = """
-- Low-similarity pairs that passed verification (embedding misses)
SELECT
    mp.id,
    mp.dependency_type,
    mp.confidence,
    1 - (ma.embedding <=> mb.embedding) AS similarity,
    ma.question AS q_a,
    mb.question AS q_b
FROM market_pairs mp
JOIN markets ma ON ma.id = mp.market_a_id
JOIN markets mb ON mb.id = mp.market_b_id
WHERE ma.embedding IS NOT NULL AND mb.embedding IS NOT NULL
  AND mp.verified
  AND 1 - (ma.embedding <=> mb.embedding) < 0.85
ORDER BY 1 - (ma.embedding <=> mb.embedding) ASC
LIMIT 10
"""


async def main():
    async with engine.connect() as conn:
        # Overall counts
        row = (await conn.execute(text(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN verified THEN 1 ELSE 0 END) AS verified, "
            "COUNT(DISTINCT market_a_id) + COUNT(DISTINCT market_b_id) AS unique_markets "
            "FROM market_pairs"
        ))).first()
        print("=" * 70)
        print(f"PAIR ACCURACY AUDIT")
        print(f"=" * 70)
        print(f"Total pairs: {row.total}  |  Verified: {row.verified}  |  "
              f"Rate: {100*row.verified/max(row.total,1):.1f}%  |  Unique markets: {row.unique_markets}")

        # By dependency type
        print(f"\n{'TYPE':<20} {'TOTAL':>6} {'VERIF':>6} {'RATE':>7} "
              f"{'AVG_SIM':>8} {'SIM_V':>8} {'SIM_UV':>8} {'AVG_CONF':>9} {'AVG_PROF':>9}")
        print("-" * 95)
        rows = (await conn.execute(text(SUMMARY_QUERY))).fetchall()
        for r in rows:
            print(f"{r.dependency_type:<20} {r.total:>6} {r.verified_ct:>6} {r.verify_pct:>6}% "
                  f"{r.avg_sim or 0:>8.4f} {r.avg_sim_verified or 0:>8.4f} "
                  f"{r.avg_sim_unverified or 0:>8.4f} {r.avg_conf or 0:>9.4f} "
                  f"{r.avg_profit_verified or 0:>9.4f}")

        # Similarity buckets
        print(f"\n{'SIMILARITY BUCKET':<18} {'TOTAL':>6} {'VERIF':>6} {'RATE':>7}")
        print("-" * 40)
        rows = (await conn.execute(text(BUCKET_QUERY))).fetchall()
        for r in rows:
            bar = "█" * int(r.verify_pct / 5) if r.verify_pct else ""
            print(f"{r.sim_bucket:<18} {r.total:>6} {r.verified_ct:>6} {r.verify_pct:>6}%  {bar}")

        # False negatives (high sim, not verified)
        print(f"\nHIGH-SIMILARITY UNVERIFIED (potential false negatives):")
        print("-" * 70)
        rows = (await conn.execute(text(FALSE_NEGATIVE_QUERY))).fetchall()
        if rows:
            for r in rows:
                print(f"  #{r.id} sim={r.similarity:.4f} conf={r.confidence:.2f} "
                      f"type={r.dependency_type}")
                print(f"    A: {r.q_a[:70]}")
                print(f"    B: {r.q_b[:70]}")
        else:
            print("  (none)")

        # Embedding misses (low sim, verified)
        print(f"\nLOW-SIMILARITY VERIFIED (embedding misses):")
        print("-" * 70)
        rows = (await conn.execute(text(LOW_SIM_VERIFIED_QUERY))).fetchall()
        if rows:
            for r in rows:
                print(f"  #{r.id} sim={r.similarity:.4f} conf={r.confidence:.2f} "
                      f"type={r.dependency_type}")
                print(f"    A: {r.q_a[:70]}")
                print(f"    B: {r.q_b[:70]}")
        else:
            print("  (none)")

        print(f"\n{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
