"""Validate LLM-predicted conditional pair correlations against empirical price data.

For each conditional pair, computes Pearson correlation on price *returns*
(changes between consecutive aligned snapshots) and compares against the
classifier's predicted direction. Pairs where empirical data contradicts
the prediction are downgraded to dependency_type='none'.

Usage:
    python -m scripts.validate_correlations [--dry-run] [--min-snapshots 10]
"""

import argparse
import asyncio
from statistics import correlation as pearson_correlation

import structlog
from sqlalchemy import select

from shared.config import settings
from shared.db import init_db, SessionFactory
from shared.logging import setup_logging
from shared.models import MarketPair, PriceSnapshot

logger = structlog.get_logger()


async def validate_conditional_pairs(
    dry_run: bool = True,
    min_snapshots: int = 10,
) -> list[dict]:
    """Validate all conditional pairs against empirical price correlation.

    Returns a list of validation results for each conditional pair.
    """
    results = []

    async with SessionFactory() as session:
        # Find all conditional pairs
        pair_result = await session.execute(
            select(MarketPair).where(MarketPair.dependency_type == "conditional")
        )
        pairs = pair_result.scalars().all()

        if not pairs:
            logger.info("no_conditional_pairs_found")
            return results

        logger.info("validating_conditional_pairs", count=len(pairs))

        for pair in pairs:
            constraint = pair.constraint_matrix or {}
            predicted_correlation = constraint.get("correlation")

            if not predicted_correlation:
                results.append({
                    "pair_id": pair.id,
                    "market_a_id": pair.market_a_id,
                    "market_b_id": pair.market_b_id,
                    "status": "skip",
                    "reason": "no_predicted_correlation",
                })
                continue

            # Get price snapshots for both markets
            snaps_a = await _get_price_series(session, pair.market_a_id)
            snaps_b = await _get_price_series(session, pair.market_b_id)

            if len(snaps_a) < min_snapshots or len(snaps_b) < min_snapshots:
                results.append({
                    "pair_id": pair.id,
                    "market_a_id": pair.market_a_id,
                    "market_b_id": pair.market_b_id,
                    "status": "skip",
                    "reason": "insufficient_snapshots",
                    "snapshots_a": len(snaps_a),
                    "snapshots_b": len(snaps_b),
                    "min_required": min_snapshots,
                })
                continue

            # Align timestamps: find overlapping time points (no sample reuse)
            prices_a, prices_b = _align_price_series(snaps_a, snaps_b)

            # Compute returns (price changes) from aligned levels
            returns_a = [prices_a[i] - prices_a[i - 1] for i in range(1, len(prices_a))]
            returns_b = [prices_b[i] - prices_b[i - 1] for i in range(1, len(prices_b))]

            if len(returns_a) < min_snapshots:
                results.append({
                    "pair_id": pair.id,
                    "market_a_id": pair.market_a_id,
                    "market_b_id": pair.market_b_id,
                    "status": "skip",
                    "reason": "insufficient_aligned_snapshots",
                    "aligned_count": len(returns_a),
                    "min_required": min_snapshots,
                })
                continue

            # Compute empirical correlation on returns
            try:
                empirical_r = pearson_correlation(returns_a, returns_b)
            except Exception as e:
                results.append({
                    "pair_id": pair.id,
                    "status": "error",
                    "reason": str(e),
                })
                continue

            empirical_direction = "positive" if empirical_r > 0 else "negative"
            matches = empirical_direction == predicted_correlation

            result = {
                "pair_id": pair.id,
                "market_a_id": pair.market_a_id,
                "market_b_id": pair.market_b_id,
                "predicted_correlation": predicted_correlation,
                "empirical_r": round(empirical_r, 4),
                "empirical_direction": empirical_direction,
                "matches": matches,
                "aligned_snapshots": len(prices_a),
                "status": "validated",
            }

            # Weak correlation (|r| < 0.1) — likely independent, downgrade
            if abs(empirical_r) < 0.1:
                result["action"] = "downgrade"
                result["reason"] = "weak_correlation"
            elif not matches:
                result["action"] = "downgrade"
                result["reason"] = "direction_mismatch"
            else:
                result["action"] = "keep"

            if result.get("action") == "downgrade" and not dry_run:
                pair.dependency_type = "none"
                pair.verified = False
                logger.warning(
                    "conditional_pair_downgraded",
                    pair_id=pair.id,
                    predicted=predicted_correlation,
                    empirical_r=empirical_r,
                    reason=result["reason"],
                )

            results.append(result)

            logger.info(
                "correlation_validated",
                pair_id=pair.id,
                predicted=predicted_correlation,
                empirical_r=round(empirical_r, 4),
                matches=matches,
                action=result.get("action", "keep"),
            )

        if not dry_run:
            await session.commit()

    return results


async def _get_price_series(session, market_id: int) -> list[dict]:
    """Get timestamped Yes prices for a market, ordered chronologically."""
    result = await session.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.timestamp.asc())
    )
    snapshots = result.scalars().all()

    series = []
    for snap in snapshots:
        yes_price = snap.prices.get("Yes") if snap.prices else None
        if yes_price is not None:
            series.append({
                "timestamp": snap.timestamp,
                "price": float(yes_price),
            })
    return series


def _align_price_series(
    series_a: list[dict], series_b: list[dict],
) -> tuple[list[float], list[float]]:
    """Align two price series by nearest timestamp within 5 minutes.

    Each series_b point is used at most once to prevent sample reuse.
    Returns two lists of aligned prices.
    """
    max_gap_secs = 300
    prices_a = []
    prices_b = []
    used_b: set[int] = set()

    for point_a in series_a:
        ts_a = point_a["timestamp"]
        best_j = None
        best_gap = None
        for j in range(len(series_b)):
            if j in used_b:
                continue
            gap = abs((series_b[j]["timestamp"] - ts_a).total_seconds())
            if gap > max_gap_secs:
                if series_b[j]["timestamp"] > ts_a and gap > max_gap_secs:
                    break
                continue
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best_j = j

        if best_j is not None:
            prices_a.append(point_a["price"])
            prices_b.append(series_b[best_j]["price"])
            used_b.add(best_j)

    return prices_a, prices_b


async def main():
    parser = argparse.ArgumentParser(
        description="Validate conditional pair correlations against empirical price data"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Don't modify the database, just report findings",
    )
    parser.add_argument(
        "--min-snapshots", type=int, default=10,
        help="Minimum aligned snapshots required for validation (default: 10)",
    )
    args = parser.parse_args()

    setup_logging(settings.log_level)
    await init_db()

    results = await validate_conditional_pairs(
        dry_run=args.dry_run,
        min_snapshots=args.min_snapshots,
    )

    # Summary
    total = len(results)
    validated = sum(1 for r in results if r["status"] == "validated")
    skipped = sum(1 for r in results if r["status"] == "skip")
    matches = sum(1 for r in results if r.get("matches"))
    downgrades = sum(1 for r in results if r.get("action") == "downgrade")

    print(f"\n{'='*60}")
    print(f"Conditional Pair Correlation Validation")
    print(f"{'='*60}")
    print(f"Total conditional pairs: {total}")
    print(f"Validated:               {validated}")
    print(f"Skipped:                 {skipped}")
    print(f"Correlation matches:     {matches}/{validated}")
    print(f"Downgrades:              {downgrades}")
    if args.dry_run:
        print(f"\n(dry-run mode — no changes written)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
