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
            implication_direction="a_implies_b",
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
            implication_direction="a_implies_b",
        )
        assert result["verified"] is False
        assert any("low_confidence" in r for r in result["reasons"])


class TestStructuralChecks:
    def test_partition_same_event(self):
        # Binary partition: the two primary contracts should sum to 1.0.
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"Yes": 0.55, "No": 0.45},
            {"Yes": 0.45, "No": 0.55},
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

    def test_me_binary_with_shared_event_passes(self):
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"Yes": 0.4, "No": 0.6},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        assert result["verified"] is True

    def test_me_binary_no_event_id_fails(self):
        """ME without any event_id is non-verifiable (likely LLM hallucination)."""
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.4, "No": 0.6},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        assert result["verified"] is False
        assert any("missing event_id" in r for r in result["reasons"])

    def test_me_one_event_id_fails(self):
        """A one-sided event_id is as non-verifiable as none: ME requires the
        SAME event_id on BOTH markets (post-E1 invariant). This previously
        passed, which let hallucinated ME pairs through whenever exactly one
        market lacked an event_id."""
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.4, "No": 0.6},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        assert result["verified"] is False

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
        # primary sum = 0.3 + 0.3 = 0.6, deviation 0.4 > 0.25 threshold
        assert result["verified"] is False

    def test_partition_sum_close_to_one(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"Yes": 0.60, "No": 0.40},
            {"Yes": 0.40, "No": 0.60},
            confidence=0.90,
        )
        # primary sum = 1.0 → passes
        assert result["verified"] is True

    def test_implication_extreme_violation(self):
        result = verify_pair(
            "implication",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.9, "No": 0.1},
            {"Yes": 0.2, "No": 0.8},
            confidence=0.90,
            implication_direction="a_implies_b",
        )
        # P(A)=0.9 >> P(B)=0.2, diff=0.7 > 0.50 → fail
        assert result["verified"] is False

    def test_me_prices_reasonable(self):
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"Yes": 0.4, "No": 0.6},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        # sum = 0.9 ≤ 1.10 → pass
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
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1"},
            {"Yes": 0.75, "No": 0.25},
            {"Yes": 0.70, "No": 0.30},
            confidence=0.90,
        )
        # sum = 1.45 > 1.10 → fail
        assert result["verified"] is False
        assert any("mutual_exclusion" in r for r in result["reasons"])

    def test_partition_with_invalid_price_value(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"outcomes": ["Yes", "No"], "event_id": "e1"},
            {"Yes": None, "No": 0.5},
            {"Yes": 0.90, "No": 0.10},
            confidence=0.90,
        )
        # None price → _f returns 0.0; primary sum = 0.0 + 0.90 = 0.90
        # abs(0.90 - 1.0) = 0.10 < 0.25 → passes
        assert result["verified"] is True

    def test_partition_multi_outcome_skips_binary_price_math(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Alice", "Bob", "Charlie"], "event_id": "e1"},
            {"outcomes": ["Alice", "Bob", "Dave"], "event_id": "e1"},
            {"Alice": 0.30, "Bob": 0.25, "Charlie": 0.45},
            {"Alice": 0.31, "Bob": 0.24, "Dave": 0.45},
            confidence=0.90,
        )
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
    def test_partition_multi_outcome_no_overlap_structural_passes(self):
        result = verify_pair(
            "partition",
            {"outcomes": ["Alice", "Bob", "Charlie"]},
            {"outcomes": ["Dave", "Eve", "Frank"]},
            None, None,
            confidence=0.90,
        )
        # No event_id, no overlap, but both have >2 outcomes → structural passes
        # However, missing prices → price_check_skipped → overall not verified
        assert result["verified"] is False
        assert any("price_check_skipped" in r for r in result["reasons"])

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

    def test_implication_missing_direction_fails(self):
        result = verify_pair(
            "implication",
            {"outcomes": ["Yes", "No"]},
            {"outcomes": ["Yes", "No"]},
            {"Yes": 0.7, "No": 0.3},
            {"Yes": 0.8, "No": 0.2},
            confidence=0.90,
        )
        assert result["verified"] is False
        assert any("missing implication_direction" in r for r in result["reasons"])

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
        # but missing prices → price_check_skipped → overall not verified
        assert result["verified"] is False
        assert any("price_check_skipped" in r for r in result["reasons"])

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


class TestMutualExclusionEventIdEquality:
    """ME must have the SAME event_id on BOTH markets — a one-sided id is
    exactly as non-verifiable as none at all (post-E1 invariant)."""

    def test_one_sided_event_id_fails(self):
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will A win?"},
            {"outcomes": ["Yes", "No"], "question": "Will B win?"},
            {"Yes": 0.4, "No": 0.6},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        assert result["verified"] is False
        assert any("missing event_id" in r for r in result["reasons"])

    def test_one_sided_event_id_fails_mirrored(self):
        result = verify_pair(
            "mutual_exclusion",
            {"outcomes": ["Yes", "No"], "question": "Will A win?"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will B win?"},
            {"Yes": 0.4, "No": 0.6},
            {"Yes": 0.5, "No": 0.5},
            confidence=0.90,
        )
        assert result["verified"] is False


class TestConditionalNegativeGates:
    """conditional/negative inherits the ME profit formula (P(A)+P(B)-1), so
    it must meet the same evidentiary bar: same event_id, distinct questions,
    and the ME price-sum cap."""

    def _verify(self, market_a, market_b, prices_a, prices_b):
        return verify_pair(
            "conditional",
            market_a,
            market_b,
            prices_a,
            prices_b,
            confidence=0.90,
            correlation="negative",
        )

    def test_same_event_passes(self):
        result = self._verify(
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will A lead?"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will B lead?"},
            {"Yes": 0.55, "No": 0.45},
            {"Yes": 0.50, "No": 0.50},
        )
        assert result["verified"] is True

    def test_missing_event_ids_fail(self):
        result = self._verify(
            {"outcomes": ["Yes", "No"], "question": "Will A lead?"},
            {"outcomes": ["Yes", "No"], "question": "Will B lead?"},
            {"Yes": 0.55, "No": 0.45},
            {"Yes": 0.50, "No": 0.50},
        )
        assert result["verified"] is False
        assert any("missing event_id" in r for r in result["reasons"])

    def test_different_event_ids_fail(self):
        result = self._verify(
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will A lead?"},
            {"outcomes": ["Yes", "No"], "event_id": "evt2", "question": "Will B lead?"},
            {"Yes": 0.55, "No": 0.45},
            {"Yes": 0.50, "No": 0.50},
        )
        assert result["verified"] is False
        assert any("different event_ids" in r for r in result["reasons"])

    def test_identical_questions_fail(self):
        result = self._verify(
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will it rain?"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will it rain?"},
            {"Yes": 0.55, "No": 0.45},
            {"Yes": 0.50, "No": 0.50},
        )
        assert result["verified"] is False
        assert any("identical questions" in r for r in result["reasons"])

    def test_sum_above_me_cap_fails(self):
        # 0.90 + 0.45 = 1.35 > 1.10 — likely independent markets, the
        # "excess" is misclassification, not arbitrage.
        result = self._verify(
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will A lead?"},
            {"outcomes": ["Yes", "No"], "event_id": "evt1", "question": "Will B lead?"},
            {"Yes": 0.90, "No": 0.10},
            {"Yes": 0.45, "No": 0.55},
        )
        assert result["verified"] is False
        assert any("> 1.1" in r for r in result["reasons"])

    def test_positive_conditional_unaffected(self):
        # conditional/positive has no provable-profit formula; the new
        # negative-only gates must not apply to it.
        result = verify_pair(
            "conditional",
            {"outcomes": ["Yes", "No"], "question": "Will A lead?"},
            {"outcomes": ["Yes", "No"], "question": "Will B lead?"},
            {"Yes": 0.55, "No": 0.45},
            {"Yes": 0.50, "No": 0.50},
            confidence=0.90,
            correlation="positive",
        )
        assert result["verified"] is True
