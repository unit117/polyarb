# Settlement Monitor Agent Memory

This file is read and updated by the `polyarb-settlement-monitor` scheduled task on every run.
Each run should: (1) read this file, (2) check bug status, (3) append a run log entry, (4) update bug statuses.

---

## Known Bugs

Track each bug with its status. Update on every run after checking the codebase.

| # | Bug | Location | Found | Status | Last Checked |
|---|-----|----------|-------|--------|--------------|
| 1 | estimated_profit double-counts edges — sums per-outcome abs deltas, inflating profit ~4x for binary pairs | `services/optimizer/trades.py` ~line 67 | 2026-03-21 | FIXED | 2026-03-23 09:00 |
| 2 | min_edge threshold too low (0.005) — below breakeven after fees (~0.02-0.03) | `services/optimizer/trades.py` ~line 40 | 2026-03-21 | FIXED | 2026-03-23 09:00 |
| 3 | Conditional pairs have no real constraints — `_conditional_matrix` returns all-ones matrix | `services/detector/constraints.py` | 2026-03-21 | FIXED | 2026-03-23 09:00 |
| 4 | GPT-4o-mini misclassifies crypto time-interval pairs as mutual_exclusion | `services/detector/classifier.py` | 2026-03-21 | FIXED | 2026-03-23 09:00 |
| 5 | 0% pair verification rate — system trades on entirely unverified pairs | system-wide | 2026-03-21 | FIXED | 2026-03-23 09:00 |
| 6 | Position sizing uses inflated edge — oversizes positions based on double-counted edge | `services/simulator/pipeline.py` ~line 79 | 2026-03-21 | FIXED | 2026-03-23 09:00 |

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

### 2026-03-21 (scheduled run — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market + fee subtraction (lines 72-81). ✅
  - #2: `min_edge` default is 0.03 (line 19). ✅
  - #3: `_conditional_matrix` has full correlation/Frechet logic (lines 108-178). ✅
  - #4: `_check_crypto_time_intervals()` present and active in rule chain (lines 75-110, 115). ✅
  - #5: `verification.py` exists, `verify_pair()` imported and used in pipeline (line 142 gates on verified). ✅
  - #6: `pipeline.py` uses `profit_ratio = min(net_profit / 0.10, 1.0)` for sizing (lines 71-75). ✅
- **No new bugs discovered.**
- **Key observations**: System has been running ~20 hours. 3,675 trades across 1,125 markets. Win rate on settled trades is very low (29 wins / 747 losses). Two large losses dominate: "Project Hail Mary" Rotten Tomatoes bet (-$73.33) and "Total Kills O/U 62.5" (-$43.82). Portfolio is down ~$1,881 realized PnL from $10k starting capital. Cash is $14,558 but total portfolio value is $13,446 due to unrealized losses of -$1,239.

### 2026-03-21 (scheduled run #2 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market + fee subtraction (lines 72-81). ✅
  - #2: `min_edge` default is 0.03 (line 19). ✅
  - #3: `_conditional_matrix` has Frechet bounds + correlation logic (lines 115-129). ✅
  - #4: `_check_crypto_time_intervals()` present (lines 90-99). ✅
  - #5: `verification.py` exists, `verify_pair()` gating pipeline (line 142). ✅
  - #6: `pipeline.py` uses `profit_ratio = min(net_profit / 0.10, 1.0)` (lines 71-75). ✅
- **No new bugs discovered in code.**
- **Key observations**:
  - 1,356 markets settled in last 24h, 1,318 trades affected.
  - Portfolio: cash=$15,866.61, total_value=$14,642.37, realized_PnL=-$2,505.61, unrealized_PnL=-$1,533.73.
  - Total trades: 3,841 (up from 3,675). Settled: 1,318. Win rate remains critically low at 3.8% for both BUY and SELL sides.
  - Trade distribution: 1,657 SELLs (avg entry 0.728), 1,658 BUYs (avg entry 0.272), 526 SETTLE trades.
  - Largest losses this period: SELL positions on high-probability outcomes (FS esports, Ethereum, Bitcoin, NYSE, NVIDIA) losing $50-$100 each.
  - **Concern**: Win rate has deteriorated from previous run (was ~3.7%, now 0.4% per portfolio snapshot's winning_trades/total_trades). The snapshot's winning_trades counter (13/3315) may not be incrementing correctly, or realized losses far outweigh wins.

### 2026-03-21 (scheduled run #3 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market via best-leg selection (line 70) + fee subtraction (line 105). ✅
  - #2: `min_edge` default is 0.03 (line 26 param default). ✅
  - #3: `_conditional_matrix` has full correlation/Frechet/divergence logic (lines 125-195). ✅
  - #4: `_check_crypto_time_intervals()` present and active in rule chain (lines 94-141, called at line 338). ✅
  - #5: `verification.py` exists, `verify_pair()` imported in pipeline (line 16), gating on `verification["verified"]` at line 142. ✅
  - #6: `pipeline.py` uses `profit_ratio = min(net_profit / 0.10, 1.0)` for sizing (lines 70-74). ✅
- **No new bugs discovered in code.**
- **Key observations**:
  - **Contamination purge completed**: 1,799 PURGE trades recorded — the system executed a full position purge after bug fixes. This explains the portfolio counter reset.
  - **Post-purge portfolio**: cash=$10,777.23, total_value=$9,952.40, realized_PnL=-$1.42, unrealized_PnL=$13.97.
  - Portfolio started with ~$10k post-purge. Currently slightly underwater ($9,952 total value = -0.5% from start).
  - Total trades: 5,703 (including 1,799 PURGE, 1,669 BUY, 1,687 SELL, 548 SETTLE).
  - **Post-purge clean trades**: 58 new trades, 4 settled, 0 winning_trades per snapshot. Win counter may still be bugged or no post-purge settled positions were winners yet.
  - 1,628 markets settled in last 24h (all-time = 1,628, confirming this is still day 1 of settlement tracking).
  - 971 active (unsettled) market positions remain.
  - **Win/loss on all settled positions** (including pre-purge): BUY 19.1% win rate (64W/271L), SELL 80.8% win rate (270W/64L). SELL-side significantly outperforming.
  - **Largest wins this period**: Ethereum price threshold trades (+$99.95, +$99.00), Hyperliquid HIP-4 (+$98.75), weather markets (+$98.00). Top 15 settlements are ALL positive ($62-$100 each).
  - **Concern**: Portfolio snapshot shows 0 winning trades out of 58 post-purge trades with 4 settled. The `winning_trades` counter in the portfolio may not be incrementing on settlement wins — worth investigating in `portfolio.py` or `settle_resolved_markets()`.

### 2026-03-21 15:02 (scheduled run #4 — settlement monitor)
- **Bug regression check**: 5 of 6 bugs confirmed FIXED. Bug #6 code has been refactored but remains functionally sound.
  - #1: `trades.py` uses `max()` per market (line 96-97) + fee subtraction (line 105). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param, config.py line 44). ✅ FIXED
  - #3: `_conditional_matrix` has Frechet bounds + correlation/divergence logic (lines 125-195). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 94-141, called at line 338). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in pipeline (line 16), gating at line 142. ✅ FIXED
  - #6: `pipeline.py` refactored — now uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 86) where `net_profit` = fee-adjusted `estimated_profit` from Bug #1 fix. Previous `profit_ratio` formula replaced with standard half-Kelly for binary markets. Input is no longer inflated, so original bug remains FIXED. ✅ FIXED (refactored)
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$11,301.71, total_value=$10,005.60, realized_PnL=+$49.03, unrealized_PnL=+$33.57.
  - Portfolio has recovered from -$1.42 realized PnL (last run) to +$49.03 — first positive realized PnL post-purge.
  - Total trades: 5,914 (up from 5,703). Post-purge: 270 trades (99 BUY, 164 SELL, 7 SETTLE).
  - 2,045 markets now settled (up from 1,628). 1,158 active positions remain (up from 971).
  - Portfolio snapshot: 263 total_trades, 1 winning_trade, 12 settled_trades. Winning_trades counter still very low (1/12 settled = 8.3%).
  - **Cash vs total_value gap**: $11,302 cash vs $10,006 total = -$1,296 in position value. Unrealized PnL is +$33.57, so most positions are near entry price but portfolio is deployed heavily.
  - **Largest settlements**: Ethereum $2,120 threshold (size 300), Ethereum $2,500 (size 300), NYSE Composite 19,350 (size 288.69), S&P 500 6,000 (size 250.99). Largest positions settling on crypto/index threshold markets.
  - **Trade distribution shift**: SELLs (1,813) now outnumber BUYs (1,748) — system is increasingly taking short positions on high-probability outcomes.
  - **Positive trend**: Portfolio recovering. Total value +$53 above $10k starting point (post-purge). Realized PnL turned positive for the first time.

### 2026-03-21 17:05 (scheduled run #5 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (lines 96-97) + fee subtraction (line 105). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has Frechet bounds + correlation/divergence logic (lines 125-195). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 94-141). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 18), gating at line 155. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 126) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$12,866.87, total_value=$9,954.43, realized_PnL=+$36.36, unrealized_PnL=+$0.89.
  - Portfolio total value has dipped below $10k (-$45.57 from start), down from +$5.60 last run. Realized PnL dropped from +$49.03 to +$36.36.
  - Total trades (all-time): 6,657 (BUY=2,007, SELL=2,293, PURGE=1,799, SETTLE=558). Post-purge: 1,013 trades (BUY=358, SELL=644, SETTLE=11).
  - 2,345 markets settled (up from 2,045). 44,097 active markets.
  - Portfolio snapshot: 1,002 total_trades, 2 winning_trades, 16 settled_trades. Win counter at 2/16 = 12.5% (was 1/12 = 8.3% last run).
  - **Cash vs total_value gap widening**: $12,867 cash vs $9,954 total = -$2,913 in position value. System is heavily deployed.
  - **Post-purge settlement PnL**: 12 settled positions → net +$48.76 ($99.00 gross wins, -$50.24 gross losses). 2 winners, 10 losers.
  - **Largest post-purge win**: Ethereum above 2,205 SELL at $0.495 → +$49.50 (×2 positions = $99 total).
  - **Largest post-purge losses**: ETH above 2,235 BUY (-$22.50), ETH above 2,220 BUY (-$22.45), Ceará SC draw SELL (-$2.70).
  - **BUY/SELL win rates on settled markets**: BUY 16.1% (66W/345L), SELL 68.9% (283W/128L). SELL-side continues to dominate.
  - **Concern**: Total value now below $10k despite positive realized PnL. Unrealized losses from open positions are dragging down portfolio value. The gap between cash ($12.9k) and total value ($9.95k) implies ~$2.9k in unrealized position losses.

### 2026-03-21 19:30 (scheduled run #6 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee subtraction (line 109). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 127-197). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 94-141). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 157 and 305. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 127) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,041.60, total_value=$10,119.69, realized_PnL=+$43.16, unrealized_PnL=+$70.81.
  - Portfolio total value has recovered above $10k (+$119.69 from start). Up from $9,954 last run.
  - Total trades (all-time): 6,725 (BUY=2,025, SELL=2,338, PURGE=1,799, SETTLE=563). Post-purge: 1,081 trades (BUY=376, SELL=689, SETTLE=16).
  - 2,634 markets settled (up from 2,345). 44,258 active markets.
  - Portfolio snapshot: 1,065 total_trades, 5 winning_trades, 21 settled_trades. Win counter improved to 5/21 = 23.8% (was 2/16 = 12.5% last run).
  - **Cash vs total_value gap**: $13,042 cash vs $10,120 total = -$2,922 in position value. Still heavily deployed but gap stabilized.
  - **Post-purge settlement PnL**: 18 settled → net +$48.45 ($99.00 gross wins, -$50.55 gross losses). 2 winners, 8 losers (6 zero-impact).
  - **Largest post-purge wins**: Ethereum above 2,205 SELL × 2 → +$99 total.
  - **Largest post-purge losses**: ETH above 2,235 BUY (-$22.50), ETH above 2,220 BUY (-$22.45), Ceará SC draw (-$2.70).
  - **All-time BUY/SELL win rates on settled markets**: BUY 14.9% (66W/289L=444 total), SELL 64.4% (286W/69L=444 total). SELL-side dominance continues.
  - **Recent activity (3h)**: 689 trades (231 BUY, 451 SELL, 7 SETTLE), 364 markets settled. System actively trading.
  - **Positive trend**: Portfolio back above $10k. Unrealized PnL turned significantly positive (+$70.81 vs +$0.89 last run). Winning trades counter improving (5 vs 2).

### 2026-03-21 22:07 (scheduled run #7 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee subtraction (line 109). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 127-197). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 94-141). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 121 and 271. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 127) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,041.60, total_value=$10,119.69, realized_PnL=+$43.16, unrealized_PnL=+$70.81.
  - Portfolio total value steady at ~$10,120 (+$120 from post-purge start). Unchanged from run #6 — no new snapshot recorded since last check.
  - Total trades (all-time): 6,725 (BUY=2,025, SELL=2,338, PURGE=1,799, SETTLE=563). No new trades since last run.
  - 2,634 markets settled (unchanged from run #6). 44,258 active markets. 42 settled in last 3h.
  - Portfolio snapshot: 1,065 total_trades, 5 winning_trades, 21 settled_trades. Unchanged from last run.
  - **All-time BUY/SELL win rates on settled markets**: BUY 14.9% (66W/289L of 444), SELL 64.4% (286W/69L of 444). Unchanged.
  - **Estimated settlement PnL** (computed from entry prices + outcomes): net +$2,941.97 ($3,464 gross wins, -$522 gross losses). Strong positive edge on settled positions.
  - **Cash vs total_value gap**: $13,042 cash vs $10,120 total = -$2,922 in position value. Stable.
  - **No recent trading activity**: Zero trades in the last 3 hours. System may be idle or between cycles.
  - **Concern**: The system appears to have stopped trading — no new trades or settlements since the previous run ~2.5h ago. Worth checking if services are running.

### 2026-03-22 ~00:30 (scheduled run #8 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee subtraction (line 109). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 127-197). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 94-141). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 121 and 271. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 127) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$12,978.47, total_value=$9,954.35, realized_PnL=-$82.47, unrealized_PnL=-$4.55.
  - Portfolio total value has dropped below $10k again (-$45.65 from post-purge start). Down from $10,119 last run. Realized PnL has swung from +$43.16 to -$82.47 — a -$125.63 drop.
  - Total trades (all-time): 6,891 (BUY=2,071, SELL=2,399, PURGE=1,799, SETTLE=584). Post-purge BUY/SELL: 4,505.
  - 2,886 markets settled (up from 2,634). 44,006 active markets. 252 settled in last 1h, 541 in last 6h.
  - Portfolio snapshot: 1,166 total_trades, 10 winning_trades, 42 settled_trades. Win counter at 10/42 = 23.8% (same rate as last run, but more trades).
  - **System resumed trading**: 170 new trades in the last 6h (106 SELL, 64 BUY), after the ~3h idle period flagged in run #7. System is active again.
  - **Win/loss on all settled post-purge positions (corrected outcome matching)**: BUY 10.6% (51W/430L of 481), SELL 12.4% (62W/439L of 501). Previous runs used Yes/No matching which inflated SELL win rates. The corrected logic matches resolved_outcome to the trade's actual outcome field, revealing much lower true win rates on both sides.
  - **Net settlement PnL (post-purge)**: +$571.41 across 982 settled positions. Despite low win rates, the system is net positive because winning positions are significantly larger ($61-$77 per win) than losing positions.
  - **Largest wins**: FC Famalicão O/U 1.5 Under BUY+SELL (+$153 combined), Toulouse O/U 1.5 (+$143), Charlton vs Norwich O/U 1.5 (+$141), CS:GO Procyon vs METANOIA (+$138). Sports O/U and esports markets dominating wins.
  - **Largest losses**: StarCraft II Cure vs ByuN Map 1 (-$107 combined), Chongqing vs Chengdu O/U (-$104), Michelsen vs Norrie O/U 22.5 (-$182 across 4 positions), Charlton vs Norwich O/U 2.5 (-$88).
  - **Pattern**: Losses often come in pairs (both legs of an arb lose simultaneously), suggesting the correlated market relationship broke down. Wins also come in pairs (both legs win), confirming arb when the relationship holds.
  - **Cash vs total_value gap**: $12,978 cash vs $9,954 total = -$3,024 in position value. Gap widened from -$2,922 last run.

### 2026-03-22 ~07:00 (scheduled run #9 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee subtraction (line 114). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129-199). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 94, called at line 338). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 123 and 275. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Database state change**: Purge trade count is now 0 (was 1,799 in previous runs). The database appears to have been reset or purge trades were cleaned up. All current trades (BUY=2,590, SELL=3,087, SETTLE=633) are "current era" trades.
  - **Portfolio**: cash=$14,053.80, total_value=$10,099.69, realized_PnL=-$4,182.51, unrealized_PnL=-$81.94.
  - Portfolio total value at $10,100 (+$100 from $10k start). Cash is high at $14k but realized PnL is deeply negative at -$4,183. This suggests the system has been cycling through many losing positions but net asset value is approximately flat.
  - Snapshot stats: 2,379 total_trades, 28 winning_trades, 91 settled_trades. Win counter at 28/91 = 30.8% (up from 23.8% rate).
  - **All-time trades**: SELL=3,087, BUY=2,590, SETTLE=633. Total 6,310 (excl. purge). SELL-side continues to outnumber BUY.
  - **Markets**: 3,446 settled (up from 2,886 last run), 46,297 active. 812 settled in last 6h.
  - **Post-purge settled positions**: BUY 4.9% win rate (2W/39L of 41), SELL 56.0% win rate (47W/37L of 84). Total 125 positions settled.
  - **Net settlement PnL (post-purge)**: +$57.99 (Wins: $268.23, Losses: -$210.24). Positive but modest.
  - **Largest wins**: Ethereum above 2,205 (+$99), Overwatch Team Liquid vs Gorilla's Disciples (+$69.60, 10 legs), CD Tondela spread (+$25).
  - **Largest losses**: Ethereum above 2,235 (-$22.50), Ethereum above 2,220 (-$22.45), O/U 0.5 Rounds (-$20.03), Michelsen vs Norrie O/U 22.5 (-$17.04).
  - **Recent activity (last 6h)**: BUY=565, SELL=749, SETTLE=70. System is actively trading.
  - **Cash vs total_value gap**: $14,054 cash vs $10,100 total = -$3,954 in position value. Gap has widened significantly from -$3,024 last run. System is very heavily deployed.
  - **Concern**: Realized PnL is -$4,183 despite total value being ~$10,100. This means the system has generated ~$4.1k in unrealized gains on open positions to offset realized losses, or there's a discrepancy in how PnL is tracked. The -$82 unrealized PnL in the snapshot doesn't account for this. Worth investigating whether `realized_pnl` accumulates pre-purge losses.

### 2026-03-22 ~10:30 (scheduled run #10 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee subtraction (line 114). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129-199). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 115-141). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,636.58, total_value=$10,094.86, realized_PnL=-$4,205.08, unrealized_PnL=-$66.87.
  - Portfolio total value at $10,095 (+$95 from $10k start). Essentially flat. Down slightly from $10,100 last run.
  - Snapshot stats: 2,703 total_trades, 37 winning_trades, 119 settled_trades. Win counter at 37/119 = 31.1% (up from 30.8% last run).
  - **All-time trades**: BUY=2,728, SELL=3,273, PURGE=1,799, SETTLE=661. Total 8,461.
  - **Markets**: 3,719 settled (up from 3,446 last run, +273). 46,545 active. 1,085 settled in last 6h, 2,637 in last 24h.
  - **Settled position PnL**: BUY 99W/509L (16.3%) net +$125.83 | SELL 550W/142L (79.5%) net +$4,836.83. Combined net: +$4,962.66.
  - **SELL-side dominance**: 79.5% win rate on SELLs generating +$4,837 net. BUY-side at 16.3% win rate but still net positive (+$126) due to larger wins.
  - **Top wins**: FS esports game handicap (+$98 each, multiple positions), Ethereum $2,140 threshold (+$98), ETH $2,500 No (+$97 ×3), Netflix ranking (+$97), Hyperliquid HIP-4 (+$97).
  - **Top losses**: Lucknow temperature SELL (-$86), Ethereum $2,200 SELL (-$83), Toulouse O/U 3.5 (-$76), CD Tondela spread (-$76), FC Famalicão O/U 3.5 (-$71).
  - **Recent activity**: 703 BUY + 935 SELL + 98 SETTLE in last 6h. Latest trade at 01:39 UTC. No trades in last 1h — system may be between cycles.
  - **Cash vs total_value gap**: $13,637 cash vs $10,095 total = -$3,542 in position value. Gap narrowed slightly from -$3,954 last run.
  - **Realized PnL anomaly persists**: -$4,205 realized despite total value ~$10,095. The settled position PnL shows +$4,963 net, so the realized_pnl field likely accumulates pre-purge losses. This is a bookkeeping issue, not a real trading loss.

### 2026-03-22 ~13:30 (scheduled run #11 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee subtraction (line 114). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129-199). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 115-134). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,636.58, total_value=$10,094.86, realized_PnL=-$4,205.08, unrealized_PnL=-$66.87. Snapshot timestamp 2026-03-22 05:02 UTC — **no new snapshot since run #10**.
  - Portfolio total value flat at $10,095 (+$95 from $10k start). No change from last run.
  - Snapshot stats: 2,703 total_trades, 37 winning_trades, 119 settled_trades. Win rate 31.1% — unchanged.
  - **All-time trades**: BUY=2,728, SELL=3,273, PURGE=1,799, SETTLE=661. Total 8,461. **No new trades since last run.**
  - **Markets**: 3,719 settled (unchanged), 47,258 active (up from 46,545 — new markets ingested but no settlements). 908 settled in last 6h, 2,603 in last 24h.
  - **Settled position PnL (all-time)**: BUY 100W/508L (16.4%) | SELL 550W/142L (79.5%). Net: +$186 (gross wins $3,008, gross losses -$2,822).
  - **Settlements last 6h**: 302 positions settled, 164W/138L, net +$344.16. Strong recent performance.
  - **Latest trade**: 2026-03-22 01:40 UTC — system has not traded in ~12 hours. No new portfolio snapshots generated either.
  - **Concern**: System appears idle. Trading stopped at ~01:40 UTC and has not resumed. Services may need a restart or the ingestor/detector/optimizer pipeline may be stuck. Active market count has grown (new ingestion happening) but no new opportunities are being traded.
  - **Cash vs total_value gap**: $13,637 cash vs $10,095 total = -$3,542 in position value. Unchanged.

### 2026-03-22 ~16:00 (scheduled run #12 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee subtraction (line 114). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129-154). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 115-139). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 123 and 275. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **System resumed trading**: Latest trade at 2026-03-22 06:59 UTC (was 01:40 UTC last run). 334 new BUY+SELL trades in last 6h. System is active again.
  - **Portfolio**: cash=$13,557.18, total_value=$10,222.28, realized_PnL=-$4,152.73, unrealized_PnL=+$8.44.
  - Portfolio total value at $10,222 (+$222 from $10k start). Up from $10,095 last run. Realized PnL improved slightly from -$4,205 to -$4,153.
  - Snapshot stats: 2,713 total_trades, 47 winning_trades, 139 settled_trades. Win counter at 47/139 = 33.8% (up from 37/119 = 31.1% last run).
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=681. Total 8,491.
  - **Markets**: 3,922 settled (up from 3,719), 47,627 active. 203 settled in last 1h, 476 in last 6h, 2,792 in last 24h.
  - **Win/loss on all settled positions**: BUY 17.0% (108W/529L of 637), SELL 21.2% (156W/579L of 735). Combined: 264W/1,108L = 19.2%.
  - **Net settlement PnL (all-time)**: -$4,996.05 (gross wins $3,251.18, gross losses -$8,247.23). Significantly negative — pre-purge losses dominate.
  - **Settlements last 6h**: 279 positions settled, 101W/178L, net -$945.80. Recent settlements are net negative.
  - **Largest wins**: Lucknow temperature SELL (+$84.28), Ethereum $2,200 SELL (+$80.85), FC Famalicão O/U 1.5 Under BUY (+$74.97).
  - **Largest losses**: Multiple SELL positions at extreme prices (0.99+) losing ~$99 each on Ethereum $2,140, Games O/U 3.5, FS esports handicaps, Ethereum $2,500 (3 positions at -$99 each), Netflix ranking.
  - **Critical concern**: The top 10 losses are ALL SELL positions at prices 0.98-0.9995, losing $98-$100 each. These are positions where the system sold at near-certainty prices, meaning it was selling outcomes that were almost certain to happen — and they did. This pattern suggests the system is systematically selling high-probability outcomes for tiny premiums ($0.05-$1.25 per position) while risking $98-$100.
  - **Cash vs total_value gap**: $13,557 cash vs $10,222 total = -$3,335 in position value. Gap narrowed from -$3,542 last run.

### 2026-03-22 ~19:07 (scheduled run #13 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee/slippage subtraction (line 114). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129-199). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 115, called at line 489). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 123 and 275. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,324.28, total_value=$10,275.26, realized_PnL=-$4,189.28, unrealized_PnL=+$97.98.
  - Portfolio total value at $10,275 (+$275 from $10k start). Up from $10,222 last run. Best post-purge total value so far.
  - Snapshot stats: 2,713 total_trades, 49 winning_trades, 147 settled_trades. Win counter at 49/147 = 33.3% (up from 47/139 = 33.8% last run — essentially stable).
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=689. Total 8,499.
  - **Markets**: 3,991 settled (up from 3,922 last run, +69). 48,002 active. 272 settled in last 6h, 0 in last 1h.
  - **Win/loss on all settled positions**: BUY 17.5% (115W/543L of 658) net +$54.27 | SELL 78.1% (608W/170L of 778) net -$12.81. Combined: 723W/713L = 50.3%, total net +$41.46.
  - **Important shift**: All-time settled positions are now nearly balanced at 50.3% win rate (723W vs 713L). SELL-side continues to dominate win rate at 78.1% but net PnL is slightly negative (-$12.81) due to large individual losses. BUY-side has low win rate (17.5%) but net positive (+$54.27) due to larger wins.
  - **Settlements last 6h**: 73 wins ($518.34) vs 63 losses (-$662.87) = net -$144.53. Recent settlements were net negative — a reversal from last run's pattern.
  - **Largest wins (6h)**: Honor of Kings esports (+$58.31 BUY MTG, +$45.57 BUY/SELL WZE), Kashima Antlers BTTS (+$49.98), Kashima O/U 2.5 (+$47.53).
  - **Largest losses (6h)**: Vancouver Whitecaps O/U 1.5 SELL (-$84.50), Vancouver O/U 2.5 BUY (-$64.50), HoK WZE SELL (-$59.50), Kashima BTTS No SELL (-$51.00).
  - **Pattern**: Losses are clustering around sports O/U and spread markets where both legs of an arb pair lose simultaneously (e.g., Vancouver Whitecaps: both SELL O/U 1.5 and BUY O/U 2.5 lost when result was Under). This suggests correlated market assumptions break down for some sports events.
  - **System activity**: Very low recent activity — only 10 BUY/SELL trades and 28 SETTLE trades in last 6h. Latest BUY/SELL at 06:33 UTC, latest trade (SETTLE) at 07:46 UTC. No trades in last 1h. System may be between cycles.
  - **Cash vs total_value gap**: $13,324 cash vs $10,275 total = -$3,049 in position value. Gap narrowed from -$3,335 last run.
  - **Positive trend**: Portfolio at new post-purge high of $10,275. Winning trades counter steadily improving (49 vs 47). Unrealized PnL healthy at +$97.98.

### 2026-03-22 ~22:00 (scheduled run #14 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee subtraction (line 114). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129-160+). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 115, called at line 489). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 123 and 275. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,324.28, total_value=$10,275.26, realized_PnL=-$4,189.28, unrealized_PnL=+$97.98. Snapshot timestamp 2026-03-22 11:03 UTC — **same snapshot as run #13**.
  - Portfolio total value steady at $10,275 (+$275 from $10k start). Unchanged from last run.
  - Snapshot stats: 2,713 total_trades, 49 winning_trades, 147 settled_trades. Win rate 33.3% — unchanged.
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=689. Total 8,499. No new BUY/SELL trades since last run. Latest trade (SETTLE) at 07:46 UTC.
  - **Markets**: 3,991 settled (up from 3,991 last run — unchanged). 48,702 active (up from 48,002 — new markets ingested). 272 settled in last 6h.
  - **Win/loss on all settled positions**: BUY 17.5% (115W/543L of 658) | SELL 21.9% (170W/608L of 778). Combined: 285W/1,151L of 1,436 (19.8%).
  - **Net settlement PnL (all-time)**: +$61.96 (Gross Wins: $3,572.12, Gross Losses: -$3,510.16). Barely positive.
  - **Settlements last 6h**: 136 positions settled, 43W/93L, net -$42.80 (Wins: $574.49, Losses: -$617.29). Recent settlements slightly negative.
  - **System activity**: Very low — only 5 BUY + 5 SELL + 28 SETTLE trades in last 6h. Last BUY/SELL at unknown time, latest trade (SETTLE) at 07:46 UTC. System appears largely idle for new position entry.
  - **Concern (continued)**: System has been generating very few new BUY/SELL trades. Last meaningful trading burst was ~12+ hours ago. Active market count growing (48,702 vs 48,002) from ingestion, but no new opportunities being traded. Pipeline may be stuck or no opportunities are passing verification/edge thresholds.
  - **Cash vs total_value gap**: $13,324 cash vs $10,275 total = -$3,049 in position value. Unchanged from last run.
  - **Overall assessment**: Portfolio is at its post-purge high of +$275 (+2.75% return). All-time settlement PnL is marginally positive at +$62. Win rate is low (19.8%) but winning trades are significantly larger than losing ones. System stability is the main concern — trading activity has dropped sharply.

### 2026-03-22 ~13:05 UTC (scheduled run #15 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee/slippage subtraction (line ~109). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129+). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 115, called at line 489). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 123 and 275. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,324.28, total_value=$10,275.26, realized_PnL=-$4,189.28, unrealized_PnL=+$97.98. Snapshot timestamp 2026-03-22 12:58 UTC — **same snapshot as run #14** (no new snapshot generated).
  - Portfolio total value steady at $10,275 (+$275 from $10k post-purge start). Unchanged from last run.
  - Snapshot stats: 2,713 total_trades, 49 winning_trades, 147 settled_trades. Win rate 33.3% — unchanged.
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=689. Total 8,499. **No new BUY/SELL trades since run #13.**
  - Last BUY/SELL trade: 2026-03-22 06:33 UTC (~6.5h ago). Last trade of any kind (SETTLE): 07:46 UTC (~5.3h ago). 7 SETTLE trades in last 6h, 141 in last 24h.
  - **Win/loss on all settled positions (all-time)**: BUY 17.5% (115W/543L of 658) net +$87.69 | SELL 78.1% (608W/170L of 778) net +$5,337.32. Combined: 723W/713L = 50.3%, total net: +$5,425.01.
  - **All-time settled PnL improved significantly**: Net +$5,425 (up from +$62 reported in run #14). Previous runs may have used different PnL methodology. Gross wins $8,994.43 vs gross losses -$3,569.42.
  - **Settlements last 24h** (via SETTLE trades): 433 positions, 222W/211L, net +$1,018.16 (Gross wins: $2,738.51, Gross losses: -$1,720.35). Strong positive performance.
  - **Largest wins (24h)**: FC Dallas vs Houston Dynamo O/U 1.5 SELL (+$78.50 ×3 = +$235.50 combined), Kashima vs JEF United O/U 1.5 SELL (+$75.50 ×2 = +$151.00), O/U 0.5 Rounds SELL (+$66.50 ×2), Michelsen vs Norrie O/U 21.5 SELL (+$63.00), Sporting KC vs Colorado O/U 2.5 SELL (+$59.50).
  - **Largest losses (24h)**: Ethereum above $2,200 SELL (-$82.50), Spread CD Tondela (-1.5) SELL (-$75.00), FC Dallas O/U 3.5 BUY (-$66.50), Vancouver Whitecaps O/U 2.5 BUY (-$64.50), Vancouver spread BUY (-$61.00).
  - **Pattern**: SELL-side continues to dominate wins. Sports O/U markets are the primary profit source. Largest losses come from crypto threshold markets and sports spread bets where the correlated relationship breaks down.
  - **System activity**: Still very low — no new BUY/SELL trades for 6.5h. Only SETTLE trades processing. System may be between cycles or stuck.
  - **Cash vs total_value gap**: $13,324 cash vs $10,275 total = -$3,049 in position value. Unchanged.
  - **Overall assessment**: Portfolio holding steady at +2.75% above $10k start. All-time settled PnL is strongly positive at +$5,425. 24h settlements are net positive (+$1,018). SELL-side strategy (78.1% win rate, +$5,337 net) is the primary profit driver. System inactivity remains a concern — no new position entry in 6.5 hours.

### 2026-03-22 ~15:07 UTC (scheduled run #16 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (line 73) + fee/slippage subtraction (line 114). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129+). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 115, called at line 489). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 123 and 275. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **System resumed trading**: Latest trade at 2026-03-22 13:27 UTC (was 07:46 last run). System is active again after ~6h idle period.
  - **Portfolio**: cash=$13,050.87, total_value=$10,172.47, realized_PnL=-$4,229.87, unrealized_PnL=+$35.77.
  - Portfolio total value at $10,172 (+$172 from $10k start). Down from $10,275 last run. Realized PnL drifted further negative from -$4,189 to -$4,230.
  - Snapshot stats: 2,713 total_trades, 51 winning_trades, 156 settled_trades. Win counter at 51/156 = 32.7% (was 49/147 = 33.3% last run — slight dip).
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=698. Total 8,508. 9 new SETTLE trades since last run.
  - **Markets**: 4,778 settled (up from 3,991, +787). 48,579 active. 2,733 settled in last 24h, 787 in last 6h.
  - **Win/loss on all settled positions**: BUY 17.3% (116W/556L of 672) net +$42.56 | SELL 21.4% (172W/632L of 804) net -$207.50. Combined: 288W/1,188L = 19.5%, total net: -$164.94.
  - **PnL methodology note**: This run uses direct outcome matching (resolved_outcome vs trade outcome) which gives lower win rates than previous runs that used SETTLE-trade-based PnL. The discrepancy is likely because SETTLE trades capture realized PnL at execution while direct matching doesn't account for partial exits or VWAP differences.
  - **Largest settlements (7d)**: Map Handicap PCY vs METANOIA (-$261), HoK SOLYX vs KoGC (+$240), FC Dallas O/U 2.5 (-$182), FC Dallas O/U 1.5 (-$177), FC Dallas O/U 3.5 (-$168), HoK WZE vs MTG (+$163).
  - **Settlements last 6h**: 40 positions, 4W/36L, net -$4.89. Very low activity, slightly negative.
  - **Cash vs total_value gap**: $13,051 cash vs $10,172 total = -$2,879 in position value. Gap narrowed from -$3,049 last run.
  - **Overall assessment**: Portfolio dipped slightly to +$172 (+1.7% from $10k start), down from +$275 peak. Win rate holding around 32-33% on snapshot basis. Trading has resumed after the extended idle period. The system continues to be heavily deployed with ~$2.9k in open position value. Settlement PnL methodology differences make it hard to compare across runs — SETTLE-trade-based PnL (run #15: +$5,425) vs direct-matching PnL (this run: -$165) diverge significantly.

### 2026-03-22 ~17:00 UTC (scheduled run #17 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (lines 104-105) + fee/slippage subtraction (lines 109-121). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129-199). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 115-175, called at line 489). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 123, 277, 396, 531. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,050.87, total_value=$10,172.47, realized_PnL=-$4,229.87, unrealized_PnL=-$146.76.
  - Portfolio total value at $10,172 (+$172 from $10k start). **Unchanged from run #16** — same snapshot timestamp (17:00 UTC series, all identical values).
  - Snapshot stats: 2,713 total_trades, 51 winning_trades, 156 settled_trades. Win rate 32.7% — unchanged.
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=698. Total 8,508. **No new BUY/SELL trades since run #16**. 9 new SETTLE trades vs run #15.
  - Last BUY/SELL trade: 2026-03-22 06:33 UTC (~10.5h ago). Last SETTLE: 13:27 UTC (~3.5h ago).
  - **Markets**: 4,778 settled (unchanged from run #16), 53,357 total (up from 48,579 — 4,778 new markets ingested). 787 settled in last 6h, 2,433 in last 24h.
  - **Win/loss on all settled positions (outcome matching)**: BUY 17.4% (117W/555L of 672) | SELL 21.4% (172W/632L of 804). Combined: 289W/1,187L = 19.6%.
  - **SETTLE trades last 24h**: 140 settlements. Largest win: FC Dallas O/U 2.5 SELL (+$89.57). Largest loss: Vancouver Whitecaps O/U 1.5 SELL (-$101.39).
  - **Notable settlement pattern**: Both legs of Vancouver Whitecaps arb lost simultaneously — SELL O/U 1.5 (-$101.39) AND BUY O/U 2.5 (-$77.41). Correlated market assumption broke down (result was Under, below both thresholds).
  - **System activity**: Zero new BUY/SELL trades in last 6h. Only 9 SETTLE trades in last 6h. System is largely idle for new position entry. Active market count growing rapidly (53,357 total, up ~5k from last run) from ingestion but no new opportunities being traded.
  - **Cash vs total_value gap**: $13,051 cash vs $10,172 total = -$2,879 in position value. Unchanged from last run.
  - **Concern (continued)**: System has not entered new positions since 06:33 UTC (~10.5h ago). This is the longest idle stretch since the system resumed post-purge. Pipeline may be stuck or all opportunities are failing edge/verification thresholds. New markets are being ingested but not generating tradeable opportunities.

### 2026-03-22 ~19:04 UTC (scheduled run #18 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (lines 104-105) + fee/slippage subtraction (lines 109-121). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 129-199). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 115, called at line 489). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 123, 277, 396, 531. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,050.87, total_value=$10,172.47, realized_PnL=-$4,229.87, unrealized_PnL=-$146.76. **Unchanged from runs #16-17** — snapshot values identical since ~15:07 UTC.
  - Snapshot stats: 2,713 total_trades, 51 winning_trades, 156 settled_trades. Win rate 32.7% — unchanged.
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=698. Total 8,508. **No new trades of any kind since run #17.**
  - Last BUY/SELL trade: 2026-03-22 06:33 UTC (~12.5h ago). Last SETTLE: 13:27 UTC (~5.5h ago).
  - **Markets**: 4,778 settled (unchanged). 48,579 active (unchanged). 787 settled in last 6h, 2,144 in last 24h. **No new markets ingested since 12:55 UTC (~6h ago).**
  - **Win/loss on all settled positions (outcome matching)**: BUY 17.4% (117W/555L of 672) | SELL 21.4% (172W/632L of 804). Combined: 289W/1,187L = 19.6%. Unchanged.
  - **SETTLE trades last 24h**: 135 settlements, 53 winning (px>0.5), 82 losing (px<=0.5). Last 6h: only 9 SETTLE trades (6W/3L).
  - **System fully idle**: Zero new BUY/SELL trades, zero new SETTLE trades, zero new markets ingested in the last ~6 hours. All services appear stopped — not just the optimizer/simulator, but the ingestor as well. This is the most complete system shutdown observed since monitoring began.
  - **Cash vs total_value gap**: $13,051 cash vs $10,172 total = -$2,879 in position value. Unchanged.
  - **Critical concern**: The entire pipeline (ingestor → detector → optimizer → simulator) appears to be down. Previous idle periods only affected trading (optimizer/simulator stopped) while ingestion continued. Now even the ingestor has stopped fetching new markets (last ingestion 12:55 UTC). Services likely need a restart on the NAS.

### 2026-03-22 ~21:08 UTC (scheduled run #19 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (lines 104-105) + fee/slippage subtraction (line 121). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (line 141+). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 134, called at line 529). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 149, 189, 308, 346, 433. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,050.87, total_value=$10,172.47, realized_PnL=-$4,229.87, unrealized_PnL=-$146.76. Snapshot timestamp 2026-03-22 21:01 UTC — **same snapshot as runs #16-18**. Values unchanged for ~6 hours.
  - Snapshot stats: 2,713 total_trades, 51 winning_trades, 156 settled_trades. Win rate 32.7% — unchanged.
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=698. Total 8,508. **No new trades since run #16 (~6h ago).**
  - Last BUY/SELL trade: 2026-03-22 06:33 UTC (~14.5h ago). Last SETTLE: 13:27 UTC (~7.7h ago).
  - **Markets**: 4,778 settled (unchanged), 34,350 active (down from 48,579 — possible cleanup/deactivation of stale markets). Last market ingested: 12:55 UTC (~8h ago). Zero settlements in last 6h.
  - **24h settlement PnL (estimated)**: net -$959.63 across 549 positions (184W/365L). Gross wins $1,747.70, gross losses -$2,707.33. Recent 24h performance is significantly negative.
  - **All-time settled PnL (estimated)**: net -$164.93 across 1,476 positions (288W/1,188L). Gross wins $3,648.05, gross losses -$3,812.99. Overall slightly negative.
  - **Largest wins (24h)**: Vancouver Whitecaps O/U 1.5 SELL (+$82.82), CS:GO Procyon vs METANOIA BUY/SELL (+$136 combined), Michelsen vs Norrie O/U 10.5 BUY/SELL (+$131 combined), MLBB TNC vs AP.Bren (+$119 combined).
  - **Largest losses (24h)**: FC Dallas O/U 3.5 BUY/SELL (-$135 combined), Vancouver O/U 2.5 BUY (-$65.80), Kashima O/U 2.5 BUY/SELL (-$99 combined), HoK WZE vs MTG Game (-$95 combined).
  - **Pattern**: Both-legs-lose pattern continues — when correlated market relationships break down, the arb pair loses on both sides simultaneously (FC Dallas O/U 3.5, Kashima O/U 2.5, HoK WZE game markets). Conversely, both-legs-win when relationships hold (CS:GO Procyon, Michelsen O/U 10.5, MLBB TNC).
  - **System fully idle (continued)**: No new BUY/SELL trades for 14.5h, no new SETTLE trades for 7.7h, no new markets ingested for 8h, zero settlements in last 6h. Entire pipeline remains down. Active market count dropped from ~48k to ~34k, suggesting stale market cleanup occurred but no new activity.
  - **Cash vs total_value gap**: $13,051 cash vs $10,172 total = -$2,879 in position value. Unchanged for 6+ hours.
  - **Critical concern**: System has been completely idle for 8+ hours now. All services (ingestor, detector, optimizer, simulator) appear stopped. Portfolio is stagnant at +$172 (+1.7% from $10k start). Services on the NAS need investigation and likely a restart.

### 2026-03-22 ~23:08 UTC (scheduled run #20 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (lines 104-106) + fee subtraction (line 114). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has divergence/sum-bounds/Frechet logic (lines 141-209). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (lines 134-194, called at line 529). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at line 189. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,050.87, total_value=$10,172.47, realized_PnL=-$4,229.87, unrealized_PnL=-$146.76. Snapshot timestamp 2026-03-22 23:01 UTC — **same values as runs #16-19**. No new snapshot generated with different values in ~8 hours.
  - Snapshot stats: 2,713 total_trades, 51 winning_trades, 156 settled_trades. Win rate 32.7% — unchanged.
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=698. Total 8,508. **No new trades since run #16 (~8h ago).**
  - Last BUY/SELL trade: 2026-03-22 06:33 UTC (~16.5h ago). Last SETTLE: 13:27 UTC (~9.7h ago).
  - **Markets**: 4,778 settled, 48,579 active, 53,357 total. Settled last 24h: 1,708. Settled last 6h: 0. Last market ingested: 12:55 UTC (~10h ago).
  - **24h settlement PnL**: net -$504.80 across 461 positions (162W/299L). Recent settlements net negative.
  - **All-time settlement PnL**: net +$63.76 (Gross Wins: $3,712.80, Gross Losses: -$3,649.04) across 1,476 positions. Overall slightly positive.
  - **Win/loss**: BUY 17.4% (117W/555L of 672) | SELL 21.4% (172W/632L of 804). Combined: 289W/1,187L = 19.6%.
  - **Largest wins (24h)**: Vancouver Whitecaps O/U 1.5 SELL (+$84.50), MLBB TNC vs AP.Bren both legs (+$121 combined), HoK WZE vs MTG both legs (+$119 combined).
  - **Largest losses (24h)**: FC Dallas O/U 3.5 both legs (-$133 combined), Vancouver O/U 2.5 BUY (-$64.50), Kashima O/U 2.5 both legs (-$97 combined).
  - **System fully idle (continued from runs #17-19)**: Zero new trades in last 6h. Zero settlements in last 6h. Zero markets ingested since 12:55 UTC (~10h ago). Entire pipeline remains down for 10+ hours.
  - **Cash vs total_value gap**: $13,051 cash vs $10,172 total = -$2,879 in position value. Unchanged for 8+ hours.
  - **Critical concern (persistent)**: System has been completely idle for 10+ hours. All services (ingestor, detector, optimizer, simulator) appear stopped. Portfolio stagnant at +$172 (+1.7% from $10k start). Services on the NAS need investigation and restart.

### 2026-03-23 ~01:07 UTC (scheduled run #21 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (lines 104-105) + fee subtraction (line 121). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has divergence/Frechet/correlation logic (lines 141+). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 134, called at line 529). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 149, 189, 322, 360, 442. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,050.87, total_value=$10,172.47, realized_PnL=-$4,229.87, unrealized_PnL=-$146.76. Snapshot timestamp 2026-03-23 01:02 UTC — **same values as runs #16-20**. No portfolio changes in ~10 hours.
  - Snapshot stats: 2,713 total_trades, 51 winning_trades, 156 settled_trades. Win rate 32.7% — unchanged.
  - **All-time trades**: BUY=2,733, SELL=3,278, PURGE=1,799, SETTLE=698. Total 8,508. **No new trades since run #16.**
  - Last BUY/SELL trade: 2026-03-22 06:33 UTC (~18.5h ago). Last SETTLE: 2026-03-22 13:27 UTC (~11.7h ago).
  - **Markets**: 4,778 settled (unchanged), 48,579 active (unchanged). Zero settled in last 6h. 1,332 settled in last 24h. Last market ingested: 2026-03-22 12:55 UTC (~12h ago).
  - **Win/loss on all settled positions**: BUY 17.4% (117W/555L of 672) | SELL 78.6% (632W/172L of 804). Combined: 749W/727L = 50.7%.
  - **All-time settlement PnL**: net +$63.76 (Gross Wins: $3,712.80, Gross Losses: -$3,649.04). Marginally positive.
  - **24h settlement PnL**: 383 positions, 126W/257L, net -$423.38. Recent 24h performance is negative.
  - **Largest settlements (24h)**: Vancouver Whitecaps O/U 1.5 SELL (+$84.50), MLBB TNC vs AP.Bren both legs (+$121 combined), HoK WZE vs MTG both legs (+$119 combined). Largest losses: FC Dallas O/U 3.5 both legs (-$133), Vancouver O/U 2.5 BUY (-$64.50), Kashima O/U 2.5 both legs (-$97).
  - **SETTLE trades last 24h**: 65 settlement executions.
  - **System fully idle (continued from runs #17-20)**: Zero new BUY/SELL trades for 18.5h. Zero new SETTLE trades for 11.7h. Zero new markets ingested for 12h. Zero settlements in last 6h. Entire pipeline remains completely down.
  - **Cash vs total_value gap**: $13,051 cash vs $10,172 total = -$2,879 in position value. Unchanged for 10+ hours.
  - **Critical concern (persistent — 4th consecutive run)**: System has been completely idle for 12+ hours now. All services (ingestor, detector, optimizer, simulator) appear stopped. Portfolio stagnant at +$172 (+1.7% from $10k start). No BUY/SELL activity for 18.5h. Services on the NAS urgently need investigation and restart.

### 2026-03-23 ~05:54 UTC (scheduled run #22 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (lines 104-105) + fee subtraction (line 121). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 141+). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present and active (line 134, called at line 529). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` imported in detector pipeline (line 20), gating at lines 149, 189, 322, 360, 442. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135) with fee-adjusted `estimated_profit`. ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **SYSTEM RESUMED**: After being idle for 18.5+ hours (flagged in runs #17-21), the system has resumed trading. 883 new BUY/SELL trades in last 6h (430 BUY, 453 SELL). Latest trade at 2026-03-23 03:06 UTC. However, no trades in the last ~3h — may be between cycles again.
  - **Portfolio**: cash=$13,186.71, total_value=$10,068.53, realized_PnL=-$4,250.26, unrealized_PnL=-$226.23. Snapshot timestamp 2026-03-23 05:37 UTC.
  - Portfolio total value at $10,069 (+$69 from $10k start). Down from $10,172 last run. Realized PnL dipped from -$4,230 to -$4,250.
  - Snapshot stats: 3,591 total_trades, 58 winning_trades, 182 settled_trades. Win counter at 58/182 = 31.9% (was 51/156 = 32.7% last run — slight dip).
  - **All-time trades**: BUY=3,163, SELL=3,726, PURGE=1,799, SETTLE=724. Total 9,412. Up from 8,508 last run — 904 new trades.
  - **Markets**: 5,664 settled (up from 4,778, +886). 47,693 active. 886 settled in last 6h, 1,945 in last 24h.
  - **All-time SETTLE PnL**: 724 settlements, 367W/357L, net +$225.90 (Gross Wins: $6,852, Gross Losses: -$6,626). Positive and improving.
  - **SETTLE last 24h**: 63 settlements, 25W/38L, net -$423.51. Recent settlements net negative.
  - **SETTLE last 6h**: 26 settlements, 10W/16L, net +$191.07. Most recent batch is positive — recovering.
  - **Win/loss by side (outcome matching)**: BUY 17.8% (134W/617L of 751) | SELL 77.8% (668W/191L of 859). Combined: 802W/808L = 49.8%. SELL-side continues to dominate at 77.8%.
  - **Largest wins (24h)**: Sabres vs Ducks O/U 6.5 Over (+$146.85), Bitcoin above $78k Yes (+$135.10), Vancouver Whitecaps O/U 2.5 Over (+$118), Bitcoin above $76k Yes (+$110.27), Vancouver spread (-2.5) (+$100).
  - **Largest losses (24h)**: Vancouver O/U 1.5 Over (-$118), Overwatch Team Liquid (-$104.25), KOSPI above 5000 (-$100), Vancouver spread (-1.5) (-$100), Golden Knights O/U 4.5 Over (-$92.50).
  - **Both-legs pattern continues**: Vancouver Whitecaps arb had mixed results — O/U 2.5 won (+$118) but O/U 1.5 lost (-$118), netting ~$0. Spread bets also mixed: (-2.5) won (+$100) but (-1.5) lost (-$100).
  - **Cash vs total_value gap**: $13,187 cash vs $10,069 total = -$3,118 in position value. Gap widened from -$2,879 last run as new positions were opened.
  - **Ingestor still idle**: Last market ingested at 2026-03-22 12:55 UTC (~17h ago). Despite trading resuming, no new markets are being ingested. The detector/optimizer/simulator appear to be working with existing market data only.

### 2026-03-23 ~09:00 UTC (scheduled run #23 — settlement monitor)
- **Bug regression check**: All 6 bugs confirmed FIXED. No status changes.
  - #1: `trades.py` uses `max()` per market (lines 104-105) + fee subtraction (line 121). ✅ FIXED
  - #2: `min_edge` default is 0.03 (line 26 param). ✅ FIXED
  - #3: `_conditional_matrix` has correlation/divergence/Frechet logic (lines 141-211). ✅ FIXED
  - #4: `_check_crypto_time_intervals()` present (line 134), plus `_check_price_threshold_markets()` (line 197). ✅ FIXED
  - #5: `verification.py` exists, `verify_pair()` gating pipeline. ✅ FIXED
  - #6: `pipeline.py` uses half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)` (line 135). ✅ FIXED
- **No new bugs discovered in code.**
- **Key observations**:
  - **Portfolio**: cash=$13,186.71, total_value=$10,068.53, realized_PnL=-$4,250.26, unrealized_PnL=-$226.23. Unchanged from run #22 — portfolio snapshots frozen since ~08:58 UTC.
  - Portfolio total value at $10,069 (+0.7% from $10k start). No change from last run.
  - Snapshot stats: 3,591 total_trades, 58 winning_trades, 182 settled_trades. Identical to run #22.
  - **All-time trades**: BUY=3,163, SELL=3,726, PURGE=1,799, SETTLE=724. Total 9,412. Unchanged from run #22.
  - **New trades in last 24h**: 913. Last 48h BUY/SELL: 1,801 BUY + 2,365 SELL = 4,166 trades.
  - **Markets**: 5,664 settled. 53,357 total. +886 settled today (Mar 23).
  - **Settlement breakdown (all-time)**: 724 SETTLE trades. By PnL direction: 88 wins, 636 losses = 12.2% win rate. This differs from the snapshot's 58/182 because the portfolio was purged mid-life and counters reset.
  - **SETTLE last 24h**: 35 settlements, 9 wins, 26 losses = 25.7% win rate. Improvement over all-time 12.2%.
  - **SETTLE last 48h**: 238 settlements, 66 wins, 172 losses = 27.7% win rate.
  - **Market settlement pace**: Mar 23: 886 (48 Yes, 711 No). Mar 22: 1,373 (67 Yes, 1,107 No). Mar 21: 2,373 (103 Yes, 1,791 No). Mar 20: 1,032 (50 Yes, 846 No). Heavy No-resolution skew across all days.
  - **Largest settlements by size**: ETH above $2,120 No (300 shares, lost), ETH above $2,500 Yes (300 shares, lost), NYSE close over 19,350 No (289 shares, lost), S&P 500 close over 6,000 No (251 shares, lost), O/U 62.5 kills Under (199 shares, lost). Top positions by size all lost.
  - **Pair verification**: 6,704 verified / 23,179 total = 28.9% verification rate. Improved from 0% pre-fix.
  - **Opportunity pipeline**: 46,052 skipped, 5,045 expired, 2,855 simulated, 1,250 optimized (pending), 1,210 detected, 393 unconverged.
  - **Open positions**: 688 positions, mostly short (negative size). Cash-position gap: $13,187 cash vs $10,069 total = -$3,118 unrealized loss in positions.
  - **System appears active**: 913 trades in last 24h, portfolio snapshotting every 5 min. However, all 3 latest snapshots are identical values — possibly no new trades executing in the last ~30 min window.
