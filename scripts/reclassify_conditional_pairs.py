"""Reclassify conditional pairs that are actually implications or non-arbitrageable.

Reads conditional pairs from the DB, applies rule-based checks to identify:
1. Implication mislabels → upgrade to implication with direction
2. Truly correlated (no logical constraint) → downgrade to none
3. Leave remaining conditionals as-is

Usage:
    POSTGRES_DB=polyarb_backtest python -m scripts.reclassify_conditional_pairs [--dry-run]
"""
import asyncio
import re
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from shared.db import engine


# ────────────────────────────────────────────────────────────────────
#  Implication detection rules
# ────────────────────────────────────────────────────────────────────

def detect_implication(q_a: str, q_b: str) -> dict | None:
    """If A and B form an implication, return direction. Else None.

    Returns {"direction": "a_implies_b"|"b_implies_a", "reason": str}
    """
    qa, qb = q_a.lower().strip(), q_b.lower().strip()

    # Rule 1: Tournament hierarchy — win higher stage implies lower stage
    result = _check_tournament_hierarchy(qa, qb)
    if result:
        return result

    # Rule 2: Time-window nesting — "by March 31" implies "by June 30"
    result = _check_time_window_implication(qa, qb, q_a, q_b)
    if result:
        return result

    # Rule 3: "Advance to X" + "Win X" → winning implies advancing
    result = _check_advance_win(qa, qb)
    if result:
        return result

    # Rule 4: Specific entity implies "any/a new" entity
    result = _check_specific_implies_general(qa, qb)
    if result:
        return result

    # Rule 5: Win election implies win nomination/primary
    result = _check_election_hierarchy(qa, qb)
    if result:
        return result

    # Rule 6: "Win X" implies "qualify for runoff/advance from primary"
    result = _check_qualify_advance(qa, qb)
    if result:
        return result

    return None


def _check_tournament_hierarchy(qa: str, qb: str) -> dict | None:
    """Win higher stage implies win lower stage."""
    # Each tuple: (higher_stage_keywords, lower_stage_keywords)
    # If A has higher and B has lower → a_implies_b
    hierarchies = [
        # Football/soccer
        (["league championship", "super bowl"], ["conference", "nfc championship", "afc championship"]),
        (["league championship", "super bowl"], ["division"]),
        (["conference", "nfc championship", "afc championship"], ["division"]),
        # Basketball
        (["nba finals"], ["conference finals", "eastern conference", "western conference"]),
        (["nba finals"], ["division", "atlantic division", "central division", "southeast division",
                          "pacific division", "northwest division", "southwest division"]),
        (["conference finals"], ["division"]),
        # Hockey
        (["stanley cup"], ["conference finals", "western conference", "eastern conference"]),
        (["stanley cup"], ["division", "pacific division", "central division",
                           "metropolitan division", "atlantic division"]),
        (["conference finals", "western conference final", "eastern conference final"],
         ["division", "pacific division", "central division"]),
        # General sports
        (["win the 20", "championship"], ["make the", "playoff"]),
        (["win the 20", "championship"], ["division"]),
        (["win", "division"], ["make", "playoff"]),
        # NCAA
        (["win the 20", "tournament"], ["advance to the national championship"]),
        (["advance to the national championship"], ["advance to the final four"]),
        (["win the 20", "tournament"], ["advance to the final four"]),
        # Baseball
        (["world series"], ["championship series", "pennant", "alcs", "nlcs"]),
        (["world series"], ["east title", "west title", "central title", "al east", "nl east",
                            "al west", "nl west", "al central", "nl central"]),
        (["championship series", "pennant", "alcs", "nlcs"],
         ["east title", "west title", "central title"]),
    ]

    for higher_kws, lower_kws in hierarchies:
        a_is_higher = any(kw in qa for kw in higher_kws)
        b_is_higher = any(kw in qb for kw in higher_kws)
        a_is_lower = any(kw in qa for kw in lower_kws)
        b_is_lower = any(kw in qb for kw in lower_kws)

        if a_is_higher and b_is_lower and not b_is_higher:
            return {"direction": "a_implies_b", "reason": "tournament_hierarchy"}
        if b_is_higher and a_is_lower and not a_is_higher:
            return {"direction": "b_implies_a", "reason": "tournament_hierarchy"}

    return None


def _check_time_window_implication(qa: str, qb: str, q_a_orig: str, q_b_orig: str) -> dict | None:
    """'by March 31' implies 'by June 30' for same event."""
    # Extract "by DATE" or "before DATE" patterns
    date_pattern = re.compile(
        r'\b(?:by|before)\s+'
        r'(?:(?:january|february|march|april|may|june|july|august|september|october|november|december)'
        r'\s+\d{1,2}(?:,?\s+\d{4})?'
        r'|\d{4})',
        re.IGNORECASE,
    )

    dates_a = date_pattern.findall(qa)
    dates_b = date_pattern.findall(qb)

    if not dates_a or not dates_b:
        return None

    # Month ordering for comparison
    month_order = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    def extract_month_num(date_str: str) -> int | None:
        for m, n in month_order.items():
            if m in date_str.lower():
                return n
        return None

    m_a = extract_month_num(dates_a[0])
    m_b = extract_month_num(dates_b[0])

    # "before 2027" → treat as month 12 (end of year)
    if m_a is None and re.search(r'\d{4}', dates_a[0]):
        m_a = 12
    if m_b is None and re.search(r'\d{4}', dates_b[0]):
        m_b = 12

    if m_a is None or m_b is None:
        return None
    if m_a == m_b:
        return None

    # Check that questions are about the same event (remove the date part and compare)
    def strip_date(q: str) -> str:
        return date_pattern.sub("", q).strip().rstrip("?").strip()

    core_a = strip_date(qa)
    core_b = strip_date(qb)

    # Simple similarity check: shared words ratio
    words_a = set(core_a.split())
    words_b = set(core_b.split())
    if not words_a or not words_b:
        return None
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
    if overlap < 0.5:
        return None

    # Earlier deadline implies later deadline
    # "X by March" = Yes → "X by June" = Yes (earlier implies later)
    if m_a < m_b:
        return {"direction": "a_implies_b", "reason": "time_window_nesting"}
    else:
        return {"direction": "b_implies_a", "reason": "time_window_nesting"}


def _check_advance_win(qa: str, qb: str) -> dict | None:
    """'Win X' implies 'Advance to X'."""
    if "win" in qa and "advance" in qb:
        return {"direction": "a_implies_b", "reason": "win_implies_advance"}
    if "win" in qb and "advance" in qa:
        return {"direction": "b_implies_a", "reason": "win_implies_advance"}
    return None


def _check_specific_implies_general(qa: str, qb: str) -> dict | None:
    """'Will Azerbaijan join' implies 'Will a new country join'."""
    general_markers = ["a new country", "a new ", "any ", "at least one"]

    for marker in general_markers:
        if marker in qa and marker not in qb:
            # A is general, B is specific → B implies A
            return {"direction": "b_implies_a", "reason": "specific_implies_general"}
        if marker in qb and marker not in qa:
            # B is general, A is specific → A implies B
            return {"direction": "a_implies_b", "reason": "specific_implies_general"}
    return None


def _check_election_hierarchy(qa: str, qb: str) -> dict | None:
    """Win election implies win nomination/primary/1st round."""
    win_election = ["win the 20", "presidential election", "governor election",
                    "senate election", "gubernatorial"]
    win_primary = ["nomination", "primary", "advance from", "1st round",
                   "first round"]

    a_election = any(kw in qa for kw in win_election) and "win" in qa
    b_election = any(kw in qb for kw in win_election) and "win" in qb
    a_primary = any(kw in qa for kw in win_primary)
    b_primary = any(kw in qb for kw in win_primary)

    # Win election implies win primary/1st round
    if a_election and b_primary:
        return {"direction": "a_implies_b", "reason": "election_hierarchy"}
    if b_election and a_primary:
        return {"direction": "b_implies_a", "reason": "election_hierarchy"}

    # Win election implies win 1st round (for same candidate)
    if a_election and not b_election and "win" in qb and ("1st round" in qb or "first round" in qb):
        return {"direction": "a_implies_b", "reason": "election_hierarchy"}
    if b_election and not a_election and "win" in qa and ("1st round" in qa or "first round" in qa):
        return {"direction": "b_implies_a", "reason": "election_hierarchy"}

    return None


def _check_qualify_advance(qa: str, qb: str) -> dict | None:
    """Win election implies qualify for runoff."""
    if ("win" in qa) and ("qualify" in qb or "runoff" in qb):
        return {"direction": "a_implies_b", "reason": "win_implies_qualify"}
    if ("win" in qb) and ("qualify" in qa or "runoff" in qa):
        return {"direction": "b_implies_a", "reason": "win_implies_qualify"}
    return None


# ────────────────────────────────────────────────────────────────────
#  Non-arbitrageable pair detection
# ────────────────────────────────────────────────────────────────────

def detect_non_arbitrageable(q_a: str, q_b: str) -> str | None:
    """Return reason if pair is correlated but has no logical constraint."""
    qa, qb = q_a.lower().strip(), q_b.lower().strip()

    # O/U vs BTTS — correlated, not constrained
    if _is_ou(qa, qb) and _is_btts(qa, qb):
        return "ou_vs_btts"

    # Spread vs O/U — correlated, not constrained
    if _is_spread(qa, qb) and _is_ou(qa, qb):
        return "spread_vs_ou"

    # Spread vs BTTS — correlated, not constrained
    if _is_spread(qa, qb) and _is_btts(qa, qb):
        return "spread_vs_btts"

    return None


def _is_ou(qa, qb):
    return "o/u" in qa or "o/u" in qb

def _is_btts(qa, qb):
    return "both teams to score" in qa or "both teams to score" in qb

def _is_spread(qa, qb):
    return "spread:" in qa or "spread:" in qb or "spread (" in qa or "spread (" in qb


# ────────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────────

async def main():
    dry_run = "--dry-run" in sys.argv

    async with engine.begin() as conn:
        rows = (await conn.execute(text("""
            SELECT mp.id, mp.dependency_type, mp.confidence,
                   mp.implication_direction, mp.constraint_matrix,
                   ma.question as q_a, mb.question as q_b,
                   ma.event_id as ev_a, mb.event_id as ev_b
            FROM market_pairs mp
            JOIN markets ma ON ma.id = mp.market_a_id
            JOIN markets mb ON mb.id = mp.market_b_id
            WHERE mp.dependency_type = 'conditional'
              AND mp.verified = true
        """))).fetchall()

        print(f"Total conditional verified pairs: {len(rows)}")
        print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
        print()

        actions = Counter()
        updates = []

        for r in rows:
            qa = r.q_a or ""
            qb = r.q_b or ""

            # Check for implication
            impl = detect_implication(qa, qb)
            if impl:
                actions[f"→implication ({impl['reason']})"] += 1
                updates.append({
                    "id": r.id,
                    "new_type": "implication",
                    "direction": impl["direction"],
                    "reason": impl["reason"],
                })
                print(f"  #{r.id} conditional → implication ({impl['direction']}, {impl['reason']})")
                print(f"    A: {qa[:75]}")
                print(f"    B: {qb[:75]}")
                continue

            # Check for non-arbitrageable
            non_arb = detect_non_arbitrageable(qa, qb)
            if non_arb:
                actions[f"→none ({non_arb})"] += 1
                updates.append({
                    "id": r.id,
                    "new_type": "none",
                    "direction": None,
                    "reason": non_arb,
                })
                print(f"  #{r.id} conditional → none ({non_arb})")
                print(f"    A: {qa[:75]}")
                print(f"    B: {qb[:75]}")
                continue

            actions["keep_conditional"] += 1

        print(f"\n{'='*60}")
        print("SUMMARY:")
        for action, cnt in actions.most_common():
            print(f"  {action:<45} {cnt:>5}")
        print(f"  {'TOTAL':<45} {len(rows):>5}")

        if dry_run:
            print(f"\nDry run — no changes written. Remove --dry-run to apply.")
            return

        # Apply updates
        upgraded = 0
        for u in updates:
            if u["new_type"] == "implication":
                await conn.execute(text("""
                    UPDATE market_pairs
                    SET dependency_type = :new_type,
                        implication_direction = :direction
                    WHERE id = :id
                """), {"id": u["id"], "new_type": u["new_type"], "direction": u["direction"]})
            else:
                # none → also set verified=false so backtest skips them
                await conn.execute(text("""
                    UPDATE market_pairs
                    SET dependency_type = :new_type,
                        verified = false,
                        implication_direction = NULL
                    WHERE id = :id
                """), {"id": u["id"], "new_type": u["new_type"]})
            upgraded += 1

        print(f"\nApplied {upgraded} updates.")


if __name__ == "__main__":
    asyncio.run(main())
