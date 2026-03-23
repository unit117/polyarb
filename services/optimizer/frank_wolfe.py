"""Frank-Wolfe optimization for Bregman projection onto marginal polytope.

Implements the FWMM algorithm from Dudik, Lahaie & Pennock (2016).
Given market prices p, finds the nearest point q* in the marginal polytope M
by minimizing D_KL(q || p) subject to q ∈ M.

If q* ≠ p, the gap reveals arbitrage: the market prices are inconsistent
with the logical constraints between markets.
"""
from __future__ import annotations

import numpy as np
import structlog

from services.optimizer.bregman import (
    duality_gap,
    kl_divergence,
    kl_gradient,
    project_to_simplex,
)
from services.optimizer.ip_oracle import solve_ip_oracle

logger = structlog.get_logger()


class FWResult:
    """Result of Frank-Wolfe optimization."""

    __slots__ = (
        "optimal_q",
        "market_prices",
        "iterations",
        "final_gap",
        "converged",
        "kl_divergence",
        "n_outcomes_a",
        "n_outcomes_b",
        "feasibility_matrix",
    )

    def __init__(
        self,
        optimal_q: np.ndarray,
        market_prices: np.ndarray,
        iterations: int,
        final_gap: float,
        converged: bool,
        kl_div: float,
        n_outcomes_a: int,
        n_outcomes_b: int,
        feasibility_matrix: list | None = None,
    ):
        self.optimal_q = optimal_q
        self.market_prices = market_prices
        self.iterations = iterations
        self.final_gap = final_gap
        self.converged = converged
        self.kl_divergence = kl_div
        self.n_outcomes_a = n_outcomes_a
        self.n_outcomes_b = n_outcomes_b
        self.feasibility_matrix = feasibility_matrix


def optimize(
    prices_a: np.ndarray,
    prices_b: np.ndarray,
    feasibility_matrix: list[list[int]],
    max_iterations: int = 200,
    gap_tolerance: float = 0.001,
    ip_timeout_ms: int = 5000,
) -> FWResult:
    """Run Frank-Wolfe to project market prices onto the marginal polytope.

    Args:
        prices_a: Probability vector for market A outcomes.
        prices_b: Probability vector for market B outcomes.
        feasibility_matrix: Binary feasibility matrix from Phase 2.
        max_iterations: Maximum FW iterations.
        gap_tolerance: Convergence threshold for duality gap.
        ip_timeout_ms: Per-iteration IP oracle timeout.

    Returns:
        FWResult with optimal distribution and convergence info.
    """
    n_a = len(prices_a)
    n_b = len(prices_b)

    # Normalize market prices to valid distributions
    p = np.concatenate([
        _normalize(prices_a),
        _normalize(prices_b),
    ])

    # Initialize q_0 at a feasible vertex of the marginal polytope
    q = _find_initial_feasible(n_a, n_b, feasibility_matrix)
    if q is None:
        logger.error("no_feasible_initial_point")
        return FWResult(p, p, 0, float("inf"), False, 0.0, n_a, n_b, feasibility_matrix)

    converged = False
    final_gap = float("inf")

    for t in range(max_iterations):
        # Compute gradient of KL divergence
        grad = kl_gradient(q, p)

        # IP oracle: find vertex s that minimizes <grad, s>
        s = solve_ip_oracle(grad, n_a, n_b, feasibility_matrix, ip_timeout_ms)
        if s is None:
            logger.warning("ip_oracle_failed", iteration=t)
            break

        # Compute duality gap
        gap = duality_gap(grad, q, s)
        final_gap = gap

        if gap < gap_tolerance:
            converged = True
            logger.info("fw_converged", iteration=t, gap=gap)
            break

        # Step size: standard FW schedule
        gamma = 2.0 / (t + 2.0)

        # Update: q_{t+1} = (1 - γ) * q_t + γ * s_t
        q = (1.0 - gamma) * q + gamma * s

        # Ensure marginals remain valid distributions
        q[:n_a] = project_to_simplex(q[:n_a])
        q[n_a:] = project_to_simplex(q[n_a:])

    kl_div = kl_divergence(q, p)
    iterations = t + 1 if not converged else t + 1

    logger.info(
        "fw_complete",
        iterations=iterations,
        converged=converged,
        final_gap=final_gap,
        kl_divergence=kl_div,
    )

    return FWResult(q, p, iterations, final_gap, converged, kl_div, n_a, n_b, feasibility_matrix)


def _normalize(v: np.ndarray) -> np.ndarray:
    """Normalize a vector to sum to 1, handling edge cases."""
    s = v.sum()
    if s <= 0:
        return np.ones_like(v) / len(v)
    return v / s


def _find_initial_feasible(
    n_a: int,
    n_b: int,
    feasibility_matrix: list[list[int]],
) -> np.ndarray | None:
    """Find an initial feasible vertex of the marginal polytope.

    A vertex is a deterministic joint assignment where exactly one (i,j)
    pair is selected and it's feasible.
    """
    for i in range(n_a):
        for j in range(n_b):
            if feasibility_matrix[i][j]:
                q = np.zeros(n_a + n_b)
                q[i] = 1.0
                q[n_a + j] = 1.0
                return q
    return None
