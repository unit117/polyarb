"""Backtest engine: replays the full PolyArb pipeline over historical data.

After running backfill_history.py to populate PriceSnapshots, this script
steps through the data day-by-day, running the full pipeline at each step:

  1. Detection — find similar pairs & classify (uses existing pairs + rescan)
  2. Optimization — Frank-Wolfe on each detected opportunity
  3. Simulation — paper-trade the optimized opportunities

At each day, only snapshots up to that day are visible to the pipeline.

Usage:
    python -m scripts.backtest [--days 30] [--capital 10000] [--max-position 100]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import structlog
from sqlalchemy import delete, select, func, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

sys.path.insert(0, ".")

from shared.config import settings, polymarket_fee
from shared.db import SessionFactory, init_db
from shared.models import (
    ArbitrageOpportunity,
    Market,
    MarketPair,
    PaperTrade,
    PortfolioSnapshot,
    PriceSnapshot,
)
from services.detector.constraints import build_constraint_matrix, build_constraint_matrix_from_vectors
from services.detector.verification import verify_pair
from services.optimizer.frank_wolfe import optimize
from services.optimizer.trades import compute_trades
from services.simulator.portfolio import Portfolio
from services.simulator.vwap import compute_vwap

RESOLUTION_THRESHOLD = 0.98

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════
#  Time-bounded query helpers
# ═══════════════════════════════════════════════════════════════════

async def get_prices_at(session, market_id: int, as_of: datetime) -> dict | None:
    """Fetch the most recent PriceSnapshot for a market at or before `as_of`."""
    result = await session.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .where(PriceSnapshot.timestamp <= as_of)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    snap = result.scalar_one_or_none()
    return snap.prices if snap else None


async def get_snapshot_at(session, market_id: int, as_of: datetime):
    """Like get_prices_at but returns the full PriceSnapshot row."""
    result = await session.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .where(PriceSnapshot.timestamp <= as_of)
        .order_by(PriceSnapshot.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _market_is_resolved_as_of(market: Market | None, as_of: datetime) -> bool:
    """Return True when a market is authoritatively resolved by `as_of`."""
    return bool(
        market
        and market.resolved_outcome
        and market.resolved_at
        and market.resolved_at <= as_of
    )


def _resolved_pair_markets(
    market_a: Market | None,
    market_b: Market | None,
    as_of: datetime,
) -> list[dict]:
    """Collect resolved pair legs for logging and guard checks."""
    resolved = []
    for market in (market_a, market_b):
        if not _market_is_resolved_as_of(market, as_of):
            continue
        resolved.append(
            {
                "market_id": market.id,
                "resolved_outcome": market.resolved_outcome,
                "resolved_at": market.resolved_at.isoformat() if market.resolved_at else None,
            }
        )
    return resolved


# Public aliases for test imports
is_resolved_as_of = _market_is_resolved_as_of


def check_pair_resolved(
    market_a: Market | None,
    market_b: Market | None,
    as_of: datetime,
) -> list[int]:
    """Return list of resolved market IDs for the pair (empty = safe to trade)."""
    resolved = []
    if _market_is_resolved_as_of(market_a, as_of):
        resolved.append(market_a.id)
    if _market_is_resolved_as_of(market_b, as_of):
        resolved.append(market_b.id)
    return resolved


# ═══════════════════════════════════════════════════════════════════
#  Detection step (time-bounded)
# ═══════════════════════════════════════════════════════════════════

async def detect_opportunities(
    session,
    pairs: list[MarketPair],
    as_of: datetime,
    resolved_skip_logged: set[int] | None = None,
    pair_ids: set[int] | None = None,
) -> list[int]:
    """Re-evaluate existing pairs with prices as-of `as_of`.

    Returns list of newly created ArbitrageOpportunity IDs.
    """
    opp_ids = []

    for pair in pairs:
        if not pair.verified:
            continue
        if pair_ids is not None and pair.id not in pair_ids:
            continue

        market_a = await session.get(Market, pair.market_a_id)
        market_b = await session.get(Market, pair.market_b_id)
        if not market_a or not market_b:
            continue

        resolved_markets = _resolved_pair_markets(market_a, market_b, as_of)
        if resolved_markets:
            if resolved_skip_logged is None or pair.id not in resolved_skip_logged:
                if resolved_skip_logged is not None:
                    resolved_skip_logged.add(pair.id)
                log.warning(
                    "resolved_market_skipped",
                    phase="detect",
                    pair_id=pair.id,
                    market_a_id=pair.market_a_id,
                    market_b_id=pair.market_b_id,
                    as_of=as_of.isoformat(),
                    resolved_markets=resolved_markets,
                )
            continue

        prices_a = await get_prices_at(session, pair.market_a_id, as_of)
        prices_b = await get_prices_at(session, pair.market_b_id, as_of)

        if not prices_a or not prices_b:
            continue

        constraint = pair.constraint_matrix
        if not constraint:
            continue

        outcomes_a = constraint.get("outcomes_a", [])
        outcomes_b = constraint.get("outcomes_b", [])

        market_a_dict = {
            "event_id": market_a.event_id,
            "question": market_a.question,
            "outcomes": market_a.outcomes if isinstance(market_a.outcomes, list) else [],
        }
        market_b_dict = {
            "event_id": market_b.event_id,
            "question": market_b.question,
            "outcomes": market_b.outcomes if isinstance(market_b.outcomes, list) else [],
        }
        imp_direction = pair.implication_direction or constraint.get("implication_direction")
        verification = verify_pair(
            dependency_type=pair.dependency_type,
            market_a=market_a_dict,
            market_b=market_b_dict,
            prices_a=prices_a,
            prices_b=prices_b,
            confidence=pair.confidence,
            correlation=constraint.get("correlation"),
            implication_direction=imp_direction,
        )
        if not verification["verified"]:
            continue

        # Recompute profit bound with this day's prices — use vectors if stored
        if pair.resolution_vectors:
            fresh = build_constraint_matrix_from_vectors(
                pair.resolution_vectors, outcomes_a, outcomes_b,
                dependency_type=pair.dependency_type,
                prices_a=prices_a, prices_b=prices_b,
                correlation=constraint.get("correlation"),
                implication_direction=imp_direction,
            )
        else:
            fresh = build_constraint_matrix(
                pair.dependency_type, outcomes_a, outcomes_b, prices_a, prices_b,
                correlation=constraint.get("correlation"),
                implication_direction=imp_direction,
            )

        profit = fresh.get("profit_bound", 0.0)
        if profit <= 0:
            continue

        # Update stored constraint matrix so optimizer reads fresh feasibility
        pair.constraint_matrix = fresh

        opp = ArbitrageOpportunity(
            pair_id=pair.id,
            type="rebalancing",
            theoretical_profit=Decimal(str(profit)),
            status="detected",
            timestamp=as_of,
            dependency_type=pair.dependency_type,
        )
        session.add(opp)
        await session.flush()
        opp_ids.append(opp.id)

    return opp_ids


# ═══════════════════════════════════════════════════════════════════
#  Optimization step (time-bounded)
# ═══════════════════════════════════════════════════════════════════

async def optimize_opportunity(session, opp_id: int, as_of: datetime) -> dict:
    """Run Frank-Wolfe on a detected opportunity using prices as-of `as_of`."""
    opp = await session.get(ArbitrageOpportunity, opp_id)
    if not opp or opp.status != "detected":
        return {"status": "skipped"}

    pair = await session.get(MarketPair, opp.pair_id)
    if not pair or not pair.constraint_matrix:
        return {"status": "no_constraints"}

    constraint = pair.constraint_matrix
    outcomes_a = constraint.get("outcomes_a", [])
    outcomes_b = constraint.get("outcomes_b", [])

    if not outcomes_a or not outcomes_b:
        return {"status": "invalid_constraints"}

    prices_a = await get_prices_at(session, pair.market_a_id, as_of)
    prices_b = await get_prices_at(session, pair.market_b_id, as_of)

    if prices_a is None or prices_b is None:
        return {"status": "no_prices"}

    # Rebuild constraint matrix with current prices (same as detection step)
    # to ensure the optimizer gets a proper feasibility matrix + profit bound
    imp_direction = pair.implication_direction or constraint.get("implication_direction")
    if pair.resolution_vectors:
        fresh = build_constraint_matrix_from_vectors(
            pair.resolution_vectors, outcomes_a, outcomes_b,
            dependency_type=pair.dependency_type,
            prices_a=prices_a, prices_b=prices_b,
            correlation=constraint.get("correlation"),
            implication_direction=imp_direction,
        )
    else:
        fresh = build_constraint_matrix(
            pair.dependency_type, outcomes_a, outcomes_b, prices_a, prices_b,
            correlation=constraint.get("correlation"),
            implication_direction=imp_direction,
        )

    feasibility = fresh.get("matrix", [])
    if not feasibility:
        return {"status": "invalid_constraints"}

    p_a = np.array([float(prices_a.get(o, 0.5)) for o in outcomes_a], dtype=np.float64)
    p_b = np.array([float(prices_b.get(o, 0.5)) for o in outcomes_b], dtype=np.float64)

    result = optimize(
        prices_a=p_a,
        prices_b=p_b,
        feasibility_matrix=feasibility,
        max_iterations=settings.fw_max_iterations,
        gap_tolerance=settings.fw_gap_tolerance,
        ip_timeout_ms=settings.fw_ip_timeout_ms,
    )

    theoretical_profit = float(fresh.get("profit_bound", 0.0))
    trade_info = compute_trades(
        result,
        outcomes_a,
        outcomes_b,
        theoretical_profit=theoretical_profit,
        min_edge=settings.optimizer_min_edge,
    )

    opp.fw_iterations = result.iterations
    opp.bregman_gap = result.final_gap
    opp.estimated_profit = Decimal(str(trade_info["estimated_profit"]))
    opp.optimal_trades = trade_info
    opp.status = "optimized" if result.converged else "unconverged"

    return {
        "status": opp.status,
        "estimated_profit": trade_info["estimated_profit"],
        "trades": len(trade_info["trades"]),
    }


# ═══════════════════════════════════════════════════════════════════
#  Simulation step (time-bounded)
# ═══════════════════════════════════════════════════════════════════

async def simulate_opportunity(
    session,
    opp_id: int,
    portfolio: Portfolio,
    as_of: datetime,
    max_position_size: float,
    resolved_skip_logged: set[int] | None = None,
) -> dict:
    """Execute paper trades for an optimized opportunity using prices as-of `as_of`."""
    opp = await session.get(ArbitrageOpportunity, opp_id)
    if not opp or opp.status not in ("optimized", "unconverged"):
        return {"status": "skipped"}

    if not opp.optimal_trades or not opp.optimal_trades.get("trades"):
        return {"status": "no_trades"}

    pair = await session.get(MarketPair, opp.pair_id)
    if not pair:
        return {"status": "no_pair"}

    market_a = await session.get(Market, pair.market_a_id)
    market_b = await session.get(Market, pair.market_b_id)
    resolved_markets = _resolved_pair_markets(market_a, market_b, as_of)
    if resolved_markets:
        if resolved_skip_logged is None or pair.id not in resolved_skip_logged:
            if resolved_skip_logged is not None:
                resolved_skip_logged.add(pair.id)
            log.warning(
                "resolved_market_skipped",
                phase="simulate",
                pair_id=pair.id,
                opportunity_id=opp.id,
                market_a_id=pair.market_a_id,
                market_b_id=pair.market_b_id,
                as_of=as_of.isoformat(),
                resolved_markets=resolved_markets,
            )
        return {"status": "skipped", "reason": "resolved_market", "trades_executed": 0}

    trades_executed = 0

    # Half-Kelly sizing — same formula as live pipeline
    net_profit = opp.optimal_trades.get("estimated_profit", 0)
    if net_profit <= 0:
        opp.status = "simulated"
        return {"status": "simulated", "trades_executed": 0}
    kelly_fraction = min(net_profit * 0.5, 1.0)

    # Drawdown scaling — same as live pipeline
    total_value = float(portfolio.cash) + sum(
        float(s) * 0.5 for s in portfolio.positions.values()  # rough mark
    )
    drawdown = 1.0 - (total_value / float(portfolio.initial_capital))
    if drawdown > 0.05:
        drawdown_scale = max(0.5, 1.0 - (drawdown - 0.05) / 0.10)
        kelly_fraction *= drawdown_scale

    base_size = kelly_fraction * max_position_size

    # Pass 1: compute fills for all legs to determine proportional scaling
    leg_fills = []
    for trade in opp.optimal_trades["trades"]:
        market = market_a if trade["market"] == "A" else market_b
        if not market:
            leg_fills.append(None)
            continue

        snapshot = await get_snapshot_at(session, market.id, as_of)
        order_book = snapshot.order_book if snapshot else None
        midpoint = trade.get("market_price", 0.5)

        size = base_size
        fill = compute_vwap(order_book, trade["side"], size, midpoint)
        leg_fills.append({"fill": fill, "requested_size": size, "market": market, "midpoint": midpoint})

    # Cross-leg proportional scaling: match the smallest fill ratio
    fill_ratios = []
    for lf in leg_fills:
        if lf and lf["requested_size"] > 0:
            fill_ratios.append(lf["fill"]["filled_size"] / lf["requested_size"])
    min_ratio = min(fill_ratios) if fill_ratios else 1.0

    for i, trade in enumerate(opp.optimal_trades["trades"]):
        lf = leg_fills[i]
        if not lf:
            continue

        fill = lf["fill"]
        market = lf["market"]
        midpoint = lf["midpoint"]

        # Scale to match the smallest fill ratio across all legs
        if min_ratio < 1.0 and lf["requested_size"] > 0:
            scaled_size = lf["requested_size"] * min_ratio
            if scaled_size < fill["filled_size"]:
                fill = dict(fill)  # copy to avoid mutating
                fill["filled_size"] = round(scaled_size, 6)

        fees = polymarket_fee(fill["vwap_price"], trade["side"]) * fill["filled_size"]

        # Track rebalancing exit PnL before executing (match live pipeline)
        key = f"{market.id}:{trade['outcome']}"
        existing_position = portfolio.positions.get(key, Decimal("0"))
        is_exit = (
            (trade["side"] == "SELL" and existing_position > 0)
            or (trade["side"] == "BUY" and existing_position < 0)
        )
        pre_trade_cost = portfolio.cost_basis.get(key, Decimal("0"))

        result = portfolio.execute_trade(
            market_id=market.id,
            outcome=trade["outcome"],
            side=trade["side"],
            size=fill["filled_size"],
            vwap_price=fill["vwap_price"],
            fees=fees,
        )

        # Realize PnL for the portion that closed an existing position
        if is_exit and existing_position != 0 and result["executed"]:
            close_size = min(
                abs(existing_position), Decimal(str(fill["filled_size"]))
            )
            avg_entry = pre_trade_cost / abs(existing_position)
            exit_price = Decimal(str(fill["vwap_price"]))

            # Subtract exit fees proportional to close size
            exit_fees = Decimal(str(fees)) * close_size / Decimal(str(fill["filled_size"])) if fill["filled_size"] > 0 else Decimal("0")

            if existing_position > 0:
                realized = (exit_price - avg_entry) * close_size - exit_fees
            else:
                realized = (avg_entry - exit_price) * close_size - exit_fees

            portfolio.realized_pnl += realized
            if realized > 0:
                portfolio.winning_trades += 1

        if not result["executed"]:
            continue

        paper_trade = PaperTrade(
            opportunity_id=opp.id,
            market_id=market.id,
            outcome=trade["outcome"],
            side=trade["side"],
            size=Decimal(str(fill["filled_size"])),
            entry_price=Decimal(str(midpoint)),
            vwap_price=Decimal(str(fill["vwap_price"])),
            slippage=Decimal(str(fill["slippage"])),
            fees=Decimal(str(fees)),
            executed_at=as_of,
            status="filled",
        )
        session.add(paper_trade)
        trades_executed += 1

    opp.status = "simulated"
    return {"status": "simulated", "trades_executed": trades_executed}


# ═══════════════════════════════════════════════════════════════════
#  Settlement step (time-bounded)
# ═══════════════════════════════════════════════════════════════════

async def settle_resolved_positions(
    session, portfolio: Portfolio, as_of: datetime,
    use_authoritative: bool = False,
) -> dict:
    """Close positions in resolved markets.

    Two modes:
    - Authoritative (use_authoritative=True): uses markets.resolved_outcome
      from the DB — the same path the live simulator uses. Preferred when
      authoritative outcomes have been imported (E1).
    - Heuristic (default): falls back to price >= 0.98 threshold.
    """
    stats = {"settled": 0, "pnl_realized": 0.0}
    if not portfolio.positions:
        return stats

    # Collect unique market IDs from open positions
    market_ids: dict[int, list[str]] = {}
    for key in list(portfolio.positions.keys()):
        parts = key.split(":")
        if len(parts) != 2:
            continue
        mid = int(parts[0])
        market_ids.setdefault(mid, []).append(key)

    for market_id, position_keys in market_ids.items():
        winning_outcome = None

        if use_authoritative:
            # Authoritative: check markets.resolved_outcome directly
            market = await session.get(Market, market_id)
            if (
                market
                and market.resolved_outcome
                and market.resolved_at
                and market.resolved_at <= as_of
            ):
                winning_outcome = market.resolved_outcome
        else:
            # Heuristic: price threshold
            snap = await get_snapshot_at(session, market_id, as_of)
            if not snap or not snap.prices:
                continue
            for outcome, price_str in snap.prices.items():
                try:
                    if float(price_str) >= RESOLUTION_THRESHOLD:
                        winning_outcome = outcome
                        break
                except (ValueError, TypeError):
                    continue

        if not winning_outcome:
            continue

        # Settle all positions in this market
        for key in position_keys:
            position_outcome = key.split(":")[1]
            settlement_price = 1.0 if position_outcome == winning_outcome else 0.0

            close_result = portfolio.close_position(key, settlement_price)
            if not close_result["closed"]:
                continue

            stats["settled"] += 1
            stats["pnl_realized"] += close_result["pnl"]

            paper_trade = PaperTrade(
                opportunity_id=None,
                market_id=market_id,
                outcome=position_outcome,
                side="SETTLE",
                size=Decimal(str(close_result["shares"])),
                entry_price=Decimal(str(settlement_price)),
                vwap_price=Decimal(str(settlement_price)),
                slippage=Decimal("0"),
                fees=Decimal("0"),
                executed_at=as_of,
                status="settled",
            )
            session.add(paper_trade)

    return stats


# ═══════════════════════════════════════════════════════════════════
#  Snapshot portfolio value at a point in time
# ═══════════════════════════════════════════════════════════════════

async def snapshot_portfolio(session, portfolio: Portfolio, as_of: datetime) -> dict:
    """Compute portfolio value using prices as-of `as_of` and persist snapshot."""
    current_prices: dict[str, float] = {}
    for key in portfolio.positions:
        parts = key.split(":")
        if len(parts) != 2:
            continue
        market_id = int(parts[0])
        outcome = parts[1]
        snap = await get_snapshot_at(session, market_id, as_of)
        if snap and snap.midpoints:
            price = snap.midpoints.get(outcome)
            if price is not None:
                current_prices[key] = float(price)
        elif snap and snap.prices:
            price = snap.prices.get(outcome)
            if price is not None:
                current_prices[key] = float(price)

    snap_dict = portfolio.to_snapshot_dict(current_prices)

    ps = PortfolioSnapshot(
        timestamp=as_of,
        cash=Decimal(str(snap_dict["cash"])),
        positions=snap_dict["positions"],
        total_value=Decimal(str(snap_dict["total_value"])),
        realized_pnl=Decimal(str(snap_dict["realized_pnl"])),
        unrealized_pnl=Decimal(str(snap_dict["unrealized_pnl"])),
        total_trades=snap_dict["total_trades"],
        winning_trades=snap_dict["winning_trades"],
        settled_trades=snap_dict["settled_trades"],
    )
    session.add(ps)
    return snap_dict


# ═══════════════════════════════════════════════════════════════════
#  Main backtest loop
# ═══════════════════════════════════════════════════════════════════

async def run_backtest(
    days: int = 30,
    initial_capital: float = 10000.0,
    max_position_size: float = 100.0,
    clean: bool = True,
    use_authoritative: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
    pair_ids: set[int] | None = None,
    pair_file: str | None = None,
) -> list[dict]:
    """Run the full backtest and return daily results."""
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )
    await init_db()

    # ── Optionally clean previous backtest artifacts ──────────────
    if clean:
        log.info("cleaning_previous_backtest")
        async with SessionFactory() as session:
            await session.execute(delete(PortfolioSnapshot))
            await session.execute(delete(PaperTrade))
            # Only delete backtest-generated opportunities (keep pair structure)
            await session.execute(
                delete(ArbitrageOpportunity)
            )
            await session.commit()

    # ── Determine date range from available snapshots ─────────────
    async with SessionFactory() as session:
        earliest = await session.scalar(select(func.min(PriceSnapshot.timestamp)))
        latest = await session.scalar(select(func.max(PriceSnapshot.timestamp)))

        if not earliest or not latest:
            log.error("no_price_data", hint="Run backfill_history.py first")
            return []

        # Override date range if explicit bounds given
        if start_date:
            earliest = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        if end_date:
            latest = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

        # Load verified market pairs only
        result = await session.execute(
            select(MarketPair).where(MarketPair.verified == True)  # noqa: E712
        )
        pairs = list(result.scalars().all())

    # ── Load pair-id filter from file if given ────────────────────
    if pair_file and not pair_ids:
        pair_ids = set()
        pf = Path(pair_file)
        if pf.suffix == ".json":
            data = json.loads(pf.read_text())
            for item in data:
                if isinstance(item, int):
                    pair_ids.add(item)
                elif isinstance(item, dict) and "pair_id" in item:
                    pair_ids.add(int(item["pair_id"]))
        else:
            # Plain text: one pair ID per line
            for line in pf.read_text().splitlines():
                line = line.strip()
                if line and line.isdigit():
                    pair_ids.add(int(line))
        log.info("pair_filter_loaded", pair_file=pair_file, pair_count=len(pair_ids))

    if not pairs:
        log.error("no_market_pairs", hint="Run the detector first to find pairs")
        return []

    effective_pairs = len(pairs)
    if pair_ids:
        effective_pairs = sum(1 for p in pairs if p.id in pair_ids)

    log.info(
        "backtest_start",
        data_range=f"{earliest.date()} → {latest.date()}",
        pairs=len(pairs),
        effective_pairs=effective_pairs,
        initial_capital=initial_capital,
        max_position=max_position_size,
        fee_model="polymarket",
        settlement="authoritative" if use_authoritative else "heuristic",
    )

    # ── Generate daily time steps ─────────────────────────────────
    start_date = earliest.replace(hour=23, minute=59, second=59)
    end_date = latest
    current = start_date
    time_steps = []
    while current <= end_date:
        time_steps.append(current)
        current += timedelta(days=1)

    if not time_steps:
        time_steps = [end_date]

    log.info("time_steps", count=len(time_steps))

    # ── Initialize portfolio ──────────────────────────────────────
    portfolio = Portfolio(initial_capital)
    daily_results = []
    resolved_skip_logged: set[int] = set()

    for step_idx, as_of in enumerate(time_steps):
        day_label = as_of.strftime("%Y-%m-%d")
        day_stats = {
            "date": day_label,
            "step": step_idx + 1,
            "opportunities_detected": 0,
            "opportunities_optimized": 0,
            "trades_executed": 0,
            "settled": 0,
            "settlement_pnl": 0.0,
            "cash": 0.0,
            "total_value": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "positions": 0,
        }

        async with SessionFactory() as session:
            # ── Step 1: Settlement (before detect to prevent same-day reopen) ──
            try:
                settle_stats = await settle_resolved_positions(
                    session, portfolio, as_of,
                    use_authoritative=use_authoritative,
                )
                day_stats["settled"] = settle_stats["settled"]
                day_stats["settlement_pnl"] = round(settle_stats["pnl_realized"], 2)
            except Exception:
                log.exception("backtest_settlement_error", day=day_label)

            # ── Step 2: Detection ─────────────────────────────────
            opp_ids = await detect_opportunities(
                session,
                pairs,
                as_of,
                resolved_skip_logged=resolved_skip_logged,
                pair_ids=pair_ids,
            )
            day_stats["opportunities_detected"] = len(opp_ids)

            # ── Step 3: Optimization ──────────────────────────────
            optimized = 0
            for opp_id in opp_ids:
                try:
                    res = await optimize_opportunity(session, opp_id, as_of)
                    if res["status"] in ("optimized", "unconverged"):
                        optimized += 1
                except Exception:
                    log.exception("backtest_optimize_error", opp_id=opp_id, day=day_label)
            day_stats["opportunities_optimized"] = optimized

            # ── Step 4: Simulation ────────────────────────────────
            total_trades = 0
            for opp_id in opp_ids:
                try:
                    res = await simulate_opportunity(
                        session, opp_id, portfolio, as_of,
                        max_position_size,
                        resolved_skip_logged=resolved_skip_logged,
                    )
                    if res.get("trades_executed"):
                        total_trades += res["trades_executed"]
                except Exception:
                    log.exception("backtest_simulate_error", opp_id=opp_id, day=day_label)
            day_stats["trades_executed"] = total_trades

            # ── Snapshot portfolio ────────────────────────────────
            snap = await snapshot_portfolio(session, portfolio, as_of)
            day_stats["cash"] = round(snap["cash"], 2)
            day_stats["total_value"] = round(snap["total_value"], 2)
            day_stats["realized_pnl"] = round(snap["realized_pnl"], 2)
            day_stats["unrealized_pnl"] = round(snap["unrealized_pnl"], 2)
            day_stats["positions"] = len(portfolio.positions)

            await session.commit()

        daily_results.append(day_stats)

        log.info(
            "backtest_day",
            **day_stats,
        )

    # ── Final summary ─────────────────────────────────────────────
    final = daily_results[-1] if daily_results else {}
    total_return = ((final.get("total_value", initial_capital) / initial_capital) - 1) * 100

    total_trades = sum(d["trades_executed"] for d in daily_results)
    total_opps = sum(d["opportunities_detected"] for d in daily_results)
    total_settled = sum(d.get("settled", 0) for d in daily_results)

    summary = {
        "period": f"{time_steps[0].strftime('%Y-%m-%d')} → {time_steps[-1].strftime('%Y-%m-%d')}",
        "days": len(time_steps),
        "initial_capital": initial_capital,
        "final_value": final.get("total_value", initial_capital),
        "total_return_pct": round(total_return, 2),
        "realized_pnl": final.get("realized_pnl", 0),
        "unrealized_pnl": final.get("unrealized_pnl", 0),
        "total_trades": total_trades,
        "total_opportunities": total_opps,
        "total_settled": total_settled,
        "open_positions": final.get("positions", 0),
        "max_drawdown_pct": _compute_max_drawdown(daily_results, initial_capital),
        "sharpe_ratio": _compute_sharpe(daily_results, initial_capital),
    }

    log.info("backtest_complete", **summary)

    return daily_results


def _compute_max_drawdown(results: list[dict], initial_capital: float) -> float:
    """Compute max drawdown as a percentage."""
    if not results:
        return 0.0
    peak = initial_capital
    max_dd = 0.0
    for r in results:
        val = r.get("total_value", initial_capital)
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def _compute_sharpe(results: list[dict], initial_capital: float) -> float:
    """Compute annualized Sharpe ratio from daily returns."""
    if len(results) < 2:
        return 0.0

    values = [initial_capital] + [r.get("total_value", initial_capital) for r in results]
    returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            returns.append((values[i] - values[i - 1]) / values[i - 1])

    if not returns:
        return 0.0

    avg = sum(returns) / len(returns)
    if len(returns) < 2:
        return 0.0
    std = (sum((r - avg) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5

    if std == 0:
        return 0.0

    # Annualize: sqrt(365) * daily_sharpe
    return round((avg / std) * (365 ** 0.5), 2)


# ═══════════════════════════════════════════════════════════════════
#  Report generation
# ═══════════════════════════════════════════════════════════════════

def generate_report(results: list[dict], output_path: str = "backtest_report.json") -> str:
    """Write results to JSON and print a summary table."""
    if not results:
        print("\n  No results to report.\n")
        return ""

    initial = 10000.0  # default
    final_val = results[-1].get("total_value", initial)
    total_return = ((final_val / initial) - 1) * 100

    # ASCII table
    print("\n" + "=" * 80)
    print("  BACKTEST RESULTS")
    print("=" * 80)
    print(f"  Period:           {results[0]['date']} → {results[-1]['date']}")
    print(f"  Days:             {len(results)}")
    print(f"  Initial Capital:  ${initial:,.2f}")
    print(f"  Final Value:      ${final_val:,.2f}")
    print(f"  Total Return:     {total_return:+.2f}%")
    print(f"  Realized PnL:     ${results[-1].get('realized_pnl', 0):,.2f}")
    print(f"  Unrealized PnL:   ${results[-1].get('unrealized_pnl', 0):,.2f}")
    print(f"  Total Trades:     {sum(d['trades_executed'] for d in results)}")
    print(f"  Settled:          {sum(d.get('settled', 0) for d in results)}")
    print(f"  Opportunities:    {sum(d['opportunities_detected'] for d in results)}")
    print(f"  Max Drawdown:     {_compute_max_drawdown(results, initial):.2f}%")
    print(f"  Sharpe Ratio:     {_compute_sharpe(results, initial):.2f}")
    print("=" * 80)

    print(f"\n  {'Date':<12} {'Value':>10} {'PnL':>10} {'Trades':>7} {'Opps':>6} {'Pos':>5}")
    print("  " + "-" * 52)
    for r in results:
        pnl = r["total_value"] - initial
        print(
            f"  {r['date']:<12} "
            f"${r['total_value']:>9,.2f} "
            f"{'$':>1}{pnl:>8,.2f} "
            f"{r['trades_executed']:>7} "
            f"{r['opportunities_detected']:>6} "
            f"{r['positions']:>5}"
        )
    print()

    # Write JSON
    with open(output_path, "w") as f:
        json.dump(
            {"daily": results, "summary": {
                "period": f"{results[0]['date']} → {results[-1]['date']}",
                "days": len(results),
                "final_value": final_val,
                "total_return_pct": round(total_return, 2),
                "total_trades": sum(d["trades_executed"] for d in results),
                "max_drawdown_pct": _compute_max_drawdown(results, initial),
                "sharpe_ratio": _compute_sharpe(results, initial),
            }},
            f,
            indent=2,
        )

    return output_path


# ═══════════════════════════════════════════════════════════════════
#  CLI entry point
# ═══════════════════════════════════════════════════════════════════

async def cli_main():
    parser = argparse.ArgumentParser(description="PolyArb Backtester")
    parser.add_argument("--days", type=int, default=30, help="Days to backtest")
    parser.add_argument("--capital", type=float, default=10000.0, help="Initial capital")
    parser.add_argument("--max-position", type=float, default=100.0, help="Max position size")
    parser.add_argument("--output", type=str, default="backtest_report.json", help="Output JSON path")
    parser.add_argument("--no-clean", action="store_true", help="Don't clean previous results")
    parser.add_argument("--authoritative", action="store_true", default=True,
                        help="Settle from markets.resolved_outcome (default: True)")
    parser.add_argument("--heuristic", action="store_true",
                        help="Use heuristic price-threshold settlement instead of authoritative")
    parser.add_argument("--start", type=str, default=None,
                        help="Start date (ISO format, e.g. 2026-01-01)")
    parser.add_argument("--end", type=str, default=None,
                        help="End date (ISO format, e.g. 2026-03-01)")
    parser.add_argument("--pair-ids", type=str, default=None,
                        help="Comma-separated pair IDs to include (e.g. 1,5,12)")
    parser.add_argument("--pair-file", type=str, default=None,
                        help="File with pair IDs (JSON list or one per line)")
    args = parser.parse_args()

    # Parse --pair-ids into a set
    _pair_ids = None
    if args.pair_ids:
        _pair_ids = {int(x.strip()) for x in args.pair_ids.split(",") if x.strip()}

    results = await run_backtest(
        days=args.days,
        initial_capital=args.capital,
        max_position_size=args.max_position,
        clean=not args.no_clean,
        use_authoritative=not args.heuristic,
        start_date=args.start,
        end_date=args.end,
        pair_ids=_pair_ids,
        pair_file=args.pair_file,
    )

    if results:
        report_path = generate_report(results, args.output)
        if report_path:
            log.info("report_saved", path=report_path)


if __name__ == "__main__":
    asyncio.run(cli_main())
