# PolyArb Constraint Audit Report — March 21, 2026

## Summary

The system has 36,266 active markets, 3,815 pairs, 3,498 opportunities, and 3,675 paper trades. The portfolio is at $13,446 (started at $10,000 initial capital) but realized PnL is **-$1,881** and unrealized PnL is **-$1,239**, with only **13 winning trades out of 3,165** (0.4% win rate). The apparent positive total value is due to mark-to-market on open positions, not genuine profit.

The core issue: **85% of trades (3,109 of 3,675) were executed on unverified pairs**, bypassing the verification gate through the `_rescan_existing_pairs` code path.

---

## Bug Regression Status

### Previously Fixed (6 bugs) — Regression Check

| Bug | Status | Notes |
|-----|--------|-------|
| #1 estimated_profit double-counting | **FIXED** ✅ | `max()` per market, fees subtracted |
| #2 min_edge too low (0.005) | **FIXED** ✅ | Now 0.03, configurable |
| #3 Conditional all-ones matrix | **FIXED** ✅ | Frechet/correlation logic implemented |
| #4 Crypto time-interval misclassification | **PARTIAL** ⚠️ | Fixed for time-range format only; see new Bug #7 |
| #5 0% verification rate | **FIXED** ✅ | `verify_pair()` works; but see Bug #8 for bypass |
| #6 Position sizing uses inflated edge | **FIXED** ✅ | Uses `profit_ratio` from net profit |

### New Bugs Discovered (6 bugs)

**Bug #7 — Hourly crypto regex miss** (`classifier.py`): The `_TIME_INTERVAL_RE` regex requires a time range like "3:15AM-3:30AM" but hourly markets use "10PM ET" (single time, no range). Result: **192 crypto pairs misclassified** (116 as mutual_exclusion, 76 as conditional, zero correctly as "none"). All HYPE, BNB, Solana, and Hyperliquid hourly pairs are affected.

**Bug #8 — Rescan bypasses verification gate** (`pipeline.py` line ~220): `_rescan_existing_pairs` creates opportunities for ALL pairs without checking `pair.verified`. This is the **primary cause of losses** — 3,276 of 3,498 opportunities came from unverified pairs, leading to 3,109 trades ($208 in fees alone) on pairs whose classifications were never validated.

**Bug #9 — 591 conditional pairs have NULL correlation**: The LLM sometimes returns `dependency_type: "conditional"` without the required `correlation` field. The constraint code silently falls through to an unconstrained all-ones matrix (line 139 in `constraints.py`). These pairs produce no real constraints and shouldn't be traded.

**Bug #10 — Top-N implication misclassification**: "Top 10" vs "Top 20" pairs are consistently classified as mutual_exclusion by the LLM. These are actually implications (finishing Top 10 implies finishing Top 20). No rule-based check exists for this common Polymarket pattern.

**Bug #11 — Stale constraint matrices**: At least one pair (ID=3765) has a negative-correlation conditional classification but an all-ones matrix, likely because the constraint matrix was built before the fix and the rescan rebuilt the constraint but the LLM misclassified the correlation direction.

**Bug #12 — Partition matrix is a no-op for binary markets**: `_partition_matrix` produces all-ones `[[1,1],[1,1]]` for binary market pairs. The comment says "let the optimizer enforce sum-to-one" but the optimizer receives no constraint signal from the matrix.

---

## Pair Classification Audit

### By Dependency Type and Verification

| Type | Verified | Unverified | Total |
|------|----------|------------|-------|
| mutual_exclusion | 447 | 2,673 | 3,120 |
| conditional | 78 | 591 | 669 |
| partition | 7 | 19 | 26 |
| implication | 0 | 0 | 0 |
| **Total** | **532** | **3,283** | **3,815** |

Only 14% of pairs are verified. The verification gate in the main `run_once()` pipeline works correctly (line 142 checks `verification["verified"]`), but the rescan bypass (Bug #8) lets all unverified pairs through anyway.

### Crypto Time-Interval Markets

192 crypto "Up or Down" pairs exist in the DB. **Zero** are classified as "none" (independent). All 192 are misclassified as either mutual_exclusion (116) or conditional (76). These represent different time windows for the same asset, which should be independent events.

The rule-based `_check_crypto_time_intervals` function works correctly for the Bitcoin-style format ("Bitcoin Up or Down - March 21, 3:15AM-3:30AM ET") but the regex doesn't match the HYPE/hourly format ("HYPE Up or Down - March 21, 10PM ET"). Both formats need to be handled.

### Constraint Matrix Quality

| Type | All-ones matrices | Non-trivial matrices |
|------|-------------------|---------------------|
| conditional | 650 (97%) | 19 (3%) |
| partition | 26 (100%) | 0 (0%) |
| mutual_exclusion | 0 (0%) | 3,120 (100%) |

Mutual exclusion matrices are correct: `[[0,1],[1,1]]` consistently. Conditional and partition matrices are almost entirely unconstrained, meaning the optimizer gets no signal from them and cannot find arbitrage.

---

## Recommended Fixes (Priority Order)

1. **Bug #8 (Critical)**: Add `if not pair.verified: continue` in `_rescan_existing_pairs` before creating opportunities. This is the single highest-impact fix — it stops 85% of bad trades immediately.

2. **Bug #7 (High)**: Extend `_TIME_INTERVAL_RE` or add a second regex for hourly format: `r"^(.+?)\s+Up or Down\b.*?(\d{1,2}(?::\d{2})?[AP]M)\s+ET"`. Or add a simpler heuristic: if both questions match "X Up or Down - DATE, TIME" for the same asset, classify by whether dates/times differ.

3. **Bug #9 (High)**: In `classify_llm`, validate that conditional responses include a correlation field. If missing, either re-prompt or downgrade to "none".

4. **Bug #10 (Medium)**: Add a rule-based check for "Top N" vs "Top M" patterns where N < M → implication.

5. **Bug #12 (Medium)**: For binary partition pairs, mark diagonal cells as infeasible: `matrix[0][1] = 0; matrix[1][0] = 0` (if outcomes match) or derive from the sum-to-one constraint.
