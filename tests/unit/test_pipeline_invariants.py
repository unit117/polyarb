"""Pipeline invariant tests — cross-stage properties that prevent silent corruption.

These test the shared data contracts and state machine rules that all
services depend on.  Pure unit tests: no DB, no Redis, no async IO.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.lifecycle import (
    IN_FLIGHT,
    TERMINAL,
    InvalidTransition,
    OppStatus,
    _OPP_TRANSITIONS,
    transition,
)
from shared.schemas.events import (
    ArbitrageFoundEvent,
    LiveStatusEvent,
    MarketResolvedEvent,
    MarketUpdatedEvent,
    OptimizationCompleteEvent,
    PairDetectedEvent,
    PortfolioUpdatedEvent,
    SnapshotCreatedEvent,
    TradeExecutedEvent,
)
from shared.schemas.opportunity import (
    MarketPriceComparison,
    OptimalTrades,
    TradeLeg,
)
from shared.schemas.pair import ConstraintMatrix


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _make_opp(status="detected"):
    """Minimal mock opportunity for transition tests."""
    opp = MagicMock()
    opp.status = status
    opp.pending_at = None
    opp.expired_at = None
    return opp


def _sample_trade_leg(**overrides):
    defaults = dict(
        market="A",
        outcome="Yes",
        outcome_index=0,
        side="BUY",
        edge=0.05,
        market_price=0.55,
        fair_price=0.60,
        venue="polymarket",
        fee_rate_bps=None,
    )
    defaults.update(overrides)
    return TradeLeg(**defaults)


def _sample_optimal_trades(**overrides):
    defaults = dict(
        trades=[
            _sample_trade_leg(),
            _sample_trade_leg(market="B", outcome="No", outcome_index=1, side="SELL",
                              edge=0.03, market_price=0.42, fair_price=0.40,
                              fee_rate_bps=150),
        ],
        estimated_profit=0.041234,
        theoretical_profit=0.058901,
        market_a_prices=MarketPriceComparison(
            current=[0.55, 0.45], optimal=[0.60, 0.40],
        ),
        market_b_prices=MarketPriceComparison(
            current=[0.58, 0.42], optimal=[0.60, 0.40],
        ),
    )
    defaults.update(overrides)
    return OptimalTrades(**defaults)


def _sample_constraint_matrix(**overrides):
    defaults = dict(
        type="mutual_exclusion",
        outcomes_a=["Yes", "No"],
        outcomes_b=["Yes", "No"],
        matrix=[[1, 0], [0, 1]],
        profit_bound=0.05,
        correlation="negative",
        implication_direction=None,
        classification_source="llm_vector",
    )
    defaults.update(overrides)
    return ConstraintMatrix(**defaults)


# ═══════════════════════════════════════════════════════════════════
#  1. Lifecycle transition table completeness
# ═══════════════════════════════════════════════════════════════════

class TestLifecycleTransitions:
    """Every legal transition produces documented side-effects;
    illegal transitions raise InvalidTransition."""

    @pytest.mark.parametrize("from_s,to_s,effects", [
        (OppStatus.DETECTED, OppStatus.OPTIMIZED, set()),
        (OppStatus.DETECTED, OppStatus.UNCONVERGED, set()),
        (OppStatus.DETECTED, OppStatus.SKIPPED, set()),
        (OppStatus.DETECTED, OppStatus.EXPIRED, {"expired_at"}),
        (OppStatus.OPTIMIZED, OppStatus.DETECTED, set()),
        (OppStatus.UNCONVERGED, OppStatus.DETECTED, set()),
        (OppStatus.OPTIMIZED, OppStatus.PENDING, {"pending_at"}),
        (OppStatus.UNCONVERGED, OppStatus.PENDING, {"pending_at"}),
        (OppStatus.OPTIMIZED, OppStatus.EXPIRED, {"expired_at"}),
        (OppStatus.UNCONVERGED, OppStatus.EXPIRED, {"expired_at"}),
        (OppStatus.PENDING, OppStatus.SIMULATED, set()),
        (OppStatus.PENDING, OppStatus.OPTIMIZED, set()),
        (OppStatus.PENDING, OppStatus.EXPIRED, {"expired_at"}),
    ])
    def test_legal_transition_and_side_effects(self, from_s, to_s, effects):
        opp = _make_opp(from_s.value)
        transition(opp, to_s)
        assert opp.status == to_s.value

        if "pending_at" in effects:
            assert opp.pending_at is not None
        else:
            assert opp.pending_at is None

        if "expired_at" in effects:
            assert opp.expired_at is not None
        else:
            assert opp.expired_at is None

    def test_transition_table_has_13_entries(self):
        assert len(_OPP_TRANSITIONS) == 13

    @pytest.mark.parametrize("terminal", list(TERMINAL))
    def test_terminal_states_have_no_outgoing_transitions(self, terminal):
        """SIMULATED, EXPIRED, SKIPPED must not allow any outgoing transition."""
        outgoing = [to for (fr, to) in _OPP_TRANSITIONS if fr == terminal]
        assert outgoing == [], f"{terminal} has outgoing transitions: {outgoing}"

    @pytest.mark.parametrize("terminal", list(TERMINAL))
    def test_transition_from_terminal_raises(self, terminal):
        opp = _make_opp(terminal.value)
        for target in OppStatus:
            with pytest.raises(InvalidTransition):
                transition(opp, target)

    def test_reversal_does_not_clear_pending_at(self):
        """PENDING → OPTIMIZED (revert on failure) must NOT wipe pending_at."""
        opp = _make_opp(OppStatus.OPTIMIZED.value)
        transition(opp, OppStatus.PENDING)
        assert opp.pending_at is not None
        saved_ts = opp.pending_at

        transition(opp, OppStatus.OPTIMIZED)
        # pending_at should remain — it was set on the forward transition
        assert opp.pending_at == saved_ts

    def test_re_detection_does_not_clear_expired_at(self):
        """OPTIMIZED → DETECTED (re-optimize) must NOT wipe expired_at
        if it was set on a previous cycle."""
        opp = _make_opp(OppStatus.DETECTED.value)
        # First cycle: expire
        transition(opp, OppStatus.EXPIRED)
        # This opp is now terminal — but a NEW opp on the same pair could
        # go OPTIMIZED → DETECTED. Test on a fresh opp that had expired_at
        # set from a prior partial cycle.
        opp2 = _make_opp(OppStatus.OPTIMIZED.value)
        opp2.expired_at = "2026-01-01T00:00:00Z"  # manually set from prior state
        transition(opp2, OppStatus.DETECTED)
        assert opp2.expired_at == "2026-01-01T00:00:00Z"


# ═══════════════════════════════════════════════════════════════════
#  2. IN_FLIGHT / TERMINAL set consistency
# ═══════════════════════════════════════════════════════════════════

class TestStatusSets:

    def test_in_flight_members(self):
        assert IN_FLIGHT == frozenset({
            OppStatus.DETECTED, OppStatus.OPTIMIZED,
            OppStatus.UNCONVERGED, OppStatus.PENDING,
        })

    def test_terminal_members(self):
        assert TERMINAL == frozenset({
            OppStatus.SIMULATED, OppStatus.EXPIRED, OppStatus.SKIPPED,
        })

    def test_in_flight_and_terminal_are_disjoint(self):
        assert IN_FLIGHT & TERMINAL == frozenset()

    def test_in_flight_and_terminal_cover_all_statuses(self):
        all_statuses = frozenset(OppStatus)
        assert IN_FLIGHT | TERMINAL == all_statuses

    def test_partial_index_matches_in_flight(self):
        """The partial unique index in migration 007 must match IN_FLIGHT exactly.

        If someone adds a new status to IN_FLIGHT without updating the
        migration, the one-per-pair invariant silently breaks.
        """
        index_statuses = {"detected", "pending", "optimized", "unconverged"}
        in_flight_values = {s.value for s in IN_FLIGHT}
        assert in_flight_values == index_statuses


# ═══════════════════════════════════════════════════════════════════
#  3. OptimalTrades JSONB round-trip
# ═══════════════════════════════════════════════════════════════════

class TestOptimalTradesRoundTrip:

    def test_full_round_trip(self):
        original = _sample_optimal_trades()
        dumped = original.model_dump()
        recovered = OptimalTrades.model_validate(dumped)
        assert recovered == original

    def test_float_precision_survives(self):
        original = _sample_optimal_trades(estimated_profit=0.123456)
        recovered = OptimalTrades.model_validate(original.model_dump())
        assert recovered.estimated_profit == 0.123456

    def test_empty_trades_round_trip(self):
        original = _sample_optimal_trades(trades=[])
        recovered = OptimalTrades.model_validate(original.model_dump())
        assert recovered.trades == []
        assert recovered.estimated_profit == original.estimated_profit

    def test_optional_fee_rate_bps_none(self):
        leg = _sample_trade_leg(fee_rate_bps=None)
        original = _sample_optimal_trades(trades=[leg])
        recovered = OptimalTrades.model_validate(original.model_dump())
        assert recovered.trades[0].fee_rate_bps is None

    def test_optional_fee_rate_bps_set(self):
        leg = _sample_trade_leg(fee_rate_bps=1000)
        original = _sample_optimal_trades(trades=[leg])
        recovered = OptimalTrades.model_validate(original.model_dump())
        assert recovered.trades[0].fee_rate_bps == 1000

    def test_venue_default_survives(self):
        leg = _sample_trade_leg()  # venue defaults to "polymarket"
        original = _sample_optimal_trades(trades=[leg])
        recovered = OptimalTrades.model_validate(original.model_dump())
        assert recovered.trades[0].venue == "polymarket"

    def test_json_string_round_trip(self):
        """model_dump_json → model_validate_json (the actual Redis path)."""
        original = _sample_optimal_trades()
        json_str = original.model_dump_json()
        recovered = OptimalTrades.model_validate_json(json_str)
        assert recovered == original


# ═══════════════════════════════════════════════════════════════════
#  4. ConstraintMatrix JSONB round-trip
# ═══════════════════════════════════════════════════════════════════

class TestConstraintMatrixRoundTrip:

    def test_full_round_trip(self):
        original = _sample_constraint_matrix()
        recovered = ConstraintMatrix.model_validate(original.model_dump())
        assert recovered == original

    def test_matrix_stays_list_of_lists(self):
        original = _sample_constraint_matrix(matrix=[[1, 0, 1], [0, 1, 0]])
        dumped = original.model_dump()
        assert isinstance(dumped["matrix"], list)
        assert all(isinstance(row, list) for row in dumped["matrix"])
        recovered = ConstraintMatrix.model_validate(dumped)
        assert recovered.matrix == [[1, 0, 1], [0, 1, 0]]

    def test_matrix_values_stay_int(self):
        original = _sample_constraint_matrix(matrix=[[1, 0], [0, 1]])
        recovered = ConstraintMatrix.model_validate(original.model_dump())
        for row in recovered.matrix:
            for cell in row:
                assert isinstance(cell, int)

    def test_optional_fields_none(self):
        original = _sample_constraint_matrix(
            correlation=None, implication_direction=None, classification_source=None,
        )
        recovered = ConstraintMatrix.model_validate(original.model_dump())
        assert recovered.correlation is None
        assert recovered.implication_direction is None
        assert recovered.classification_source is None

    def test_optional_fields_set(self):
        original = _sample_constraint_matrix(
            correlation="positive",
            implication_direction="a_implies_b",
            classification_source="rule_based",
        )
        recovered = ConstraintMatrix.model_validate(original.model_dump())
        assert recovered.correlation == "positive"
        assert recovered.implication_direction == "a_implies_b"
        assert recovered.classification_source == "rule_based"

    def test_json_string_round_trip(self):
        original = _sample_constraint_matrix()
        json_str = original.model_dump_json()
        recovered = ConstraintMatrix.model_validate_json(json_str)
        assert recovered == original


# ═══════════════════════════════════════════════════════════════════
#  5. Event schema round-trip (all 9 event types)
# ═══════════════════════════════════════════════════════════════════

_EVENT_EXAMPLES = [
    MarketUpdatedEvent(action="sync", count=500),
    SnapshotCreatedEvent(count=100, source="websocket", market_ids=[1, 2, 3]),
    MarketResolvedEvent(market_id=42, resolved_outcome="Yes", source="api", price=0.99),
    PairDetectedEvent(pair_id=1, market_a_id=10, market_b_id=20,
                      dependency_type="mutual_exclusion", confidence=0.92),
    ArbitrageFoundEvent(opportunity_id=1, pair_id=1,
                        type="rebalancing", theoretical_profit=0.05),
    OptimizationCompleteEvent(opportunity_id=1, pair_id=1, status="optimized",
                              iterations=50, bregman_gap=0.0001,
                              estimated_profit=0.04, n_trades=2, converged=True),
    TradeExecutedEvent(trade_id=1, opportunity_id=1, market_id=10,
                       outcome="Yes", side="BUY", size=25.0,
                       vwap_price=0.55, slippage=0.003),
    PortfolioUpdatedEvent(cash=9500.0, positions={"10:Yes": 25.0},
                          cost_basis={"10:Yes": 13.75}, total_value=9525.0,
                          realized_pnl=0.0, unrealized_pnl=25.0,
                          total_trades=10, settled_trades=2, winning_trades=1,
                          positions_in_profit=1, total_positions=1),
    LiveStatusEvent(enabled=True, dry_run=False, active=True,
                    kill_switch=False, adapter_ready=True,
                    last_heartbeat="2026-04-15T14:00:00Z",
                    updated_at="2026-04-15T14:00:00Z"),
]


class TestEventSchemaRoundTrip:

    @pytest.mark.parametrize("event", _EVENT_EXAMPLES,
                             ids=lambda e: type(e).__name__)
    def test_json_round_trip(self, event):
        """model_dump_json → model_validate_json for every event type."""
        json_str = event.model_dump_json()
        recovered = type(event).model_validate_json(json_str)
        assert recovered == event

    @pytest.mark.parametrize("event", _EVENT_EXAMPLES,
                             ids=lambda e: type(e).__name__)
    def test_dict_round_trip(self, event):
        """model_dump → model_validate for every event type."""
        dumped = event.model_dump()
        recovered = type(event).model_validate(dumped)
        assert recovered == event

    def test_market_resolved_optional_price_none(self):
        event = MarketResolvedEvent(market_id=1, resolved_outcome="No",
                                    source="price_threshold")
        recovered = MarketResolvedEvent.model_validate_json(
            event.model_dump_json()
        )
        assert recovered.price is None

    def test_live_status_defaults(self):
        """LiveStatusEvent with all defaults must round-trip."""
        event = LiveStatusEvent()
        recovered = LiveStatusEvent.model_validate_json(
            event.model_dump_json()
        )
        assert recovered.enabled is False
        assert recovered.dry_run is True
        assert recovered.last_heartbeat is None
