"""Dependency classifier: determines relationship type between market pairs.

Uses a two-stage approach:
1. Rule-based heuristics (same event, subset outcomes) — fast, high confidence
2. LLM classification for ambiguous cases — slower, moderate confidence
"""

import json
import re

import openai
import structlog

logger = structlog.get_logger()

DEPENDENCY_TYPES = ("implication", "partition", "mutual_exclusion", "conditional")

CLASSIFIER_SYSTEM_PROMPT = """You classify the logical dependency between two prediction markets.

Given two markets with their questions, descriptions, and outcomes, determine:
1. dependency_type: one of "implication", "partition", "mutual_exclusion", "conditional", or "none"
2. confidence: float 0-1

Definitions:
- implication: If market A resolves Yes, market B must resolve a specific way (or vice versa)
- partition: Markets A and B together form an exhaustive partition of the same event space
- mutual_exclusion: Markets A and B cannot both resolve Yes simultaneously
- conditional: Market A's outcome probabilities are logically constrained by market B's outcome

Respond ONLY with valid JSON: {"dependency_type": "...", "confidence": 0.XX, "reasoning": "..."}"""


def _check_same_event(market_a: dict, market_b: dict) -> dict | None:
    """If two markets share the same event_id, they likely form a partition."""
    if (
        market_a.get("event_id")
        and market_b.get("event_id")
        and market_a["event_id"] == market_b["event_id"]
    ):
        return {
            "dependency_type": "partition",
            "confidence": 0.95,
            "reasoning": "Same event_id — markets are part of the same event partition",
        }
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


# Matches "Bitcoin Up or Down — March 21, 3:15AM-3:30AM ET" style questions.
# Captures: (asset, start_time, end_time)
_TIME_INTERVAL_RE = re.compile(
    r"^(.+?)\s+Up or Down\b.*?(\d{1,2}:\d{2}[AP]M)\s*-\s*(\d{1,2}:\d{2}[AP]M)",
    re.IGNORECASE,
)


def _check_crypto_time_intervals(market_a: dict, market_b: dict) -> dict | None:
    """Detect crypto time-interval markets on the same asset with different windows.

    Adjacent (non-overlapping) time windows are independent — the price can go up
    in both intervals. Only the *same* window would be mutual exclusion (up vs down).
    """
    q_a = market_a.get("question", "")
    q_b = market_b.get("question", "")

    m_a = _TIME_INTERVAL_RE.search(q_a)
    m_b = _TIME_INTERVAL_RE.search(q_b)

    if not m_a or not m_b:
        return None

    asset_a, start_a, end_a = m_a.group(1).strip(), m_a.group(2), m_a.group(3)
    asset_b, start_b, end_b = m_b.group(1).strip(), m_b.group(2), m_b.group(3)

    # Different assets — not the same pattern, let LLM decide
    if asset_a.lower() != asset_b.lower():
        return None

    # Same asset, same time window → genuine mutual exclusion (up vs down)
    if start_a == start_b and end_a == end_b:
        return {
            "dependency_type": "mutual_exclusion",
            "confidence": 0.95,
            "reasoning": f"Same asset '{asset_a}', same time window {start_a}-{end_a} — up/down are mutually exclusive",
        }

    # Same asset, different time window → independent
    return {
        "dependency_type": "none",
        "confidence": 0.95,
        "reasoning": f"Same asset '{asset_a}', different time windows ({start_a}-{end_a} vs {start_b}-{end_b}) — independent events",
    }


async def classify_rule_based(market_a: dict, market_b: dict) -> dict | None:
    """Apply rule-based heuristics. Returns result dict or None if ambiguous."""
    for check in (_check_same_event, _check_outcome_subset, _check_crypto_time_intervals):
        result = check(market_a, market_b)
        if result:
            logger.info(
                "rule_based_classification",
                dep_type=result["dependency_type"],
                confidence=result["confidence"],
            )
            return result
    return None


async def classify_llm(
    client: openai.AsyncOpenAI,
    model: str,
    market_a: dict,
    market_b: dict,
) -> dict:
    """Use LLM to classify the dependency between two markets."""
    user_prompt = f"""Market A:
- Question: {market_a['question']}
- Description: {market_a.get('description', 'N/A')}
- Outcomes: {market_a.get('outcomes', [])}

Market B:
- Question: {market_b['question']}
- Description: {market_b.get('description', 'N/A')}
- Outcomes: {market_b.get('outcomes', [])}"""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=256,
        )

        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)

        if result.get("dependency_type") not in (*DEPENDENCY_TYPES, "none"):
            logger.warning("llm_invalid_type", raw=raw)
            return {"dependency_type": "none", "confidence": 0.0, "reasoning": raw}

        logger.info(
            "llm_classification",
            dep_type=result["dependency_type"],
            confidence=result.get("confidence", 0),
        )
        return result

    except (json.JSONDecodeError, KeyError, openai.APIError) as e:
        logger.error("llm_classification_failed", error=str(e))
        return {"dependency_type": "none", "confidence": 0.0, "reasoning": str(e)}


async def classify_pair(
    client: openai.AsyncOpenAI,
    model: str,
    market_a: dict,
    market_b: dict,
) -> dict:
    """Classify a market pair: try rules first, fall back to LLM."""
    result = await classify_rule_based(market_a, market_b)
    if result:
        return result
    return await classify_llm(client, model, market_a, market_b)
