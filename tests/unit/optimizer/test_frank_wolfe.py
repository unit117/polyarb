"""Tests for Frank-Wolfe optimization."""

import numpy as np
import pytest

from services.optimizer.frank_wolfe import FWResult, optimize, _normalize, _find_initial_feasible


class TestNormalize:
    def test_valid_distribution(self):
        v = np.array([0.3, 0.7])
        result = _normalize(v)
        assert result.sum() == pytest.approx(1.0)

    def test_unnormalized(self):
        v = np.array([3.0, 7.0])
        result = _normalize(v)
        np.testing.assert_allclose(result, [0.3, 0.7])

    def test_zero_vector(self):
        v = np.array([0.0, 0.0])
        result = _normalize(v)
        np.testing.assert_allclose(result, [0.5, 0.5])


class TestFindInitialFeasible:
    def test_finds_feasible_vertex(self):
        matrix = [[1, 0], [0, 1]]
        q = _find_initial_feasible(2, 2, matrix)
        assert q is not None
        assert q.sum() == 2.0  # Two 1.0 entries
        assert q[0] == 1.0 and q[2] == 1.0  # First feasible: (0,0)

    def test_all_infeasible_returns_none(self):
        matrix = [[0, 0], [0, 0]]
        assert _find_initial_feasible(2, 2, matrix) is None

    def test_single_feasible_cell(self):
        matrix = [[0, 0], [0, 1]]
        q = _find_initial_feasible(2, 2, matrix)
        assert q is not None
        assert q[1] == 1.0  # A outcome 1
        assert q[3] == 1.0  # B outcome 1


class TestOptimize:
    def test_consistent_prices_converge_fast(self):
        """Prices already in the marginal polytope should converge quickly."""
        # Cross-platform: identity constraint, prices already agree
        result = optimize(
            prices_a=np.array([0.6, 0.4]),
            prices_b=np.array([0.6, 0.4]),
            feasibility_matrix=[[1, 0], [0, 1]],
            max_iterations=200,
            gap_tolerance=0.001,
        )
        assert result.converged is True
        assert result.kl_divergence < 0.01

    def test_inconsistent_prices_find_projection(self):
        """Prices violating constraints should be projected."""
        # Cross-platform: identity but prices disagree
        result = optimize(
            prices_a=np.array([0.7, 0.3]),
            prices_b=np.array([0.5, 0.5]),
            feasibility_matrix=[[1, 0], [0, 1]],
            max_iterations=200,
        )
        # Optimal q should be somewhere between the two
        q_a = result.optimal_q[:2]
        q_b = result.optimal_q[2:]
        # For identity constraint, q_a should equal q_b at optimum
        np.testing.assert_allclose(q_a, q_b, atol=0.05)

    def test_partition_constraint(self):
        """Partition: both Yes can't be true."""
        result = optimize(
            prices_a=np.array([0.6, 0.4]),
            prices_b=np.array([0.6, 0.4]),
            feasibility_matrix=[[0, 1], [1, 0]],
            max_iterations=200,
        )
        assert isinstance(result, FWResult)
        assert result.iterations > 0

    def test_mutual_exclusion(self):
        """ME: both Yes is infeasible."""
        result = optimize(
            prices_a=np.array([0.6, 0.4]),
            prices_b=np.array([0.6, 0.4]),
            feasibility_matrix=[[0, 1], [1, 1]],
            max_iterations=200,
        )
        assert isinstance(result, FWResult)

    def test_result_has_correct_dimensions(self):
        result = optimize(
            prices_a=np.array([0.5, 0.5]),
            prices_b=np.array([0.5, 0.5]),
            feasibility_matrix=[[1, 0], [0, 1]],
        )
        assert result.n_outcomes_a == 2
        assert result.n_outcomes_b == 2
        assert len(result.optimal_q) == 4
        assert len(result.market_prices) == 4

    def test_all_infeasible_returns_early(self):
        result = optimize(
            prices_a=np.array([0.5, 0.5]),
            prices_b=np.array([0.5, 0.5]),
            feasibility_matrix=[[0, 0], [0, 0]],
        )
        assert result.converged is False
        assert result.final_gap == float("inf")

    def test_ip_oracle_failure_breaks_loop(self):
        """If IP oracle returns None mid-optimization the loop breaks early."""
        from unittest.mock import patch

        with patch("services.optimizer.frank_wolfe.solve_ip_oracle", return_value=None):
            result = optimize(
                prices_a=np.array([0.6, 0.4]),
                prices_b=np.array([0.5, 0.5]),
                feasibility_matrix=[[1, 0], [0, 1]],
                max_iterations=100,
            )
        # Should not have converged since oracle always fails
        assert result.converged is False
