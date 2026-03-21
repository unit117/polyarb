"""VWAP (Volume-Weighted Average Price) execution simulation.

Computes the realistic fill price by walking through order book levels,
accounting for the depth consumed at each level.
"""

from decimal import Decimal

import structlog

logger = structlog.get_logger()


def compute_vwap(
    order_book: dict | None,
    side: str,
    size: float,
    midpoint: float,
) -> dict:
    """Compute VWAP fill price for a given order size.

    Args:
        order_book: Order book dict with "bids" and "asks" lists of [price, size].
        side: "BUY" or "SELL".
        size: Target fill size in shares.
        midpoint: Midpoint price fallback if no order book.

    Returns:
        Dict with vwap_price, slippage, filled_size, levels_consumed.
    """
    if not order_book:
        return _midpoint_fill(midpoint, side, size)

    # BUY walks up the asks, SELL walks down the bids
    levels = order_book.get("asks" if side == "BUY" else "bids", [])
    if not levels:
        return _midpoint_fill(midpoint, side, size)

    remaining = size
    total_cost = 0.0
    levels_consumed = 0

    for level in levels:
        if remaining <= 0:
            break

        price = float(level[0]) if isinstance(level, (list, tuple)) else float(level.get("price", 0))
        available = float(level[1]) if isinstance(level, (list, tuple)) else float(level.get("size", 0))

        fill_at_level = min(remaining, available)
        total_cost += fill_at_level * price
        remaining -= fill_at_level
        levels_consumed += 1

    filled = size - remaining
    if filled <= 0:
        return _midpoint_fill(midpoint, side, size)

    vwap_price = total_cost / filled
    slippage = abs(vwap_price - midpoint) / midpoint if midpoint > 0 else 0.0

    return {
        "vwap_price": round(vwap_price, 6),
        "slippage": round(slippage, 6),
        "filled_size": round(filled, 6),
        "levels_consumed": levels_consumed,
        "partial_fill": remaining > 0,
    }


def _midpoint_fill(midpoint: float, side: str, size: float) -> dict:
    """Fallback fill at midpoint with estimated slippage."""
    # Apply a small estimated slippage when no book data
    estimated_slippage = 0.005
    if side == "BUY":
        vwap_price = midpoint * (1 + estimated_slippage)
    else:
        vwap_price = midpoint * (1 - estimated_slippage)

    return {
        "vwap_price": round(vwap_price, 6),
        "slippage": estimated_slippage,
        "filled_size": size,
        "levels_consumed": 0,
        "partial_fill": False,
    }
