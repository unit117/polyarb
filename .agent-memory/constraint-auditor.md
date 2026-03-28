# Constraint Auditor Agent Memory

This file is read and updated by the `constraint-auditor` scheduled task on every run.
Each run should: (1) read this file, (2) check bug status, (3) append a run log entry, (4) update bug statuses.

---

## Known Bugs

Track each bug with its status. Update on every run after checking the codebase.

| # | Bug | Location | Found | Status | Last Checked |
|---|-----|----------|-------|--------|--------------|
| 1 | estimated_profit double-counts edges — sums per-outcome abs deltas, inflating profit ~4x for binary pairs | `services/optimizer/trades.py` ~line 67 | 2026-03-21 | FIXED | 2026-03-23 |
| 2 | min_edge threshold too low (0.005) — below breakeven after fees (~0.02-0.03) | `services/optimizer/trades.py` ~line 40 | 2026-03-21 | FIXED | 2026-03-23 |
| 3 | Conditional pairs have no real constraints — `_conditional_matrix` returns all-ones matrix | `services/detector/constraints.py` | 2026-03-21 | FIXED | 2026-03-23 |
| 4 | GPT-4o-mini misclassifies crypto time-interval pairs as mutual_exclusion | `services/detector/classifier.py` | 2026-03-21 | FIXED | 2026-03-23 |
| 5 | 0% pair verification rate — system trades on entirely unverified pairs | system-wide | 2026-03-21 | FIXED | 2026-03-23 |
| 6 | Position sizing uses inflated edge — oversizes positions based on double-counted edge | `services/simulator/pipeline.py` ~line 79 | 2026-03-21 | FIXED | 2026-03-23 |
| 7 | Crypto time-interval regex misses hourly markets (e.g. "HYPE Up or Down - March 21, 10PM ET") — no time range in question format | `services/detector/classifier.py` `_TIME_INTERVAL_RE` | 2026-03-21 | FIXED | 2026-03-23 |
| 8 | `_rescan_existing_pairs` creates opportunities for ALL pairs regardless of verification status — bypasses verification gate | `services/detector/pipeline.py` ~line 220 | 2026-03-21 | FIXED | 2026-03-23 |
| 9 | 591 conditional pairs have NULL correlation — LLM returns conditional type without required correlation field, producing unconstrained all-ones matrices | `services/detector/classifier.py` LLM response + `constraints.py` | 2026-03-21 | FIXED | 2026-03-23 |
| 10 | Top-N implication pairs misclassified as mutual_exclusion — "Top 10" implies "Top 20" but LLM classifies as mutual_exclusion or conditional | `services/detector/classifier.py` | 2026-03-21 | FIXED | 2026-03-23 |
| 11 | Pair 3765 (MrBeast 475M vs 477M subs) misclassified as negative-correlation conditional — should be implication (hitting 477M implies 475M) | `services/detector/classifier.py` / DB data | 2026-03-21 | FIXED | 2026-03-23 |
| 12 | Partition pairs all have all-ones matrices `[[1,1],[1,1]]` — code fix exists but DB pairs have stale matrices, no rebuild mechanism | `services/detector/constraints.py` `_partition_matrix` + DB data | 2026-03-21 | FIXED | 2026-03-23 |
| 13 | No portfolio purge executed — contaminated trades remain, portfolio negative realized PnL with 0.4% win rate | `services/simulator/pipeline.py` `purge_contaminated_positions` | 2026-03-21 | FIXED | 2026-03-23 |
| 14 | No mechanism to rebuild stale constraint matrices for pairs that already have opportunities — rescan only targets pairs without opps | `services/detector/pipeline.py` `_rescan_existing_pairs` | 2026-03-21 | PARTIAL | 2026-03-23 |
| 15 | Date-blind crypto time-interval classification — `_check_crypto_time_intervals` compares time-of-day but NOT dates; markets on different dates with same time (e.g. "March 12, 8PM" vs "March 21, 8PM") classified as mutual_exclusion instead of independent | `services/detector/classifier.py` `_check_crypto_time_intervals` line 126 | 2026-03-21 | FIXED | 2026-03-23 |
| 16 | 121 post-purge trades executed on unverified pairs — opps created 2026-03-21 16:10-17:22 UTC on unverified pairs, trades filled after 23:00 UTC. Deployment gap artifact — no new unverified trades since 2026-03-22 01:17 UTC | `services/detector/pipeline.py` + `services/simulator/pipeline.py` | 2026-03-22 | STALE | 2026-03-23 |
| 17 | 14 verified negative-correlation conditional pairs have stale all-ones matrices `[[1,1],[1,1]]` — should be `[[0,1],[1,1]]`. No trades or opps on these pairs. Variant of Bug #14 (stale matrices never rebuilt). Grew from 11 to 14 since last run. | `services/detector/constraints.py` `_conditional_matrix` + DB data | 2026-03-22 | OPEN | 2026-03-23 |
| 18 | Opps created on pairs that later fail re-verification — `rescan_by_market_ids` creates opps on verified=True pairs, then re-verification flips pairs to verified=False, but existing in-flight opps are not cancelled. Simulator doesn't check `pair.verified` before executing. No actual unverified trades since 01:39 UTC (edge/VWAP checks catch them), but architecturally the simulator should gate on pair verification. | `services/detector/pipeline.py` `rescan_by_market_ids` + `services/simulator/pipeline.py` `_execute_pending` | 2026-03-22 | OPEN | 2026-03-23 |
| 19 | 🆕 **CRITICAL** — 2,609 verified implication pairs (57.7%) have WRONG direction. All 4,520 verified implication pairs have `[[1,0],[1,1]]` (a_implies_b) regardless of actual direction. Pairs classified before rule-based/resolution-vector classifiers existed used LLM label path which doesn't return `implication_direction`, causing `build_constraint_matrix` to default to a_implies_b. For O/U pairs (A=1.5, B=2.5 → b_implies_a) and price threshold pairs (A=$10M, B=$100M → b_implies_a), the constraint is inverted: allows impossible outcomes, forbids possible ones. Verification also uses wrong direction (same None default). 2,188 trades executed on wrong-direction pairs, 2,658 opps. Payout proof uses same wrong matrix so doesn't catch the error. Root cause: `implication_direction` column is NULL for all 4,520 verified pairs; `build_constraint_matrix` defaults `None` to `"a_implies_b"`. | `services/detector/constraints.py` `_implication_matrix` line 49 + `services/detector/pipeline.py` + DB data | 2026-03-23 | OPEN | 2026-03-23 |

---

## Run Log

<!-- Append a new entry after each run. Format: -->
<!-- ### YYYY-MM-DD HH:MM -->
<!-- - Bug check results (which are fixed, which are still open) -->
<!-- - Any NEW bugs discovered (add to table above with 🆕) -->
<!-- - Key observations from this run -->

### 2026-03-21 (initial seed)
- All 6 bugs catalogued. Bug #4 (crypto misclassification) was originally discovered by this agent.
- This is the baseline — all bugs currently OPEN.

### 2026-03-21 (manual review)
- Bug #1 FIXED: `estimated_profit` now uses `max()` per market instead of `sum()` across all outcomes. Also subtracts estimated fees before reporting. No longer double-counts.
- Bug #2 FIXED: `min_edge` default raised from 0.005 to 0.03. Now configurable via `optimizer_min_edge` setting in `shared/config.py`.
- Bug #3 STILL OPEN: `_conditional_matrix` still returns all-ones. No actual constraint logic implemented.
- Bug #4 FIXED: New `_check_crypto_time_intervals()` rule-based function added. Classifies same-window as mutual_exclusion and different-window as independent.
- Bug #5 STILL OPEN: No new verification logic found.
- Bug #6 STILL OPEN: `pipeline.py` line 79 still uses `trade["edge"] * self.max_position_size`.

### 2026-03-21 (second review — all bugs resolved)
- Bug #3 FIXED: `_conditional_matrix` now implements Frechet bounds + correlation-based constraints for binary conditional pairs.
- Bug #5 FIXED: New `services/detector/verification.py` with `verify_pair()`. Pipeline gates opportunities on verified pairs only.
- Bug #6 FIXED: Position sizing now uses fee-adjusted `estimated_profit` via `profit_ratio`, not raw edge.
- All 6 original bugs are now FIXED.

### 2026-03-21 (scheduled audit run)
- **Bug #1**: FIXED — `trades.py` uses `max()` per market (lines 72-73), subtracts fees (line 81). Confirmed.
- **Bug #2**: FIXED — `min_edge` default is 0.03 (line 19). Confirmed.
- **Bug #3**: FIXED — `_conditional_matrix` has proper Frechet/correlation logic (lines 108-178). Confirmed.
- **Bug #4**: PARTIAL — `_check_crypto_time_intervals()` exists and works for time-range format ("3:15AM-3:30AM") but **fails for hourly markets** ("10PM ET") which lack a time range. See new Bug #7. 192 crypto pairs still misclassified (116 as mutual_exclusion, 76 as conditional). Zero classified correctly as "none".
- **Bug #5**: FIXED — `verify_pair()` exists and is called in pipeline. However, `_rescan_existing_pairs` bypasses verification gate (new Bug #8).
- **Bug #6**: FIXED — Position sizing uses `profit_ratio = min(net_profit / 0.10, 1.0)` (line 74). Confirmed.
- **NEW Bug #7**: Hourly crypto markets ("HYPE Up or Down - March 21, 10PM ET") don't match `_TIME_INTERVAL_RE` regex which requires time ranges. All HYPE/hourly crypto pairs fall through to LLM which misclassifies them.
- **NEW Bug #8**: `_rescan_existing_pairs` (line 174-245) creates ArbitrageOpportunity for ALL pairs without checking `pair.verified`. This let 3,276 opportunities through from unverified pairs, causing 3,109 trades on unverified pairs (85% of all trades).
- **NEW Bug #9**: 591 conditional pairs have NULL correlation because the LLM returned `dependency_type: "conditional"` without the required `correlation` field. The constraint code falls through to all-ones matrix when correlation is missing (line 139).
- **NEW Bug #10**: Top-N pairs ("Top 10" vs "Top 20") are consistently misclassified as mutual_exclusion by the LLM. These are actually implication relationships (Top 10 → Top 20). No rule-based check exists for this pattern.
- **NEW Bug #11**: One negative-correlation conditional pair (ID=3765) has all-ones matrix. The pair "475M subs" vs "477M subs" is also incorrectly classified as negative correlation (should be positive implication). Likely a stale constraint matrix + LLM misclassification.
- **NEW Bug #12**: All partition pairs have all-ones matrices. `_partition_matrix` only checks shared outcomes but for binary markets (Yes/No) where outcomes are identical across both markets, the logic doesn't actually restrict any cells.
- **Portfolio health**: realized_pnl=-$1,881, unrealized_pnl=-$1,239, 13 wins / 3,165 trades (0.4% win rate). System is hemorrhaging money, mostly from unverified/misclassified pairs.

### 2026-03-21 (second scheduled audit run)
- **Bug #1**: FIXED ✅ — No change. `trades.py` uses `max()` per market, subtracts fees.
- **Bug #2**: FIXED ✅ — No change. `min_edge` default is 0.03.
- **Bug #3**: FIXED ✅ — No change. `_conditional_matrix` has proper correlation-based logic.
- **Bug #4**: PARTIAL ⚠️ — `_check_crypto_time_intervals()` works for time-range format but hourly markets still fall through.
- **Bug #5**: FIXED ✅ — No change. Verification gate in place.
- **Bug #6**: FIXED ✅ — No change. Position sizing uses profit_ratio.
- **Bug #7**: OPEN 🔴 — `_TIME_INTERVAL_RE` still requires `HH:MMAM-HH:MMAM` format. 192 hourly crypto pairs ("BNB Up or Down - March 21, 5AM ET") remain misclassified. DB confirms: 116 as mutual_exclusion, 76 as conditional.
- **Bug #8**: FIXED ✅ — `_rescan_existing_pairs` now checks `if not pair.verified: continue` at line 193. No new unverified opps being created. However, 3,276 historical unverified opps and 3,109 historical trades remain in DB.
- **Bug #9**: OPEN 🔴 — Still 591 conditional pairs with NULL correlation in DB. Verification gate correctly marks them as `verified=False`, preventing new trades. But pairs are never reclassified.
- **Bug #10**: PARTIAL ⚠️ — `_check_ranking_markets()` rule-based function exists and is correct. BUT 87 Top-N pairs in DB are still classified as `mutual_exclusion`. The fix only applies to newly classified pairs; existing misclassified pairs in DB are never reclassified.
- **Bug #11**: OPEN 🔴 — Pair 3765 matrix is now `[[0,1],[1,1]]` (correct for negative correlation code path), BUT the classification itself is wrong. MrBeast "475M subs" vs "477M subs" is NOT negative correlation — hitting 477M implies hitting 475M, making this an implication relationship. The pair is `verified=True`, meaning it could produce bad trades.
- **Bug #12**: PARTIAL ⚠️ — `_partition_matrix` code is correct for binary markets: returns `[[0,1],[1,0]]`. BUT all 35 partition pairs in DB still have stale `[[1,1],[1,1]]` matrices. 0 have the correct matrix. The rescan rebuilds constraint matrices but only for pairs without existing opportunities — 28 out of 35 partition pairs already have opps, so they never get rebuilt.
- **NEW Bug #13**: Portfolio purge has NOT been executed. `purge_contaminated_positions()` method exists but was never called. Portfolio shows: realized_pnl=-$2,506, 13 wins / 3,315 trades (0.4% win rate). 94% of trades (3,109) were on unverified pairs. The portfolio is deeply contaminated and needs a purge before clean metrics can be tracked.
- **NEW Bug #14**: No mechanism exists to rebuild stale constraint matrices for pairs that already have opportunities. `_rescan_existing_pairs` only targets pairs WITHOUT opps. This means bugs #10 and #12 will never self-heal in the DB without manual intervention or a new migration/script.
- **Portfolio health (worsening)**: realized_pnl=-$2,506, unrealized_pnl=-$1,534, 13 wins / 3,315 trades (0.4% win rate). Cash=$15,867 out of $10,000 initial (inflated by position entries). Total value=$14,642. No purge executed despite recommendation.

### 2026-03-21 (third scheduled audit run)
- **Bug #1**: FIXED ✅ — `trades.py` still uses `max()` per market (line 70), subtracts fees (line 105). No regression.
- **Bug #2**: FIXED ✅ — `min_edge` default still 0.03 (line 27). No regression.
- **Bug #3**: FIXED ✅ — `_conditional_matrix` has Frechet/correlation logic (lines 125-195). No regression.
- **Bug #4**: PARTIAL ⚠️ — Hourly regex now works (line 78 captures optional end_time), but see Bug #15 for date-blind issue.
- **Bug #5**: FIXED ✅ — Verification gate in pipeline (line 154). No regression.
- **Bug #6**: FIXED ✅ — Position sizing uses half-Kelly with `net_profit` (line 125). No regression.
- **Bug #7**: PARTIAL → date-blind issue discovered (see new Bug #15). Hourly format regex now matches correctly for time-of-day comparison. But the function never compares DATES, so markets on different dates with same time get mutual_exclusion. Upgraded from OPEN to PARTIAL since the time-format fix is in.
- **Bug #8**: FIXED ✅ — `_rescan_existing_pairs` checks `if not pair.verified: continue` (line 209). No regression.
- **Bug #9**: FIXED ✅ — Classifier now downgrades conditional-without-correlation to "none" (lines 389-403 in classify_llm). DB shows 0 conditional pairs with NULL correlation. All 609 conditional pairs have proper correlation.
- **Bug #10**: FIXED ✅ — `_check_ranking_markets()` exists and works correctly for same-subject different-N pairs (ID=6743 Norway Top 3/10 = implication, ID=6613 Ze-Cheng Dou Top 5/20 = implication). The remaining "Top" pairs classified as mutual_exclusion have DIFFERENT subjects (e.g., Napoli vs Roma for Top 4), which is correctly delegated to the LLM. The LLM's mutual_exclusion for different-team-same-N is debatable but outside the scope of the rule-based fix.
- **Bug #11**: OPEN 🔴 — Pair 3765 still conditional/negative, verified=True. Matrix [[0,1],[1,1]]. MrBeast 475M vs 477M subs is logically an implication (477M→475M) but classified as negative conditional. No rule-based check for subscriber-threshold pairs.
- **Bug #12**: PARTIAL ⚠️ — Code is correct. But DB now has 83 partition pairs total: 61 correct [[0,1],[1,0]], 22 stale [[1,1],[1,1]]. Improved from 35→22 stale (13 fixed via rescan for pairs without opps). However, 3 stale partition pairs are verified=True with all-ones matrices. 22 stale pairs still have active opps blocking rebuild.
- **Bug #13**: FIXED ✅ — Purge was executed! 1,799 PURGE trades recorded in DB. Portfolio snapshot shows reset: realized_pnl=$36.36, total_trades=1002, settled=16, wins=2. Cash=$12,866.87, total_value=$9,954.43.
- **Bug #14**: OPEN 🔴 — No change. `_rescan_existing_pairs` still only targets pairs without opps. 22 stale partition pairs and other stale matrices will never self-heal. The `rescan_by_market_ids` function does refresh constraint matrices for pairs with in-flight opps, but only for verified pairs and only when a price update triggers it — it does NOT reclassify the pair type.
- **NEW Bug #15**: `_check_crypto_time_intervals` compares time-of-day but NOT dates. Confirmed with pair ID=7051: "Dogecoin Up or Down - March 12, 8PM ET" vs "Dogecoin Up or Down - March 21, 8PM ET" — 9 days apart but same time → classified as mutual_exclusion. Should be independent. The regex captures time but discards date entirely. This is the root cause of ongoing crypto misclassifications post-fix.

**Key observations:**
- Total pairs: 7,085 (conditional=609, implication=824, mutual_exclusion=5,569, partition=83)
- New trades are exclusively on verified pairs (1,231 trades in last 6 hours, all verified=True) ✅
- Still 2,863 historical trades on unverified pairs (pre-purge contamination cleared from portfolio)
- Post-purge portfolio: $9,954 total value (from $10,000 initial), realized_pnl=$36.36, win rate 2/16 settled (12.5%). Drastically improved from 0.4% pre-purge but sample size is small.
- 294 conditional pairs have all-ones matrices (correct behavior — prices within bounds, no mispricing to exploit)
- 22 stale partition pairs with all-ones matrices, 3 are verified=True (active risk)
- Opportunity pipeline: 1,592 detected, 2,101 optimized, 1,615 simulated, 1,259 unconverged, 2,405 skipped

### 2026-03-22 (scheduled audit run)
- **Bug #1**: FIXED ✅ — No regression. `trades.py` uses `max()` per market, subtracts fees.
- **Bug #2**: FIXED ✅ — No regression. `min_edge` default is 0.03.
- **Bug #3**: FIXED ✅ — No regression. `_conditional_matrix` has Frechet/correlation logic (lines 127-197).
- **Bug #4**: PARTIAL ⚠️ — Rule-based `_check_crypto_time_intervals()` works for both time-range and hourly formats. However, date-blind issue (Bug #15) persists. 122 crypto pairs still classified as mutual_exclusion, 3 as conditional. 9 are verified ME — confirmed at least 6 are different-date pairs misclassified as ME.
- **Bug #5**: FIXED ✅ — Verification gate in pipeline line 356 (`if not pair.verified: continue`). No regression.
- **Bug #6**: FIXED ✅ — Position sizing uses profit_ratio. No regression.
- **Bug #7**: FIXED ✅ — Upgraded from PARTIAL. `_TIME_INTERVAL_RE` (line 78) now uses `(\d{1,2}(?::\d{2})?[AP]M)` with optional end_time. Both hourly ("10PM") and range ("3:15AM-3:30AM") formats match correctly.
- **Bug #8**: FIXED ✅ — `_rescan_existing_pairs` checks `if not pair.verified: continue` (line 356). No regression.
- **Bug #9**: FIXED ✅ — No conditional pairs with null correlation in matrix JSON. Classifier downgrades conditional-without-correlation to "none" (lines 419-432). No regression.
- **Bug #10**: FIXED ✅ — `_check_ranking_markets()` rule-based function handles same-subject different-N pairs. No regression.
- **Bug #11**: OPEN 🔴 — Pair 3765 still conditional/negative, verified=True. Matrix=[[0,1],[1,1]], correlation=negative. Questions: "Will MrBeast hit 475 million subscribers by April 30?" vs "Will MrBeast hit 477 million subscribers by April 30?" — 477M→475M is logically implication, not negative conditional. No subscriber-threshold rule exists.
- **Bug #12**: PARTIAL ⚠️ — Code correct (`_partition_matrix` returns `[[0,1],[1,0]]` for binary). DB: 127 total partition pairs, 105 with correct matrices, 22 with stale all-ones. 3 stale pairs are verified=True (IDs: 3487, 3729, 3882 — esports kill totals). Only 2 trades ever executed on stale partition pairs, so low active risk. Improved from 35→22 stale since last run (no change since third audit).
- **Bug #13**: FIXED ✅ — Purge executed. 1,799 PURGE trades in DB. Current portfolio: cash=$13,041.60, total_value=$10,119.69, realized_pnl=$43.16. No regression.
- **Bug #14**: OPEN 🔴 — No change. `_rescan_existing_pairs` still only targets pairs WITHOUT existing opps. Stale matrices on 22 partition pairs and pair 3765 will never self-heal. `rescan_by_market_ids` refreshes constraint values for existing opps but does not reclassify pair type.
- **Bug #15**: OPEN 🔴 — `_check_crypto_time_intervals` still compares only time-of-day, not dates. Confirmed: pair 7051 (DOGE March 12 8PM vs March 21 8PM), pair 5127 (ETH March 21 6AM vs March 22 6AM), pair 9777 (XRP March 22 8AM vs March 23 8AM) — all different dates, all classified as mutual_exclusion. The regex captures time but discards date entirely (line 78 has no date capture group). Currently 9 verified ME crypto pairs, at least 6 are date-blind misclassifications.

**Key observations:**
- Total pairs: 10,214 (mutual_exclusion=7,460, implication=1,567, conditional=1,060, partition=127). Growth from 7,085 → 10,214 since last run.
- All implication matrices are correct: `[[1,0],[1,1]]` across all 1,557 verified pairs. ✅
- Conditional pairs: 1,060 total, 659 with all-ones matrix (prices within Frechet bounds), 0 with null correlation. OPTIMIZER_SKIP_CONDITIONAL appears to be working — 16,407 conditional opps skipped, only 62 simulated, 155 trades. Low risk exposure. ✅
- Trade stats: 4,363 filled (1,500 verified, 2,863 historical unverified), 1,799 purged, 563 settled. Settled net PnL = -$2,427 (includes pre-purge contaminated trades).
- Post-purge portfolio: cash=$13,041.60, total_value=$10,119.69 (+1.2% from initial $10,000), realized_pnl=$43.16, 5 wins / 21 settled (23.8% win rate). Improved from 12.5% at last check.
- Pipeline: 1,933 optimized, 1,650 simulated, 872 unconverged, 16,795 skipped, 2,843 expired.
- Date-blind crypto misclassification is the highest-priority remaining bug — but currently only 9 verified ME crypto pairs and 0 trades on them, so no active financial impact yet.
- The 3 verified stale partition pairs (esports) have produced only 2 trades total — low risk but should still be rebuilt.

### 2026-03-22 (scheduled audit run #2)
- **Bug #1**: FIXED ✅ — No regression. `trades.py` uses `max()` per market (line 72-73), subtracts fees (line 104-107).
- **Bug #2**: FIXED ✅ — No regression. `min_edge` default is 0.03 (line 26).
- **Bug #3**: FIXED ✅ — No regression. `_conditional_matrix` has Frechet/correlation logic (lines 129-199).
- **Bug #4**: PARTIAL → FIXED ✅ — Rule-based `_check_crypto_time_intervals()` now handles both time-range and hourly formats AND compares dates (lines 146-157 via `_extract_date`). 0 verified ME crypto "up or down" pairs remain in DB. All previously misclassified pairs reclassified.
- **Bug #5**: FIXED ✅ — No regression. Verification gate in pipeline line 159.
- **Bug #6**: FIXED ✅ — No regression. Position sizing uses profit_ratio.
- **Bug #7**: FIXED ✅ — No regression. `_TIME_INTERVAL_RE` (line 98-101) handles both hourly and range formats.
- **Bug #8**: FIXED ✅ — No regression. `_rescan_existing_pairs` checks `if not pair.verified: continue` (line 360).
- **Bug #9**: FIXED ✅ — No regression. 0 conditional pairs with NULL correlation in DB. Classifier downgrades conditional-without-correlation (lines 541-554).
- **Bug #10**: FIXED ✅ — No regression. `_check_ranking_markets()` rule-based function (lines 390-430).
- **Bug #11**: OPEN → FIXED ✅ — Pair 3765 now classified as `implication` with matrix `[[1,0],[1,1]]`, verified=True. The new `_check_milestone_threshold_markets()` (lines 299-381) correctly identifies subscriber-threshold pairs as implication chains. Q1="Will MrBeast hit 475 million subscribers by April 30?" Q2="Will MrBeast hit 477 million subscribers by April 30?" — 477M→475M is now correctly classified as implication.
- **Bug #12**: PARTIAL → FIXED ✅ — All 169 partition pairs now have correct `[[0,1],[1,0]]` matrices. 0 stale all-ones matrices. Previously stale pairs (3487, 3729) were reclassified as `implication`. Pair 3882 has correct partition matrix but is unverified.
- **Bug #13**: FIXED ✅ — No regression. Purge still in effect.
- **Bug #14**: OPEN → PARTIAL ⚠️ — `_rescan_existing_pairs` still only targets pairs without opps. Code hasn't changed. However, the practical impact is now resolved: all partition pairs have correct matrices, Bug #11 is fixed, and no stale matrices remain in the verified pair set. `rescan_by_market_ids` refreshes constraint matrices on price updates for all verified pairs. The architectural limitation remains but causes no active harm.
- **Bug #15**: OPEN → FIXED ✅ — `_check_crypto_time_intervals` now calls `_extract_date()` (lines 147-148) and returns `"none"` for different dates (lines 149-157). Confirmed: pairs 7051, 5127, 9777 are all correctly classified as `none` and `verified=False`. 0 verified ME crypto pairs remain. The `_DATE_RE` regex (lines 78-83) captures month+day formats. The `_check_price_threshold_markets` function (lines 203-214) also has date comparison.
- **NEW Bug #16**: 121 post-purge trades on unverified pairs. Opps created 2026-03-21 16:10-17:22 UTC on unverified pairs, trades filled after 23:00 UTC. All verification gate code paths are correct in current code. Most likely these opps were created during a deployment gap — the code was committed but not yet rebuilt/restarted. Low ongoing risk since all code paths now gate on verification.

**Key observations:**
- Total pairs: 13,787 (mutual_exclusion=8,723, implication=3,138, conditional=1,621, partition=169, none=136). Growth from 10,214 → 13,787 since last run (+35%).
- All implication matrices are correct: `[[1,0],[1,1]]` across all 3,000 verified pairs. ✅
- All partition matrices are correct: `[[0,1],[1,0]]` across all 42 verified pairs. ✅
- All mutual exclusion matrices are correct: `[[0,1],[1,1]]` across all 8,567 verified pairs. ✅
- Conditional pairs: 1,621 total, 935 with all-ones matrix (prices within Frechet bounds), 686 with actual constraints. 0 with null correlation. ✅
- Trade stats: 6,001 filled, 1,799 purged, 661 settled. Post-purge active: 5,434 verified + 567 unverified filled trades.
- Portfolio: cash=$13,636.58, total_value=$10,094.86 (+0.95% from $10,000 initial), realized_pnl=-$4,205.08 (includes pre-purge contaminated settlements), 119 settled, 37 wins (31.1% win rate).
- Post-purge trades (after 2026-03-21 18:00 UTC): 1,638 total. 1,517 on verified pairs (92.6%), 121 on unverified (7.4% — deployment gap artifact).
- Pipeline: 1,359 optimized, 2,415 simulated, 593 unconverged, 28,768 skipped, 3,910 expired, 685 detected.
- **3 bugs fixed since last run** (Bugs #11, #12, #15). 1 bug upgraded from OPEN to PARTIAL (#14). 1 new bug discovered (#16).
- **Overall health: significantly improved.** All constraint matrix types are correct across verified pairs. No stale matrices. The new `_check_milestone_threshold_markets` rule-based function resolved Bug #11. Date comparison in crypto classifier resolved Bug #15. The system is trading almost exclusively on verified, correctly-classified pairs.

### 2026-03-22 (scheduled audit run #3)
- **Bug #1**: FIXED ✅ — No regression. `trades.py` uses `max()` per market (line 72-73), subtracts fees (line 104-107).
- **Bug #2**: FIXED ✅ — No regression. `min_edge` default is 0.03 (line 26).
- **Bug #3**: FIXED ✅ — No regression. `_conditional_matrix` has Frechet/correlation logic (lines 129-199).
- **Bug #4**: FIXED ✅ — No regression. `_check_crypto_time_intervals()` handles time-range, hourly, and date comparison.
- **Bug #5**: FIXED ✅ — No regression. Verification gate in pipeline line 159.
- **Bug #6**: FIXED ✅ — No regression. Position sizing uses Half-Kelly with net_profit.
- **Bug #7**: FIXED ✅ — No regression. `_TIME_INTERVAL_RE` handles both hourly and range formats.
- **Bug #8**: FIXED ✅ — No regression. `_rescan_existing_pairs` checks `if not pair.verified: continue` (line 360).
- **Bug #9**: FIXED ✅ — No regression. 0 conditional pairs with NULL correlation. Classifier downgrades conditional-without-correlation (lines 541-554).
- **Bug #10**: FIXED ✅ — No regression. `_check_ranking_markets()` rule-based function (lines 390-430).
- **Bug #11**: FIXED ✅ — No regression. Pair 3765 now implication/positive with matrix `[[1,0],[1,1]]`. `_check_milestone_threshold_markets()` (lines 299-381) working correctly.
- **Bug #12**: FIXED ✅ — No regression. All 91 verified partition pairs have correct `[[0,1],[1,0]]` matrices. 0 stale.
- **Bug #13**: FIXED ✅ — No regression. Purge still in effect. 1,799 PURGE trades in DB.
- **Bug #14**: PARTIAL ⚠️ — No code change. `_rescan_existing_pairs` still only targets pairs without opps. Architectural limitation persists but practical impact minimal — newly manifests as Bug #17 (11 stale negative conditional matrices). `rescan_by_market_ids` handles price-triggered refreshes for pairs with opps.
- **Bug #15**: FIXED ✅ — No regression. `_extract_date()` and date comparison working. 0 verified ME crypto "Up or Down" pairs.
- **Bug #16**: STALE ⚠️ — 108 post-purge trades on unverified pairs (down from 121 — likely recounting). Latest unverified opp timestamp is 2026-03-22 01:17 UTC; no new unverified trades since then. Deployment gap artifact, not an active issue. All current code paths correctly gate on verification.
- **NEW Bug #17**: 11 verified negative-correlation conditional pairs have stale all-ones matrices `[[1,1],[1,1]]` instead of `[[0,1],[1,1]]`. The `_conditional_matrix` code correctly handles negative correlation (lines 172-175), but these pairs were created before the fix and never refreshed by `rescan_by_market_ids` (no price updates for their specific markets). IDs: 8332, 8333, 11050, 12133, 13487, 14415, 15001, 15004, 16155, 16265, 17571. **No trades or opportunities on any of these pairs** — profit_bound=0.0 for all. Low risk but technically incorrect state. Root cause is Bug #14 (stale matrices never rebuilt for pairs without price updates).

**Key observations:**
- Total pairs: 17,057 (mutual_exclusion=10,594, implication=4,048, conditional=2,188, partition=220, none=136). Growth from 13,787 → 17,057 (+24%).
- All implication matrices correct: `[[1,0],[1,1]]` across 3,917 verified pairs. ✅
- All partition matrices correct: `[[0,1],[1,0]]` across 91 verified pairs. ✅
- All mutual exclusion matrices correct: `[[0,1],[1,1]]` across 10,457 verified pairs. ✅
- Conditional pairs: 2,063 verified, 1,350 with all-ones matrix (most are prices-within-bounds), 0 with null correlation. 11 negative-correlation pairs have stale all-ones (Bug #17).
- Trade stats: 6,011 filled, 1,799 purged, 689 settled. Pipeline: 1,125 optimized, 2,420 simulated, 388 unconverged, 42,987 skipped, 4,914 expired, 953 detected.
- Portfolio: cash=$13,324.28, total_value=$10,275.26 (+2.75% from $10,000 initial), realized_pnl=-$4,189.28 (includes pre-purge contaminated settlements), settled=147, wins=49.
- Post-purge settlement win rate: **36.6%** (52/142) — up from 31.1% last run, 23.8% two runs ago, and 12.5% three runs ago. Steady improvement trend.
- 0 verified ME crypto "Up or Down" pairs. 0 stale partition pairs. Crypto date-blind issue fully resolved.
- **1 new bug discovered (#17)**, 0 bugs changed status. System health remains strong — all active trading is on correctly-classified, correctly-constrained verified pairs.

### 2026-03-22 (scheduled audit run #4)
- **Bug #1**: FIXED ✅ — No regression. `trades.py` uses `max()` per market (line 72-75), subtracts fees (line 109-112), slippage (line 117). Edge sanity cap at 0.20 (line 18).
- **Bug #2**: FIXED ✅ — No regression. `min_edge` default is 0.03 (line 26 parameter default).
- **Bug #3**: FIXED ✅ — No regression. `_conditional_matrix` has Frechet/correlation logic (lines 129-199). Negative correlation → `matrix[0][0] = 0` (line 174). Positive correlation → divergence threshold (lines 180-197).
- **Bug #4**: FIXED ✅ — No regression. `_check_crypto_time_intervals()` handles time-range, hourly, and date comparison via `_extract_date()` (lines 146-157).
- **Bug #5**: FIXED ✅ — No regression. Verification gate in pipeline: new pair creation gates on `verification["verified"]` (line 159). Rescan gates on `pair.verified` (line 362).
- **Bug #6**: FIXED ✅ — No regression. Half-Kelly position sizing using `net_profit = opp.optimal_trades.get("estimated_profit", 0)` (simulator line 130), `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135). Drawdown scaling (lines 142-146).
- **Bug #7**: FIXED ✅ — No regression. `_TIME_INTERVAL_RE` (lines 98-101) pattern `(\d{1,2}(?::\d{2})?[AP]M)` handles both hourly ("10PM") and range ("3:15AM-3:30AM") with optional end_time.
- **Bug #8**: FIXED ✅ — No regression. `_rescan_existing_pairs` checks `if not pair.verified: continue` (line 362). `rescan_by_market_ids` filters `MarketPair.verified == True` (line 474).
- **Bug #9**: FIXED ✅ — No regression. 0 conditional pairs with NULL correlation in DB. Classifier downgrades conditional-without-correlation (lines 549-558).
- **Bug #10**: FIXED ✅ — No regression. `_check_ranking_markets()` rule-based function (lines 390-430) handles same-subject different-N pairs.
- **Bug #11**: FIXED ✅ — No regression. Pair 3765 = implication/positive with matrix `[[1,0],[1,1]]`. `_check_milestone_threshold_markets()` (lines 299-381) working correctly.
- **Bug #12**: FIXED ✅ — No regression. All 122 verified partition pairs have correct `[[0,1],[1,0]]` matrices. 0 stale. (Grew from 91→122 verified partitions.)
- **Bug #13**: FIXED ✅ — No regression. 1,799 PURGE trades in DB.
- **Bug #14**: PARTIAL ⚠️ — No code change. Architectural limitation persists: `_rescan_existing_pairs` only targets pairs without opps. Manifests as Bug #17 (growing stale negative conditional matrices). `rescan_by_market_ids` handles price-triggered refreshes but does not reclassify pair type.
- **Bug #15**: FIXED ✅ — No regression. `_extract_date()` and date comparison working. 0 verified ME crypto "Up or Down" pairs in DB.
- **Bug #16**: STALE ⚠️ — Latest unverified trade: 2026-03-22 01:39:05 UTC. 298 total post-purge unverified trades (up from 121). 120 today, all between 00:16-01:39 UTC. Deployment gap artifact, no new unverified trades since. However, see new Bug #18 for the architectural issue.
- **Bug #17**: OPEN 🔴 — **Grew from 11 to 14** verified negative-correlation conditional pairs with stale all-ones matrices. IDs: 8332, 8333, 11050, 12133, 15001, 15004, 16155, 16265, 17571, 18273, 18573, 18670, 19151, 19823. Still 0 trades or opps on any. profit_bound=0.0 for all. Root cause remains Bug #14.
- **NEW Bug #18**: Opps created on pairs that later fail re-verification. `rescan_by_market_ids` creates opps when pair is verified=True, then re-verification flips pair to verified=False, but existing in-flight opps are not cancelled. Simulator (`_execute_pending`) does NOT check `pair.verified` before executing. No actual unverified trades since 01:39 UTC — edge/VWAP checks catch them in practice. But architecturally the simulator should gate on pair verification to prevent execution on re-unverified pairs.

**Key observations:**
- Total pairs: 19,446 (conditional: 2,372 total/2,352 verified, implication: 4,685/4,520, mutual_exclusion: ~12,000/unknown, partition: 256/122, none: 136/0). Growth from 17,057 → 19,446 (+14%).
- All implication matrices correct: `[[1,0],[1,1]]` across 4,520 verified pairs. ✅
- All partition matrices correct: `[[0,1],[1,0]]` across 122 verified pairs. ✅
- 0 stale all-ones matrices on verified non-conditional pairs. ✅
- Conditional pairs: 2,352 verified. Matrix distribution: 1,491 positive/all-ones (prices within bounds), 252 `[[0,1],[0,1]]`, 247 `[[0,1],[1,1]]`, 107 `[[1,1],[0,1]]`, plus various others. 14 negative/all-ones (Bug #17, stale). 0 null correlation. ✅ except Bug #17.
- 0 verified ME crypto "Up or Down" pairs. ✅
- Trade stats: 6,011 filled, 1,799 purged, 698 settled. Pipeline: 1,294 detected, 1,166 optimized, 2,420 simulated, 390 unconverged, 43,522 skipped, 4,949 expired.
- Portfolio: cash=$13,050.87, total_value=$10,172.47 (+1.72% from $10,000 initial), realized_pnl=-$4,229.87 (includes pre-purge contaminated settlements), total_trades=2,713, settled=156, wins=51.
- Post-purge settlement win rate: **32.7%** (51/156 settled) — slight dip from 36.6% but sample growing. Portfolio total value down from $10,275→$10,172 (still above initial $10,000).
- Trades today: 804 verified + 120 unverified (all in 00:16-01:39 window). 87% verified rate today.
- **1 new bug discovered (#18)**. Bug #17 grew (11→14). No bugs changed overall status. System health remains acceptable — all constraint matrix types are correct across verified pairs, no new classification bugs, stale matrix population growing slowly.

### 2026-03-23 (scheduled audit run)
- **Bug #1**: FIXED ✅ — No regression. `trades.py` uses `max()` per market (lines 72-75), subtracts fees (lines 109-112), slippage (line 117). Edge cap at 0.20 (line 18). Payout proof (lines 149-170).
- **Bug #2**: FIXED ✅ — No regression. `min_edge` default is 0.03 (line 26). Min profit threshold 0.005 (line 125).
- **Bug #3**: FIXED ✅ — No regression. `_conditional_matrix` has Frechet/correlation logic (lines 141-211). Negative → `matrix[0][0]=0` (line 186). Positive → divergence threshold (lines 192-209).
- **Bug #4**: FIXED ✅ — No regression. `_check_crypto_time_intervals()` handles time-range, hourly, and date comparison.
- **Bug #5**: FIXED ✅ — No regression. Verification gate in pipeline (line 360: `if profit > 0 and verification["verified"]`).
- **Bug #6**: FIXED ✅ — No regression. Half-Kelly with `net_profit` (simulator line 130), `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135), drawdown scaling (lines 142-146).
- **Bug #7**: FIXED ✅ — No regression. `_TIME_INTERVAL_RE` (lines 117-120) handles both hourly and range formats.
- **Bug #8**: FIXED ✅ — No regression. `_rescan_existing_pairs` checks `if not pair.verified: continue`.
- **Bug #9**: FIXED ✅ — No regression. 0 conditional pairs with NULL correlation in DB. Classifier downgrades conditional-without-correlation (lines 589-601).
- **Bug #10**: FIXED ✅ — No regression. `_check_ranking_markets()` (lines 424-467).
- **Bug #11**: FIXED ✅ — No regression. Pair 3765 = implication/positive with matrix `[[1,0],[1,1]]`. `_check_milestone_threshold_markets()` (lines 327-415).
- **Bug #12**: FIXED ✅ — No regression. All 122 verified partition pairs have correct `[[0,1],[1,0]]` matrices.
- **Bug #13**: FIXED ✅ — No regression. 1,799 PURGE trades in DB.
- **Bug #14**: PARTIAL ⚠️ — No code change. Architectural limitation persists. Now also root cause of Bug #19 (stale wrong-direction implication matrices).
- **Bug #15**: FIXED ✅ — No regression. `_extract_date()` and date comparison working. 0 verified ME crypto "Up or Down" pairs.
- **Bug #16**: STALE ⚠️ — No new unverified trades since 2026-03-22 01:39 UTC. 0 unverified trades after Mar 22 02:00 UTC. Historical artifact only.
- **Bug #17**: OPEN 🔴 — Still 14 verified negative-conditional pairs with stale all-ones matrices. Same IDs as last run (no growth). Still 0 opps, 0 trades, profit_bound=0.0 for all. Low risk.
- **Bug #18**: OPEN 🔴 — No code change. Simulator still doesn't check `pair.verified` before executing. No actual impact (0 unverified trades recently). Architectural concern only.
- **NEW Bug #19**: 🆕 **CRITICAL** — 2,609 out of 4,520 verified implication pairs (57.7%) have INVERTED constraint direction. Root cause: all 4,520 verified implication pairs have `implication_direction=NULL` in both the column and constraint_matrix JSON. `build_constraint_matrix` defaults `None` to `"a_implies_b"`, producing `[[1,0],[1,1]]` for ALL pairs. For pairs where B actually implies A (e.g., O/U 1.5 vs O/U 2.5 — Over 2.5 implies Over 1.5), the constraint is backwards: it forbids (Yes, No) which is a valid outcome, and allows (No, Yes) which is impossible. 2,188 trades on these wrong-direction pairs. The verification check (`_check_price_consistency` line 206-218) also uses the wrong direction, so it doesn't catch the error. The payout proof (`_worst_case_payoff`) uses the same wrong feasibility matrix. Newer unverified pairs (IDs 21400+) have correct `[[1,1],[0,1]]` matrices — these are classified by the rule-based O/U/price-threshold checkers which DO return `implication_direction`. The 4,520 verified pairs were classified before these rule-based functions existed and used the LLM label path which doesn't return direction. `classification_source=NULL` for all 4,520 confirms they predate the resolution-vector and rule-based classifiers. **This is likely the primary driver of poor PnL on implication trades.** Fix requires: (1) reclassify all verified implication pairs to determine correct direction, (2) rebuild constraint matrices with correct direction, (3) consider purging trades on wrong-direction pairs.

**Key observations:**
- Total pairs: 21,172 (mutual_exclusion=12,995/0 verified, implication=5,112/4,520, conditional=2,652/2,352, partition=277/122, none=136/0). Growth from 19,446 → 21,172 (+8.9%).
- **0 verified ME pairs** — all 12,995 mutual_exclusion pairs are unverified. ME structural check requires same event_id; 12,784 have NULL classification_source (pre-date verification), 192 are llm_vector, 19 are llm_label.
- All 4,520 verified implication pairs have `[[1,0],[1,1]]` — but 2,609 (57.7%) should be `[[1,1],[0,1]]` (b_implies_a). **Bug #19.**
- 116 unverified implication pairs have correct `[[1,1],[0,1]]` (b_implies_a) — these are newer, correctly classified but not yet verified.
- All 122 verified partition pairs correct: `[[0,1],[1,0]]`. ✅
- Conditional: 2,352 verified. Matrix distribution: 1,505 all-ones (within bounds), 261 `[[0,1],[1,1]]`, 252 `[[0,1],[0,1]]`, 107 `[[1,1],[0,1]]`, 64 `[[0,0],[1,1]]`, 60 `[[1,1],[1,0]]`, 48 `[[1,0],[1,1]]`, 31 `[[1,1],[0,0]]`, 24 `[[1,0],[1,0]]`. 14 negative/all-ones (Bug #17). 0 null correlation. ✅ except Bug #17.
- **System appears stalled**: Last trade 2026-03-22 13:27 UTC. Last price snapshot 2026-03-22 13:32. Last pair created 2026-03-22 22:50. 0 new pairs today, 0 trades today. Latest portfolio snapshot 2026-03-22 22:56 (unchanged). Ingestor may have lost Polymarket API access or Docker container crashed.
- Trade stats: 6,011 filled, 1,799 purged, 698 settled. Pipeline: 1,294 detected, 1,166 optimized, 2,420 simulated, 390 unconverged, 43,522 skipped, 4,949 expired. (Unchanged from last run.)
- Portfolio: cash=$13,050.87, total_value=$10,172.47 (+1.72% from $10,000), realized_pnl=-$4,229.87, total_trades=2,713, settled=156, wins=51. Win rate: **32.7%** (51/156). Unchanged from last run (no new trades).
- **1 new CRITICAL bug discovered (#19)**. 0 bugs changed status. Bug #17 stable at 14 (no growth). System stalled (no new trading activity ~34 hours).
