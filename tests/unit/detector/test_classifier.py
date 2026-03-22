"""Tests for classifier heuristic rules."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock

import openai

from services.detector.classifier import (
    _check_same_event,
    _check_outcome_subset,
    _check_crypto_time_intervals,
    _check_price_threshold_markets,
    _check_ranking_markets,
    _check_over_under_markets,
    _check_milestone_threshold_markets,
    _derive_dependency_type,
    _strip_think_tags,
    classify_rule_based,
    classify_llm,
    classify_llm_resolution,
    classify_pair,
)


class TestCheckSameEvent:
    def test_same_event_id_with_overlapping_outcomes(self):
        """Same event_id + multi-outcome overlap → partition."""
        a = {"event_id": "evt_123", "outcomes": ["Alice", "Bob", "Charlie"]}
        b = {"event_id": "evt_123", "outcomes": ["Alice", "Bob", "Dave"]}
        result = _check_same_event(a, b)
        assert result is not None
        assert result["dependency_type"] == "partition"
        assert result["confidence"] == 0.95

    def test_same_event_id_binary_returns_none(self):
        """Same event_id but binary markets (Yes/No) — not enough evidence for partition."""
        a = {"event_id": "evt_123", "outcomes": ["Yes", "No"]}
        b = {"event_id": "evt_123", "outcomes": ["Yes", "No"]}
        assert _check_same_event(a, b) is None

    def test_same_event_id_no_outcome_overlap(self):
        """Same event_id but no outcome overlap → None (let LLM decide)."""
        a = {"event_id": "evt_123", "outcomes": ["Alice", "Bob", "Charlie"]}
        b = {"event_id": "evt_123", "outcomes": ["Dave", "Eve", "Frank"]}
        assert _check_same_event(a, b) is None

    def test_different_event_id(self):
        a = {"event_id": "evt_123"}
        b = {"event_id": "evt_456"}
        assert _check_same_event(a, b) is None

    def test_missing_event_id(self):
        a = {"event_id": None}
        b = {"event_id": "evt_123"}
        assert _check_same_event(a, b) is None

    def test_both_empty(self):
        assert _check_same_event({}, {}) is None


class TestCheckOutcomeSubset:
    def test_overlapping_multi_outcome(self):
        # overlap {Alice, Bob, Charlie} is a full subset of a's outcomes
        a = {"outcomes": ["Alice", "Bob", "Charlie"]}
        b = {"outcomes": ["Alice", "Bob", "Charlie", "Dave"]}
        result = _check_outcome_subset(a, b)
        assert result is not None
        assert result["dependency_type"] == "partition"

    def test_binary_markets_skip(self):
        a = {"outcomes": ["Yes", "No"]}
        b = {"outcomes": ["Yes", "No"]}
        assert _check_outcome_subset(a, b) is None

    def test_no_overlap(self):
        a = {"outcomes": ["Alice", "Bob", "Charlie"]}
        b = {"outcomes": ["Dave", "Eve", "Frank"]}
        assert _check_outcome_subset(a, b) is None


class TestCryptoTimeIntervals:
    def test_same_asset_same_window_me(self):
        a = {"question": "Bitcoin Up or Down — March 21, 3:15AM-3:30AM ET"}
        b = {"question": "Bitcoin Up or Down — March 21, 3:15AM-3:30AM ET"}
        result = _check_crypto_time_intervals(a, b)
        assert result is not None
        assert result["dependency_type"] == "mutual_exclusion"

    def test_same_asset_different_window_independent(self):
        a = {"question": "Bitcoin Up or Down — March 21, 3:15AM-3:30AM ET"}
        b = {"question": "Bitcoin Up or Down — March 21, 3:30AM-3:45AM ET"}
        result = _check_crypto_time_intervals(a, b)
        assert result is not None
        assert result["dependency_type"] == "none"

    def test_different_assets_none(self):
        a = {"question": "Bitcoin Up or Down — March 21, 3:15AM-3:30AM ET"}
        b = {"question": "Ethereum Up or Down — March 21, 3:15AM-3:30AM ET"}
        assert _check_crypto_time_intervals(a, b) is None

    def test_hourly_format(self):
        a = {"question": "HYPE Up or Down — March 21, 10PM ET"}
        b = {"question": "HYPE Up or Down — March 21, 10PM ET"}
        result = _check_crypto_time_intervals(a, b)
        assert result is not None
        assert result["dependency_type"] == "mutual_exclusion"

    def test_non_matching_question(self):
        a = {"question": "Will Bitcoin reach 100k?"}
        b = {"question": "Will Ethereum reach 5k?"}
        assert _check_crypto_time_intervals(a, b) is None


class TestPriceThresholdMarkets:
    def test_implication_above(self):
        a = {"question": "PLTR above $128 on March 21?"}
        b = {"question": "PLTR above $134 on March 21?"}
        result = _check_price_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"

    def test_different_assets_none(self):
        a = {"question": "PLTR above $128 on March 21?"}
        b = {"question": "AAPL above $134 on March 21?"}
        assert _check_price_threshold_markets(a, b) is None

    def test_different_time_windows_independent(self):
        a = {"question": "BTC above $90,000 — March 21, 3:15AM-3:30AM ET"}
        b = {"question": "BTC above $90,000 — March 21, 3:30AM-3:45AM ET"}
        result = _check_price_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "none"

    def test_same_threshold_returns_none(self):
        a = {"question": "PLTR above $128 on March 21?"}
        b = {"question": "PLTR above $128 on March 21?"}
        assert _check_price_threshold_markets(a, b) is None

    def test_comma_in_price(self):
        a = {"question": "BTC above $90,000 on March 21?"}
        b = {"question": "BTC above $95,000 on March 21?"}
        result = _check_price_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"


class TestRankingMarkets:
    def test_top_n_implication(self):
        a = {"question": "Will Tiger Woods finish Top 10 at the Masters?"}
        b = {"question": "Will Tiger Woods finish Top 20 at the Masters?"}
        result = _check_ranking_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"

    def test_different_subjects(self):
        a = {"question": "Will Tiger Woods finish Top 10 at the Masters?"}
        b = {"question": "Will Rory McIlroy finish Top 10 at the Masters?"}
        assert _check_ranking_markets(a, b) is None

    def test_same_ranking(self):
        a = {"question": "Will Tiger Woods finish Top 10 at the Masters?"}
        b = {"question": "Will Tiger Woods finish Top 10 at the Masters?"}
        assert _check_ranking_markets(a, b) is None


class TestOverUnderMarkets:
    def test_nested_lines_implication(self):
        a = {"question": "Manchester City vs Liverpool O/U 1.5 goals"}
        b = {"question": "Manchester City vs Liverpool O/U 2.5 goals"}
        result = _check_over_under_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"

    def test_same_line_none(self):
        a = {"question": "Game X O/U 2.5 goals"}
        b = {"question": "Game X O/U 2.5 goals"}
        assert _check_over_under_markets(a, b) is None

    def test_different_matches(self):
        a = {"question": "Game A O/U 2.5 goals"}
        b = {"question": "Game B O/U 2.5 goals"}
        assert _check_over_under_markets(a, b) is None

    def test_no_ou_pattern_returns_none(self):
        a = {"question": "Will the match end in a draw?"}
        b = {"question": "Will Player X score a hat trick?"}
        assert _check_over_under_markets(a, b) is None

    def test_different_subjects_different_lines_returns_none(self):
        a = {"question": "Game A O/U 2.5 goals"}
        b = {"question": "Game B O/U 3.5 goals"}
        assert _check_over_under_markets(a, b) is None


class TestPriceThresholdExtra:
    def test_no_price_pattern_returns_none(self):
        a = {"question": "Will the Fed cut rates?"}
        b = {"question": "Will the economy grow?"}
        assert _check_price_threshold_markets(a, b) is None

    def test_above_vs_below_direction_returns_none(self):
        a = {"question": "PLTR above $128 on March 21?"}
        b = {"question": "PLTR below $134 on March 21?"}
        assert _check_price_threshold_markets(a, b) is None

    def test_below_thresholds_implication(self):
        a = {"question": "PLTR below $128 on March 21?"}
        b = {"question": "PLTR below $134 on March 21?"}
        result = _check_price_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"


class TestRankingMarketsExtra:
    def test_no_ranking_pattern_returns_none(self):
        a = {"question": "Will Team A win?"}
        b = {"question": "Will Team B win?"}
        assert _check_ranking_markets(a, b) is None

    def test_different_subjects_different_ranks_returns_none(self):
        a = {"question": "Will Tiger Woods finish Top 10 at the Masters?"}
        b = {"question": "Will Rory McIlroy finish Top 20 at the Masters?"}
        assert _check_ranking_markets(a, b) is None


class TestClassifyRuleBased:
    @pytest.mark.asyncio
    async def test_returns_none_for_unrelated_markets(self):
        a = {"question": "Will Team A win the championship?"}
        b = {"question": "Will it rain in London on Tuesday?"}
        result = await classify_rule_based(a, b)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_partition_for_same_event_with_overlapping_outcomes(self):
        a = {"event_id": "evt_abc", "question": "Will A win?", "outcomes": ["Alice", "Bob", "Charlie"]}
        b = {"event_id": "evt_abc", "question": "Will B win?", "outcomes": ["Alice", "Bob", "Dave"]}
        result = await classify_rule_based(a, b)
        assert result is not None
        assert result["dependency_type"] == "partition"

    @pytest.mark.asyncio
    async def test_returns_implication_for_price_thresholds(self):
        a = {"question": "BTC above $90,000 on April 1?"}
        b = {"question": "BTC above $95,000 on April 1?"}
        result = await classify_rule_based(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"


def _make_llm_response(content: str):
    response = MagicMock()
    response.choices[0].message.content = content
    return response


class TestClassifyLLM:
    @pytest.mark.asyncio
    async def test_valid_implication_response(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_llm_response(
            '{"dependency_type": "implication", "confidence": 0.85, "correlation": "positive", "reasoning": "A implies B"}'
        ))
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "implication"
        # LLM confidence gets 0.80x discount: 0.85 * 0.80 = 0.68
        assert result["confidence"] == pytest.approx(0.68, abs=0.01)

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none_type(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_llm_response("not valid json"))
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "none"
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_invalid_dependency_type_returns_none(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_llm_response(
            '{"dependency_type": "banana", "confidence": 0.9, "reasoning": "weird"}'
        ))
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "none"

    @pytest.mark.asyncio
    async def test_conditional_missing_correlation_downgraded(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_llm_response(
            '{"dependency_type": "conditional", "confidence": 0.8, "correlation": null, "reasoning": "related"}'
        ))
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "none"
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_api_error_returns_none_type(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=openai.APIConnectionError(request=MagicMock()))
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "none"
        assert result["confidence"] == 0.0


class TestClassifyPair:
    @pytest.mark.asyncio
    async def test_rule_based_shortcircuits_llm(self):
        client = AsyncMock()
        a = {"event_id": "evt1", "question": "A wins?", "outcomes": ["Alice", "Bob", "Charlie"]}
        b = {"event_id": "evt1", "question": "B wins?", "outcomes": ["Alice", "Bob", "Dave"]}
        result = await classify_pair(client, "gpt-4o-mini", a, b)
        assert result["dependency_type"] == "partition"
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_llm_when_no_rule(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_llm_response(
            '{"dependency_type": "none", "confidence": 0.6, "reasoning": "unrelated"}'
        ))
        a = {"question": "Will Team A win the championship?"}
        b = {"question": "Will it rain in London on Tuesday?"}
        result = await classify_pair(client, "gpt-4o-mini", a, b)
        assert result["dependency_type"] == "none"
        # Now called twice: resolution vectors (fails on this mock) + label fallback
        assert client.chat.completions.create.call_count == 2


class TestCryptoTimeIntervalsDateBranch:
    def test_same_asset_different_dates_returns_none_type(self):
        # Same asset + same window but different calendar dates → independent
        a = {"question": "Bitcoin Up or Down — March 21, 3:15AM-3:30AM ET"}
        b = {"question": "Bitcoin Up or Down — March 22, 3:15AM-3:30AM ET"}
        result = _check_crypto_time_intervals(a, b)
        assert result is not None
        assert result["dependency_type"] == "none"
        assert "independent" in result["reasoning"]


class TestPriceThresholdDateBranch:
    def test_same_asset_different_dates_returns_none_type(self):
        # Same asset + different calendar dates → independent
        a = {"question": "PLTR above $128 on March 21?"}
        b = {"question": "PLTR above $134 on March 22?"}
        result = _check_price_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "none"


class TestMilestoneThresholdMarkets:
    def test_nested_above_thresholds_implication(self):
        a = {"question": "YouTube subscribers above 475 million"}
        b = {"question": "YouTube subscribers above 480 million"}
        result = _check_milestone_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"
        assert result["correlation"] == "positive"

    def test_same_threshold_returns_none(self):
        a = {"question": "YouTube subscribers above 475 million"}
        b = {"question": "YouTube subscribers above 475 million"}
        assert _check_milestone_threshold_markets(a, b) is None

    def test_different_subjects_returns_none(self):
        a = {"question": "YouTube subscribers above 475 million"}
        b = {"question": "TikTok followers above 480 million"}
        assert _check_milestone_threshold_markets(a, b) is None

    def test_no_milestone_pattern_returns_none(self):
        a = {"question": "Will it rain tomorrow?"}
        b = {"question": "Will the sun rise?"}
        assert _check_milestone_threshold_markets(a, b) is None

    def test_nested_below_thresholds_implication(self):
        a = {"question": "TikTok followers below 200 million"}
        b = {"question": "TikTok followers below 300 million"}
        result = _check_milestone_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"

    def test_mixed_direction_returns_none(self):
        # One above, one below → no implication
        a = {"question": "YouTube subscribers above 475 million"}
        b = {"question": "YouTube subscribers below 480 million"}
        assert _check_milestone_threshold_markets(a, b) is None

    def test_different_dates_returns_none_type(self):
        a = {"question": "YouTube subscribers above 475 million by March 21"}
        b = {"question": "YouTube subscribers above 480 million by March 22"}
        result = _check_milestone_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "none"

    def test_billion_multiplier(self):
        a = {"question": "Global population above 8 billion"}
        b = {"question": "Global population above 9 billion"}
        result = _check_milestone_threshold_markets(a, b)
        assert result is not None
        assert result["dependency_type"] == "implication"


class TestImplicationDirection:
    """Verify all implication classifiers emit correct direction."""

    def test_price_threshold_above_a_higher(self):
        # A=$134 > B=$128 → above $134 implies above $128 → a_implies_b
        a = {"question": "PLTR above $134 on March 21?"}
        b = {"question": "PLTR above $128 on March 21?"}
        result = _check_price_threshold_markets(a, b)
        assert result["implication_direction"] == "a_implies_b"

    def test_price_threshold_above_b_higher(self):
        # A=$128 < B=$134 → above $134 implies above $128 → b_implies_a
        a = {"question": "PLTR above $128 on March 21?"}
        b = {"question": "PLTR above $134 on March 21?"}
        result = _check_price_threshold_markets(a, b)
        assert result["implication_direction"] == "b_implies_a"

    def test_price_threshold_below_a_lower(self):
        # A=$128 < B=$134 → below $128 implies below $134 → a_implies_b
        a = {"question": "PLTR below $128 on March 21?"}
        b = {"question": "PLTR below $134 on March 21?"}
        result = _check_price_threshold_markets(a, b)
        assert result["implication_direction"] == "a_implies_b"

    def test_price_threshold_below_b_lower(self):
        # A=$134 > B=$128 → below $128 implies below $134 → b_implies_a
        a = {"question": "PLTR below $134 on March 21?"}
        b = {"question": "PLTR below $128 on March 21?"}
        result = _check_price_threshold_markets(a, b)
        assert result["implication_direction"] == "b_implies_a"

    def test_milestone_above_a_higher(self):
        a = {"question": "YouTube subscribers above 480 million"}
        b = {"question": "YouTube subscribers above 475 million"}
        result = _check_milestone_threshold_markets(a, b)
        assert result["implication_direction"] == "a_implies_b"

    def test_milestone_above_b_higher(self):
        a = {"question": "YouTube subscribers above 475 million"}
        b = {"question": "YouTube subscribers above 480 million"}
        result = _check_milestone_threshold_markets(a, b)
        assert result["implication_direction"] == "b_implies_a"

    def test_ranking_a_smaller(self):
        # Top 10 implies Top 20 → a is antecedent → a_implies_b
        a = {"question": "Will Tiger Woods finish Top 10 at the Masters?"}
        b = {"question": "Will Tiger Woods finish Top 20 at the Masters?"}
        result = _check_ranking_markets(a, b)
        assert result["implication_direction"] == "a_implies_b"

    def test_ranking_b_smaller(self):
        a = {"question": "Will Tiger Woods finish Top 20 at the Masters?"}
        b = {"question": "Will Tiger Woods finish Top 10 at the Masters?"}
        result = _check_ranking_markets(a, b)
        assert result["implication_direction"] == "b_implies_a"

    def test_over_under_a_higher(self):
        # Over 2.5 implies Over 1.5 → a has higher line → a_implies_b
        a = {"question": "Manchester City vs Liverpool O/U 2.5 goals"}
        b = {"question": "Manchester City vs Liverpool O/U 1.5 goals"}
        result = _check_over_under_markets(a, b)
        assert result["implication_direction"] == "a_implies_b"

    def test_over_under_b_higher(self):
        a = {"question": "Manchester City vs Liverpool O/U 1.5 goals"}
        b = {"question": "Manchester City vs Liverpool O/U 2.5 goals"}
        result = _check_over_under_markets(a, b)
        assert result["implication_direction"] == "b_implies_a"


class TestPairOrderInvariant:
    """classify(A,B) and classify(B,A) must produce logically equivalent constraint matrices."""

    def _get_constraint_matrix(self, classification: dict, outcomes_a, outcomes_b):
        from services.detector.constraints import build_constraint_matrix
        return build_constraint_matrix(
            classification["dependency_type"],
            outcomes_a, outcomes_b,
            prices_a={"Yes": 0.5, "No": 0.5},
            prices_b={"Yes": 0.5, "No": 0.5},
            implication_direction=classification.get("implication_direction"),
        )["matrix"]

    def test_price_threshold_order_invariant(self):
        a = {"question": "PLTR above $128 on March 21?"}
        b = {"question": "PLTR above $134 on March 21?"}
        outcomes = ["Yes", "No"]

        r_ab = _check_price_threshold_markets(a, b)
        r_ba = _check_price_threshold_markets(b, a)

        m_ab = self._get_constraint_matrix(r_ab, outcomes, outcomes)
        m_ba = self._get_constraint_matrix(r_ba, outcomes, outcomes)

        # Matrices should be transposes of each other (swapping A↔B)
        for i in range(2):
            for j in range(2):
                assert m_ab[i][j] == m_ba[j][i], (
                    f"Matrix not order-invariant at [{i}][{j}]: "
                    f"m_ab={m_ab}, m_ba={m_ba}"
                )

    def test_ranking_order_invariant(self):
        a = {"question": "Will Tiger Woods finish Top 10 at the Masters?"}
        b = {"question": "Will Tiger Woods finish Top 20 at the Masters?"}
        outcomes = ["Yes", "No"]

        r_ab = _check_ranking_markets(a, b)
        r_ba = _check_ranking_markets(b, a)

        m_ab = self._get_constraint_matrix(r_ab, outcomes, outcomes)
        m_ba = self._get_constraint_matrix(r_ba, outcomes, outcomes)

        for i in range(2):
            for j in range(2):
                assert m_ab[i][j] == m_ba[j][i]

    def test_over_under_order_invariant(self):
        a = {"question": "Game X O/U 1.5 goals"}
        b = {"question": "Game X O/U 2.5 goals"}
        outcomes = ["Yes", "No"]

        r_ab = _check_over_under_markets(a, b)
        r_ba = _check_over_under_markets(b, a)

        m_ab = self._get_constraint_matrix(r_ab, outcomes, outcomes)
        m_ba = self._get_constraint_matrix(r_ba, outcomes, outcomes)

        for i in range(2):
            for j in range(2):
                assert m_ab[i][j] == m_ba[j][i]

    def test_milestone_order_invariant(self):
        a = {"question": "YouTube subscribers above 475 million"}
        b = {"question": "YouTube subscribers above 480 million"}
        outcomes = ["Yes", "No"]

        r_ab = _check_milestone_threshold_markets(a, b)
        r_ba = _check_milestone_threshold_markets(b, a)

        m_ab = self._get_constraint_matrix(r_ab, outcomes, outcomes)
        m_ba = self._get_constraint_matrix(r_ba, outcomes, outcomes)

        for i in range(2):
            for j in range(2):
                assert m_ab[i][j] == m_ba[j][i]


class TestStripThinkTags:
    def test_strips_think_block(self):
        raw = '<think>Let me reason about this...</think>{"valid_outcomes": []}'
        assert _strip_think_tags(raw) == '{"valid_outcomes": []}'

    def test_no_think_tags_extracts_json(self):
        raw = 'Some preamble {"valid_outcomes": []} trailing'
        assert _strip_think_tags(raw) == '{"valid_outcomes": []}'

    def test_pure_json_unchanged(self):
        raw = '{"valid_outcomes": [{"a": "Yes", "b": "No"}]}'
        assert _strip_think_tags(raw) == raw

    def test_think_with_json_inside(self):
        """JSON examples inside <think> should NOT be extracted."""
        raw = '<think>Like {"type": "partition"} but actually...</think>{"valid_outcomes": []}'
        result = _strip_think_tags(raw)
        assert result == '{"valid_outcomes": []}'


class TestDeriveType:
    """Test deterministic mapping from resolution vectors to dependency type."""

    def test_all_four_valid_is_none(self):
        vectors = [
            {"a": "Yes", "b": "Yes"}, {"a": "Yes", "b": "No"},
            {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
        ]
        result = _derive_dependency_type(vectors, ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "none"

    def test_missing_yy_is_mutual_exclusion(self):
        vectors = [
            {"a": "Yes", "b": "No"}, {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
        ]
        result = _derive_dependency_type(vectors, ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "mutual_exclusion"

    def test_missing_yn_is_a_implies_b(self):
        vectors = [
            {"a": "Yes", "b": "Yes"}, {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
        ]
        result = _derive_dependency_type(vectors, ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "implication"
        assert result["implication_direction"] == "a_implies_b"

    def test_missing_ny_is_b_implies_a(self):
        vectors = [
            {"a": "Yes", "b": "Yes"}, {"a": "Yes", "b": "No"}, {"a": "No", "b": "No"},
        ]
        result = _derive_dependency_type(vectors, ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "implication"
        assert result["implication_direction"] == "b_implies_a"

    def test_missing_nn_is_conditional_positive(self):
        vectors = [
            {"a": "Yes", "b": "Yes"}, {"a": "Yes", "b": "No"}, {"a": "No", "b": "Yes"},
        ]
        result = _derive_dependency_type(vectors, ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "conditional"
        assert result["correlation"] == "positive"

    def test_xor_is_partition(self):
        vectors = [{"a": "Yes", "b": "No"}, {"a": "No", "b": "Yes"}]
        result = _derive_dependency_type(vectors, ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "partition"

    def test_identity_is_cross_platform(self):
        vectors = [{"a": "Yes", "b": "Yes"}, {"a": "No", "b": "No"}]
        result = _derive_dependency_type(vectors, ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "cross_platform"

    def test_zero_combos_is_error(self):
        result = _derive_dependency_type([], ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "_error"

    def test_one_combo_is_error(self):
        vectors = [{"a": "Yes", "b": "Yes"}]
        result = _derive_dependency_type(vectors, ["Yes", "No"], ["Yes", "No"])
        assert result["dependency_type"] == "_error"


class TestClassifyLLMResolution:
    @pytest.mark.asyncio
    async def test_independent_markets(self):
        """All 4 combos valid → none."""
        response_json = json.dumps({
            "valid_outcomes": [
                {"a": "Yes", "b": "Yes"}, {"a": "Yes", "b": "No"},
                {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
            ],
            "reasoning": "Independent events",
            "confidence": 0.95,
        })
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_llm_response(response_json)
        )
        result = await classify_llm_resolution(
            client, "gpt-4.1-mini",
            {"question": "Will Lana attend?", "outcomes": ["Yes", "No"]},
            {"question": "Will Blake attend?", "outcomes": ["Yes", "No"]},
        )
        assert result is not None
        assert result["dependency_type"] == "none"
        assert result["classification_source"] == "llm_vector"

    @pytest.mark.asyncio
    async def test_mutual_exclusion(self):
        """Missing (Y,Y) → mutual_exclusion."""
        response_json = json.dumps({
            "valid_outcomes": [
                {"a": "Yes", "b": "No"}, {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
            ],
            "reasoning": "Cannot both win",
            "confidence": 0.90,
        })
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_llm_response(response_json)
        )
        result = await classify_llm_resolution(
            client, "gpt-4.1-mini",
            {"question": "Team A wins?", "outcomes": ["Yes", "No"]},
            {"question": "Team B wins?", "outcomes": ["Yes", "No"]},
        )
        assert result["dependency_type"] == "mutual_exclusion"
        assert result["confidence"] == 0.90

    @pytest.mark.asyncio
    async def test_non_binary_returns_none(self):
        """Resolution vectors only work for binary markets."""
        client = AsyncMock()
        result = await classify_llm_resolution(
            client, "gpt-4.1-mini",
            {"question": "Who wins?", "outcomes": ["A", "B", "C"]},
            {"question": "Who places?", "outcomes": ["X", "Y"]},
        )
        assert result is None
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_llm_response("not valid json at all")
        )
        result = await classify_llm_resolution(
            client, "gpt-4.1-mini",
            {"question": "A?", "outcomes": ["Yes", "No"]},
            {"question": "B?", "outcomes": ["Yes", "No"]},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_think_tags_stripped(self):
        """MiniMax M2.7 wraps response in <think> tags."""
        inner = json.dumps({
            "valid_outcomes": [
                {"a": "Yes", "b": "Yes"}, {"a": "Yes", "b": "No"},
                {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
            ],
            "reasoning": "Independent",
            "confidence": 0.90,
        })
        raw = f"<think>Let me think about this carefully.</think>{inner}"
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_llm_response(raw)
        )
        result = await classify_llm_resolution(
            client, "minimax/minimax-m2.7",
            {"question": "A?", "outcomes": ["Yes", "No"]},
            {"question": "B?", "outcomes": ["Yes", "No"]},
        )
        assert result is not None
        assert result["dependency_type"] == "none"

    @pytest.mark.asyncio
    async def test_implication_with_direction(self):
        """Missing (Y,N) → a_implies_b."""
        response_json = json.dumps({
            "valid_outcomes": [
                {"a": "Yes", "b": "Yes"}, {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
            ],
            "reasoning": "Above 134 implies above 128",
            "confidence": 0.95,
        })
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_llm_response(response_json)
        )
        result = await classify_llm_resolution(
            client, "gpt-4.1-mini",
            {"question": "PLTR above $134?", "outcomes": ["Yes", "No"]},
            {"question": "PLTR above $128?", "outcomes": ["Yes", "No"]},
        )
        assert result["dependency_type"] == "implication"
        assert result["implication_direction"] == "a_implies_b"


class TestClassifyPairWithResolutionVectors:
    @pytest.mark.asyncio
    async def test_resolution_vectors_used_before_label_fallback(self):
        """When resolution vectors succeed, label-based LLM is not called."""
        vector_response = json.dumps({
            "valid_outcomes": [
                {"a": "Yes", "b": "Yes"}, {"a": "Yes", "b": "No"},
                {"a": "No", "b": "Yes"}, {"a": "No", "b": "No"},
            ],
            "reasoning": "Independent",
            "confidence": 0.90,
        })
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_llm_response(vector_response)
        )
        result = await classify_pair(
            client, "gpt-4.1-mini",
            {"question": "Will it rain?", "outcomes": ["Yes", "No"]},
            {"question": "Will it snow?", "outcomes": ["Yes", "No"]},
        )
        assert result["dependency_type"] == "none"
        assert result["classification_source"] == "llm_vector"
        # Only one API call (resolution vectors), not two
        assert client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_to_label_on_vector_failure(self):
        """When resolution vectors fail, falls back to label-based with capped confidence."""
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (resolution vectors) returns garbage
                return _make_llm_response("not json")
            else:
                # Second call (label-based) returns valid
                return _make_llm_response(json.dumps({
                    "dependency_type": "mutual_exclusion",
                    "confidence": 0.90,
                    "correlation": None,
                    "reasoning": "ME",
                }))

        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=mock_create)
        result = await classify_pair(
            client, "gpt-4.1-mini",
            {"question": "Team A wins?", "outcomes": ["Yes", "No"]},
            {"question": "Team B wins?", "outcomes": ["Yes", "No"]},
        )
        assert result["dependency_type"] == "mutual_exclusion"
        assert result["classification_source"] == "llm_label"
        # Fallback confidence capped at 0.70
        assert result["confidence"] <= 0.70
        assert call_count == 2
