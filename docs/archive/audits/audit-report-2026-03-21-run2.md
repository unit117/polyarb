# PolyArb Constraint Audit Report — 2026-03-21 (Run 2)

## Bug Regression Status

| # | Bug | Status | Change |
|---|-----|--------|--------|
| 1 | estimated_profit double-counts edges | FIXED ✅ | — |
| 2 | min_edge threshold too low | FIXED ✅ | — |
| 3 | Conditional pairs unconstrained (all-ones) | FIXED ✅ | — |
| 4 | GPT-4o-mini misclassifies crypto pairs | PARTIAL ⚠️ | — |
| 5 | 0% pair verification rate | FIXED ✅ | — |
| 6 | Position sizing uses inflated edge | FIXED ✅ | — |
| 7 | Hourly crypto regex misses non-range format | OPEN 🔴 | — |
| 8 | `_rescan_existing_pairs` bypasses verification | FIXED ✅ | **FIXED since last run** |
| 9 | 591 conditional pairs NULL correlation | OPEN 🔴 | — |
| 10 | Top-N pairs misclassified as mutual_exclusion | PARTIAL ⚠️ | Code fix exists, DB stale |
| 11 | Pair 3765 wrong classification (implication, not neg-conditional) | OPEN 🔴 | Matrix fixed, classification still wrong |
| 12 | Partition pairs stale all-ones matrices in DB | PARTIAL ⚠️ | Code fix exists, 35/35 DB records stale |
| 13 | 🆕 No portfolio purge executed | OPEN 🔴 | NEW |
| 14 | 🆕 No mechanism to rebuild stale constraint matrices | OPEN 🔴 | NEW |

**Summary**: 6 FIXED, 3 PARTIAL, 5 OPEN (2 new this run)

## Key Findings

### 1. Bug #8 is Fixed

The `_rescan_existing_pairs` method now correctly checks `pair.verified` at line 193 before creating opportunities. This was a critical fix that stops the bleeding — no new unverified opportunities are being created.

### 2. Stale Data Problem (Bugs #10, #12, #14)

Multiple code fixes have been deployed but existing DB records were never rebuilt:

- **35 partition pairs** all have `[[1,1],[1,1]]` matrices (should be `[[0,1],[1,0]]`). The code correctly generates the right matrix now, but 28 of these pairs already have opportunities, so the rescan skips them.
- **87 Top-N pairs** still classified as `mutual_exclusion` despite `_check_ranking_markets()` being implemented. These were classified before the rule was added and are never reclassified.
- **Root cause**: `_rescan_existing_pairs` only targets pairs without existing opportunities. A one-time migration or "rebuild all constraint matrices" script is needed.

### 3. Hourly Crypto Pairs Still Broken (Bug #7)

192 crypto "Up or Down" pairs with hourly format (e.g., "BNB Up or Down - March 21, 5AM ET") are misclassified — 116 as mutual_exclusion, 76 as conditional. The regex `_TIME_INTERVAL_RE` requires a `HH:MMAM-HH:MMAM` time range and doesn't match single-hour timestamps. These different-window pairs should be classified as `none` (independent).

**Recommended fix**: Extend the regex to also match single-timestamp format like `(\d{1,2}(?::\d{2})?[AP]M)\s+ET`.

### 4. Portfolio Contamination Worsening (Bug #13)

The portfolio purge has never been executed. Current state:

- Realized PnL: **-$2,506** (was -$1,881 last run — worsening)
- Unrealized PnL: **-$1,534** (was -$1,239 — worsening)
- Win rate: **0.4%** (13 wins / 3,315 trades)
- **94% of all trades** (3,109 / 3,315) were on unverified pairs
- Cash: $15,867 / Total value: $14,642

The `purge_contaminated_positions()` method exists but has never been triggered. Until the purge runs, all portfolio metrics are meaningless — they reflect trades on pairs with broken constraints.

### 5. Pair 3765 Misclassification (Bug #11)

MrBeast "475M subs" vs "477M subs" is classified as negative-correlation conditional, but this is clearly an implication: hitting 477M subscribers necessarily means having already hit 475M. The pair is `verified=True` and has matrix `[[0,1],[1,1]]`. This is the mutual-exclusion matrix shape, not implication. With implication, `matrix[0][1]` should be 0 (A=Yes + B=No infeasible), not `matrix[0][0]`.

**Recommended fix**: Extend `_check_ranking_markets` or add a new `_check_threshold_progression` rule to catch "will X reach Y by date" pairs where Y values form an implication chain.

## Recommended Priority Actions

1. **CRITICAL — Run portfolio purge**: Call `purge_contaminated_positions()` to close all contaminated positions and reset metrics.
2. **HIGH — Build a constraint matrix rebuild script**: One-time script to re-classify and rebuild constraint matrices for all existing pairs, applying the new rule-based checks.
3. **HIGH — Fix hourly crypto regex** (Bug #7): Add single-timestamp matching to `_TIME_INTERVAL_RE`.
4. **MEDIUM — Add threshold-progression rule** (Bug #11): Detect "will X reach Y by date" pairs and classify as implication.
5. **LOW — Reclassify NULL-correlation conditionals** (Bug #9): Re-run classifier on 591 pairs or mark them as `none`.
