"""Tests for pair verification logic."""

import pytest

from services.detector.verification import verify_pair


class TestConfidenceCheck:
    def test_high_confidence_passes(self):
        result = verify_pair(
            "implication",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.7, "No": 0.3},
            {"Yes": 0.8, "No": 0.2},
            confidence=0.90,
        )
        assert result["verified"] is True

    def test_low_confidence_fails(self):
        result = verify_pair(
            "implication",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.5, "No": 0.5},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.50,
        )
        assert result["verified"] is False
        assert any("low_confidence" in r for r in result["reasons"])


class TestStructuralChecks:
    def test_partition_same_event(self):
        # Prices must sum close to 1.0 across both markets for partition
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"Yes": 0.3, "No": 0.2},
            {"Yes": 0.25, "No": 0.25},
            confidence=0.95,
        )
        assert result["verified"] is True

    def test_partition_no_shared_info_binary(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.3, "No": 0.7},
            {"Yes": 0.4, "No": 0.6},
            confidence=0.95,
        )
        # Binary markets with no event_id or overlap fail structural
        assert result["verified"] is False

    def test_me_binary_passes(self):
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.4, "No": 0.6},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        assert result["verified"] is True

    def test_me_non_binary_fails(self):
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["A", "B", "C"]},
            {"outcomes": ["Yes", "No"]},
            None, None,
            confidence=0.90,
        )
        assert result["verified"] is False

    def test_conditional_needs_correlation(self):
        result = verify_pair(
            "conditional",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.5, "No": 0.5},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
            correlation=None,
        )
        assert result["verified"] is False

    def test_conditional_with_correlation(self):
        result = verify_pair(
            "conditional",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.5, "No": 0.5},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
            correlation="positive",
        )
        assert result["verified"] is True

    def test_cross_platform_different_venues(self):
        result = verify_pair(
            "cross_platform",
            {"outcomes": ["Yes", "No"], "venue": "polymarket"},
            {"outcomes": ["Yes", "No"], "venue": "kalshi"},
            {"Yes": 0.5, "No": 0.5},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        assert result["verified"] is True

    def test_cross_platform_same_venue_fails(self):
        result = verify_pair(
            "cross_platform",
            {"outcomes": ["Yes", "No"], "venue": "polymarket"},
            {"outcomes": ["Yes", "No"], "venue": "polymarket"},
            {"Yes": 0.5, "No": 0.5},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        assert result["verified"] is False


class TestPriceConsistency:
    def test_partition_sum_reasonable(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"Yes": 0.3, "No": 0.7},
            {"Yes": 0.3, "No": 0.7},
            confidence=0.90,
        )
        # sum = 2.0, deviation 1.0 > 0.5 threshold → fail price check
        assert result["verified"] is False

    def test_partition_sum_close_to_one(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"Yes": 0.3, "No": 0.2},
            {"Yes": 0.25, "No": 0.25},
            confidence=0.90,
        )
        # sum = 1.0 → passes
        assert result["verified"] is True

    def test_implication_extreme_violation(self):
        result = verify_pair(
            "implication",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.9, "No": 0.1},
            {"Yes": 0.2, "No": 0.8},
            confidence=0.90,
        )
        # P(A)=0.9 >> P(B)=0.2, diff=0.7 > 0.50 → fail
        assert result["verified"] is False

    def test_me_prices_reasonable(self):
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.4, "No": 0.6},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        # sum = 0.9 ≤ 1.20 → pass
        assert result["verified"] is True

    def test_conditional_price_out_of_range(self):
        result = verify_pair(
            "conditional",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.0, "No": 1.0},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
            correlation="positive",
        )
        # p_a = 0.0 not in (0, 1) → fail
        assert result["verified"] is False

    def test_cross_platform_extreme_price(self):
        result = verify_pair(
            "cross_platform",
            {"outcomes": ["Yes", "No"], "venue": "polymarket"},
            {"outcomes": ["Yes", "No"], "venue": "kalshi"},
            {"Yes": 0.99, "No": 0.01},
            {"Yes": 0.50, "No": 0.50},
            confidence=0.90,
        )
        # 0.99 > 0.95 → fail
        assert result["verified"] is False

    def test_me_sum_exceeds_threshold_fails(self):
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.75, "No": 0.25},
            {"Yes": 0.70, "No": 0.30},
            confidence=0.90,
        )
        # sum = 1.45 > 1.20 → fail
        assert result["verified"] is False
        assert any("mutual_exclusion" in r for r in result["reasons"])

    def test_partition_with_invalid_price_value(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"Yes": None, "No": 0.5},
            {"Yes": 0.25, "No": 0.25},
            confidence=0.90,
        )
        # None price → _f returns 0.0; sum = 0+0.5+0.25+0.25 = 1.0 → passes
        assert result["verified"] is True

    def test_unknown_type_price_check_passes(self):
        result = verify_pair(
            "unknown_dependency",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.5, "No": 0.5},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        # unknown type fails structural but price consistency returns True (fallback)
        assert result["verified"] is False
        assert any("unknown dependency_type" in r for r in result["reasons"])


class TestStructuralEdgeCases:
    def test_partition_multi_outcome_no_overlap_passes(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Alice", "Bob", "Charlie"]},
            {"outcomes": ["Dave", "Eve", "Frank"]},
            None, None,
            confidence=0.90,
        )
        # No event_id, no overlap, but both have >2 outcomes → structural passes
        assert result["verified"] is True

    def test_partition_binary_different_outcomes_no_event_fails(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["True", "False"]},
            None, None,
            confidence=0.90,
        )
        # No event_id, no outcome overlap (Yes≠True/False), both binary → structural fail
        assert result["verified"] is False
        assert any("partition" in r for r in result["reasons"])

    def test_implication_too_few_outcomes_fails(self):
        result = verify_pair(
            "implication",
            {"outcomes": ["Yes"]},
            {"outcomes": ["Yes", "No"]},
            None, None,
            confidence=0.90,
        )
        assert result["verified"] is False
        assert any("implication" in r for r in result["reasons"])

    def test_conditional_non_binary_passes_structural(self):
        result = verify_pair(
            "conditional",
            {"outcomes": ["A", "B", "C"]},
            {"outcomes": ["X", "Y", "Z"]},
            None, None,
            confidence=0.90,
        )
        # Non-binary conditional passes structural check without correlation
        assert result["verified"] is True

    def test_cross_platform_non_binary_fails(self):
        result = verify_pair(
            "cross_platform",
            {"outcomes": ["A", "B", "C"], "venue": "polymarket"},
            {"outcomes": ["X", "Y"], "venue": "kalshi"},
            None, None,
            confidence=0.90,
        )
        # Different venues but non-binary → structural fail
        assert result["verified"] is False
        assert any("non-binary" in r for r in result["reasons"])

    def test_unknown_dependency_type_fails(self):
        result = verify_pair(
            "unknown_dependency",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            None, None,
            confidence=0.90,
        )
        assert result["verified"] is False
        assert any("unknown dependency_type" in r for r in result["reasons"])
