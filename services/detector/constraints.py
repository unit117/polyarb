from __future__ import annotations

"""Constraint matrix generation for the optimizer.

Given a dependency type and two markets, produces a JSONB-serializable
constraint matrix that Phase 3's Frank-Wolfe optimizer will consume.
"""

import structlog

logger = structlog.get_logger()


def build_constraint_matrix(
    dependency_type: str,
    outcomes_a: list[str],
    outcomes_b: list[str],
    prices_a: dict | None = None,
    prices_b: dict | None = None,
    correlation: str | None = None,
    venue_a: str = "polymarket",
    venue_b: str = "polymarket",
    implication_direction: str | None = None,
) -> dict:
    """Build a constraint matrix for a market pair.

    Returns a dict with:
    - type: the dependency type
    - outcomes_a, outcomes_b: outcome labels
    - matrix: a len(outcomes_a) x len(outcomes_b) binary feasibility matrix
      where 1 = feasible joint outcome, 0 = infeasible
    - profit_bound: theoretical profit if prices violate constraints
    - correlation: "positive" or "negative" for conditional pairs
    """
    n_a = len(outcomes_a)
    n_b = len(outcomes_b)

    # Guard: binary matrix logic assumes outcomes[0]="Yes", outcomes[1]="No"
    for label, outcomes in [("a", outcomes_a), ("b", outcomes_b)]:
        if len(outcomes) == 2 and outcomes[0] != "Yes":
            logger.warning(
                "unexpected_outcome_order",
                market=label,
                outcomes=outcomes,
                msg="Expected outcomes[0]='Yes'; constraint matrix may be inverted",
            )

    if dependency_type == "implication":
        if not implication_direction:
            logger.warning(
                "implication_direction_missing",
                msg="No direction specified; defaulting to unconstrained matrix",
            )
            matrix = _unconstrained_matrix(n_a, n_b)
        else:
            matrix = _implication_matrix(n_a, n_b, direction=implication_direction)
    elif dependency_type == "partition":
        matrix = _partition_matrix(outcomes_a, outcomes_b)
    elif dependency_type == "mutual_exclusion":
        matrix = _mutual_exclusion_matrix(n_a, n_b)
    elif dependency_type == "conditional":
        matrix = _conditional_matrix(
            n_a, n_b, outcomes_a, outcomes_b, prices_a, prices_b, correlation
        )
    elif dependency_type == "cross_platform":
        matrix = _cross_platform_matrix(n_a, n_b)
    else:
        matrix = _unconstrained_matrix(n_a, n_b)

    profit_bound = _compute_profit_bound(
        dependency_type, matrix, outcomes_a, outcomes_b, prices_a, prices_b,
        correlation, venue_a=venue_a, venue_b=venue_b,
    )

    result = {
        "type": dependency_type,
        "outcomes_a": outcomes_a,
        "outcomes_b": outcomes_b,
        "matrix": matrix,
        "profit_bound": profit_bound,
        "correlation": correlation,
        "implication_direction": implication_direction,
    }

    logger.info(
        "constraint_matrix_built",
        dep_type=dependency_type,
        shape=f"{n_a}x{n_b}",
        profit_bound=profit_bound,
        correlation=correlation,
    )
    return result


def _implication_matrix(n_a: int, n_b: int, direction: str = "a_implies_b") -> list[list[int]]:
    """Build implication feasibility matrix with correct direction.

    direction="a_implies_b": A=Yes forces B=Yes → A=Yes+B=No infeasible
    direction="b_implies_a": B=Yes forces A=Yes → B=Yes+A=No (i.e. A=No+B=Yes) infeasible
    """
    matrix = [[1] * n_b for _ in range(n_a)]
    if n_a >= 2 and n_b >= 2:
        if direction == "b_implies_a":
            # B=Yes forces A=Yes, so A=No + B=Yes is infeasible
            matrix[1][0] = 0
        else:
            # A=Yes forces B=Yes, so A=Yes + B=No is infeasible
            matrix[0][1] = 0
    return matrix


def _partition_matrix(outcomes_a: list[str], outcomes_b: list[str]) -> list[list[int]]:
    """Markets partition the same space: at most one outcome across both can be true.

    For binary markets (2x2): both "Yes" can't be true simultaneously and both
    "No" can't be true simultaneously (exactly one event in the partition occurs).
    For multi-outcome: different shared outcomes can't both resolve Yes.
    """
    n_a = len(outcomes_a)
    n_b = len(outcomes_b)

    # Binary partition: exactly one of the two markets resolves Yes
    if n_a == 2 and n_b == 2:
        return [
            [0, 1],  # A=Yes + B=Yes infeasible; A=Yes + B=No feasible
            [1, 0],  # A=No + B=Yes feasible; A=No + B=No infeasible
        ]

    # Multi-outcome: different shared outcomes can't both be true
    shared = set(outcomes_a) & set(outcomes_b)
    matrix = [[1] * n_b for _ in range(n_a)]
    for i, oa in enumerate(outcomes_a):
        for j, ob in enumerate(outcomes_b):
            if oa in shared and ob in shared and oa != ob:
                # Different shared outcomes — both can't be true in a partition
                matrix[i][j] = 0
    return matrix


def _mutual_exclusion_matrix(n_a: int, n_b: int) -> list[list[int]]:
    """A=Yes and B=Yes are mutually exclusive."""
    matrix = [[1] * n_b for _ in range(n_a)]
    if n_a >= 1 and n_b >= 1:
        matrix[0][0] = 0  # Both Yes is infeasible
    return matrix


def _conditional_matrix(
    n_a: int,
    n_b: int,
    outcomes_a: list[str] | None = None,
    outcomes_b: list[str] | None = None,
    prices_a: dict | None = None,
    prices_b: dict | None = None,
    correlation: str | None = None,
) -> list[list[int]]:
    """Derive feasibility constraints for conditional pairs.

    For binary conditional pairs, uses the correlation direction and current
    prices to mark anti-correlated joint outcomes as infeasible:

    - Positive correlation (A=Yes makes B=Yes more likely):
      Mark (Yes, No) infeasible when |p_a - p_b| is large — prices should
      move together, so a big divergence implies one side is mispriced.
      Also mark (No, Yes) infeasible symmetrically.

    - Negative correlation (A=Yes makes B=Yes less likely):
      Equivalent to mutual_exclusion — mark (Yes, Yes) infeasible.

    For non-binary markets or missing data, falls back to unconstrained.
    """
    matrix = [[1] * n_b for _ in range(n_a)]

    # Can only derive constraints for binary pairs with prices + correlation
    if n_a != 2 or n_b != 2:
        return matrix
    if not prices_a or not prices_b or not outcomes_a or not outcomes_b:
        return matrix
    if not correlation:
        return matrix

    def _f(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    p_a = _f(prices_a.get(outcomes_a[0], 0))  # P(A=Yes)
    p_b = _f(prices_b.get(outcomes_b[0], 0))  # P(B=Yes)

    if correlation == "negative":
        # Negative correlation ≈ mutual exclusion: (Yes, Yes) is infeasible
        matrix[0][0] = 0
        return matrix

    # Positive correlation: all four outcomes remain logically feasible.
    # Price divergence alone does not eliminate logical possibilities —
    # inferring infeasibility from prices is circular reasoning that
    # creates phantom arbitrage (the optimizer "corrects" the divergence
    # that was used to mark the cell infeasible in the first place).
    #
    # If the pair truly has a logical constraint (e.g., A implies B),
    # it should be classified as "implication", not "conditional".
    # Conditionals are for correlated-but-not-constrained pairs.
    return matrix


def _cross_platform_matrix(n_a: int, n_b: int) -> list[list[int]]:
    """Same event on two venues: outcomes must agree (identity constraint).

    (Yes,Yes)=1, (No,No)=1, mixed=0 — the markets should resolve identically.
    """
    if n_a == 2 and n_b == 2:
        return [
            [1, 0],  # A=Yes ↔ B=Yes
            [0, 1],  # A=No ↔ B=No
        ]
    # Fallback for non-binary (shouldn't happen for cross-platform)
    return [[1 if i == j else 0 for j in range(n_b)] for i in range(n_a)]


def _unconstrained_matrix(n_a: int, n_b: int) -> list[list[int]]:
    return [[1] * n_b for _ in range(n_a)]


def build_constraint_matrix_from_vectors(
    valid_outcomes: list[dict],
    outcomes_a: list[str],
    outcomes_b: list[str],
    dependency_type: str,
    prices_a: dict | None = None,
    prices_b: dict | None = None,
    correlation: str | None = None,
    implication_direction: str | None = None,
    venue_a: str = "polymarket",
    venue_b: str = "polymarket",
) -> dict:
    """Build constraint matrix directly from resolution vectors.

    Populates the feasibility matrix from the LLM's valid_outcomes list
    instead of from a dependency type label, preserving full information.
    Still computes profit bound using type-specific formulas (retained until
    a proved matrix-based bound handles both buy and sell sides).
    """
    n_a = len(outcomes_a)
    n_b = len(outcomes_b)

    # Build outcome → index maps
    idx_a = {o: i for i, o in enumerate(outcomes_a)}
    idx_b = {o: i for i, o in enumerate(outcomes_b)}

    # Start with all infeasible, mark feasible from vectors
    matrix = [[0] * n_b for _ in range(n_a)]
    for v in valid_outcomes:
        a_val = v.get("a", "")
        b_val = v.get("b", "")
        i = idx_a.get(a_val)
        j = idx_b.get(b_val)
        if i is not None and j is not None:
            matrix[i][j] = 1

    profit_bound = _compute_profit_bound(
        dependency_type, matrix, outcomes_a, outcomes_b, prices_a, prices_b,
        correlation, venue_a=venue_a, venue_b=venue_b,
    )

    result = {
        "type": dependency_type,
        "outcomes_a": outcomes_a,
        "outcomes_b": outcomes_b,
        "matrix": matrix,
        "profit_bound": profit_bound,
        "correlation": correlation,
        "implication_direction": implication_direction,
        "classification_source": "llm_vector",
    }

    logger.info(
        "constraint_matrix_from_vectors",
        dep_type=dependency_type,
        shape=f"{n_a}x{n_b}",
        profit_bound=profit_bound,
        n_feasible=sum(sum(row) for row in matrix),
    )
    return result


def _compute_profit_bound(
    dependency_type: str,
    matrix: list[list[int]],
    outcomes_a: list[str],
    outcomes_b: list[str],
    prices_a: dict | None,
    prices_b: dict | None,
    correlation: str | None = None,
    venue_a: str = "polymarket",
    venue_b: str = "polymarket",
) -> float:
    """Compute a theoretical profit bound from price inconsistency.

    For binary markets: if prices on a constrained pair sum to != 1 (for
    partitions) or violate implication bounds, there's arbitrage.
    """
    if not prices_a or not prices_b:
        return 0.0

    def _f(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    if dependency_type == "cross_platform":
        # Cross-platform arb: buy cheap Yes on one venue, sell expensive Yes
        # on the other. Profit = spread minus fees on both venues.
        from shared.config import venue_fee

        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        spread = abs(p_a - p_b)
        # Fee on the buy leg (cheaper side) and the sell leg (dearer side)
        fee_a = venue_fee(venue_a, p_a, "BUY")
        fee_b = venue_fee(venue_b, p_b, "BUY")
        net = spread - fee_a - fee_b
        return round(net, 6) if net > 0.001 else 0.0

    if dependency_type == "partition":
        total = sum(_f(prices_a.get(o, 0)) for o in outcomes_a) + sum(
            _f(prices_b.get(o, 0)) for o in outcomes_b
        )
        deviation = abs(total - 1.0)
        return round(deviation, 6) if deviation > 0.001 else 0.0

    if dependency_type == "implication":
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        # Use the matrix to determine direction:
        # a_implies_b: matrix[0][1]=0, constraint is P(A) ≤ P(B), arb when P(A) > P(B)
        # b_implies_a: matrix[1][0]=0, constraint is P(B) ≤ P(A), arb when P(B) > P(A)
        # unconstrained (all ones): no provable direction → no arb
        if len(matrix) >= 2 and len(matrix[0]) >= 2:
            if matrix[1][0] == 0:
                # b_implies_a direction
                if p_b > p_a:
                    return round(p_b - p_a, 6)
            elif matrix[0][1] == 0:
                # a_implies_b direction
                if p_a > p_b:
                    return round(p_a - p_b, 6)
            # else: unconstrained — no provable arb
        return 0.0

    if dependency_type == "mutual_exclusion":
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        excess = (p_a + p_b) - 1.0
        return round(excess, 6) if excess > 0.001 else 0.0

    if dependency_type == "conditional":
        if not outcomes_a or not outcomes_b:
            return 0.0
        p_a = _f(prices_a.get(outcomes_a[0], 0))
        p_b = _f(prices_b.get(outcomes_b[0], 0))

        if correlation == "negative":
            # Same as mutual exclusion
            excess = (p_a + p_b) - 1.0
            return round(excess, 6) if excess > 0.001 else 0.0

        if correlation == "positive":
            # Positive conditional: unconstrained matrix → no provable arb.
            # Price divergence is not a proof of mispricing for merely-
            # correlated pairs.  If there's a real logical constraint,
            # the pair should be classified as "implication" instead.
            return 0.0

        return 0.0

    return 0.0
