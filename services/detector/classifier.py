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
3. correlation: "positive" or "negative" (REQUIRED when dependency_type is "conditional")

Definitions:
- implication: If market A resolves Yes, market B must resolve a specific way (or vice versa)
- partition: Markets A and B together form an exhaustive partition of the same event space
- mutual_exclusion: Markets A and B cannot both resolve Yes simultaneously
- conditional: Market A's outcome probabilities are logically constrained by market B's outcome
  - positive correlation: A=Yes makes B=Yes more likely (e.g., "Win Iowa" → "Win Election")
  - negative correlation: A=Yes makes B=Yes less likely (e.g., "Team A wins" → "Team B wins")

CRITICAL — price-threshold markets:
- "X above $A" and "X above $B" where A > B: this is IMPLICATION, not mutual_exclusion.
  If X is above $134, it is necessarily also above $128. Both CAN resolve Yes simultaneously.
- "X above $A" and "X above $B" on DIFFERENT dates or time windows: these are INDEPENDENT (none).
  The price can be above $128 on Monday and below $128 on Tuesday.
- Only use mutual_exclusion when the events truly cannot BOTH happen (e.g., "Team A wins" vs "Team B wins" in the same game).

Respond ONLY with valid JSON: {"dependency_type": "...", "confidence": 0.XX, "correlation": "positive"|"negative"|null, "reasoning": "..."}"""


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
        return {
            "dependency_type": "implication",
            "confidence": 0.95,
            "correlation": "positive",
            "reasoning": (
                f"'{m_a.group(1).strip()}' above ${higher} implies above ${lower} — "
                f"nested price thresholds form an implication chain"
            ),
        }
    else:  # below
        higher = max(threshold_a, threshold_b)
        lower = min(threshold_a, threshold_b)
        return {
            "dependency_type": "implication",
            "confidence": 0.95,
            "correlation": "positive",
            "reasoning": (
                f"'{m_a.group(1).strip()}' below ${lower} implies below ${higher} — "
                f"nested price thresholds form an implication chain"
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

    return {
        "dependency_type": "implication",
        "confidence": 0.95,
        "correlation": "positive",
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

    return {
        "dependency_type": "implication",
        "confidence": 0.95,
        "correlation": "positive",
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
