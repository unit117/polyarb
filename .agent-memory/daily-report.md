# Daily Report Agent Memory

This file is read and updated by the `polyarb-daily-report` scheduled task on every run.
Each run should: (1) read this file, (2) check bug status, (3) append a run log entry, (4) update bug statuses.

---

## Known Bugs

Track each bug with its status. Update on every run after checking the codebase.

| # | Bug | Location | Found | Status | Last Checked |
|---|-----|----------|-------|--------|--------------|
| 1 | estimated_profit double-counts edges — sums per-outcome abs deltas, inflating profit ~4x for binary pairs | `services/optimizer/trades.py` ~line 73 | 2026-03-21 | FIXED | 2026-03-22 |
| 2 | min_edge threshold too low (0.005) — below breakeven after fees (~0.02-0.03) | `services/optimizer/trades.py` ~line 26 | 2026-03-21 | FIXED | 2026-03-22 |
| 3 | Conditional pairs have no real constraints — `_conditional_matrix` returns all-ones matrix | `services/detector/constraints.py` ~line 129 | 2026-03-21 | FIXED | 2026-03-22 |
| 4 | GPT-4o-mini misclassifies crypto time-interval pairs as mutual_exclusion | `services/detector/classifier.py` ~line 113 | 2026-03-21 | FIXED | 2026-03-22 |
| 5 | 0% pair verification rate — system trades on entirely unverified pairs | system-wide | 2026-03-21 | FIXED | 2026-03-22 |
| 6 | Position sizing uses inflated edge — oversizes positions based on double-counted edge | `services/simulator/pipeline.py` ~line 127 | 2026-03-21 | FIXED | 2026-03-22 |
| 7 | `_implication_matrix()` only handles binary (2×2) outcomes — multi-outcome implications get all-ones (no constraints) | `services/detector/constraints.py` ~line 84 | 2026-03-21 EVE | OPEN | 2026-03-22 |
| 8 | 🆕 Zero open positions — portfolio fully unwound, no new trades being placed | system-wide (optimizer/simulator) | 2026-03-22 | OPEN | 2026-03-22 |

---

## Run Log

<!-- Append a new entry after each run. Format: -->
<!-- ### YYYY-MM-DD HH:MM -->
<!-- - Bug check results (which are fixed, which are still open) -->
<!-- - Any NEW bugs discovered (add to table above with 🆕) -->
<!-- - Key observations from this run -->

### 2026-03-21 (initial seed)
- All 6 bugs catalogued from performance-monitor and constraint-auditor findings.
- This is the baseline — all bugs currently OPEN.

### 2026-03-21 (manual review)
- Bug #1 FIXED: `estimated_profit` now uses `max()` per market instead of `sum()` across all outcomes (lines 72-74). Also subtracts estimated fees before reporting (line 81). No longer double-counts.
- Bug #2 FIXED: `min_edge` default raised from 0.005 to 0.03 (line 19). Now configurable via `optimizer_min_edge` setting in `shared/config.py` (also defaults to 0.03). Wired through pipeline and main.
- Bug #3 STILL OPEN: `_conditional_matrix` (line 101-107) still returns all-ones. Comment says "probabilities are constrained" but no actual constraint logic implemented.
- Bug #4 FIXED: New `_check_crypto_time_intervals()` rule-based function added (lines 72-107). Uses regex to detect "Up or Down" time-interval markets, classifies same-window as mutual_exclusion and different-window as independent ("none"). Integrated into `classify_rule_based()` pipeline.
- Bug #5 STILL OPEN: No new verification logic found. Dashboard displays `verified` field but no service-level verification workflow exists.
- Bug #6 STILL OPEN: `pipeline.py` line 79 still uses `trade["edge"] * self.max_position_size`. Edge is now the per-outcome delta (not double-counted), which is better, but still not the net capturable profit per share.

### 2026-03-21 (second review — all bugs resolved)
- Bug #3 FIXED: `_conditional_matrix` now takes prices, outcomes, and correlation direction. Implements Frechet bounds + correlation-based constraints for binary conditional pairs. Negative correlation → marks (Yes,Yes) infeasible like mutual_exclusion. Positive correlation → marks anti-correlated outcomes infeasible when price divergence is large.
- Bug #5 FIXED: New `services/detector/verification.py` module with `verify_pair()` function. Runs structural + price-consistency checks after classification. Sets `MarketPair.verified = True` only if all checks pass. Pipeline now gates opportunity creation on `verification["verified"]`.
- Bug #6 FIXED: Position sizing in `pipeline.py` now uses `net_profit = estimated_profit` (the fee-adjusted value from the optimizer), computes a `profit_ratio` against a 0.10 reference, and derives `base_size` from that. No longer uses raw per-outcome edge.
- All 6 original bugs are now FIXED. Bug tracker is clean.

### 2026-03-21 PM (scheduled task run)
- All 6 bugs re-checked against source code — all remain FIXED. No regressions.
- Bug #1: `trades.py` lines 72-74 still use `max()` per market; line 81 subtracts fees. Confirmed.
- Bug #2: `min_edge` default still 0.03 on line 19. Confirmed.
- Bug #3: `_conditional_matrix` (line 108+) implements Frechet bounds with correlation/price logic. Confirmed.
- Bug #4: `_check_crypto_time_intervals()` still present (lines 75-110) with regex + rule logic. Confirmed.
- Bug #5: `services/detector/verification.py` exists and is operational. DB shows 532/3815 pairs verified (13.9%). Confirmed.
- Bug #6: `pipeline.py` lines 71-75 use `net_profit` / 0.10 ratio for sizing. Confirmed.
- No new bugs discovered.
- Key concern: Fee drag ($258/day) exceeds estimated edge capture (~$185/day). Realized PnL worsened from -$1,092 to -$1,881 in 24h.

### 2026-03-21 EVE (scheduled task run — evening)
- All 6 bugs re-checked against source code — all remain FIXED. No regressions.
- Bug #1: trades.py lines 96-105 use `max()` per market + fee subtraction. Confirmed.
- Bug #2: min_edge default 0.03 at line 26 of trades.py and line 44 of config.py. Confirmed.
- Bug #3: _conditional_matrix (lines 125-195) implements Frechet bounds, divergence thresholds, correlation logic. Confirmed.
- Bug #4: _check_crypto_time_intervals() at lines 94-141 of classifier.py with regex + rule logic. Confirmed.
- Bug #5: verification.py exists with verify_pair(). Pipeline gates on verified at line 156. DB shows 4,896/7,602 pairs verified (64.4%, up from 13.9%). Confirmed.
- Bug #6: pipeline.py lines 119-140 use Half-Kelly on estimated_profit with drawdown scaling. Confirmed.
- 🆕 Bug #7 DISCOVERED: `_implication_matrix()` in constraints.py (lines 44-46) only handles binary 2×2 outcomes. Multi-outcome implication pairs (e.g., ranking markets) receive an all-ones matrix, meaning no constraints are applied. Medium severity — only affects non-binary markets.
- Key observations:
  - Portfolio value: $10,120 (+1.2% since inception). Significant improvement from -$1,881 → +$43 realized PnL.
  - Fee drag exploded to $535/day (was $258/day last run). 5.3% of portfolio daily — unsustainable.
  - Win rate extremely low at 0.5% (5/1065). Needs investigation.
  - 369 active positions for $10K portfolio = avg ~$27/position (too granular).
  - Verification rate jumped 13.9% → 64.4% — verification pipeline is working well.
  - 2,578 markets resolved in 24h — high churn environment.
  - Zero active opportunities currently — pipeline is cycling but nothing meeting criteria right now.

### 2026-03-22 AM (scheduled task run)
- All 7 bugs re-checked against source code. Bugs #1-6 remain FIXED. Bug #7 remains OPEN.
- Bug #1: trades.py lines 71-73 use `max()` per market to pick best leg. Line 114 subtracts fees + slippage. Confirmed FIXED.
- Bug #2: min_edge default 0.03 at line 26 of trades.py. Confirmed FIXED.
- Bug #3: _conditional_matrix (lines 129-199) implements full Frechet bounds + divergence + correlation. Confirmed FIXED.
- Bug #4: _check_crypto_time_intervals() at lines 113-170 of classifier.py. Confirmed FIXED.
- Bug #5: verification.py exists. DB shows 8,721/11,434 pairs verified (76.3%, up from 64.4%). Confirmed FIXED.
- Bug #6: pipeline.py lines 127-148 use Half-Kelly on estimated_profit with drawdown scaling. Confirmed FIXED.
- Bug #7: _implication_matrix() at lines 84-90 of constraints.py still only handles binary (sets matrix[0][1]=0 for n_a>=2, n_b>=2). Multi-outcome markets get all-ones. Still OPEN.
- No new bugs discovered.
- Key observations:
  - Portfolio value: $10,099.69 (+1.0% since inception). Down from $10,120 last run.
  - CRITICAL: Realized PnL collapsed from +$43 → -$4,182.51 in ~8 hours (between 17:28 and 23:59 Mar 21 UTC). Massive batch of losing settlements.
  - Fee drag: $562/day (5.6% of portfolio). Worsened from $535/day last run. Still unsustainable.
  - Win rate: 28/2,379 = 1.2%. Marginally better than 0.5% last run but still extremely low.
  - Active positions reduced from 369 → 596 (positions dict has 596 entries, 223 long / 373 short).
  - Total exposure: $20,557 (2x portfolio value) — significant leverage.
  - Verification rate: 76.3% (up from 64.4%). Steady improvement.
  - 2,398 markets resolved in last 24h. High churn continues.
  - Zero active opportunities. Portfolio value flatlined since 00:38 UTC (identical snapshots for 30+ minutes).
  - 34,444 opportunities evaluated in 24h: 81.5% skipped, 9.8% expired, 3.9% simulated.
  - Conditional pairs dominate at 81% of opportunities with highest avg profit ($0.18).

### 2026-03-22 (scheduled task run — daily report)
- All 7 bugs re-checked against source code. Bugs #1-6 remain FIXED. Bug #7 remains OPEN.
- Bug #1: trades.py lines 21-29 use `max()` per market, min_edge=0.03 default. Confirmed FIXED.
- Bug #2: min_edge default 0.03 at line 26 of trades.py. Confirmed FIXED.
- Bug #3: _conditional_matrix (lines 129+) implements Frechet bounds + correlation logic. Confirmed FIXED.
- Bug #4: _check_crypto_time_intervals() at lines 115+ of classifier.py with regex rules. Confirmed FIXED.
- Bug #5: verification.py exists. DB: 14,412/14,971 pairs verified (96.3%, up from 76.3%). Confirmed FIXED.
- Bug #6: pipeline.py lines 127-148 use Half-Kelly on estimated_profit with drawdown scaling. Confirmed FIXED.
- Bug #7: _implication_matrix() at lines 84-90 of constraints.py still binary-only. Still OPEN.
- 🆕 Bug #8 DISCOVERED: Zero open positions — portfolio is fully unwound with 0 active trades. 5,290 trades executed in 24h but none remain open. Either all settled/exited or new opportunities aren't being entered. Needs investigation — may be a pipeline stall or all positions expiring faster than new ones are created.
- Key observations:
  - Portfolio value: $10,224.60 (+2.2% since inception). Up slightly from $10,099.69 last run.
  - Realized PnL: -$4,152.73 (improved slightly from -$4,182.51 last run — some winning settlements).
  - Fee drag: $567.76/day (5.6% of portfolio). Unchanged. Still unsustainable.
  - Win rate: 47W / 139 settled = 33.8%. MASSIVE improvement from 1.2% last run — post-bugfix trades performing much better.
  - Verification rate: 96.3% (up from 76.3%). Verification pipeline nearly complete.
  - 39,020 opportunities evaluated: 0 converged, 1,504 simulated, 31,999 skipped. Zero convergences is new and concerning.
  - Implication pairs have best conversion: 1,137/3,584 simulated (31.7%) vs conditional 59/31,572 (0.2%).
  - 2,781 markets resolved in 24h. 34,352 active markets.
  - Portfolio has been flat 01:00-07:00 UTC with zero position movement — confirms pipeline stall.
