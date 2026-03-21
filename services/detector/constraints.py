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
) -> dict:
    """Build a constraint matrix for a market pair.

    Returns a dict with:
    - type: the dependency type
    - outcomes_a, outcomes_b: outcome labels
    - matrix: a len(outcomes_a) x len(outcomes_b) binary feasibility matrix
      where 1 = feasible joint outcome, 0 = infeasible
    - profit_bound: theoretical profit if prices violate constraints
    """
    n_a = len(outcomes_a)
    n_b = len(outcomes_b)

    if dependency_type == "implication":
        matrix = _implication_matrix(n_a, n_b)
    elif dependency_type == "partition":
        matrix = _partition_matrix(outcomes_a, outcomes_b)
    elif dependency_type == "mutual_exclusion":
        matrix = _mutual_exclusion_matrix(n_a, n_b)
    elif dependency_type == "conditional":
        matrix = _conditional_matrix(n_a, n_b)
    else:
        matrix = _unconstrained_matrix(n_a, n_b)

    profit_bound = _compute_profit_bound(
        dependency_type, matrix, outcomes_a, outcomes_b, prices_a, prices_b
    )

    result = {
        "type": dependency_type,
        "outcomes_a": outcomes_a,
        "outcomes_b": outcomes_b,
        "matrix": matrix,
        "profit_bound": profit_bound,
    }

    logger.info(
        "constraint_matrix_built",
        dep_type=dependency_type,
        shape=f"{n_a}x{n_b}",
        profit_bound=profit_bound,
    )
    return result


def _implication_matrix(n_a: int, n_b: int) -> list[list[int]]:
    """A implies B[0]: if A resolves Yes (idx 0), B must resolve Yes (idx 0)."""
    matrix = [[1] * n_b for _ in range(n_a)]
    if n_a >= 2 and n_b >= 2:
        # A=Yes implies B=Yes, so A=Yes + B=No is infeasible
        matrix[0][1] = 0
    return matrix


def _partition_matrix(outcomes_a: list[str], outcomes_b: list[str]) -> list[list[int]]:
    """Markets partition the same space: at most one outcome across both can be true."""
    n_a = len(outcomes_a)
    n_b = len(outcomes_b)
    # Shared outcomes can't both resolve Yes
    shared = set(outcomes_a) & set(outcomes_b)
    matrix = [[1] * n_b for _ in range(n_a)]
    for i, oa in enumerate(outcomes_a):
        for j, ob in enumerate(outcomes_b):
            if oa in shared and ob in shared and oa != ob:
                # Different shared outcomes — both can't be true
                pass  # stays 1, both could be in the event
            if oa == ob and oa in shared:
                # Same outcome in both — feasible (it's the same event)
                matrix[i][j] = 1
    # For partition: exactly one outcome is true across the combined space
    # This is more nuanced; mark all as feasible for now and let
    # the optimizer enforce the sum-to-one constraint
    return matrix


def _mutual_exclusion_matrix(n_a: int, n_b: int) -> list[list[int]]:
    """A=Yes and B=Yes are mutually exclusive."""
    matrix = [[1] * n_b for _ in range(n_a)]
    if n_a >= 1 and n_b >= 1:
        matrix[0][0] = 0  # Both Yes is infeasible
    return matrix


def _conditional_matrix(n_a: int, n_b: int) -> list[list[int]]:
    """All joint outcomes are feasible but probabilities are constrained.

    The actual constraint is on probability values, not on feasibility.
    We pass through all-ones and attach metadata for the optimizer.
    """
    return [[1] * n_b for _ in range(n_a)]


def _unconstrained_matrix(n_a: int, n_b: int) -> list[list[int]]:
    return [[1] * n_b for _ in range(n_a)]


def _compute_profit_bound(
    dependency_type: str,
    matrix: list[list[int]],
    outcomes_a: list[str],
    outcomes_b: list[str],
    prices_a: dict | None,
    prices_b: dict | None,
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

    if dependency_type == "partition":
        total = sum(_f(prices_a.get(o, 0)) for o in outcomes_a) + sum(
            _f(prices_b.get(o, 0)) for o in outcomes_b
        )
        deviation = abs(total - 1.0)
        return round(deviation, 6) if deviation > 0.001 else 0.0

    if dependency_type == "implication":
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        if p_a > p_b:
            return round(p_a - p_b, 6)
        return 0.0

    if dependency_type == "mutual_exclusion":
        p_a = _f(prices_a.get(outcomes_a[0], 0)) if outcomes_a else 0.0
        p_b = _f(prices_b.get(outcomes_b[0], 0)) if outcomes_b else 0.0
        excess = (p_a + p_b) - 1.0
        return round(excess, 6) if excess > 0.001 else 0.0

    return 0.0
