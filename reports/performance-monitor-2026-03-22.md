# PolyArb Performance Monitor Report — March 22, 2026

**Run time**: ~06:00 UTC | **Period analyzed**: Post-purge (March 21 12:02 UTC → March 22 01:07 UTC)

---

## Executive Summary

The portfolio has effectively stalled at breakeven since the contamination purge, with total value at **$10,100** (+1.0% from $10,000 initial). However, this masks a rapid deterioration: realized PnL collapsed from **+$43** at 17:00 March 21 to **-$4,183** by 01:00 March 22. The March 22 win rate fell to **3.6%** (1 win out of 28 settlements), driven by concentrated losses on two markets (Munich weather and Slovenian elections). Three new bugs were identified — the most critical being the lack of per-market position concentration limits, which amplifies single-market losses into portfolio-level blowups.

---

## Portfolio State

| Metric | Value |
|--------|-------|
| Total Value | $10,100 (+1.0%) |
| Cash | $14,054 |
| Realized PnL | -$4,183 |
| Unrealized PnL | -$82 |
| Post-purge Trades | 2,379 |
| Post-purge Settlements | 91 |
| Post-purge Wins | 28 (30.8%) |
| March 22 Win Rate | **3.6%** (1/28) |

---

## Win Rate Analysis

Overall post-purge win rate is 30.8% (28/91), but this is heavily front-loaded. The March 21 post-purge window had a 41.4% win rate (24/58), while March 22 collapsed to 3.6% (1/28).

**By pair type (settlement-level):**

| Type | Settlements | Wins | Win % |
|------|------------|------|-------|
| Mutual Exclusion | 83 | 34 | 41.0% |
| Conditional | 35 | 15 | 42.9% |
| Implication | 110 | 19 | 17.3% |

The implication pair win rate of 17.3% is concerning — these represent the bulk of simulated opportunities (900 of 1,183) but produce the weakest settlement outcomes.

---

## Edge Capture Efficiency

| Metric | Value |
|--------|-------|
| Avg Estimated Profit | $0.147 |
| Avg Theoretical Profit | $0.186 |
| Est/Theo Ratio | 0.847 (conservative) |
| Est > Theo Anomaly Rate | 1.2% (14/1,183) |
| Edge Cap Triggers | 923 opps blocked |

The est/theo ratio of 0.847 means the system is appropriately conservative in its profit estimates post-fix. Only 1.2% of opportunities show estimated profit exceeding theoretical — a massive improvement from 99.9% pre-fix. The edge cap at 0.20 is blocking 923 phantom-edge opportunities effectively.

**However**, the gap between estimated and realized profit is enormous. The system estimates $0.147 profit per opportunity on average, but the portfolio is net negative on realized PnL. The primary driver is not estimation error — it's that the system is trading on *structurally wrong pairs* (bugs #13, #14, #16) where the constraint model itself is incorrect.

---

## Fee and Slippage Impact

| Metric | Value |
|--------|-------|
| Total Fees (post-purge) | $113 (BUY $38 + SELL $75) |
| Total Slippage | $12 |
| Avg Fee per Trade | $0.048 |
| Avg Slippage per Trade | $0.005 |
| Avg Fee per Share | $0.003 |

Fees and slippage are **not** the primary drag. At $0.048 + $0.005 = $0.053 per trade versus an average estimated profit of $0.155, execution costs consume ~34% of edge. This is reasonable for a paper trading system. The losses are driven by structural misclassification, not execution friction.

---

## Performance by Pair Type

| Type | Opps | Trades | Avg Est | Avg Theo | Fees | Slippage |
|------|------|--------|---------|----------|------|----------|
| Implication | 900 | 1,808 | $0.150 | $0.164 | $86 | $9.04 |
| Mutual Exclusion | 249 | 465 | $0.173 | $0.189 | $22 | $2.33 |
| Partition | 34 | 63 | $0.190 | **$1.000** | $5 | $0.32 |

**Partition pairs are wildly miscalibrated**: average theo of $1.00 (the maximum possible) vs est of $0.19. These are deadline-nested events ("by June" vs "by December") classified as partition instead of implication — see Bug #16.

---

## Trend Detection

**Hourly portfolio value (post-purge):**

| Hour (UTC) | Value | Realized PnL | Trades | Wins |
|------------|-------|-------------|--------|------|
| Mar 21 12:00 | $10,105 | -$0.17 | 58 | 0 |
| Mar 21 14:00 | $9,939 | +$10 | 257 | 1 |
| Mar 21 16:00 | $9,958 | +$42 | 1,002 | 2 |
| Mar 21 17:00 | $10,021 | +$41 | 1,065 | 5 |
| Mar 21 23:00 | $10,102 | **-$3,982** | 1,789 | 15 |
| Mar 22 00:00 | $10,103 | **-$4,187** | 2,379 | 28 |
| Mar 22 01:00 | $10,100 | **-$4,183** | 2,379 | 28 |

The catastrophic swing between 17:00 and 23:00 correlates with a burst of 42 settlements at 23:00 (19 wins, 23 losses) and 28 settlements at 00:00 (1 win, 27 losses). The system entered large positions on markets that subsequently resolved against it.

**Concentrated loss markets:**

- **Munich weather 16°C** (market 130470): 9 settlements, ALL losses, 88.4 shares wiped
- **Slovenian election turnout 75%+** (market 120924): 9 settlements, ALL losses, 73.7 shares wiped
- **US tariff rate on China** (market 110072): 8 settlements, ALL losses, 22.7 shares

---

## Bug Regression Status

### Fixed (Bugs #1–11) — All Confirmed, No Regressions

All 11 previously-fixed bugs remain fixed in the codebase. Key verifications: `trades.py` uses `max()` per market (not sum), `min_edge=0.03`, `_conditional_matrix` has full divergence/correlation/sum logic, `_check_over_under_markets()` and `_check_price_threshold_markets()` both exist with correct regex patterns, verification gating is active, and position sizing uses Half-Kelly on net profit.

### Partially Fixed (Bug #12) — MAX_EDGE Cap

The MAX_EDGE=0.20 cap blocks extreme phantom edges (923 opps capped post-purge). However, moderate phantom edges (0.10–0.19 per leg) from stale misclassified pairs still pass through. The cap is a Band-Aid — the root fix requires re-classifying stale pairs (#13).

### Open Bugs

| # | Bug | Severity | Impact |
|---|-----|----------|--------|
| **#13** | 520 O/U pairs still classified as ME (was 468) | **HIGH** | Still generating phantom-edge trades. FC Dallas O/U simulated at 23:59 UTC. Count is growing, not shrinking. |
| **#14** | 14 esports game-winner pairs as ME | MEDIUM | LoL GIANTX vs Fnatic pair simulated 3x in last hour with phantom est=0.16–0.20 |
| **#15** | Conditional est/theo overestimation | LOW (dormant) | 0 conditional opps simulated post-purge. Pipeline appears inactive for this type. |
| **#16** | 🆕 Deadline-nested pairs as partition | **HIGH** | LLM classifies "by June" vs "by December" as partition (theo=$1.00). 34 simulated, 145 pairs in DB. Should be implication. |
| **#17** | 🆕 No per-market position concentration limit | **CRITICAL** | System re-enters same market 25+ times (Bitcoin: 256 shares, Munich: 88 shares). When it loses, the concentrated exposure creates outsized losses. |
| **#18** | 🆕 March 22 win rate collapse (3.6%) | **HIGH** | Compound effect of #13 + #17. Single-market blowups on weather and elections. |

---

## Root Cause Analysis

The portfolio's poor performance is NOT caused by estimation error, fee drag, or slippage. The core pipeline (optimizer, position sizing, edge estimation) is working correctly for properly classified pairs. The three root causes are:

1. **Stale misclassified pairs (#13, #14)**: The classifier was fixed to handle O/U and game-winner patterns, but existing pairs in the database were never re-classified. 520+ stale pairs continue generating phantom-edge opportunities. This is the #1 priority fix — implement a one-time re-classification sweep or invalidate old pairs.

2. **No position concentration limit (#17)**: The circuit breaker checks per-trade risk but doesn't cap aggregate exposure to a single market. The system happily accumulates 250+ shares on a single binary outcome across multiple opportunities. When that outcome resolves as a loss, the damage is catastrophic. A per-market position cap (e.g., max 50 shares per market:outcome) would prevent this.

3. **LLM misclassification of deadline-nested pairs (#16)**: The LLM classifies "event by June" vs "event by December" as partition rather than implication. This produces theoretical profit of $1.00 (wildly wrong) and causes the system to trade aggressively on non-existent arbitrage. A rule-based handler for deadline-nested patterns is needed.

---

## Recommended Actions (Priority Order)

1. **CRITICAL**: Add per-market position concentration limit to `SimulatorPipeline`. Cap total shares per market:outcome at e.g. 50. This prevents single-market blowups immediately.

2. **HIGH**: Run a one-time re-classification sweep of all existing market pairs. Re-run the rule-based classifier on all pairs currently tagged as `mutual_exclusion` and update any that match the O/U, price-threshold, or game-winner patterns.

3. **HIGH**: Add a rule-based handler for deadline-nested events ("by March 31" vs "by June 30"). Classify as implication (shorter deadline implies longer deadline).

4. **MEDIUM**: Add a rule-based handler for esports "Game X Winner" patterns in the same series. Different game numbers are independent, not mutually exclusive.

5. **LOW**: Investigate why conditional pair pipeline is inactive (0 simulated post-purge). May be a data flow issue or verification gating filtering them all out.
