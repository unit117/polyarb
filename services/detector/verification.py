"""Pair verification: validates that classifier output is structurally and
price-consistent before allowing the pair to be traded.

Runs after classification, sets MarketPair.verified = True if all checks pass.
"""

import structlog

logger = structlog.get_logger()

# Tolerance for price-based checks — prices must violate constraints
# by at most this much to still be considered consistent
PRICE_TOLERANCE = 0.20


def verify_pair(
    dependency_type: str,
    market_a: dict,
    market_b: dict,
    prices_a: dict | None,
    prices_b: dict | None,
    confidence: float,
    correlation: str | None = None,
) -> dict:
    """Verify a classified pair via structural and price-consistency checks.

    Returns {"verified": bool, "reasons": [str]} explaining what passed/failed.
    """
    reasons: list[str] = []
    checks_passed = 0
    checks_total = 0

    # ── Check 1: Minimum classifier confidence ──────────────────────
    checks_total += 1
    if confidence >= 0.70:
        checks_passed += 1
    else:
        reasons.append(f"low_confidence: {confidence:.2f} < 0.70")

    # ── Check 2: Structural checks per dependency type ──────────────
    checks_total += 1
    structural_ok = _check_structural(
        dependency_type, market_a, market_b, correlation, reasons
    )
    if structural_ok:
        checks_passed += 1

    # ── Check 3: Price consistency — do prices agree with the constraint? ──
    if prices_a and prices_b:
        checks_total += 1
        price_ok = _check_price_consistency(
            dependency_type, market_a, market_b, prices_a, prices_b,
            correlation, reasons,
        )
        if price_ok:
            checks_passed += 1

    verified = checks_passed == checks_total

    logger.info(
        "pair_verification",
        dependency_type=dependency_type,
        verified=verified,
        checks=f"{checks_passed}/{checks_total}",
        reasons=reasons or ["all_passed"],
    )

    return {"verified": verified, "reasons": reasons}


def _check_structural(
    dependency_type: str,
    market_a: dict,
    market_b: dict,
    correlation: str | None,
    reasons: list[str],
) -> bool:
    """Validate structural properties of the pair."""

    if dependency_type == "partition":
        # Partition pairs should share event_id or have overlapping outcomes
        if market_a.get("event_id") and market_a["event_id"] == market_b.get("event_id"):
            return True
        outcomes_a = set(market_a.get("outcomes", []))
        outcomes_b = set(market_b.get("outcomes", []))
        if outcomes_a & outcomes_b:
            return True
        # Weaker check: both must have >2 outcomes for a meaningful partition
        if len(outcomes_a) > 2 or len(outcomes_b) > 2:
            return True
        reasons.append("partition: no shared event_id or overlapping outcomes")
        return False

    if dependency_type == "mutual_exclusion":
        # Both markets must be binary (Yes/No style) for mutual_exclusion to make sense
        outcomes_a = market_a.get("outcomes", [])
        outcomes_b = market_b.get("outcomes", [])
        if len(outcomes_a) == 2 and len(outcomes_b) == 2:
            return True
        reasons.append("mutual_exclusion: non-binary markets")
        return False

    if dependency_type == "implication":
        outcomes_a = market_a.get("outcomes", [])
        outcomes_b = market_b.get("outcomes", [])
        if len(outcomes_a) >= 2 and len(outcomes_b) >= 2:
            return True
        reasons.append("implication: markets need at least 2 outcomes each")
        return False

    if dependency_type == "conditional":
        # Must have correlation direction for binary pairs
        outcomes_a = market_a.get("outcomes", [])
        outcomes_b = market_b.get("outcomes", [])
        if len(outcomes_a) == 2 and len(outcomes_b) == 2:
            if correlation in ("positive", "negative"):
                return True
            reasons.append("conditional: missing correlation direction for binary pair")
            return False
        # Non-binary conditional pairs pass structural check but won't get constraints
        return True

    # Unknown type
    reasons.append(f"unknown dependency_type: {dependency_type}")
    return False


def _check_price_consistency(
    dependency_type: str,
    market_a: dict,
    market_b: dict,
    prices_a: dict,
    prices_b: dict,
    correlation: str | None,
    reasons: list[str],
) -> bool:
    """Check that prices are roughly consistent with the constraint.

    We don't require exact satisfaction — that would filter out all arb
    opportunities. We check that prices aren't wildly inconsistent with
    the dependency type (e.g., a partition pair summing to 3.0).
    """

    def _f(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    outcomes_a = market_a.get("outcomes", [])
    outcomes_b = market_b.get("outcomes", [])

    if dependency_type == "partition":
        # Sum of all prices across both markets should be near 1.0
        total = sum(_f(prices_a.get(o, 0)) for o in outcomes_a) + sum(
            _f(prices_b.get(o, 0)) for o in outcomes_b
        )
        if abs(total - 1.0) > PRICE_TOLERANCE:
            # Still OK if it's a moderate violation — that's the arb opportunity
            if abs(total - 1.0) > 0.50:
                reasons.append(f"partition: price sum {total:.2f} too far from 1.0")
                return False
        return True

    if dependency_type == "implication":
        # For A→B, P(A) should be ≤ P(B) + tolerance
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        if p_a > p_b + 0.50:
            reasons.append(f"implication: P(A)={p_a:.2f} >> P(B)={p_b:.2f}, extreme violation")
            return False
        return True

    if dependency_type == "mutual_exclusion":
        # P(A) + P(B) should be ≤ 1 + tolerance.  Real ME pairs sum to ~1.0;
        # the arb is in small violations.  1.20 catches genuine ME while
        # rejecting independent pairs that happen to look binary.
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        if p_a + p_b > 1.20:
            reasons.append(f"mutual_exclusion: P(A)+P(B)={p_a+p_b:.2f} > 1.20")
            return False
        return True

    if dependency_type == "conditional":
        # For conditional, both prices should be valid (between 0 and 1)
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        if not (0.0 < p_a < 1.0) or not (0.0 < p_b < 1.0):
            reasons.append(f"conditional: prices out of range ({p_a:.2f}, {p_b:.2f})")
            return False
        return True

    return True
