"""Backfill implication_direction for implication pairs that are missing it.

Applies rule-based direction inference using the same logic as the classifier
plus additional patterns for gaps (spreads, "close over", generic thresholds).

Usage:
    POSTGRES_DB=polyarb_backtest python -m scripts.backfill_implication_direction [--dry-run]
"""
import asyncio
import re
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from shared.db import engine

# Import existing classifier rule functions
from services.detector.classifier import (
    _check_price_threshold_markets,
    _check_milestone_threshold_markets,
    _check_ranking_markets,
    _check_over_under_markets,
)

# Also import reclassify rules for tournament/time/election patterns
from scripts.reclassify_conditional_pairs import detect_implication


# ────────────────────────────────────────────────────────────────────
#  Additional direction inference rules (gaps in classifier)
# ────────────────────────────────────────────────────────────────────

# Spread: "Spread: Team (-1.5)" vs "Spread: Team (-2.5)"
_SPREAD_RE = re.compile(
    r"Spread:\s*(.+?)\s*\((-?\d+(?:\.\d+)?)\)",
    re.IGNORECASE,
)


def _check_spread_markets(q_a: str, q_b: str) -> dict | None:
    """Spread -2.5 implies Spread -1.5 (winning by more implies winning by less)."""
    m_a = _SPREAD_RE.search(q_a)
    m_b = _SPREAD_RE.search(q_b)
    if not m_a or not m_b:
        return None

    subject_a = m_a.group(1).strip().lower()
    subject_b = m_b.group(1).strip().lower()
    if subject_a != subject_b:
        return None

    spread_a = float(m_a.group(2))
    spread_b = float(m_b.group(2))
    if spread_a == spread_b:
        return None

    # For negative spreads (favorite): more negative = harder to cover
    # Spread -2.5 (win by 3+) implies Spread -1.5 (win by 2+)
    # So the MORE negative spread is the antecedent (harder implies easier)
    if spread_a < spread_b:
        # A is more negative → A implies B
        return {"direction": "a_implies_b", "reason": "spread_pair"}
    else:
        return {"direction": "b_implies_a", "reason": "spread_pair"}


# "close over $X" or "close above $X" — variant of price threshold
_CLOSE_OVER_RE = re.compile(
    r"close\s+(?:over|above)\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Generic "over X,XXX" without $ sign (for indices like NYSE Composite)
_OVER_NUM_RE = re.compile(
    r"(?:close\s+)?(?:over|above)\s+([\d,]+(?:\.\d+)?)\b(?!\s*(?:million|billion|[MB]\b))",
    re.IGNORECASE,
)


def _check_close_over(q_a: str, q_b: str) -> dict | None:
    """'Close over 19,200' implies 'close over 19,050' — same as price threshold."""
    m_a = _CLOSE_OVER_RE.search(q_a) or _OVER_NUM_RE.search(q_a)
    m_b = _CLOSE_OVER_RE.search(q_b) or _OVER_NUM_RE.search(q_b)
    if not m_a or not m_b:
        return None

    val_a = float(m_a.group(1).replace(",", ""))
    val_b = float(m_b.group(1).replace(",", ""))
    if val_a == val_b:
        return None

    # Strip the number and compare subjects
    stripped_a = re.sub(r'[\d,]+(?:\.\d+)?', '', q_a).lower().strip()
    stripped_b = re.sub(r'[\d,]+(?:\.\d+)?', '', q_b).lower().strip()

    # Simple overlap check
    words_a = set(stripped_a.split())
    words_b = set(stripped_b.split())
    if not words_a or not words_b:
        return None
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
    if overlap < 0.6:
        return None

    # Higher "over" implies lower "over"
    if val_a > val_b:
        return {"direction": "a_implies_b", "reason": "close_over_threshold"}
    else:
        return {"direction": "b_implies_a", "reason": "close_over_threshold"}


# Generic numeric threshold: "hit 1.25 (Low)", "dip below 3.5%"
_GENERIC_THRESHOLD_RE = re.compile(
    r"(?:hit|reach|dip\s+below|fall\s+below|drop\s+below|rise\s+above)\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _check_generic_threshold(q_a: str, q_b: str) -> dict | None:
    """Generic numeric threshold: 'hit 1.25' implies 'hit 1.20' for same subject."""
    m_a = _GENERIC_THRESHOLD_RE.search(q_a)
    m_b = _GENERIC_THRESHOLD_RE.search(q_b)
    if not m_a or not m_b:
        return None

    val_a = float(m_a.group(1).replace(",", ""))
    val_b = float(m_b.group(1).replace(",", ""))
    if val_a == val_b:
        return None

    # Check same subject
    stripped_a = _GENERIC_THRESHOLD_RE.sub("", q_a).lower().strip()
    stripped_b = _GENERIC_THRESHOLD_RE.sub("", q_b).lower().strip()
    words_a = set(stripped_a.split())
    words_b = set(stripped_b.split())
    if not words_a or not words_b:
        return None
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
    if overlap < 0.6:
        return None

    # Determine direction based on "above"/"reach" vs "below"
    is_below_a = bool(re.search(r"dip\s+below|fall\s+below|drop\s+below", q_a, re.I))
    is_below_b = bool(re.search(r"dip\s+below|fall\s+below|drop\s+below", q_b, re.I))

    if is_below_a != is_below_b:
        return None  # Mixed directions

    if is_below_a:
        # "below 3.0%" implies "below 3.5%" — lower threshold is antecedent
        if val_a < val_b:
            return {"direction": "a_implies_b", "reason": "generic_threshold_below"}
        else:
            return {"direction": "b_implies_a", "reason": "generic_threshold_below"}
    else:
        # "hit 1.25" implies "hit 1.20" — higher threshold is antecedent
        if val_a > val_b:
            return {"direction": "a_implies_b", "reason": "generic_threshold_above"}
        else:
            return {"direction": "b_implies_a", "reason": "generic_threshold_above"}


# "Win more than X.5 games"
_GAMES_RE = re.compile(
    r"more than\s+([\d.]+)\s+(?:regular\s+season\s+)?games",
    re.IGNORECASE,
)


def _check_games_threshold(q_a: str, q_b: str) -> dict | None:
    """'Win more than 45.5 games' implies 'win more than 40.5 games'."""
    m_a = _GAMES_RE.search(q_a)
    m_b = _GAMES_RE.search(q_b)
    if not m_a or not m_b:
        return None

    val_a = float(m_a.group(1))
    val_b = float(m_b.group(1))
    if val_a == val_b:
        return None

    # Strip numbers and check same team
    stripped_a = _GAMES_RE.sub("", q_a).lower().strip()
    stripped_b = _GAMES_RE.sub("", q_b).lower().strip()
    words_a = set(stripped_a.split())
    words_b = set(stripped_b.split())
    if not words_a or not words_b:
        return None
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
    if overlap < 0.6:
        return None

    # More games implies fewer games (higher threshold is antecedent)
    if val_a > val_b:
        return {"direction": "a_implies_b", "reason": "games_threshold"}
    else:
        return {"direction": "b_implies_a", "reason": "games_threshold"}


# "dip to $X" — lower dip implies higher dip (if it dips to 50k, it dipped to 55k)
_DIP_TO_RE = re.compile(
    r"dip\s+to\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _check_dip_to(q_a: str, q_b: str) -> dict | None:
    """'Dip to $50k' implies 'dip to $55k' — lower dip is antecedent."""
    m_a = _DIP_TO_RE.search(q_a)
    m_b = _DIP_TO_RE.search(q_b)
    if not m_a or not m_b:
        return None

    val_a = float(m_a.group(1).replace(",", ""))
    val_b = float(m_b.group(1).replace(",", ""))
    if val_a == val_b:
        return None

    # Check same subject
    stripped_a = _DIP_TO_RE.sub("", q_a).lower().strip()
    stripped_b = _DIP_TO_RE.sub("", q_b).lower().strip()
    words_a = set(stripped_a.split())
    words_b = set(stripped_b.split())
    if not words_a or not words_b:
        return None
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
    if overlap < 0.5:
        return None

    # Lower dip implies higher dip
    if val_a < val_b:
        return {"direction": "a_implies_b", "reason": "dip_to_threshold"}
    else:
        return {"direction": "b_implies_a", "reason": "dip_to_threshold"}


# "at least X" / "score of at least X"
_AT_LEAST_RE = re.compile(
    r"(?:at\s+least|greater\s+than|more\s+than)\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _check_at_least(q_a: str, q_b: str) -> dict | None:
    """'At least 1700' implies 'at least 1650' — higher threshold is antecedent."""
    m_a = _AT_LEAST_RE.search(q_a)
    m_b = _AT_LEAST_RE.search(q_b)
    if not m_a or not m_b:
        return None

    val_a = float(m_a.group(1).replace(",", ""))
    val_b = float(m_b.group(1).replace(",", ""))
    if val_a == val_b:
        return None

    # Check same subject
    stripped_a = _AT_LEAST_RE.sub("", q_a).lower().strip()
    stripped_b = _AT_LEAST_RE.sub("", q_b).lower().strip()
    words_a = set(stripped_a.split())
    words_b = set(stripped_b.split())
    if not words_a or not words_b:
        return None
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
    if overlap < 0.5:
        return None

    # Higher "at least" implies lower "at least"
    if val_a > val_b:
        return {"direction": "a_implies_b", "reason": "at_least_threshold"}
    else:
        return {"direction": "b_implies_a", "reason": "at_least_threshold"}


# ────────────────────────────────────────────────────────────────────
#  Combined direction inference
# ────────────────────────────────────────────────────────────────────

def infer_direction(q_a: str, q_b: str) -> dict | None:
    """Try all direction inference methods. Returns {direction, reason} or None."""
    # 1. Existing classifier rules (wrap as dicts)
    for check_fn in [
        _check_over_under_markets,
        _check_price_threshold_markets,
        _check_milestone_threshold_markets,
        _check_ranking_markets,
    ]:
        market_a = {"question": q_a}
        market_b = {"question": q_b}
        result = check_fn(market_a, market_b)
        if result and result.get("implication_direction"):
            return {
                "direction": result["implication_direction"],
                "reason": check_fn.__name__.replace("_check_", ""),
            }

    # 2. Reclassify rules (from conditional cleanup)
    result = detect_implication(q_a, q_b)
    if result:
        return result

    # 3. New gap-filling rules
    for check_fn in [
        _check_spread_markets,
        _check_close_over,
        _check_games_threshold,
        _check_generic_threshold,
        _check_dip_to,
        _check_at_least,
    ]:
        result = check_fn(q_a, q_b)
        if result:
            return result

    return None


# ────────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────────

async def main():
    dry_run = "--dry-run" in sys.argv

    async with engine.begin() as conn:
        rows = (await conn.execute(text("""
            SELECT mp.id, ma.question as q_a, mb.question as q_b
            FROM market_pairs mp
            JOIN markets ma ON ma.id = mp.market_a_id
            JOIN markets mb ON mb.id = mp.market_b_id
            WHERE mp.dependency_type = 'implication'
              AND mp.implication_direction IS NULL
              AND mp.verified = true
            ORDER BY mp.id
        """))).fetchall()

        print(f"Total implication pairs missing direction: {len(rows)}")
        print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
        print()

        actions = Counter()
        updates = []

        for r in rows:
            result = infer_direction(r.q_a or "", r.q_b or "")
            if result:
                actions[result["reason"]] += 1
                updates.append({
                    "id": r.id,
                    "direction": result["direction"],
                    "reason": result["reason"],
                })
            else:
                actions["no_match"] += 1

        print("DIRECTION INFERENCE RESULTS:")
        print("-" * 60)
        inferred = 0
        for reason, cnt in actions.most_common():
            tag = "INFER" if reason != "no_match" else "MISS"
            print(f"  [{tag}] {reason:<40} {cnt:>5}")
            if reason != "no_match":
                inferred += cnt

        print(f"\n  Inferred: {inferred}/{len(rows)} ({100*inferred/max(len(rows),1):.1f}%)")
        print(f"  No match: {actions['no_match']}")

        if dry_run:
            # Print some no-match samples
            no_match_samples = []
            for r in rows:
                result = infer_direction(r.q_a or "", r.q_b or "")
                if not result and len(no_match_samples) < 15:
                    no_match_samples.append(r)
            if no_match_samples:
                print(f"\nNO-MATCH SAMPLES ({len(no_match_samples)}):")
                for r in no_match_samples:
                    print(f"  #{r.id}")
                    print(f"    A: {(r.q_a or '')[:85]}")
                    print(f"    B: {(r.q_b or '')[:85]}")

            print(f"\nDry run — no changes. Remove --dry-run to apply.")
            return

        # Apply updates
        for u in updates:
            await conn.execute(text("""
                UPDATE market_pairs
                SET implication_direction = :direction
                WHERE id = :id
            """), {"id": u["id"], "direction": u["direction"]})

        print(f"\nApplied {len(updates)} direction updates.")


if __name__ == "__main__":
    asyncio.run(main())
