"""Declarative state machines for opportunity, trade, and order lifecycles.

Every status transition in the system flows through this module.  The
transition table is the single source of truth for which moves are legal
and what timestamp side-effects each move requires.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

try:
    StrEnum = enum.StrEnum  # Python 3.11+
except AttributeError:
    class StrEnum(str, enum.Enum):  # type: ignore[no-redef]
        """Backport: behaves like str for comparisons and serialization."""

from sqlalchemy import func


# ---------------------------------------------------------------------------
# Opportunity lifecycle
# ---------------------------------------------------------------------------

class OppStatus(StrEnum):
    DETECTED = "detected"
    OPTIMIZED = "optimized"
    UNCONVERGED = "unconverged"
    PENDING = "pending"
    SIMULATED = "simulated"
    EXPIRED = "expired"
    SKIPPED = "skipped"


TERMINAL = frozenset({OppStatus.SIMULATED, OppStatus.EXPIRED, OppStatus.SKIPPED})
IN_FLIGHT = frozenset({OppStatus.DETECTED, OppStatus.OPTIMIZED, OppStatus.UNCONVERGED, OppStatus.PENDING})

# Transition table: (from, to) → set of timestamp fields to populate.
# An empty set means the transition is legal but has no side-effects.
_OPP_TRANSITIONS: dict[tuple[OppStatus, OppStatus], set[str]] = {
    # Optimizer outputs
    (OppStatus.DETECTED, OppStatus.OPTIMIZED): set(),
    (OppStatus.DETECTED, OppStatus.UNCONVERGED): set(),
    (OppStatus.DETECTED, OppStatus.SKIPPED): set(),
    (OppStatus.DETECTED, OppStatus.EXPIRED): {"expired_at"},
    # Detector resets for re-optimization (caller clears FW fields)
    (OppStatus.OPTIMIZED, OppStatus.DETECTED): set(),
    (OppStatus.UNCONVERGED, OppStatus.DETECTED): set(),
    # Simulator picks up optimized/unconverged
    (OppStatus.OPTIMIZED, OppStatus.PENDING): {"pending_at"},
    (OppStatus.UNCONVERGED, OppStatus.PENDING): {"pending_at"},
    (OppStatus.OPTIMIZED, OppStatus.EXPIRED): {"expired_at"},
    (OppStatus.UNCONVERGED, OppStatus.EXPIRED): {"expired_at"},
    # Pending outcomes
    (OppStatus.PENDING, OppStatus.SIMULATED): set(),
    (OppStatus.PENDING, OppStatus.OPTIMIZED): set(),   # revert on failure
    (OppStatus.PENDING, OppStatus.EXPIRED): {"expired_at"},
}


class InvalidTransition(Exception):
    """Raised when a status transition is not in the transition table."""

    def __init__(self, from_status: OppStatus, to_status: OppStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"invalid opportunity transition: {from_status} -> {to_status}")


def transition(opp, to: OppStatus) -> None:
    """Validate and apply a status transition on an ORM ArbitrageOpportunity.

    Sets ``opp.status`` and any required timestamp side-effects.
    Raises ``InvalidTransition`` if the move is not in the table.
    """
    from_status = OppStatus(opp.status)
    effects = _OPP_TRANSITIONS.get((from_status, to))
    if effects is None:
        raise InvalidTransition(from_status, to)

    opp.status = to.value
    now = datetime.now(timezone.utc)
    if "pending_at" in effects:
        opp.pending_at = now
    if "expired_at" in effects:
        opp.expired_at = now


def bulk_transition_values(from_status: OppStatus, to: OppStatus) -> dict:
    """Return a ``values()`` dict for a bulk ``UPDATE`` statement.

    Includes ``status`` plus any timestamp columns required by the
    transition table.  Timestamps use ``func.now()`` so the DB sets them.

    Raises ``InvalidTransition`` if the move is not in the table.
    """
    effects = _OPP_TRANSITIONS.get((from_status, to))
    if effects is None:
        raise InvalidTransition(from_status, to)

    vals: dict = {"status": to.value}
    if "pending_at" in effects:
        vals["pending_at"] = func.now()
    if "expired_at" in effects:
        vals["expired_at"] = func.now()
    return vals


# ---------------------------------------------------------------------------
# Trade lifecycle (documentation + type-safety, no runtime enforcement)
# ---------------------------------------------------------------------------

class TradeStatus(StrEnum):
    FILLED = "filled"
    SETTLED = "settled"
    PURGED = "purged"


# ---------------------------------------------------------------------------
# Live order lifecycle (documentation + type-safety, no runtime enforcement)
# ---------------------------------------------------------------------------

class OrderStatus(StrEnum):
    DRY_RUN = "dry_run"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SETTLED = "settled"
