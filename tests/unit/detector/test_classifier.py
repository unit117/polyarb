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
    classify_rule_based,
    classify_llm,
    classify_pair,
)


class TestCheckSameEvent:
    def test_same_event_id(self):
        a = {"event_id": "evt_123"}
        b = {"event_id": "evt_123"}
        result = _check_same_event(a, b)
        assert result is not None
        assert result["dependency_type"] == "partition"
        assert result["confidence"] == 0.95

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
    async def test_returns_partition_for_same_event(self):
        a = {"event_id": "evt_abc", "question": "Will A win?"}
        b = {"event_id": "evt_abc", "question": "Will B win?"}
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
        assert result["confidence"] == 0.85

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
        a = {"event_id": "evt1", "question": "A wins?"}
        b = {"event_id": "evt1", "question": "B wins?"}
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
        client.chat.completions.create.assert_called_once()


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
