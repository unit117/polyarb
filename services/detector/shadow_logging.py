"""Helpers for durable live shadow candidate logging."""
from __future__ import annotations

from typing import Any

SILVER_FAILURE_SIGNATURES = {
    "mutual_exclusion: neither market has event_id": "mutual_exclusion_missing_event_id",
    "mutual_exclusion: different event_ids": "mutual_exclusion_different_event_ids",
    "mutual_exclusion: identical questions suggest different event instances": "mutual_exclusion_identical_questions",
}


def extract_order_book_summary(
    order_book: dict | None,
    *,
    depth_levels: int = 5,
) -> dict[str, float | None]:
    """Summarize top-of-book spread and visible depth for review rows."""
    if not isinstance(order_book, dict):
        return {
            "best_bid": None,
            "best_ask": None,
            "spread": None,
            "visible_depth": None,
        }

    bids = order_book.get("bids") or []
    asks = order_book.get("asks") or []

    best_bid = _level_price(bids[0]) if bids else None
    best_ask = _level_price(asks[0]) if asks else None
    spread = (
        round(best_ask - best_bid, 6)
        if best_bid is not None and best_ask is not None
        else None
    )

    visible_depth = 0.0
    has_depth = False
    for level in list(bids[:depth_levels]) + list(asks[:depth_levels]):
        size = _level_size(level)
        if size is not None:
            visible_depth += size
            has_depth = True

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "visible_depth": round(visible_depth, 6) if has_depth else None,
    }


def derive_silver_failure_signature(reasons: list[str] | None) -> str | None:
    """Bucket verification failures that match the current silver-set blockers."""
    if not reasons:
        return None

    for reason in reasons:
        for prefix, signature in SILVER_FAILURE_SIGNATURES.items():
            if reason.startswith(prefix):
                return signature
    return None


def preview_trade_gates(
    constraint: dict | None,
    prices_a: dict | None,
    prices_b: dict | None,
    *,
    venue_a: str = "polymarket",
    venue_b: str = "polymarket",
    min_edge: float = 0.03,
    max_iterations: int = 200,
    gap_tolerance: float = 0.001,
    ip_timeout_ms: int = 5000,
    skip_conditional: bool = True,
) -> dict[str, Any]:
    """Run the current optimizer/trade gates without mutating DB state."""
    try:
        import numpy as np
        from services.optimizer.frank_wolfe import optimize
        from services.optimizer.trades import compute_trades
    except ImportError:
        return {"status": "optimizer_unavailable", "would_trade": False}

    if not constraint:
        return {"status": "no_constraints", "would_trade": False}
    if prices_a is None or prices_b is None:
        return {"status": "no_prices", "would_trade": False}

    dependency_type = constraint.get("type", "")
    outcomes_a = constraint.get("outcomes_a", [])
    outcomes_b = constraint.get("outcomes_b", [])
    feasibility = constraint.get("matrix", [])

    if not outcomes_a or not outcomes_b or not feasibility:
        return {"status": "invalid_constraints", "would_trade": False}

    if dependency_type == "conditional":
        is_unconstrained = all(
            feasibility[i][j] == 1
            for i in range(len(feasibility))
            for j in range(len(feasibility[0]))
        )
        source = constraint.get("classification_source", "")
        vector_with_constraints = source == "llm_vector" and not is_unconstrained
        if is_unconstrained or (skip_conditional and not vector_with_constraints):
            return {
                "status": "optimizer_rejected",
                "would_trade": False,
                "rejection_reason": "conditional_unconstrained",
                "trade_count": 0,
            }

    p_a = np.array([float(prices_a.get(o, 0.5)) for o in outcomes_a], dtype=np.float64)
    p_b = np.array([float(prices_b.get(o, 0.5)) for o in outcomes_b], dtype=np.float64)

    result = optimize(
        prices_a=p_a,
        prices_b=p_b,
        feasibility_matrix=feasibility,
        max_iterations=max_iterations,
        gap_tolerance=gap_tolerance,
        ip_timeout_ms=ip_timeout_ms,
    )
    trade_info = compute_trades(
        result,
        outcomes_a,
        outcomes_b,
        theoretical_profit=float(constraint.get("profit_bound", 0.0)),
        min_edge=min_edge,
        venue_a=venue_a,
        venue_b=venue_b,
    )
    trade_count = len(trade_info["trades"])
    would_trade = trade_count > 0

    return {
        "status": "would_trade" if would_trade else "optimizer_rejected",
        "would_trade": would_trade,
        "trade_count": trade_count,
        "estimated_profit": float(trade_info.get("estimated_profit", 0.0)),
        "max_edge": trade_info.get("max_edge"),
        "rejection_reason": trade_info.get("rejection_reason"),
        "iterations": result.iterations,
        "gap": result.final_gap,
    }


def _level_price(level: Any) -> float | None:
    if isinstance(level, (list, tuple)) and level:
        return _as_float(level[0])
    if isinstance(level, dict):
        return _as_float(level.get("price"))
    return None


def _level_size(level: Any) -> float | None:
    if isinstance(level, (list, tuple)) and len(level) > 1:
        return _as_float(level[1])
    if isinstance(level, dict):
        return _as_float(level.get("size"))
    return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
