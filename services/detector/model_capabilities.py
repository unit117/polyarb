"""Declarative per-model capability registry for the LLM classifier.

Replaces the model-name substring checks that were scattered across
classifier.py and prompt_specs.py (kimi fixed-temperature/thinking mode,
MiniMax token budgets and temperature floor, Qwen/MiniMax JSON-mode gaps,
Claude prompt adapter) with one registry, overridable from the environment
via CLASSIFIER_MODEL_CAPABILITIES so a future provider quirk is a .env edit
on the NAS instead of a code hotfix — the drift pattern that produced the
kimi temperature-400 incident.

Override format (JSON object, pattern -> partial capability fields; a
pattern matches when it is a case-insensitive substring of the model name):

    CLASSIFIER_MODEL_CAPABILITIES={"kimi-k3": {"temperature_label": null,
        "extra_body": {"thinking": {"type": "disabled"}}}}

Overrides are applied on top of the built-in resolution, in insertion order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace

import structlog

from shared.config import settings

logger = structlog.get_logger()


@dataclass(frozen=True)
class ModelCapabilities:
    temperature_label: float | None = 0.1  # None = omit the param entirely
    temperature_vector: float | None = 0.0
    max_tokens_label: int = 256
    max_tokens_vector: int = 512
    supports_json_response_format: bool = True
    extra_body: dict | None = None
    prompt_adapter: str = "openai_generic"


DEFAULT_CAPS = ModelCapabilities()
_FIELD_NAMES = {f.name for f in fields(ModelCapabilities)}
# Expected value types per field for .env override validation; None is
# allowed where the default is Optional. Kept in sync with the dataclass.
_FIELD_TYPES: dict[str, tuple] = {
    "temperature_label": (float, int, type(None)),
    "temperature_vector": (float, int, type(None)),
    "max_tokens_label": (int,),
    "max_tokens_vector": (int,),
    "supports_json_response_format": (bool,),
    "extra_body": (dict, type(None)),
    "prompt_adapter": (str,),
}
_VALID_PROMPT_ADAPTERS = {"openai_generic", "claude_xml"}


def _validate_override(pattern: str, override: dict) -> dict:
    """Drop mistyped/invalid override fields with a warning."""
    clean = {}
    for k, v in override.items():
        if k not in _FIELD_NAMES:
            logger.warning(
                "classifier_capabilities_unknown_field", pattern=pattern, field=k
            )
            continue
        if not isinstance(v, _FIELD_TYPES[k]) or (
            k.startswith("max_tokens") and isinstance(v, bool)
        ):
            logger.warning(
                "classifier_capabilities_bad_type",
                pattern=pattern,
                field=k,
                value=repr(v)[:80],
            )
            continue
        if k == "prompt_adapter" and v not in _VALID_PROMPT_ADAPTERS:
            logger.warning(
                "classifier_capabilities_bad_adapter", pattern=pattern, value=v
            )
            continue
        clean[k] = v
    return clean


def is_kimi_fixed_param_model(model: str) -> bool:
    """Kimi k2.5/k2.6 served directly by Moonshot.

    These models pin ``temperature`` to a fixed per-mode value and reject any
    custom value ("invalid temperature: only 1 is allowed for this model"),
    so temperature must be omitted. They also default to a ``thinking``
    reasoning mode that can exhaust the classifier's small token budget.
    OpenRouter-style IDs ('moonshotai/kimi-k2.6') carry a slash and use the
    generic OpenAI-compatible path instead.
    """
    m = model.lower()
    if "/" in m:
        return False
    return m.startswith("kimi-k2.5") or m.startswith("kimi-k2.6") or m == "kimi-latest"


def _builtin_capabilities(model: str) -> ModelCapabilities:
    m = model.lower()
    if is_kimi_fixed_param_model(m):
        return ModelCapabilities(
            temperature_label=None,
            temperature_vector=None,
            extra_body={"thinking": {"type": "disabled"}},
        )
    if "minimax" in m:
        # M2.7's mandatory <think> block needs token budget; rejects temp 0.0;
        # response_format={"type": "json_object"} unsupported.
        return ModelCapabilities(
            temperature_vector=0.01,
            max_tokens_label=1024,
            max_tokens_vector=2048,
            supports_json_response_format=False,
        )
    if "qwen" in m:
        # DashScope Qwen exposes an OpenAI-compatible endpoint without full
        # JSON-mode support; prompt-only JSON discipline.
        return ModelCapabilities(supports_json_response_format=False)
    if "claude" in m or "anthropic" in m:
        return ModelCapabilities(prompt_adapter="claude_xml")
    return DEFAULT_CAPS


def _env_overrides() -> dict[str, dict]:
    raw = (getattr(settings, "classifier_model_capabilities", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("must be a JSON object of pattern -> fields")
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("classifier_capabilities_override_invalid", error=str(exc))
        return {}


def resolve_capabilities(model: str) -> ModelCapabilities:
    """Built-in capabilities for the model, with .env overrides applied."""
    caps = _builtin_capabilities(model)
    m = model.lower()
    for pattern, override in _env_overrides().items():
        if pattern.lower() in m and isinstance(override, dict):
            clean = _validate_override(pattern, override)
            if clean:
                caps = replace(caps, **clean)
    return caps
