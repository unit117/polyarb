"""Tests for constraint matrix generation."""

import pytest

from services.detector.constraints import build_constraint_matrix, build_constraint_matrix_from_vectors


class TestImplicationMatrix:
    def test_binary_implication_a_implies_b(self):
        result = build_constraint_matrix(
            "implication", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.8, "No": 0.2},
            prices_b={"Yes": 0.6, "No": 0.4},
            implication_direction="a_implies_b",
        )
        m = result["matrix"]
        assert m[0][0] == 1  # A=Yes, B=Yes: feasible
        assert m[0][1] == 0  # A=Yes, B=No: infeasible (A implies B)
        assert m[1][0] == 1  # A=No, B=Yes: feasible
        assert m[1][1] == 1  # A=No, B=No: feasible

    def test_binary_implication_b_implies_a(self):
        result = build_constraint_matrix(
            "implication", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.6, "No": 0.4},
            prices_b={"Yes": 0.8, "No": 0.2},
            implication_direction="b_implies_a",
        )
        m = result["matrix"]
        assert m[0][0] == 1  # A=Yes, B=Yes: feasible
        assert m[0][1] == 1  # A=Yes, B=No: feasible
        assert m[1][0] == 0  # A=No, B=Yes: infeasible (B implies A)
        assert m[1][1] == 1  # A=No, B=No: feasible

    def test_missing_direction_returns_unconstrained(self):
        result = build_constraint_matrix(
            "implication", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.8, "No": 0.2},
            prices_b={"Yes": 0.6, "No": 0.4},
        )
        m = result["matrix"]
        # No direction → unconstrained (all ones), no false arb signal
        assert m == [[1, 1], [1, 1]]
        assert result["profit_bound"] == 0.0

    def test_profit_bound_a_implies_b_when_pa_gt_pb(self):
        result = build_constraint_matrix(
            "implication", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.8, "No": 0.2},
            prices_b={"Yes": 0.6, "No": 0.4},
            implication_direction="a_implies_b",
        )
        assert result["profit_bound"] == pytest.approx(0.2, abs=0.001)

    def test_profit_bound_b_implies_a_when_pb_gt_pa(self):
        result = build_constraint_matrix(
            "implication", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.5, "No": 0.5},
            prices_b={"Yes": 0.8, "No": 0.2},
            implication_direction="b_implies_a",
        )
        # B→A: arb when P(B) > P(A), profit = 0.8 - 0.5 = 0.3
        assert result["profit_bound"] == pytest.approx(0.3, abs=0.001)

    def test_no_profit_when_pa_le_pb(self):
        result = build_constraint_matrix(
            "implication", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.5, "No": 0.5},
            prices_b={"Yes": 0.7, "No": 0.3},
        )
        assert result["profit_bound"] == 0.0

    def test_implication_direction_stored_in_result(self):
        result = build_constraint_matrix(
            "implication", ["Yes", "No"], ["Yes", "No"],
            implication_direction="b_implies_a",
        )
        assert result["implication_direction"] == "b_implies_a"


class TestPartitionMatrix:
    def test_binary_partition(self):
        result = build_constraint_matrix(
            "partition", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.3, "No": 0.7},
            prices_b={"Yes": 0.4, "No": 0.6},
        )
        m = result["matrix"]
        assert m == [[0, 1], [1, 0]]

    def test_multi_outcome_partition(self):
        result = build_constraint_matrix(
            "partition",
            ["Alice", "Bob", "Charlie"],
            ["Alice", "Bob", "Dave"],
        )
        m = result["matrix"]
        # Alice & Bob are shared; different shared outcomes can't both be true
        assert m[0][1] == 0  # Alice vs Bob: infeasible
        assert m[1][0] == 0  # Bob vs Alice: infeasible
        assert m[0][0] == 1  # Alice vs Alice: same outcome, feasible
        assert m[2][2] == 1  # Charlie vs Dave: not shared, feasible

    def test_profit_bound_sum_deviation(self):
        result = build_constraint_matrix(
            "partition", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.3, "No": 0.7},
            prices_b={"Yes": 0.4, "No": 0.6},
        )
        # total = 0.3+0.7+0.4+0.6 = 2.0, deviation from 1.0 = 1.0
        assert result["profit_bound"] == pytest.approx(1.0, abs=0.001)


class TestMutualExclusionMatrix:
    def test_binary_me(self):
        result = build_constraint_matrix(
            "mutual_exclusion", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.6, "No": 0.4},
            prices_b={"Yes": 0.5, "No": 0.5},
        )
        m = result["matrix"]
        assert m[0][0] == 0  # Both Yes infeasible
        assert m[0][1] == 1
        assert m[1][0] == 1
        assert m[1][1] == 1

    def test_profit_bound_excess(self):
        result = build_constraint_matrix(
            "mutual_exclusion", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.6, "No": 0.4},
            prices_b={"Yes": 0.5, "No": 0.5},
        )
        # excess = 0.6 + 0.5 - 1.0 = 0.1
        assert result["profit_bound"] == pytest.approx(0.1, abs=0.001)


class TestConditionalMatrix:
    def test_negative_correlation(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.6, "No": 0.4},
            prices_b={"Yes": 0.5, "No": 0.5},
            correlation="negative",
        )
        m = result["matrix"]
        assert m[0][0] == 0  # Both Yes infeasible (like ME)

    def test_positive_correlation_divergent_prices(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.8, "No": 0.2},
            prices_b={"Yes": 0.5, "No": 0.5},
            correlation="positive",
        )
        m = result["matrix"]
        # Positive conditional no longer infers logical infeasibility from prices.
        assert m == [[1, 1], [1, 1]]

    def test_positive_correlation_no_divergence(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.55, "No": 0.45},
            prices_b={"Yes": 0.50, "No": 0.50},
            correlation="positive",
        )
        m = result["matrix"]
        # divergence 0.05 < 0.15, no constraint triggered
        assert m == [[1, 1], [1, 1]]

    def test_non_binary_returns_unconstrained(self):
        result = build_constraint_matrix(
            "conditional", ["A", "B", "C"], ["X", "Y"],
            correlation="positive",
        )
        m = result["matrix"]
        assert all(all(c == 1 for c in row) for row in m)

    def test_both_high_prices(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.7, "No": 0.3},
            prices_b={"Yes": 0.6, "No": 0.4},
            correlation="positive",
        )
        m = result["matrix"]
        assert m == [[1, 1], [1, 1]]

    def test_both_low_prices(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.3, "No": 0.7},
            prices_b={"Yes": 0.4, "No": 0.6},
            correlation="positive",
        )
        m = result["matrix"]
        assert m == [[1, 1], [1, 1]]


class TestCrossPlatformMatrix:
    def test_binary_identity(self):
        result = build_constraint_matrix(
            "cross_platform", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.6, "No": 0.4},
            prices_b={"Yes": 0.55, "No": 0.45},
            venue_a="polymarket",
            venue_b="kalshi",
        )
        m = result["matrix"]
        assert m == [[1, 0], [0, 1]]

    def test_multi_outcome_diagonal(self):
        result = build_constraint_matrix(
            "cross_platform", ["A", "B", "C"], ["A", "B", "C"],
        )
        m = result["matrix"]
        for i in range(3):
            for j in range(3):
                assert m[i][j] == (1 if i == j else 0)


class TestUnknownType:
    def test_unconstrained_fallback(self):
        result = build_constraint_matrix(
            "unknown_type", ["Yes", "No"], ["Yes", "No"],
        )
        m = result["matrix"]
        assert m == [[1, 1], [1, 1]]


class TestNoPrices:
    def test_profit_bound_zero_without_prices(self):
        result = build_constraint_matrix(
            "implication", ["Yes", "No"], ["Yes", "No"],
        )
        assert result["profit_bound"] == 0.0


class TestConditionalEdgeCases:
    def test_binary_no_prices_returns_unconstrained(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a=None, prices_b=None,
            correlation="positive",
        )
        # No prices → unconstrained matrix
        m = result["matrix"]
        assert all(all(c == 1 for c in row) for row in m)

    def test_binary_no_correlation_returns_unconstrained(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.6, "No": 0.4},
            prices_b={"Yes": 0.5, "No": 0.5},
            correlation=None,
        )
        # No correlation → unconstrained matrix
        m = result["matrix"]
        assert all(all(c == 1 for c in row) for row in m)

    def test_non_numeric_price_treated_as_zero(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": "N/A", "No": 0.4},
            prices_b={"Yes": 0.5, "No": 0.5},
            correlation="negative",
        )
        # "N/A" → _f returns 0.0, still negative correlation → matrix[0][0] = 0
        m = result["matrix"]
        assert m[0][0] == 0

    def test_positive_correlation_b_much_higher_than_a(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.3, "No": 0.7},
            prices_b={"Yes": 0.6, "No": 0.4},
            correlation="positive",
        )
        m = result["matrix"]
        assert m == [[1, 1], [1, 1]]

    def test_profit_bound_conditional_no_outcomes(self):
        result = build_constraint_matrix(
            "conditional", [], [],
            prices_a={"Yes": 0.6},
            prices_b={"Yes": 0.5},
            correlation="negative",
        )
        # Empty outcomes → profit bound = 0
        assert result["profit_bound"] == 0.0

    def test_profit_bound_conditional_no_correlation_returns_zero(self):
        result = build_constraint_matrix(
            "conditional", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": 0.8, "No": 0.2},
            prices_b={"Yes": 0.5, "No": 0.5},
            correlation=None,
        )
        # No correlation → profit_bound = 0
        assert result["profit_bound"] == 0.0

    def test_profit_bound_non_numeric_price_in_compute(self):
        result = build_constraint_matrix(
            "mutual_exclusion", ["Yes", "No"], ["Yes", "No"],
            prices_a={"Yes": "bad_value", "No": 0.4},
            prices_b={"Yes": 0.5, "No": 0.5},
        )
        # "bad_value" → _f returns 0.0; excess = (0+0.5)-1.0 = -0.5 → 0.0
        assert result["profit_bound"] == 0.0


class TestBuildConstraintMatrixFromVectors:
    def test_me_from_vectors(self):
        """Missing (Y,Y) → matrix[0][0] = 0."""
        vectors = [
            {"a": "Yes", "b": "No"}, {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
        ]
        result = build_constraint_matrix_from_vectors(
            vectors, ["Yes", "No"], ["Yes", "No"],
            dependency_type="mutual_exclusion",
            prices_a={"Yes": 0.6, "No": 0.4},
            prices_b={"Yes": 0.5, "No": 0.5},
        )
        m = result["matrix"]
        assert m[0][0] == 0  # Both Yes infeasible
        assert m[0][1] == 1
        assert m[1][0] == 1
        assert m[1][1] == 1
        assert result["classification_source"] == "llm_vector"

    def test_implication_a_implies_b_from_vectors(self):
        """Missing (Y,N) → matrix[0][1] = 0."""
        vectors = [
            {"a": "Yes", "b": "Yes"}, {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
        ]
        result = build_constraint_matrix_from_vectors(
            vectors, ["Yes", "No"], ["Yes", "No"],
            dependency_type="implication",
            implication_direction="a_implies_b",
            prices_a={"Yes": 0.8, "No": 0.2},
            prices_b={"Yes": 0.6, "No": 0.4},
        )
        m = result["matrix"]
        assert m[0][0] == 1
        assert m[0][1] == 0  # A=Yes + B=No infeasible
        assert m[1][0] == 1
        assert m[1][1] == 1
        assert result["profit_bound"] == pytest.approx(0.2, abs=0.001)

    def test_partition_from_vectors(self):
        """XOR: only (Y,N) and (N,Y) feasible."""
        vectors = [{"a": "Yes", "b": "No"}, {"a": "No", "b": "Yes"}]
        result = build_constraint_matrix_from_vectors(
            vectors, ["Yes", "No"], ["Yes", "No"],
            dependency_type="partition",
        )
        assert result["matrix"] == [[0, 1], [1, 0]]

    def test_all_four_from_vectors(self):
        """All combos valid → unconstrained."""
        vectors = [
            {"a": "Yes", "b": "Yes"}, {"a": "Yes", "b": "No"},
            {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
        ]
        result = build_constraint_matrix_from_vectors(
            vectors, ["Yes", "No"], ["Yes", "No"],
            dependency_type="none",
        )
        assert result["matrix"] == [[1, 1], [1, 1]]

    def test_preserves_type_key(self):
        """Optimizer reads constraint.get('type') — must be present."""
        vectors = [{"a": "Yes", "b": "No"}, {"a": "No", "b": "Yes"}]
        result = build_constraint_matrix_from_vectors(
            vectors, ["Yes", "No"], ["Yes", "No"],
            dependency_type="partition",
        )
        assert result["type"] == "partition"
