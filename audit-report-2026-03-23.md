# PolyArb Constraint Audit Report — 2026-03-23

## Bug Regression Status

| # | Bug | Status | Change |
|---|-----|--------|--------|
| 1 | estimated_profit double-counts edges | FIXED ✅ | — |
| 2 | min_edge too low | FIXED ✅ | — |
| 3 | Conditional pairs unconstrained | FIXED ✅ | — |
| 4 | Crypto time-interval misclassification | FIXED ✅ | — |
| 5 | 0% verification rate | FIXED ✅ | — |
| 6 | Position sizing uses inflated edge | FIXED ✅ | — |
| 7 | Hourly crypto regex miss | FIXED ✅ | — |
| 8 | Rescan bypasses verification | FIXED ✅ | — |
| 9 | Conditional pairs NULL correlation | FIXED ✅ | — |
| 10 | Top-N misclassified as ME | FIXED ✅ | — |
| 11 | MrBeast sub threshold misclassified | FIXED ✅ | — |
| 12 | Partition all-ones matrices | FIXED ✅ | — |
| 13 | Portfolio purge not executed | FIXED ✅ | — |
| 14 | No stale matrix rebuild mechanism | PARTIAL ⚠️ | — |
| 15 | Date-blind crypto classification | FIXED ✅ | — |
| 16 | Post-purge unverified trades | STALE ⚠️ | — |
| 17 | 14 neg-conditional stale all-ones | OPEN 🔴 | stable |
| 18 | Opps on re-unverified pairs | OPEN 🔴 | — |
| **19** | **🆕 CRITICAL: 2,609 implication pairs have WRONG direction** | **OPEN 🔴** | **NEW** |

## New Critical Bug #19: Implication Direction Inversion

**Severity: CRITICAL — affects 57.7% of verified implication pairs and 2,188 trades.**

All 4,520 verified implication pairs have matrix `[[1,0],[1,1]]` (a_implies_b direction), but 2,609 of them should have `[[1,1],[0,1]]` (b_implies_a). The `implication_direction` column is NULL for all verified pairs.

**Root cause:** These pairs were classified before the rule-based classifiers (`_check_over_under_markets`, `_check_price_threshold_markets`, etc.) existed. The LLM label-based classifier (`classify_llm`) does not return `implication_direction`. When `build_constraint_matrix` receives `implication_direction=None`, it defaults to `"a_implies_b"` (line 49 of `constraints.py`).

**Impact:** For a pair like O/U 1.5 (A) vs O/U 2.5 (B):

- **Real constraint:** Over 2.5 → Over 1.5 (b_implies_a). A=No + B=Yes is impossible.
- **Wrong constraint:** Over 1.5 → Over 2.5 (a_implies_b). A=Yes + B=No is impossible.
- **Result:** The optimizer sees false arbitrage when P(A) > P(B), but the real constraint says P(B) ≤ P(A) — meaning P(A) > P(B) is the *expected* state, not an arb opportunity.

Verification doesn't catch this because `_check_price_consistency` also defaults to a_implies_b when direction is None. The payout proof (`_worst_case_payoff`) uses the same wrong feasibility matrix.

**Evidence:** 116 newer unverified implication pairs DO have the correct `[[1,1],[0,1]]` matrix — these were classified by the rule-based O/U checker which returns `implication_direction="b_implies_a"`.

**Recommended fix:**
1. Reclassify all 4,520 verified implication pairs through the rule-based classifier pipeline to determine correct direction
2. Rebuild constraint matrices with correct direction
3. Consider purging trades executed on wrong-direction pairs (2,188 trades)

## System Status

**The system appears stalled.** No new trading activity for ~34 hours:

- Last trade: 2026-03-22 13:27 UTC
- Last price snapshot: 2026-03-22 13:32 UTC
- Last pair created: 2026-03-22 22:50 UTC
- 0 new pairs today, 0 trades today
- Portfolio snapshots unchanged since 2026-03-22 22:56 UTC

The ingestor may have lost Polymarket API access or Docker containers may have crashed. Recommend checking container health on the NAS.

## Pair & Matrix Health

| Type | Total | Verified | Matrix Status |
|------|-------|----------|---------------|
| mutual_exclusion | 12,995 | 0 | N/A (all unverified) |
| implication | 5,112 | 4,520 | ⚠️ 2,609 wrong direction (Bug #19) |
| conditional | 2,652 | 2,352 | ⚠️ 14 stale neg-conditional (Bug #17) |
| partition | 277 | 122 | ✅ All correct |
| none | 136 | 0 | N/A |
| **Total** | **21,172** | **6,994** | |

Growth: 19,446 → 21,172 (+8.9%) since last audit.

**Notable:** 0 verified mutual_exclusion pairs. All 12,995 ME pairs fail the structural verification check (requires same `event_id`). 12,784 have NULL `classification_source`, predating the verification system.

## Portfolio

| Metric | Value |
|--------|-------|
| Total Value | $10,172.47 (+1.72%) |
| Cash | $13,050.87 |
| Realized PnL | -$4,229.87 (includes pre-purge contamination) |
| Total Trades | 2,713 |
| Settled | 156 |
| Wins | 51 (32.7% win rate) |

Portfolio unchanged since last audit — no new trades executing.

## Recommendations (Priority Order)

1. **🔴 Fix Bug #19** — Reclassify verified implication pairs with correct direction. This is the highest-impact fix: 2,609 pairs with wrong constraints, 2,188 trades affected.
2. **🟡 Investigate system stall** — Check Docker container health on NAS. No trading activity for 34+ hours.
3. **🟡 Fix Bug #14** — Add mechanism to rebuild stale constraint matrices for pairs with existing opportunities. Root cause of Bugs #17 and #19.
4. **🟢 Fix Bug #18** — Add `pair.verified` check in simulator's `_execute_pending` before trade execution.
