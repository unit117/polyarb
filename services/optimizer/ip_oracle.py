"""Integer Programming oracle using OR-Tools CP-SAT.

Solves the linear minimization subproblem over the marginal polytope:
    s* = argmin_{s ∈ M} <c, s>

where M is the marginal polytope defined by:
- Each market has exactly one true outcome (simplex constraint)
- Joint outcomes must be feasible per the constraint matrix

This is the core inner loop of Frank-Wolfe — called once per iteration.
"""
from __future__ import annotations

import numpy as np
import structlog
from ortools.sat.python import cp_model

logger = structlog.get_logger()


def solve_ip_oracle(
    gradient: np.ndarray,
    n_outcomes_a: int,
    n_outcomes_b: int,
    feasibility_matrix: list[list[int]],
    timeout_ms: int = 5000,
) -> np.ndarray | None:
    """Solve the linear minimization over the marginal polytope.

    The marginal polytope for two markets with a feasibility constraint is:
    - Joint distribution π(i,j) >= 0 for feasible (i,j), π(i,j) = 0 for infeasible
    - sum_j π(i,j) = p_a(i) for all i (marginal constraint A)
    - sum_i π(i,j) = p_b(j) for all j (marginal constraint B)
    - sum_ij π(i,j) = 1 (normalization)

    We minimize <c, [p_a; p_b]> over the marginals, where the joint must
    be supported only on feasible entries.

    For binary/small markets, this is tractable as a CP-SAT problem by
    finding a vertex of the marginal polytope (deterministic assignment).

    Args:
        gradient: Linear objective coefficients [c_a; c_b] of length n_a + n_b.
        n_outcomes_a: Number of outcomes for market A.
        n_outcomes_b: Number of outcomes for market B.
        feasibility_matrix: Binary matrix, 1 = feasible joint outcome.
        timeout_ms: Solver time limit in milliseconds.

    Returns:
        Vertex of the marginal polytope (marginal probabilities) or None if infeasible.
    """
    model = cp_model.CpModel()

    # Binary variables for each joint outcome (i, j)
    x = {}
    for i in range(n_outcomes_a):
        for j in range(n_outcomes_b):
            if feasibility_matrix[i][j]:
                x[i, j] = model.new_bool_var(f"x_{i}_{j}")

    # Exactly one joint outcome is true
    model.add_exactly_one(x.values())

    # Derive marginals from the joint assignment
    # p_a(i) = sum_j x(i,j), p_b(j) = sum_i x(i,j)
    # At a vertex, these are 0 or 1.

    # Objective: minimize <gradient, marginals>
    # = sum_i grad_a[i] * p_a(i) + sum_j grad_b[j] * p_b(j)
    # = sum_i grad_a[i] * sum_j x(i,j) + sum_j grad_b[j] * sum_i x(i,j)
    # = sum_{i,j} (grad_a[i] + grad_b[j]) * x(i,j)
    grad_a = gradient[:n_outcomes_a]
    grad_b = gradient[n_outcomes_a:]

    # Scale to integers for CP-SAT (multiply by large factor)
    scale = 10000
    objective_terms = []
    for (i, j), var in x.items():
        coeff = int(round((grad_a[i] + grad_b[j]) * scale))
        objective_terms.append(coeff * var)

    model.minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_ms / 1000.0

    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning("ip_oracle_infeasible", status=status)
        return None

    # Extract the marginal probabilities from the vertex
    result = np.zeros(n_outcomes_a + n_outcomes_b)
    for (i, j), var in x.items():
        if solver.value(var):
            result[i] = 1.0  # p_a(i) = 1
            result[n_outcomes_a + j] = 1.0  # p_b(j) = 1

    return result
