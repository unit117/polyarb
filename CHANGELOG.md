# Changelog

## 2026-03-21 (4) — Rescan Verification Gate, Top-N Classifier, Partition Matrix Fix

### Bug Fixes

**8. Rescan bypasses verification gate (detector/pipeline.py) — CRITICAL**
- `_rescan_existing_pairs` created opportunities for ALL pairs without checking `pair.verified`, causing 85% of trades (3,109 of 3,675) to execute on unverified pairs.
- Added `if not pair.verified: continue` gate in the rescan loop.

**10. Top-N implication misclassification (detector/classifier.py) — MEDIUM**
- "Top 10" vs "Top 20" pairs were classified as `mutual_exclusion` by the LLM. Finishing Top 10 implies finishing Top 20 — this is `implication`.
- Added `_check_ranking_markets()` rule-based classifier with `_RANKING_RE` regex. Matches same-subject "Top/Bottom N" patterns and classifies as implication.

**11. Stale constraint matrices (scripts/rebuild_constraints.py) — HIGH**
- Pairs classified before bug fixes had incorrect constraint matrices that persisted in the DB.
- Added `scripts/rebuild_constraints.py` one-time script that re-classifies all pairs via rule-based checks and rebuilds constraint matrices with fixed logic.
- Run result: 2,050 pairs rebuilt, 206 reclassified, 482 marked unverified.

**12. Partition matrix no-op for binary markets (detector/constraints.py) — MEDIUM**
- `_partition_matrix` returned all-ones `[[1,1],[1,1]]` for binary markets, giving the optimizer no constraint signal.
- Fixed to return `[[0,1],[1,0]]` — both Yes can't be true simultaneously, and both No can't be true simultaneously.
- Multi-outcome partitions now correctly mark different shared outcomes as infeasible.

### Files Changed

- `services/detector/pipeline.py` — verification gate in `_rescan_existing_pairs`
- `services/detector/classifier.py` — `_RANKING_RE`, `_check_ranking_markets()`
- `services/detector/constraints.py` — `_partition_matrix()` binary market fix
- `scripts/rebuild_constraints.py` — NEW: one-time constraint matrix rebuild script

### Post-Deploy Action Required

```bash
docker compose run --rm backtest python -m scripts.rebuild_constraints
```

---

## 2026-03-21 (3) — Price-Threshold Classifier, Regex Gap, Portfolio Purge

### Bug Fixes

**7. Price-threshold misclassification (detector/classifier.py) — HIGH**
- LLM was classifying price-threshold market pairs like "PLTR above $128" vs "PLTR above $134" as `mutual_exclusion`. These are actually `implication` — if price is above $134, it's necessarily above $128.
- Added `_check_price_threshold_markets()` rule-based classifier with `_PRICE_THRESHOLD_RE` regex matching "above/below/over/under $X" patterns.
- Handles same-asset different-threshold (implication), same-asset different-time-window (independent), and mixed-direction (defers to LLM).
- Enhanced LLM system prompt with price-threshold domain knowledge as a safety net.

**8. Regex gap for "above $X" time-interval patterns (detector/classifier.py) — MEDIUM**
- `_TIME_INTERVAL_RE` only matched "Up or Down" patterns, missing price-threshold markets with time intervals like "BTC above $90,000 — March 21, 3:15AM-3:30AM".
- New `_PRICE_THRESHOLD_RE` captures optional time windows, so same-asset-different-date pairs are correctly classified as independent.

**9. Pre-fix data contamination (simulator/pipeline.py, main.py) — HIGH**
- 95% of trades (1,025 of 1,082 opps) were executed during pre-fix period with inflated profit estimates, no pair verification, and wrong position sizing.
- Added `purge_contaminated_positions()` method: closes all open positions at current market prices, records `PURGE` trades for auditability, resets win/loss counters.
- Added `scripts/purge_positions.py` one-time cleanup script.
- Updated `_restore_portfolio()` to handle PURGE trades in cost basis replay.

### Files Changed

- `services/detector/classifier.py` — `_PRICE_THRESHOLD_RE`, `_check_price_threshold_markets()`, LLM prompt update
- `services/simulator/pipeline.py` — `purge_contaminated_positions()` method
- `services/simulator/main.py` — PURGE trade handling in portfolio restore
- `scripts/purge_positions.py` — NEW: one-time portfolio purge script

### Post-Deploy Action Required

```bash
docker compose run --rm simulator python -m scripts.purge_positions
```

---

## 2026-03-21 (2) — Conditional Constraints, Pair Verification, Position Sizing

### Bug Fixes

**3. Conditional pair constraints (detector/constraints.py)**
- `_conditional_matrix` previously returned all-ones (identical to unconstrained). Now derives real feasibility constraints from Fréchet bounds + classifier correlation direction.
- Classifier enhanced to output `correlation: "positive"|"negative"` for conditional pairs.
- Positive correlation + price divergence > 0.15 → anti-correlated cell infeasible. Both high (sum > 1.15) → (No,No) infeasible. Both low (sum < 0.85) → (Yes,Yes) infeasible. Negative correlation → same as mutual_exclusion.
- Conditional pairs with all-ones matrix (no correlation data) still skipped by optimizer.
- `OPTIMIZER_SKIP_CONDITIONAL` default changed from `true` to `false` now that real constraints exist.

**5. Pair verification (detector/verification.py — NEW)**
- New verification pipeline runs 3 checks: classifier confidence ≥ 0.70, structural validity per dependency type, and price consistency.
- Wired into detection pipeline — `MarketPair.verified` now populated.
- Opportunities only created for verified pairs, preventing unvalidated classifications from reaching the optimizer.

**6. Position sizing uses net profit (simulator/pipeline.py)**
- Replaced `trade["edge"] * max_position_size` with sizing from opportunity-level `estimated_profit` (net of fees).
- Scale: 0.10 net profit → full max_position_size, linear below. All trades in the bundle sized uniformly.
- Opportunities with estimated_profit ≤ 0 skipped entirely.

### Files Changed

- `services/detector/classifier.py` — correlation field in LLM output for conditional pairs
- `services/detector/constraints.py` — Fréchet-based conditional matrix + profit bounds
- `services/detector/pipeline.py` — verification integration, correlation passthrough
- `services/detector/verification.py` — NEW: structural + price verification module
- `services/optimizer/pipeline.py` — smart conditional skip (all-ones check vs forced)
- `services/simulator/pipeline.py` — net-profit position sizing
- `shared/config.py` — `optimizer_skip_conditional` default → false

---

## 2026-03-21 — Profitability Fixes (Classifier + Optimizer + Simulator)

### Bug Fixes

**1. estimated_profit double-counting (optimizer/trades.py)**
- `estimated_profit` was summing `abs(edge)` across every outcome in both markets. For binary pairs this counted each mispricing 2× per market (once for Yes, once for No), inflating profit estimates ~4× vs actual capturable edge.
- Now takes `max(edge)` per market and subtracts estimated round-trip fees. Also passes through `theoretical_profit` from the constraint matrix for comparison.

**2. min_edge threshold too low (optimizer/trades.py, shared/config.py)**
- Hardcoded `0.005` (0.5 cent) threshold let through trades where fees alone exceeded the entire edge. With 2% fee rate on two legs, breakeven is ~$0.02.
- New configurable `OPTIMIZER_MIN_EDGE` setting, default **0.03** (3 cents). Also bumped `LIVE_TRADING_MIN_EDGE` default from 0.005 to 0.03.

**3. Conditional pairs produce no real edge (optimizer/pipeline.py)**
- `_conditional_matrix` returns all-ones (identical to unconstrained), so Frank-Wolfe projects back to roughly the original prices — producing noise-level edges that always lose to fees.
- New `OPTIMIZER_SKIP_CONDITIONAL` setting (default `true`). Conditional pairs now get `status = "skipped"` before FW runs.

**4. Crypto time-interval misclassification (detector/classifier.py)**
- GPT-4o-mini was labeling adjacent 15-minute crypto "Up or Down" windows (e.g., Bitcoin 3:15-3:30 vs 3:30-3:45) as `mutual_exclusion` when they're actually independent events.
- New rule-based filter `_check_crypto_time_intervals` matches the `"Asset Up or Down — Date, StartAM-EndAM ET"` pattern:
  - Same asset + same time window → `mutual_exclusion` (correct: can't be both up and down)
  - Same asset + different time window → `none` (independent events)
  - Runs before LLM, saving API calls for these 23+ pairs.

### Configuration Changes

| Setting | Old Default | New Default |
|---|---|---|
| `OPTIMIZER_MIN_EDGE` | 0.005 (hardcoded) | 0.03 |
| `OPTIMIZER_SKIP_CONDITIONAL` | N/A | true |
| `LIVE_TRADING_MIN_EDGE` | 0.005 | 0.03 |

### Files Changed

- `services/detector/classifier.py` — added `_check_crypto_time_intervals` rule
- `services/optimizer/trades.py` — fixed estimated_profit calculation, configurable min_edge
- `services/optimizer/pipeline.py` — conditional pair skip, pass fee_rate/min_edge/theoretical_profit
- `services/optimizer/main.py` — wire new settings into pipeline
- `shared/config.py` — added `optimizer_min_edge`, `optimizer_skip_conditional`, bumped `live_trading_min_edge`
- `scripts/backtest.py` — pass new params to `compute_trades`
- `.env.example` — documented new settings
