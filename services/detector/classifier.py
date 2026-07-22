"""Dependency classifier: determines relationship type between market pairs.

Uses a two-stage approach:
1. Rule-based heuristics (same event, subset outcomes) — fast, high confidence
2. LLM classification for ambiguous cases — slower, moderate confidence
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Optional

import openai
import structlog

from services.detector.model_capabilities import (
    is_kimi_fixed_param_model,
    resolve_capabilities,
)
from services.detector.prompt_specs import (
    LABEL_PROMPT_SPEC_V1,
    RESOLUTION_VECTOR_PROMPT_SPEC_V1,
    render_prompt,
)

logger = structlog.get_logger()

DEPENDENCY_TYPES = ("implication", "partition", "mutual_exclusion", "conditional", "cross_platform")

# Bounded app-level retry for LLM calls. The AsyncOpenAI client is built with
# max_retries=0 and an explicit timeout (see services/detector/main.py) so
# this policy is the only retry layer — before it, every failure class fell
# straight through to a fail-closed "none" that got cached permanently.
_RETRY_BACKOFF = (1.0, 4.0)  # sleeps between the 3 attempts
# Retry-After is server-controlled; quota 429s can carry hours. Sleeping
# that long would hold the detection lock — beyond this cap, fail the call
# now (the error result is never cached, so the pair retries next cycle).
_MAX_RETRY_AFTER_SECONDS = 30.0


def _is_transient_llm_error(exc: Exception) -> bool:
    """Timeouts, connection drops, 429s, and 5xx are worth retrying; other
    API errors (400/401/403/404/422) are config breakage — retrying spams."""
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return True
    if isinstance(exc, openai.RateLimitError):
        return True
    status = getattr(exc, "status_code", None)
    return status is not None and status >= 500


def _retry_after_seconds(exc: Exception) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        val = headers.get("retry-after")
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


async def _create_with_retry(client: openai.AsyncOpenAI, kwargs: dict, *, call: str):
    """chat.completions.create with bounded retry on transient errors only."""
    attempts = len(_RETRY_BACKOFF) + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await client.chat.completions.create(**kwargs)
        except openai.APIError as exc:
            if not _is_transient_llm_error(exc):
                logger.error(
                    "llm_permanent_error",
                    call=call,
                    model=kwargs.get("model"),
                    status_code=getattr(exc, "status_code", None),
                    error=str(exc),
                )
                raise
            last_exc = exc
            if attempt == attempts - 1:
                break
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None and retry_after > _MAX_RETRY_AFTER_SECONDS:
                logger.warning(
                    "llm_retry_after_too_large",
                    call=call,
                    retry_after_seconds=retry_after,
                )
                break
            delay = min(
                max(_RETRY_BACKOFF[attempt], retry_after or 0.0),
                _MAX_RETRY_AFTER_SECONDS,
            )
            logger.warning(
                "llm_transient_error_retrying",
                call=call,
                attempt=attempt + 1,
                delay_seconds=delay,
                error=str(exc),
            )
            await asyncio.sleep(delay)
    logger.error(
        "llm_transient_retries_exhausted",
        call=call,
        model=kwargs.get("model"),
        attempts=attempts,
        error=str(last_exc),
    )
    raise last_exc


def _check_same_event(market_a: dict, market_b: dict) -> dict | None:
    """If two markets share the same event_id AND have overlapping outcomes,
    they likely form a partition.

    Polymarket's event_id groups markets by topic (e.g. "2024 US Election"),
    not by logical partition. Two markets in the same event can be completely
    independent, so we require outcome overlap as structural evidence.
    """
    if not (
        market_a.get("event_id")
        and market_b.get("event_id")
        and market_a["event_id"] == market_b["event_id"]
    ):
        return None

    # Require overlapping outcomes (beyond the trivial Yes/No)
    outcomes_a = set(market_a.get("outcomes", []))
    outcomes_b = set(market_b.get("outcomes", []))
    overlap = outcomes_a & outcomes_b

    # For multi-outcome markets, shared non-trivial outcomes indicate partition
    if len(outcomes_a) > 2 and len(outcomes_b) > 2 and len(overlap) >= 2:
        return {
            "dependency_type": "partition",
            "confidence": 0.95,
            "reasoning": f"Same event_id + overlapping outcomes {overlap} — partition",
        }

    # For binary markets (Yes/No), same event_id alone is not enough —
    # "Will X win state A?" and "Will Y win state B?" share an event but
    # are independent.  Demote to None and let LLM classify.
    return None


def _check_outcome_subset(market_a: dict, market_b: dict) -> dict | None:
    """Check if one market's outcomes are a subset of the other's."""
    outcomes_a = set(market_a.get("outcomes", []))
    outcomes_b = set(market_b.get("outcomes", []))

    if len(outcomes_a) > 2 and len(outcomes_b) > 2:
        overlap = outcomes_a & outcomes_b
        if len(overlap) >= 2 and (overlap == outcomes_a or overlap == outcomes_b):
            return {
                "dependency_type": "partition",
                "confidence": 0.85,
                "reasoning": f"Outcome overlap: {overlap}",
            }
    return None


# Extracts a calendar date like "March 21" from a question string.
_DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}",
    re.IGNORECASE,
)


def _extract_date(question: str) -> Optional[str]:
    """Extract a calendar date like 'March 21' from a question string.

    Returns a lowercased canonical form for comparison, or None if no date found.
    """
    m = _DATE_RE.search(question)
    return m.group(0).lower().replace(".", "") if m else None


# Matches "Bitcoin Up or Down — March 21, 3:15AM-3:30AM ET" style questions
# AND hourly format "HYPE Up or Down — March 21, 10PM ET".
# Captures: (asset, start_time, end_time_or_None)
_TIME_INTERVAL_RE = re.compile(
    r"^(.+?)\s+Up or Down\b.*?(\d{1,2}(?::\d{2})?[AP]M)\s*(?:-\s*(\d{1,2}(?::\d{2})?[AP]M))?",
    re.IGNORECASE,
)

# Matches price-threshold markets with optional $ and flexible timestamps:
#   "PLTR above $128 on March 21?"
#   "BTC above $90,000 — March 21, 3:15AM-3:30AM ET"
#   "Ethereum above 2,205 on March 21, 5AM ET"
# Captures: (asset, threshold, optional start_time, optional end_time)
_PRICE_THRESHOLD_RE = re.compile(
    r"^(.+?)\s+(?:above|below|over|under)\s+\$?([0-9,]+(?:\.\d+)?)"
    r"(?:.*?(\d{1,2}(?::\d{2})?[AP]M)\s*(?:-\s*(\d{1,2}(?::\d{2})?[AP]M))?)?",
    re.IGNORECASE,
)


def _check_crypto_time_intervals(market_a: dict, market_b: dict) -> dict | None:
    """Detect crypto time-interval markets on the same asset with different windows.

    Adjacent (non-overlapping) time windows are independent — the price can go up
    in both intervals. Only the *same* window would be mutual exclusion (up vs down).
    Handles both "Up or Down" and "above $X" patterns.
    """
    q_a = market_a.get("question", "")
    q_b = market_b.get("question", "")

    # Try "Up or Down" pattern first, then fall back to price-threshold pattern
    m_a_updown = _TIME_INTERVAL_RE.search(q_a)
    m_b_updown = _TIME_INTERVAL_RE.search(q_b)

    # Only use this function for "Up or Down" patterns; price-threshold pairs
    # are handled by _check_price_threshold_markets instead.
    if not m_a_updown or not m_b_updown:
        return None

    m_a, m_b = m_a_updown, m_b_updown

    asset_a, start_a = m_a.group(1).strip(), m_a.group(2)
    asset_b, start_b = m_b.group(1).strip(), m_b.group(2)
    # end_time is None for hourly format ("10PM ET")
    end_a = m_a.group(3) or start_a
    end_b = m_b.group(3) or start_b

    # Different assets — not the same pattern, let LLM decide
    if asset_a.lower() != asset_b.lower():
        return None

    # Different calendar dates → independent regardless of time window
    date_a = _extract_date(q_a)
    date_b = _extract_date(q_b)
    if date_a and date_b and date_a != date_b:
        return {
            "dependency_type": "none",
            "confidence": 0.95,
            "reasoning": (
                f"Same asset '{asset_a}', different dates ({date_a} vs {date_b}) "
                f"— independent events"
            ),
        }

    # Same asset, same time window → genuine mutual exclusion (up vs down)
    if start_a == start_b and end_a == end_b:
        window = f"{start_a}-{end_a}" if start_a != end_a else start_a
        return {
            "dependency_type": "mutual_exclusion",
            "confidence": 0.95,
            "reasoning": f"Same asset '{asset_a}', same time window {window} — up/down are mutually exclusive",
        }

    # Same asset, different time window → independent
    window_a = f"{start_a}-{end_a}" if start_a != end_a else start_a
    window_b = f"{start_b}-{end_b}" if start_b != end_b else start_b
    return {
        "dependency_type": "none",
        "confidence": 0.95,
        "reasoning": f"Same asset '{asset_a}', different time windows ({window_a} vs {window_b}) — independent events",
    }


def _check_price_threshold_markets(market_a: dict, market_b: dict) -> dict | None:
    """Detect price-threshold markets on the same asset.

    "PLTR above $128" and "PLTR above $134" form an implication chain:
    if the higher threshold resolves Yes, the lower threshold must also resolve Yes.

    If they have time intervals and the intervals differ, they are independent
    (same as crypto time-interval logic).
    """
    q_a = market_a.get("question", "")
    q_b = market_b.get("question", "")

    m_a = _PRICE_THRESHOLD_RE.search(q_a)
    m_b = _PRICE_THRESHOLD_RE.search(q_b)

    if not m_a or not m_b:
        return None

    asset_a = m_a.group(1).strip().lower()
    asset_b = m_b.group(1).strip().lower()

    # Different assets — not the same pattern
    if asset_a != asset_b:
        return None

    # Different calendar dates → independent regardless of threshold
    date_a = _extract_date(q_a)
    date_b = _extract_date(q_b)
    if date_a and date_b and date_a != date_b:
        return {
            "dependency_type": "none",
            "confidence": 0.95,
            "reasoning": (
                f"Same asset '{m_a.group(1).strip()}', different dates "
                f"({date_a} vs {date_b}) — independent events"
            ),
        }

    threshold_a = float(m_a.group(2).replace(",", ""))
    threshold_b = float(m_b.group(2).replace(",", ""))

    start_a = m_a.group(3)
    start_b = m_b.group(3)
    # end_time is None for single-timestamp format ("5AM ET")
    end_a = m_a.group(4) or start_a
    end_b = m_b.group(4) or start_b

    # Both have timestamps — check if same window
    if start_a and start_b:
        if start_a != start_b or end_a != end_b:
            # Different time windows → independent regardless of threshold
            window_a = f"{start_a}-{end_a}" if start_a != end_a else start_a
            window_b = f"{start_b}-{end_b}" if start_b != end_b else start_b
            return {
                "dependency_type": "none",
                "confidence": 0.95,
                "reasoning": (
                    f"Same asset '{m_a.group(1).strip()}', different time windows "
                    f"({window_a} vs {window_b}) — independent events"
                ),
            }

    # Same asset, same time window (or no time window) — compare thresholds
    if threshold_a == threshold_b:
        # Same threshold, same window — these are the same market
        return None

    # Different thresholds: higher "above" implies lower "above"
    # Detect direction from the question
    dir_a = "above" if re.search(r"\b(?:above|over)\b", q_a, re.IGNORECASE) else "below"
    dir_b = "above" if re.search(r"\b(?:above|over)\b", q_b, re.IGNORECASE) else "below"

    if dir_a != dir_b:
        # "above $128" vs "below $134" — not a simple implication, let LLM decide
        return None

    if dir_a == "above":
        higher = max(threshold_a, threshold_b)
        lower = min(threshold_a, threshold_b)
        # "above $higher" implies "above $lower" — the market with the higher
        # threshold is the antecedent.  If market_a has the higher threshold,
        # direction is a_implies_b; otherwise b_implies_a.
        direction = "a_implies_b" if threshold_a >= threshold_b else "b_implies_a"
        return {
            "dependency_type": "implication",
            "confidence": 0.95,
            "correlation": "positive",
            "implication_direction": direction,
            "reasoning": (
                f"'{m_a.group(1).strip()}' above ${higher} implies above ${lower} — "
                f"nested price thresholds form an implication chain"
            ),
        }
    else:  # below
        higher = max(threshold_a, threshold_b)
        lower = min(threshold_a, threshold_b)
        # "below $lower" implies "below $higher" — the market with the lower
        # threshold is the antecedent.
        direction = "a_implies_b" if threshold_a <= threshold_b else "b_implies_a"
        return {
            "dependency_type": "implication",
            "confidence": 0.95,
            "correlation": "positive",
            "implication_direction": direction,
            "reasoning": (
                f"'{m_a.group(1).strip()}' below ${lower} implies below ${higher} — "
                f"nested price thresholds form an implication chain"
            ),
        }


# Matches milestone/subscriber threshold markets:
#   "YouTube subscribers above 475 million"
#   "TikTok followers above 200M"
#   "Views exceed 1.5 billion"
# Captures: (subject, threshold, multiplier)
_MILESTONE_RE = re.compile(
    r"^(.+?)\s+(?:above|below|over|under|reach|hit|exceed)\s+"
    r"([0-9,]+(?:\.\d+)?)\s*"
    r"(million|billion|trillion|[MBT])\b",
    re.IGNORECASE,
)

_MULTIPLIER_MAP = {
    "million": 1_000_000, "m": 1_000_000,
    "billion": 1_000_000_000, "b": 1_000_000_000,
    "trillion": 1_000_000_000_000, "t": 1_000_000_000_000,
}


def _check_milestone_threshold_markets(market_a: dict, market_b: dict) -> dict | None:
    """Detect milestone/subscriber threshold markets forming implication chains.

    "YouTube subscribers above 475 million" and "above 477 million" form an
    implication chain identical to price thresholds: if subscribers exceed 477M,
    they necessarily also exceed 475M.
    """
    q_a = market_a.get("question", "")
    q_b = market_b.get("question", "")

    m_a = _MILESTONE_RE.search(q_a)
    m_b = _MILESTONE_RE.search(q_b)

    if not m_a or not m_b:
        return None

    subject_a = m_a.group(1).strip().lower()
    subject_b = m_b.group(1).strip().lower()

    if subject_a != subject_b:
        return None

    mult_a = _MULTIPLIER_MAP[m_a.group(3).lower()]
    mult_b = _MULTIPLIER_MAP[m_b.group(3).lower()]
    threshold_a = float(m_a.group(2).replace(",", "")) * mult_a
    threshold_b = float(m_b.group(2).replace(",", "")) * mult_b

    if threshold_a == threshold_b:
        return None

    # Different calendar dates → independent
    date_a = _extract_date(q_a)
    date_b = _extract_date(q_b)
    if date_a and date_b and date_a != date_b:
        return {
            "dependency_type": "none",
            "confidence": 0.95,
            "reasoning": (
                f"Same subject '{m_a.group(1).strip()}', different dates "
                f"({date_a} vs {date_b}) — independent events"
            ),
        }

    # Detect direction
    dir_a = "above" if re.search(r"\b(?:above|over|exceed|reach|hit)\b", q_a, re.IGNORECASE) else "below"
    dir_b = "above" if re.search(r"\b(?:above|over|exceed|reach|hit)\b", q_b, re.IGNORECASE) else "below"

    if dir_a != dir_b:
        return None

    higher = max(threshold_a, threshold_b)
    lower = min(threshold_a, threshold_b)

    # Format for readable output
    def _fmt(v: float) -> str:
        if v >= 1_000_000_000_000:
            return f"{v / 1_000_000_000_000:g}T"
        if v >= 1_000_000_000:
            return f"{v / 1_000_000_000:g}B"
        if v >= 1_000_000:
            return f"{v / 1_000_000:g}M"
        return f"{v:g}"

    if dir_a == "above":
        # "above higher" implies "above lower" — higher threshold is antecedent
        direction = "a_implies_b" if threshold_a >= threshold_b else "b_implies_a"
        return {
            "dependency_type": "implication",
            "confidence": 0.95,
            "correlation": "positive",
            "implication_direction": direction,
            "reasoning": (
                f"'{m_a.group(1).strip()}' above {_fmt(higher)} implies above {_fmt(lower)} — "
                f"nested milestone thresholds form an implication chain"
            ),
        }
    else:
        # "below lower" implies "below higher" — lower threshold is antecedent
        direction = "a_implies_b" if threshold_a <= threshold_b else "b_implies_a"
        return {
            "dependency_type": "implication",
            "confidence": 0.95,
            "correlation": "positive",
            "implication_direction": direction,
            "reasoning": (
                f"'{m_a.group(1).strip()}' below {_fmt(lower)} implies below {_fmt(higher)} — "
                f"nested milestone thresholds form an implication chain"
            ),
        }


_RANKING_RE = re.compile(
    r"(?:Top|Bottom)\s+(\d+)",
    re.IGNORECASE,
)


def _check_ranking_markets(market_a: dict, market_b: dict) -> dict | None:
    """Detect "Top N" vs "Top M" markets on the same event.

    Finishing Top 10 implies finishing Top 20 (N < M → implication).
    Only applies when both questions reference the same subject/event
    and differ only in the ranking cutoff.
    """
    q_a = market_a.get("question", "")
    q_b = market_b.get("question", "")

    m_a = _RANKING_RE.search(q_a)
    m_b = _RANKING_RE.search(q_b)

    if not m_a or not m_b:
        return None

    n_a = int(m_a.group(1))
    n_b = int(m_b.group(1))

    if n_a == n_b:
        return None

    # Strip the "Top N" portion and compare the rest to ensure same subject
    subject_a = _RANKING_RE.sub("", q_a).strip().lower()
    subject_b = _RANKING_RE.sub("", q_b).strip().lower()

    if subject_a != subject_b:
        return None

    smaller = min(n_a, n_b)
    larger = max(n_a, n_b)

    # "Top smaller" implies "Top larger" — market with smaller N is antecedent
    direction = "a_implies_b" if n_a <= n_b else "b_implies_a"
    return {
        "dependency_type": "implication",
        "confidence": 0.95,
        "correlation": "positive",
        "implication_direction": direction,
        "reasoning": (
            f"Top {smaller} implies Top {larger} — "
            f"ranking cutoffs form an implication chain"
        ),
    }


# Matches sports O/U lines: "O/U 2.5", "Over/Under 1.5", "O/U 190.5"
# Captures: (line_value,)
_OVER_UNDER_RE = re.compile(
    r"(?:O/U|Over/Under|Over Under)\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _check_over_under_markets(market_a: dict, market_b: dict) -> dict | None:
    """Detect sports Over/Under lines on the same match.

    O/U 1.5 and O/U 2.5 on the same match form an implication chain:
    if the total is over 2.5, it is necessarily over 1.5.
    Same line on same match = same market (no dependency to classify).
    """
    q_a = market_a.get("question", "")
    q_b = market_b.get("question", "")

    m_a = _OVER_UNDER_RE.search(q_a)
    m_b = _OVER_UNDER_RE.search(q_b)

    if not m_a or not m_b:
        return None

    line_a = float(m_a.group(1))
    line_b = float(m_b.group(1))

    if line_a == line_b:
        return None  # Same line — let other checks handle it

    # Strip the O/U portion and compare the rest to ensure same match
    subject_a = _OVER_UNDER_RE.sub("", q_a).strip().lower()
    subject_b = _OVER_UNDER_RE.sub("", q_b).strip().lower()

    if subject_a != subject_b:
        return None

    higher = max(line_a, line_b)
    lower = min(line_a, line_b)

    # "Over higher" implies "Over lower" — market with higher line is antecedent
    direction = "a_implies_b" if line_a >= line_b else "b_implies_a"
    return {
        "dependency_type": "implication",
        "confidence": 0.95,
        "correlation": "positive",
        "implication_direction": direction,
        "reasoning": (
            f"Over {lower} is implied by Over {higher} — "
            f"nested O/U lines form an implication chain"
        ),
    }


async def classify_rule_based(market_a: dict, market_b: dict) -> dict | None:
    """Apply rule-based heuristics. Returns result dict or None if ambiguous."""
    for check in (
        _check_same_event,
        _check_outcome_subset,
        _check_crypto_time_intervals,
        _check_milestone_threshold_markets,
        _check_price_threshold_markets,
        _check_ranking_markets,
        _check_over_under_markets,
    ):
        result = check(market_a, market_b)
        if result:
            logger.info(
                "rule_based_classification",
                dep_type=result["dependency_type"],
                confidence=result["confidence"],
            )
            return result
    return None


def _is_kimi_fixed_param_model(model: str) -> bool:
    """Back-compat wrapper — the truth lives in the capability registry."""
    return is_kimi_fixed_param_model(model)


async def classify_llm(
    client: openai.AsyncOpenAI,
    model: str,
    market_a: dict,
    market_b: dict,
    prompt_adapter: str = "auto",
) -> dict:
    """Use LLM to classify the dependency between two markets."""
    rendered_prompt = render_prompt(
        LABEL_PROMPT_SPEC_V1,
        market_a,
        market_b,
        model=model,
        prompt_adapter=prompt_adapter,
    )
    caps = resolve_capabilities(model)

    try:
        kwargs = {
            "model": model,
            "messages": list(rendered_prompt.messages),
            "max_tokens": caps.max_tokens_label,
        }
        if caps.temperature_label is not None:
            kwargs["temperature"] = caps.temperature_label
        if caps.extra_body:
            kwargs["extra_body"] = caps.extra_body
        response = await _create_with_retry(client, kwargs, call="label")

        if not response.choices:
            logger.warning("llm_no_choices", model=model)
            return {
                "dependency_type": "none",
                "confidence": 0.0,
                "reasoning": "no choices in response",
                "classification_error": True,
            }
        msg = response.choices[0].message
        content = msg.content
        if not content:
            # Reasoning-only response (e.g. M2.7 exhausted token budget on <think>).
            # Fail closed — reasoning text is CoT, not a valid JSON answer.
            extras = getattr(msg, "model_extra", {}) or {}
            has_reasoning = bool(
                getattr(msg, "reasoning_content", None)
                or getattr(msg, "reasoning", None)
                or extras.get("reasoning")
                or extras.get("reasoning_content")
            )
            try:
                dump = response.model_dump() if hasattr(response, "model_dump") else repr(response)
            except Exception:
                dump = repr(response)
            logger.warning(
                "llm_empty_content_debug",
                model=model,
                has_reasoning=has_reasoning,
                finish_reason=response.choices[0].finish_reason,
                response_dump=str(dump)[:2000],
            )
            return {
                "dependency_type": "none",
                "confidence": 0.0,
                "reasoning": "empty response (reasoning only)" if has_reasoning else "empty response",
                # Provider glitch, not a verdict — must not be cached
                "classification_error": True,
            }
        raw = content.strip()
        # Strip think tags in case label-based fallback hits a reasoning model
        raw = _strip_think_tags(raw)
        result = json.loads(raw)
        if not isinstance(result, dict):
            # Valid JSON but not an object (e.g. a bare list/string) —
            # result.get below would raise and abort the whole cycle
            logger.warning("llm_non_object_json", raw=raw[:200])
            return {
                "dependency_type": "none",
                "confidence": 0.0,
                "reasoning": raw[:500],
                "classification_error": True,
            }
        result["prompt_version"] = rendered_prompt.version
        result["prompt_adapter"] = rendered_prompt.adapter

        # Calibrate LLM confidence: LLMs are systematically overconfident
        # Cap at 0.85 and apply 0.8x discount so raw >= 0.875 is needed
        # to pass the 0.70 verification threshold
        raw_confidence = float(result.get("confidence", 0.0))
        result["raw_llm_confidence"] = raw_confidence
        result["confidence"] = min(raw_confidence * 0.80, 0.85)

        if result.get("dependency_type") not in (*DEPENDENCY_TYPES, "none"):
            logger.warning("llm_invalid_type", raw=raw)
            return {
                "dependency_type": "none",
                "confidence": 0.0,
                "reasoning": raw,
                # Malformed output, not a verdict — retry next cycle
                "classification_error": True,
            }

        # Conditional without correlation is useless — downgrade to none
        if (
            result.get("dependency_type") == "conditional"
            and result.get("correlation") not in ("positive", "negative")
        ):
            logger.warning(
                "llm_conditional_missing_correlation",
                raw=raw,
            )
            result["dependency_type"] = "none"
            result["confidence"] = 0.0
            result["reasoning"] = (
                f"Downgraded from conditional: missing correlation. Original: {raw}"
            )

        # Label-path conditional/positive is provably untradeable: it builds
        # an unconstrained all-ones matrix, gets a 0.0 profit bound, and the
        # optimizer skips llm_label conditionals anyway — while the verified
        # MarketPair row is rescanned every cycle forever. Pure cost. (The
        # VECTOR path keeps its conditional/positive label — decision D-B on
        # implementing its excluded-(No,No) profit bound is still open.)
        if (
            result.get("dependency_type") == "conditional"
            and result.get("correlation") == "positive"
        ):
            logger.info("llm_conditional_positive_downgraded", raw=raw[:200])
            result["dependency_type"] = "none"
            result["confidence"] = 0.0
            result["reasoning"] = (
                f"Downgraded label-path conditional/positive (untradeable). Original: {raw}"
            )

        logger.info(
            "llm_classification",
            dep_type=result["dependency_type"],
            confidence=result.get("confidence", 0),
            prompt_version=rendered_prompt.version,
            prompt_adapter=rendered_prompt.adapter,
        )
        return result

    except (json.JSONDecodeError, KeyError, openai.APIError) as e:
        logger.error("llm_classification_failed", error=str(e))
        return {
            "dependency_type": "none",
            "confidence": 0.0,
            "reasoning": str(e),
            # Failure, not a verdict: _build_cache_row skips error-tagged
            # results, so the pair re-classifies next detection cycle
            # instead of being blackholed by a cached transient error.
            "classification_error": True,
        }


def _strip_think_tags(raw: str) -> str:
    """Strip <think>...</think> tags from model output (e.g. MiniMax M2.7).

    M2.7's mandatory reasoning outputs <think>...</think> before the JSON body.
    Split on </think> and take everything after. If </think> is absent, extract
    from first { to last } as fallback.
    """
    if "</think>" in raw:
        return raw.split("</think>", 1)[1].strip()
    # Fallback: extract JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


def _supports_json_response_format(model: str) -> bool:
    """Back-compat wrapper — the truth lives in the capability registry."""
    return resolve_capabilities(model).supports_json_response_format


def _derive_dependency_type(
    valid_outcomes: list[dict],
    outcomes_a: list,
    outcomes_b: list,
) -> dict:
    """Deterministic mapping from resolution vectors to dependency type + direction.

    Returns {"dependency_type": str, "implication_direction": str|None, "correlation": str|None}.
    """
    # Build a set of (a_outcome, b_outcome) tuples from the LLM output
    combos = set()
    for v in valid_outcomes:
        a_val = v.get("a", "")
        b_val = v.get("b", "")
        combos.add((a_val, b_val))

    # For binary markets, check against the 4 possible combinations
    all_four = {("Yes", "Yes"), ("Yes", "No"), ("No", "Yes"), ("No", "No")}
    missing = all_four - combos

    n_valid = len(combos & all_four)  # only count canonical combos

    if n_valid == 4:
        return {"dependency_type": "none", "implication_direction": None, "correlation": None}

    if n_valid == 0 or n_valid == 1:
        # Degenerate — LLM error
        return {"dependency_type": "_error", "implication_direction": None, "correlation": None}

    if n_valid == 3:
        # Exactly one combo excluded
        excluded = missing.pop()
        if excluded == ("Yes", "Yes"):
            return {"dependency_type": "mutual_exclusion", "implication_direction": None, "correlation": None}
        if excluded == ("Yes", "No"):
            # A=Yes forces B=Yes → a_implies_b
            return {"dependency_type": "implication", "implication_direction": "a_implies_b", "correlation": "positive"}
        if excluded == ("No", "Yes"):
            # B=Yes forces A=Yes → b_implies_a
            return {"dependency_type": "implication", "implication_direction": "b_implies_a", "correlation": "positive"}
        if excluded == ("No", "No"):
            # Both can't be No — conditional with positive correlation
            return {"dependency_type": "conditional", "implication_direction": None, "correlation": "positive"}

    if n_valid == 2:
        if combos & all_four == {("Yes", "No"), ("No", "Yes")}:
            return {"dependency_type": "partition", "implication_direction": None, "correlation": None}
        if combos & all_four == {("Yes", "Yes"), ("No", "No")}:
            return {"dependency_type": "cross_platform", "implication_direction": None, "correlation": None}
        # Any other 2-combo set fixes one market's outcome regardless of the
        # other (e.g. {YN, NN} claims B can never resolve Yes). A market with
        # a live mid-range price is never logically certain or impossible, so
        # these are hallucinated structure, not a tradeable relationship.
        # They used to map to conditional/negative, which inherits the
        # mutual-exclusion profit formula with none of its safeguards — one
        # such vector set made an unhedgeable directional bet look like
        # provable arbitrage (the E1 failure class).
        return {"dependency_type": "_error", "implication_direction": None, "correlation": None}

    return {"dependency_type": "_error", "implication_direction": None, "correlation": None}


async def classify_llm_resolution(
    client: openai.AsyncOpenAI,
    model: str,
    market_a: dict,
    market_b: dict,
    prompt_adapter: str = "auto",
) -> dict | None:
    """Classify via resolution vectors — ask the LLM which outcome combos are valid.

    Returns a result dict with dependency_type, confidence, implication_direction,
    correlation, valid_outcomes, and classification_source="llm_vector".
    Returns None if parsing fails (caller should fall back to label-based).
    """
    model_lower = model.lower()
    outcomes_a = market_a.get("outcomes", ["Yes", "No"])
    outcomes_b = market_b.get("outcomes", ["Yes", "No"])

    # Resolution vectors only work for binary markets
    if len(outcomes_a) != 2 or len(outcomes_b) != 2:
        return None

    rendered_prompt = render_prompt(
        RESOLUTION_VECTOR_PROMPT_SPEC_V1,
        {**market_a, "outcomes": outcomes_a},
        {**market_b, "outcomes": outcomes_b},
        model=model,
        prompt_adapter=prompt_adapter,
    )

    caps = resolve_capabilities(model)
    try:
        kwargs = {
            "model": model,
            "messages": list(rendered_prompt.messages),
            "max_tokens": caps.max_tokens_vector,
        }
        if caps.temperature_vector is not None:
            kwargs["temperature"] = caps.temperature_vector
        if caps.extra_body:
            kwargs["extra_body"] = caps.extra_body
        if caps.supports_json_response_format:
            kwargs["response_format"] = {"type": "json_object"}

        response = await _create_with_retry(client, kwargs, call="vector")
        if not response.choices:
            logger.warning("resolution_vector_no_choices", model=model)
            return None
        msg = response.choices[0].message
        content = msg.content
        # Reasoning-only response (e.g. M2.7 exhausted token budget on <think>):
        # fail closed — CoT text is not a valid JSON answer.
        if not content:
            extras = getattr(msg, "model_extra", {}) or {}
            has_reasoning = bool(
                getattr(msg, "reasoning_content", None)
                or getattr(msg, "reasoning", None)
                or extras.get("reasoning")
                or extras.get("reasoning_content")
            )
            try:
                dump = response.model_dump() if hasattr(response, "model_dump") else repr(response)
            except Exception:
                dump = repr(response)
            logger.warning(
                "resolution_vector_empty_debug",
                model=model,
                has_reasoning=has_reasoning,
                finish_reason=response.choices[0].finish_reason,
                response_dump=str(dump)[:2000],
            )
            return None
        raw = content.strip()

        # Strip <think> tags (MiniMax M2.7 mandatory reasoning)
        cleaned = _strip_think_tags(raw)
        result = json.loads(cleaned)
        if not isinstance(result, dict):
            logger.warning("resolution_vector_non_object_json", raw=raw[:200])
            return None

        valid_outcomes = result.get("valid_outcomes", [])
        if not valid_outcomes or not isinstance(valid_outcomes, list):
            logger.warning("resolution_vector_empty", raw=raw[:200])
            return None

        # Derive type deterministically from vectors
        derived = _derive_dependency_type(valid_outcomes, outcomes_a, outcomes_b)
        if derived["dependency_type"] == "_error":
            logger.warning("resolution_vector_degenerate", combos=len(valid_outcomes), raw=raw[:200])
            return None

        # Binary confidence: vectors are structurally correct or wrong
        confidence = 0.90

        classification = {
            "dependency_type": derived["dependency_type"],
            "confidence": confidence,
            "implication_direction": derived["implication_direction"],
            "correlation": derived["correlation"],
            "reasoning": result.get("reasoning", ""),
            "valid_outcomes": valid_outcomes,
            "classification_source": "llm_vector",
            "prompt_version": rendered_prompt.version,
            "prompt_adapter": rendered_prompt.adapter,
        }

        logger.info(
            "resolution_vector_classification",
            dep_type=derived["dependency_type"],
            n_valid=len(valid_outcomes),
            direction=derived.get("implication_direction"),
            prompt_version=rendered_prompt.version,
            prompt_adapter=rendered_prompt.adapter,
        )
        return classification

    except (json.JSONDecodeError, KeyError) as e:
        # Parse trouble is model-output noise — fall back to the label path
        logger.warning("resolution_vector_parse_failed", error=str(e))
        return None
    except openai.APIError as e:
        # The provider itself is failing (post-retry). Falling back to the
        # label path would just fire more doomed calls at the same provider;
        # return an error-tagged verdict so classify_pair stops here and the
        # pair re-classifies next cycle (never cached).
        logger.error("resolution_vector_api_failed", error=str(e))
        return {
            "dependency_type": "none",
            "confidence": 0.0,
            "reasoning": f"llm unavailable: {e}",
            "classification_source": "llm_vector",
            "classification_error": True,
        }


async def classify_pair(
    client: openai.AsyncOpenAI,
    model: str,
    market_a: dict,
    market_b: dict,
    prompt_adapter: str = "auto",
) -> dict:
    """Classify a market pair: rules → resolution vectors → label-based LLM fallback."""
    # 1. Try rule-based heuristics (fast, high confidence)
    result = await classify_rule_based(market_a, market_b)
    if result:
        result["classification_source"] = "rule_based"
        return result

    # 2. Try resolution vector classification (structured, moderate latency)
    result = await classify_llm_resolution(
        client,
        model,
        market_a,
        market_b,
        prompt_adapter=prompt_adapter,
    )
    if result:
        return result

    # 3. Fall back to label-based LLM (legacy, higher hallucination risk)
    result = await classify_llm(
        client,
        model,
        market_a,
        market_b,
        prompt_adapter=prompt_adapter,
    )
    result["classification_source"] = "llm_label"
    # Fallback safety: cap confidence at 0.70 so fallback pairs don't
    # reach the optimizer without additional validation
    result["confidence"] = min(result.get("confidence", 0.0), 0.70)
    return result
