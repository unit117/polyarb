# Performance Monitor Agent Memory

This file is read and updated by the `performance-monitor` scheduled task on every run.
Each run should: (1) read this file, (2) check bug status, (3) append a run log entry, (4) update bug statuses.

---

## Known Bugs

Track each bug with its status. Update on every run after checking the codebase.

| # | Bug | Location | Found | Status | Last Checked |
|---|-----|----------|-------|--------|--------------|
| 1 | estimated_profit double-counts edges — sums per-outcome abs deltas, inflating profit ~4x for binary pairs | `services/optimizer/trades.py` ~line 67 | 2026-03-21 | FIXED | 2026-03-21 |
| 2 | min_edge threshold too low (0.005) — below breakeven after fees (~0.02-0.03) | `services/optimizer/trades.py` ~line 40 | 2026-03-21 | FIXED | 2026-03-21 |
| 3 | Conditional pairs have no real constraints — `_conditional_matrix` returns all-ones matrix | `services/detector/constraints.py` | 2026-03-21 | FIXED | 2026-03-21 |
| 4 | GPT-4o-mini misclassifies crypto time-interval pairs as mutual_exclusion | `services/detector/classifier.py` | 2026-03-21 | FIXED | 2026-03-21 |
| 5 | 0% pair verification rate — system trades on entirely unverified pairs | system-wide | 2026-03-21 | FIXED | 2026-03-21 |
| 6 | Position sizing uses inflated edge — oversizes positions based on double-counted edge | `services/simulator/pipeline.py` ~line 79 | 2026-03-21 | FIXED | 2026-03-21 |
| 7 | LLM misclassifies price-threshold markets as mutual_exclusion instead of implication | `services/detector/classifier.py` (LLM path) | 2026-03-21 | FIXED | 2026-03-21 |
| 8 | LLM misclassifies same-date-different-threshold markets as mutual_exclusion | `services/detector/classifier.py` (LLM path) | 2026-03-21 | FIXED | 2026-03-21 |
| 9 | Pre-fix data contamination — portfolio never purged, carrying losses from pre-fix trades | DB data / `services/simulator/pipeline.py` | 2026-03-21 | FIXED | 2026-03-21 |
| 10 | `_PRICE_THRESHOLD_RE` requires `$` before number — misses "close over 5,625" patterns without dollar signs | `services/detector/classifier.py` line 83-87 | 2026-03-21 | FIXED | 2026-03-21 |
| 11 | Over/Under sports markets ("O/U 227.5" vs "O/U 228.5") not handled by rule-based heuristics — fall to LLM which misclassifies as mutual_exclusion | `services/detector/classifier.py` (missing rule) | 2026-03-21 | FIXED | 2026-03-21 |
| 12 | Optimizer produces phantom 50¢+ edges on misclassified mutual_exclusion pairs where both sides price near $1.00 — constraint says they can't both be Yes, optimizer halves fair prices | `services/optimizer/frank_wolfe.py` + classifier | 2026-03-21 | PARTIALLY FIXED | 2026-03-23 |
| 13 | Old misclassified pairs never re-classified — 120 O/U pairs still tagged as ME (down from 520→71→120 rebounding as new O/U markets paired), plus 81 esports game-winner pairs (up from 52). No re-classification pipeline. | DB stale data + no re-classification pipeline | 2026-03-21 | OPEN (worsened) | 2026-03-23 |
| 14 | Esports "Game X Winner" pairs misclassified as ME — "Game 1 Winner" and "Game 4 Winner" in same series are independent, not mutually exclusive. 81 such pairs now (up from 52). | `services/detector/classifier.py` (no rule) | 2026-03-21 | OPEN (worsened) | 2026-03-23 |
| 15 | Conditional pairs est/theo ratio — conditional pipeline appears inactive. 45,402 conditional opps detected post-purge but only 1 simulated. avg_est=0.008 vs avg_theo=0.497 (ratio 0.016x). Pipeline effectively self-suppresses via low est_profit. | `services/detector/constraints.py` _conditional_matrix | 2026-03-21 | LOW RISK | 2026-03-23 |
| 16 | "By June" vs "By December" pairs misclassified as partition — LLM classifies deadline-nested events as partition instead of implication. Partition constraint yields theo=1.0, massively overstating profit. 37 simulated post-purge. Iran conflict pairs and Discord/Remote IPO pairs actively trading. | `services/detector/classifier.py` (LLM path) | 2026-03-22 | OPEN | 2026-03-23 |
| 17 | Per-market position cap (200 shares) exists in circuit breaker but is bypassed in some cases. 2 markets exceed 200 shares (Atlas O/U 265, USD/CAD 245). Improved from 6 markets. Execution lock serialization helping but race window still exists. | `shared/circuit_breaker.py` line 138-161 | 2026-03-22 | PARTIALLY FIXED (improving) | 2026-03-23 |
| 18 | Win rate deterioration: March 22 overall 36.6% (34/93), March 23 so far 50.0% (13/26). BTC and O/U single-settlement blowups drive most losses (100-135 shares per loss). | system-wide | 2026-03-22 | OPEN (improving) | 2026-03-23 |
| 19 | 🆕 **CRITICAL** — All services down since 03:06 UTC March 23. No price snapshots, no market updates, no opportunities, no trades for 5+ hours. Last activity burst was 02:00-03:06 UTC. Likely Docker container crash on NAS. | All services | 2026-03-22 | OPEN (CRITICAL) | 2026-03-23 |
| 20 | La Liga partition misclassification — "Villarreal top 4" vs "Real Sociedad top 4" classified as partition (theo=1.0) but these are NOT exhaustive: both could finish top 4 or neither could. Still simulated (opp 37961 at 01:17 UTC Mar 22). | `services/detector/classifier.py` (LLM path) | 2026-03-22 | OPEN | 2026-03-23 |
| 21 | 🆕 Discord IPO / Remote IPO misclassified as partition — "Discord IPO before 2027" and "Remote IPO before 2027" classified as partition (theo=1.0) by LLM. These are completely independent companies. Simulated as opp 53726 with est=0.351. | `services/detector/classifier.py` (LLM path) | 2026-03-23 | OPEN | 2026-03-23 |
| 22 | 🆕 Pair verification rate collapsed to 29.2% (6,704/22,981) — down from 96.4% on Mar 22. Massive influx of new pairs not being verified, suggesting verification pipeline can't keep up with pair creation rate. | `services/detector/verification.py` | 2026-03-23 | OPEN | 2026-03-23 |

---

## Run Log

<!-- Append a new entry after each run. Format: -->
<!-- ### YYYY-MM-DD HH:MM -->
<!-- - Bug check results (which are fixed, which are still open) -->
<!-- - Any NEW bugs discovered (add to table above with 🆕) -->
<!-- - Key observations from this run -->

### 2026-03-21 (initial seed)
- All 6 bugs catalogued from this agent's own deep-dive analysis.
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

### 2026-03-21 ~10:15 UTC (scheduled performance monitor run)
- **Bug #1 FIXED**: Confirmed. `trades.py` line 72-74 uses `max()` per market, not sum. Correct.
- **Bug #2 FIXED**: Confirmed. `min_edge=0.03` on line 19. Correct.
- **Bug #3 FIXED**: Confirmed. `_conditional_matrix()` now implements divergence threshold, correlation-based, and sum-based constraints. Lines 108-178 of constraints.py.
- **Bug #4 FIXED**: Confirmed. `_check_crypto_time_intervals()` exists in classifier.py lines 75-110 with regex matching and same/different window logic.
- **Bug #5 FIXED**: Confirmed. Detector pipeline.py line 142 gates on `verification["verified"]`. Post-fix data (57 opps) all show verified=True.
- **Bug #6 FIXED**: Confirmed. pipeline.py line 74 uses `profit_ratio = min(net_profit / 0.10, 1.0)` instead of raw edge.
- **Bug #7 NEW (OPEN)**: LLM classifier misclassifies price-threshold markets (e.g., "PLTR above $128" + "PLTR above $134") as mutual_exclusion. These should be implication ($134 implies $128). Unverified, so post-fix they won't trade, but still pollutes pair DB.
- **Bug #8 NEW (OPEN)**: LLM classifier misclassifies same-metric-different-date pairs as mutual_exclusion (e.g., "BTC above $80K on March 23" vs "March 24"). The `_check_crypto_time_intervals` rule only matches "Up or Down" pattern, not "above $X" pattern. Should be extended.
- **Bug #9 NEW (OPEN)**: Database contains 1025 pre-fix simulated opps with inflated estimated_profit (95.7% have est>theo). These contribute to the -$1,881 realized PnL. Portfolio is contaminated with positions entered at wrong sizes on wrong premises. Consider flushing portfolio state or starting fresh.
- **Key metrics this run**: Portfolio at $13,446 total value (from $10,000), but realized PnL is -$1,881 and unrealized PnL is -$1,239. Only 13 winning trades out of 3,165 total (0.41% win rate). Post-fix period shows improvement: all 57 opps verified, est>theo anomaly rate drops from 99.9% to 19.3%.

### 2026-03-21 ~11:15 UTC (scheduled performance monitor run)
- **Bug #1 FIXED**: Confirmed. `trades.py` lines 72-74 use `max()` per market.
- **Bug #2 FIXED**: Confirmed. `min_edge=0.03` on line 19.
- **Bug #3 FIXED**: Confirmed. `_conditional_matrix()` has full divergence/correlation/sum logic (lines 115-185 of constraints.py).
- **Bug #4 FIXED**: Confirmed. `_check_crypto_time_intervals()` in classifier.py lines 90-131.
- **Bug #5 FIXED**: Confirmed. Verification gating still in place.
- **Bug #6 FIXED**: Confirmed. `profit_ratio = min(net_profit / 0.10, 1.0)` on line 74 of pipeline.py.
- **Bug #7 PARTIALLY FIXED**: `_check_price_threshold_markets()` now exists (lines 134-215) and handles "above $X" pattern correctly as implication. However, the `_PRICE_THRESHOLD_RE` regex requires `$` before the number and won't match questions like "close over 5,625" without dollar signs (see new Bug #10).
- **Bug #8 PARTIALLY FIXED**: The `_check_price_threshold_markets()` handles same-asset time-interval comparisons. The LLM prompt also includes guidance. However, date-only patterns (without HH:MM time intervals) still fall through to LLM only.
- **Bug #9 STILL OPEN**: **Contamination purge never executed**. 0 PURGE trades in DB. No portfolio resets (total_trades never went to 0). Portfolio carries full pre-fix contamination.
- **Bug #10 NEW (OPEN)**: `_PRICE_THRESHOLD_RE` regex requires `\$` before the number. Questions like "Will S&P 500 (SPX) close over 5,625..." and "Celtics vs. Grizzlies: O/U 227.5" do not match, falling through to LLM which misclassifies as mutual_exclusion. Evidence: Opp IDs 2954-2956 show SPX threshold pairs classified as ME with $0.98 phantom edges.
- **Bug #11 NEW (OPEN)**: Over/Under sports markets (e.g., "O/U 227.5" vs "O/U 228.5") have no rule-based handler. These are implication pairs (Over 228.5 implies Over 227.5) but get classified as mutual_exclusion by LLM.
- **Bug #12 NEW (OPEN)**: Downstream of #10 and #11 — when implication pairs are misclassified as mutual_exclusion, the optimizer sees two highly-priced ($0.999) outcomes that "can't both be Yes" and halves both fair prices to ~$0.50, producing phantom 50¢ edges. The system then trades 400 shares at these phantom edges, taking massive losing positions. This is the primary driver of post-fix realized losses.
- **Key metrics this run**:
  - Portfolio: $14,972 total value (from $10,000 initial), Cash: $16,495
  - Realized PnL: -$2,579, Unrealized PnL: -$1,702
  - Total trades: 3,389 (3,917 including settlements), Winning: 13 (0.38% win rate)
  - Post-fix: 126 simulated opps, 420 trades (210 buy + 210 sell), 56 settlements
  - Post-fix est. dollar profit: $12,406 (on paper) — but this is based on phantom edges from misclassified pairs
  - Fees: $306 post-fix, $466 total; Slippage cost: $153 post-fix, $233 total
  - Est>Theo anomaly: Pre-fix 35.6%, Post-fix 3.5% (major improvement from bug #1/#2 fixes)
  - System still active: ~200-600 opps/hour, 23-57 simulated/hour
  - Conditional pair Est/Theo ratio: 2.08x (est overestimates by 2x — constraints too loose)

### 2026-03-21 ~17:30 UTC (scheduled performance monitor run)
- **MAJOR EVENT**: Contamination purge executed at 12:02 UTC. 1,799 positions closed. Portfolio counters reset. Bug #9 is now FIXED.
- **Bug #1-6 FIXED**: All confirmed in code. No regressions.
- **Bug #7 FIXED**: `_check_price_threshold_markets()` handles "above/below/over/under $X" as implication.
- **Bug #8 FIXED**: Same function handles same-asset different-time-window as independent.
- **Bug #9 FIXED**: Purge executed at 12:02 UTC. 1,799 PURGE trades. Portfolio reset (trades 3,537→58, realized PnL reset to ~0).
- **Bug #10 FIXED**: `_PRICE_THRESHOLD_RE` regex now uses `\$?` (optional dollar sign). "close over 5,625" matches.
- **Bug #11 FIXED**: `_check_over_under_markets()` exists (lines 290-330). Handles O/U as implication chains.
- **Bug #12 PARTIALLY FIXED**: MAX_EDGE cap at 0.20 catches extreme phantom edges. 2,631 opps capped. But moderate phantom edges (0.10-0.15/leg) from old misclassified pairs still pass.
- **Bug #13 NEW (OPEN)**: 468 O/U pairs still classified as ME in DB. Never re-classified after rule added. Continue generating phantom-edge trades (Pair 3329 simulated at 17:22 UTC with est=0.264).
- **Bug #14 NEW (OPEN)**: Esports "Game X Winner" pairs misclassified as ME. "Game 1 Winner" vs "Game 4 Winner" are independent. Pair 5630 simulated with est=0.253.
- **Bug #15 NEW (OPEN)**: Conditional pairs est/theo ratio 2.31x. 82% (51/62) simulated conditional opps have est > theo. DIVERGENCE_THRESHOLD of 0.15 too wide.
- **Key metrics (post-purge, 12:02-17:28 UTC)**:
  - Portfolio: $10,119 value (+$167, +1.7% since purge)
  - Cash: $13,041, Realized PnL: +$43.16, Unrealized PnL: +$70.81
  - Post-purge trades: 1,065 total, 5 wins out of 21 settlements = 23.8% win rate
  - Post-purge fees: $91.24, slippage: $77.33
  - Edge cap triggers: 2,631 (blocking phantom edges effectively)
  - Open positions: 369 non-zero
  - Pair verification: 4,908/7,614 = 64% verified
  - Est>Theo anomaly: 1.1% post-fix (excellent, down from 99.9% pre-fix)
  - Primary remaining loss driver: old misclassified O/U/esports pairs (#13, #14)

### 2026-03-22 ~06:00 UTC (scheduled performance monitor run)
- **CRITICAL DETERIORATION**: Portfolio realized PnL crashed from +$43 → -$4,183 in ~12 hours (17:00 Mar 21 → 01:00 Mar 22). Total value: $10,100 (+$100 from initial, +1.0%). March 22 win rate collapsed to 3.6% (1/28 settlements).
- **Bug #1-11 FIXED**: All confirmed in code. No regressions. trades.py uses `max()` per market (line 72-74), min_edge=0.03, `_conditional_matrix` has divergence/correlation/sum logic, `_check_crypto_time_intervals()` exists, verification gating in place, `kelly_fraction = min(net_profit * 0.5, 1.0)` on line 135, `_check_price_threshold_markets()` handles optional `$`, `_check_over_under_markets()` handles O/U as implication.
- **Bug #12 PARTIALLY FIXED**: MAX_EDGE=0.20 cap still in place. 923 edge-capped opps post-purge. Moderate phantom edges (0.10-0.19) from stale misclassified pairs still pass through.
- **Bug #13 STILL OPEN**: **WORSENED**. O/U pairs classified as ME now at 520 (was 468). Still generating trades — FC Dallas O/U pairs simulated at 23:59 UTC with est=0.332. These old pairs are never re-classified.
- **Bug #14 STILL OPEN**: 14 esports game-winner pairs still tagged as ME. LoL GIANTX vs Fnatic pair (7567) simulated 3 times in last hour alone with phantom est=0.16-0.20.
- **Bug #15 OPEN (no data)**: 0 conditional pair opps simulated post-purge. Cannot assess est/theo ratio. The conditional pipeline appears inactive.
- **Bug #16 NEW (OPEN)**: "By June" vs "By December" deadline-nested events misclassified as partition by LLM (no event_id match, falls to LLM). Partition constraint yields theoretical_profit=1.0 — wildly inflated. 34 simulated post-purge, 145 such pairs in DB. Examples: "Iran conflict ends by March 31" vs "by June 30", "Mahmoud Abbas out by June" vs "by December". These should be implication (shorter deadline implies longer deadline).
- **Bug #17 NEW (OPEN)**: No per-market position concentration limit. System re-enters the same market across multiple opportunities. Bitcoin $74K on Mar 27: 25 BUY entries, 256 total shares. Munich weather 16°C: 9 settlements, ALL losses, 88.4 shares wiped. The circuit breaker checks per-trade but doesn't cap per-market aggregate exposure.
- **Bug #18 NEW (OPEN)**: March 22 win rate collapse — 1 win out of 28 settlements (3.6%). Two markets drove bulk of losses: Munich weather (9 settlements, 88 shares, all lost) and Slovenian election turnout (9 settlements, 74 shares, all lost). Root cause: bugs #13 (stale pairs) + #17 (no concentration limit) compound to create single-market blowups.
- **Key metrics**:
  - Portfolio: $10,100 value (+$100, +1.0% since purge), Cash: $14,054
  - Realized PnL: -$4,183 (cratered from +$43 at 17:00 Mar 21)
  - Unrealized PnL: -$82
  - Total trades (post-purge): 2,379, Settled: 91, Winning: 28
  - Post-purge win rate: 28/91 = 30.8% overall, but **March 22: 1/28 = 3.6%**
  - Post-purge fees: $113 (BUY $38 + SELL $75), Slippage: $12
  - Fee drag: avg $0.048/trade, avg slippage $0.005/trade (both modest vs avg est_profit $0.155)
  - Est vs Theo: avg ratio 0.847 (est < theo — conservative, good), only 14/1183 (1.2%) have est > theo
  - Edge cap: 923 opps blocked (highly effective)
  - By pair type: implication 900 opps, mutual_exclusion 249 opps, partition 34 opps
  - Pair verification: 8,721 verified / 11,434 total = 76%
  - Opportunity flow (24h): 28,060 skipped, 3,383 expired, 1,354 simulated, 704 detected, 701 optimized
  - **Primary loss drivers**: (1) Stale misclassified O/U/esports ME pairs (#13, #14) generating phantom edges, (2) Position concentration amplifying single-market losses (#17), (3) Partition misclassification inflating profit on deadline pairs (#16)

### 2026-03-22 ~08:15 UTC (scheduled performance monitor run)
- **Bug #1-11 FIXED**: All confirmed in code. No regressions. trades.py uses `max()` per market (line 72-74), min_edge=0.03, `_conditional_matrix` has divergence/correlation/sum logic, `_check_crypto_time_intervals()` exists, verification gating in place, kelly_fraction sizing, `_check_price_threshold_markets()` with optional `$`, `_check_over_under_markets()` handles O/U as implication.
- **Bug #12 PARTIALLY FIXED**: MAX_EDGE=0.20 cap still in place (trades.py line 18). 1,085 edge-capped opps post-purge. Moderate phantom edges from stale pairs still pass.
- **Bug #13 OPEN (improving)**: O/U pairs as ME dropped from 520 → 71 (markets resolving/expiring). 52 esports game-winner pairs remain. Still no re-classification pipeline.
- **Bug #14 OPEN**: 52 esports game-winner pairs still as ME. No rule-based handler added.
- **Bug #15 LOW RISK**: Conditional pipeline effectively self-suppresses. 42,245 conditional opps detected but only 1 simulated (avg_est=0.008, way below min_edge). Not causing losses.
- **Bug #16 OPEN**: Deadline-nested partition misclassification continues. 35 simulated post-purge with theo=1.0. Iran conflict and Abbas pairs actively trading. New finding: La Liga placement pairs also misclassified (see Bug #20).
- **Bug #17 PARTIALLY FIXED**: Circuit breaker has 200-share per-market cap (`shared/circuit_breaker.py` line 152), but 6 markets exceed it (up to 334 shares). Root cause appears to be rapid sequential entries from queued opportunities that check position before prior leg's position update is reflected.
- **Bug #18 OPEN**: Win rate 33.3% for March 22 (28/84). Weather markets 0/18 wins, election markets 0/12 wins. O/U 32W/25L but concentrated size on losers. Losses now spread across more categories vs. previous run.
- **Bug #19 NEW**: Simulation pipeline stalled during 07:00-08:00 UTC window. 10,243 opps processed, 0 simulated. 06:00 hour had only 4 simulations. System may have hit drawdown circuit breaker trip or cash exhaustion.
- **Bug #20 NEW**: La Liga placement pairs misclassified as partition. "Villarreal top 4" vs "Real Sociedad top 4" — LLM says partition (theo=1.0) but both or neither could finish top 4. Not exhaustive/exclusive events.
- **Key metrics**:
  - Portfolio: $10,275 value (+2.75% since purge, +$175), Cash: $13,324
  - Realized PnL: -$4,189 (slight worsening from -$4,183 last run — losses stabilizing)
  - Unrealized PnL: +$98 (improved from -$82 — open positions recovering)
  - Total trades (post-purge): 2,720 BUY+SELL, Settled: 147 (up from 91), Winning: 49 (up from 28)
  - Post-purge win rate: 49/147 = 33.3% overall. By date: Mar 21 41.4% (24/58), Mar 22 33.3% (28/84)
  - Win rate by 6h window: 12:00-18:00 31.2%, 18:00-00:00 45.2%, 00:00-06:00 28.6%, 06:00-12:00 42.9%
  - Post-purge fees: BUY $42 + SELL $82 = $124 total. Slippage: BUY $58 + SELL $82 = $140 total
  - By pair type: implication 3,546 opps (1,076 sim), ME 2,728 (225 sim), conditional 42,245 (1 sim), partition 167 (35 sim)
  - Pair verification: 14,918/15,479 = 96.4% (up from 76%)
  - Open positions: 609 non-zero across 609 unique markets (very dispersed)
  - Top exposures: Atlas O/U 4.5 (265 shares), AAPL $245 (300 shares), BTC $74K (295 shares)
  - Opp flow (24h): 42,785 skipped, 4,099 expired, 1,504 simulated, 1,112 detected, 702 optimized
  - Edge cap: 1,085 opps blocked
  - **Primary loss drivers**: (1) Weather markets — 18 settlements, 0 wins, 106 shares lost (2) Election/turnout — 12 settlements, 0 wins, 91 shares lost (3) Partition misclassification — deadline-nested and La Liga pairs with theo=1.0 (4) Position concentration bypass on 6 markets exceeding 200-share cap

### 2026-03-23 ~08:15 UTC (scheduled performance monitor run)
- **CRITICAL: ALL SERVICES DOWN** since 03:06 UTC March 23. No price snapshots, market updates, opportunities, or trades for 5+ hours. Last activity was a burst at 02:00-03:06 UTC (409 opps simulated, 878 trades). Portfolio snapshots still being written (same stale data) suggesting the snapshot loop runs but pipeline services (ingestor, detector, optimizer, simulator) are all dead. Likely Docker container crash on NAS.
- **Bug #1-11 FIXED**: All confirmed in code. No regressions. trades.py uses `max()` per market (line 71-75), min_edge=0.03 (line 60), `_conditional_matrix` has divergence/correlation/sum logic (lines 141-211), `_check_crypto_time_intervals()` exists (lines 134-194), verification gating in place, kelly_fraction sizing (line 135), `_check_price_threshold_markets()` with optional `$` (line 128), `_check_over_under_markets()` handles O/U as implication (lines 478-521). New: `_check_milestone_threshold_markets()` (lines 327-415) and `_check_ranking_markets()` (lines 424-467) added.
- **Bug #12 PARTIALLY FIXED**: MAX_EDGE=0.20 cap still in place (trades.py line 18). 612 edge-capped opps post-purge. Payout proof (BT-009) now added (lines 147-170) — rejects trades with negative worst-case payoff. Additional minimum profit filter (BT-008, line 125) rejects opps with est < 0.005.
- **Bug #13 OPEN (worsened)**: O/U pairs as ME rebounded to 120 (was 71 last run). New O/U markets being paired and falling to LLM which still misclassifies. Esports game-winner pairs up to 81 (was 52). No re-classification pipeline exists.
- **Bug #14 OPEN (worsened)**: 81 esports game-winner pairs still as ME (up from 52). No rule-based handler added.
- **Bug #15 LOW RISK**: Conditional pipeline still self-suppresses. 45,402 opps detected, only 1 simulated. avg_est=0.008 vs avg_theo=0.497.
- **Bug #16 OPEN**: Deadline-nested partition misclassification continues. 37 simulated post-purge. Iran conflict "ends by March 31" vs "by June 30" / "by December 31" still actively generating trades with theo=1.0, est=0.14-0.35. New: Discord IPO vs Remote IPO misclassified as partition (see Bug #21).
- **Bug #17 PARTIALLY FIXED (improving)**: Only 2 markets now exceed 200-share cap (down from 6): Atlas O/U 4.5 (265 shares) and USD/CAD 1.20 (245 shares). Execution lock serialization is helping.
- **Bug #18 OPEN (improving)**: March 22 win rate improved to 36.6% (34/93, up from 33.3%). March 23 so far 50.0% (13/26). However, share-weighted losses still heavy — single BTC settlements losing 135 shares and O/U settlements losing 100-118 shares dwarf winning positions.
- **Bug #19 CRITICAL (escalated)**: No longer just a simulation stall — entire system is down since 03:06 UTC. All services (ingestor, detector, optimizer, simulator) appear crashed. Portfolio snapshot loop still writes identical data every 5 minutes. Need to check Docker containers on NAS.
- **Bug #20 OPEN**: La Liga partition misclassification confirmed still present. Opp 37961 simulated at 01:17 UTC Mar 22.
- **Bug #21 NEW**: Discord IPO / Remote IPO classified as partition (theo=1.0) by LLM — these are completely independent companies. Opp 53726 simulated with est=0.351.
- **Bug #22 NEW**: Pair verification rate collapsed to 29.2% (6,704/22,981), down from 96.4% at last run. Massive pair creation outpacing verification. 16,277 unverified pairs. Verification pipeline may be broken or overwhelmed.
- **Key metrics**:
  - Portfolio: $10,069 value (+0.69% since purge), Cash: $13,187
  - Realized PnL: -$4,250 (worsened from -$4,189 last run, -$61 since)
  - Unrealized PnL: -$226 (deteriorated from +$98 — open positions losing)
  - Total trades (post-purge): 3,598 BUY+SELL, Settled: 177, Winning: 71
  - Post-purge win rate: 71/177 = 40.1% overall (improved from 33.3%)
  - By date: Mar 21 41.4% (24/58), Mar 22 36.6% (34/93), Mar 23 50.0% (13/26)
  - Win rate by 6h window: 12-18 31.2%, 18-00 45.2%, 00-06 28.6%→50.0% (improving), 06-12 42.9%→66.7%
  - Post-purge fees: BUY $46 + SELL $87 = $134 total. Slippage: BUY $68 + SELL $92 = $160 total
  - Fee drag: avg $0.037/trade, avg slippage 0.50%, avg price impact $0.002
  - By pair type: implication 4,366 opps (1,502 sim), ME 2,809 (232 sim), conditional 45,402 (1 sim), partition 219 (37 sim)
  - Pair verification: 6,704/22,981 = 29.2% (COLLAPSED from 96.4%)
  - Open positions: 688 unique markets
  - Top exposures: Atlas O/U 4.5 (265), USD/CAD 1.20 (245), SKC O/U 4.5 (199), Trump Nebraska (198), BTC $70K (196)
  - Edge cap: 612 opps blocked
  - Simulated est vs theo: avg_est=0.132, avg_theo=0.165, est>theo only 26/1,772 (1.5%) — excellent calibration
  - **CRITICAL**: All services down 5+ hours. No trades since 03:06 UTC. Need restart.
  - **Primary loss drivers**: (1) Single-market blowups — BTC $78K (135 shares lost), Vancouver O/U (118), BTC $76K (110), Blues O/U (106) (2) Partition misclassification — Iran conflict, Discord/Remote IPO with theo=1.0 (3) Stale O/U pairs rebounding (120 still as ME) and esports growing (81 pairs) (4) Verification collapse — 70% of pairs now unverified
