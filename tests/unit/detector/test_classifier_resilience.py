"""Tests for the Phase-3 classifier robustness work: bounded transient-only
retries, error tagging (never cache failures), the provider-capability
registry, and the label-path conditional/positive downgrade."""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest

import services.detector.classifier as classifier
from services.detector.classifier import classify_llm, classify_pair
from services.detector.model_capabilities import (
    ModelCapabilities,
    resolve_capabilities,
)
from services.detector.pipeline import _build_cache_row
from shared.config import settings


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(classifier, "_RETRY_BACKOFF", (0.0, 0.0))


def _response(content: str):
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def _status_error(cls, status: int, message: str = "err"):
    req = httpx.Request("POST", "http://test/v1/chat/completions")
    resp = httpx.Response(status, request=req)
    return cls(message, response=resp, body=None)


GOOD_JSON = '{"dependency_type": "implication", "confidence": 0.9, "correlation": "positive", "reasoning": "ok"}'


class TestTransientRetry:
    @pytest.mark.asyncio
    async def test_rate_limit_retried_then_succeeds(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[
                _status_error(openai.RateLimitError, 429),
                _response(GOOD_JSON),
            ]
        )
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "implication"
        assert "classification_error" not in result
        assert client.chat.completions.create.await_count == 2

    @pytest.mark.asyncio
    async def test_5xx_retried_until_exhausted_then_tagged(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            side_effect=_status_error(openai.InternalServerError, 503)
        )
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "none"
        assert result["classification_error"] is True
        assert client.chat.completions.create.await_count == 3  # 1 + 2 retries

    @pytest.mark.asyncio
    async def test_permanent_400_not_retried(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            side_effect=_status_error(openai.BadRequestError, 400, "invalid temperature")
        )
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["classification_error"] is True
        assert client.chat.completions.create.await_count == 1

    @pytest.mark.asyncio
    async def test_vector_api_failure_skips_label_fallback(self):
        # Provider down: the vector path must return an error-tagged verdict
        # and classify_pair must NOT fire more doomed calls at the label path.
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            side_effect=_status_error(openai.InternalServerError, 502)
        )
        result = await classify_pair(
            client,
            "gpt-4o-mini",
            {"id": 1, "question": "A", "outcomes": ["Yes", "No"]},
            {"id": 2, "question": "B", "outcomes": ["Yes", "No"]},
        )
        assert result["classification_error"] is True
        assert result["classification_source"] == "llm_vector"
        # 3 attempts for the vector call only — no label-path calls after
        assert client.chat.completions.create.await_count == 3


class TestErrorResultsNeverCached:
    def _row(self, classification):
        return _build_cache_row(
            {"id": 1, "question": "A"},
            {"id": 2, "question": "B"},
            classification,
            classifier_model="m",
            prompt_adapter="auto",
        )

    def test_error_tagged_result_not_cached(self):
        row = self._row(
            {
                "dependency_type": "none",
                "confidence": 0.0,
                "classification_source": "llm_label",
                "classification_error": True,
            }
        )
        assert row is None

    def test_genuine_none_verdict_still_cached(self):
        row = self._row(
            {
                "dependency_type": "none",
                "confidence": 0.55,
                "classification_source": "llm_label",
            }
        )
        assert row is not None


class TestConditionalPositiveDowngrade:
    @pytest.mark.asyncio
    async def test_label_path_conditional_positive_downgraded(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_response(
                '{"dependency_type": "conditional", "confidence": 0.9, "correlation": "positive", "reasoning": "r"}'
            )
        )
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "none"
        assert result["confidence"] == 0.0
        # A downgrade is a legitimate verdict, not an error — cacheable
        assert "classification_error" not in result

    @pytest.mark.asyncio
    async def test_conditional_negative_kept(self):
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_response(
                '{"dependency_type": "conditional", "confidence": 0.9, "correlation": "negative", "reasoning": "r"}'
            )
        )
        result = await classify_llm(client, "gpt-4o-mini", {"question": "A"}, {"question": "B"})
        assert result["dependency_type"] == "conditional"
        assert result["correlation"] == "negative"


class TestCapabilityRegistry:
    def test_kimi_direct(self):
        caps = resolve_capabilities("kimi-k2.6")
        assert caps.temperature_label is None
        assert caps.temperature_vector is None
        assert caps.extra_body == {"thinking": {"type": "disabled"}}
        assert caps.supports_json_response_format is True

    def test_openrouter_kimi_uses_default(self):
        caps = resolve_capabilities("moonshotai/kimi-k2.6")
        assert caps.temperature_label == 0.1
        assert caps.extra_body is None

    def test_minimax(self):
        caps = resolve_capabilities("minimax/minimax-m2.7")
        assert caps.max_tokens_label == 1024
        assert caps.max_tokens_vector == 2048
        assert caps.temperature_vector == 0.01
        assert caps.supports_json_response_format is False

    def test_qwen(self):
        assert resolve_capabilities("qwen-max").supports_json_response_format is False

    def test_claude_adapter(self):
        assert resolve_capabilities("claude-sonnet-5").prompt_adapter == "claude_xml"

    def test_default(self):
        assert resolve_capabilities("gpt-4.1-mini") == ModelCapabilities()

    def test_env_override_merges_over_builtin(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "classifier_model_capabilities",
            json.dumps({"kimi-k3": {"temperature_label": None, "max_tokens_label": 512}}),
        )
        caps = resolve_capabilities("kimi-k3-turbo")
        assert caps.temperature_label is None
        assert caps.max_tokens_label == 512
        # untouched fields keep their (default) values
        assert caps.supports_json_response_format is True

    def test_env_override_invalid_json_ignored(self, monkeypatch):
        monkeypatch.setattr(settings, "classifier_model_capabilities", "{not json")
        assert resolve_capabilities("gpt-4.1-mini") == ModelCapabilities()

    def test_env_override_unknown_fields_dropped(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "classifier_model_capabilities",
            json.dumps({"gpt": {"bogus_field": 1, "max_tokens_label": 300}}),
        )
        caps = resolve_capabilities("gpt-4.1-mini")
        assert caps.max_tokens_label == 300
