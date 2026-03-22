"""Tests for the IP oracle (CP-SAT linear minimization)."""

import numpy as np
import pytest

from services.optimizer.ip_oracle import solve_ip_oracle


class TestSolveIPOracle:
    def test_identity_constraint_selects_minimum(self):
        """With identity constraint [[1,0],[0,1]], should pick the (i,j) that minimizes grad."""
        gradient = np.array([2.0, 1.0, 3.0, 0.5])
        # Feasible: (0,0) and (1,1)
        # Cost: (0,0) → grad[0]+grad[2] = 5.0, (1,1) → grad[1]+grad[3] = 1.5
        result = solve_ip_oracle(gradient, 2, 2, [[1, 0], [0, 1]])
        assert result is not None
        # Should select (1,1): A=1, B=1
        assert result[1] == 1.0
        assert result[3] == 1.0

    def test_unconstrained_selects_minimum(self):
        gradient = np.array([1.0, 2.0, 0.5, 3.0])
        # All cells feasible, minimum is (0,0): grad[0]+grad[2] = 1.5
        result = solve_ip_oracle(gradient, 2, 2, [[1, 1], [1, 1]])
        assert result is not None
        assert result[0] == 1.0  # A outcome 0
        assert result[2] == 1.0  # B outcome 0

    def test_all_infeasible_returns_none(self):
        gradient = np.array([1.0, 1.0, 1.0, 1.0])
        result = solve_ip_oracle(gradient, 2, 2, [[0, 0], [0, 0]])
        assert result is None

    def test_single_feasible_cell(self):
        gradient = np.array([10.0, 1.0, 10.0, 1.0])
        # Only (0,1) is feasible
        result = solve_ip_oracle(gradient, 2, 2, [[0, 1], [0, 0]])
        assert result is not None
        assert result[0] == 1.0  # A=0
        assert result[3] == 1.0  # B=1

    def test_result_is_vertex(self):
        """Result should be a deterministic assignment (vertex of marginal polytope)."""
        gradient = np.array([1.0, 2.0, 3.0, 4.0])
        result = solve_ip_oracle(gradient, 2, 2, [[1, 1], [1, 1]])
        assert result is not None
        # Exactly one A outcome and one B outcome should be 1
        assert result[:2].sum() == 1.0
        assert result[2:].sum() == 1.0

    def test_three_outcome_market(self):
        gradient = np.array([1.0, 2.0, 3.0, 0.5, 1.5])
        # 3 outcomes A, 2 outcomes B
        matrix = [[1, 1], [1, 0], [0, 1]]
        result = solve_ip_oracle(gradient, 3, 2, matrix)
        assert result is not None
        assert result[:3].sum() == 1.0
        assert result[3:].sum() == 1.0

    def test_negative_gradient(self):
        gradient = np.array([-2.0, -1.0, -3.0, -0.5])
        result = solve_ip_oracle(gradient, 2, 2, [[1, 1], [1, 1]])
        assert result is not None
        # Should pick most negative sum: (0,1) → -2.0 + -0.5 = -2.5
        # Or (0,0) → -2.0 + -3.0 = -5.0 ← this is the min
        assert result[0] == 1.0
        assert result[2] == 1.0
