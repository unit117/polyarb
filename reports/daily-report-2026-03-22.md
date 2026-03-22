# PolyArb Daily Report — 2026-03-22 (AM)

**Report generated:** 2026-03-22 ~07:05 UTC
**Reporting period:** 24 hours (2026-03-21 07:00 → 2026-03-22 07:00 UTC)

---

## Portfolio Summary

| Metric | Current | 24h Ago | Change |
|--------|---------|---------|--------|
| Total Value | $10,224.60 | $12,322.50 | **-$2,097.90 (-17.0%)** |
| Cash | $13,557.18 | $13,473.35 | +$83.83 |
| Realized PnL | -$4,152.73 | -$1,286.46 | **-$2,866.27** |
| Unrealized PnL | $10.76 | -$930.25 | +$941.01 |
| Win/Loss (cumulative) | 47W / 92L | 12W / — | — |
| Settled Trades (cumulative) | 139 | — | — |

**Portfolio return since inception:** +2.2% ($10,224.60 on $10,000 capital)

The portfolio dropped significantly over the past 24 hours, losing $2,098 in total value (-17.0%). Realized PnL worsened by $2,866, driven by a large batch of losing settlements. Unrealized PnL recovered by $941 as positions were closed. The portfolio is now essentially flat with zero open positions.

---

## Hourly Portfolio Trajectory (last 24h)

| Hour (UTC) | Total Value | Realized PnL | Unrealized PnL |
|------------|-------------|--------------|----------------|
| 2026-03-22 07:00 | $10,222.27 | -$4,152.73 | $8.44 |
| 2026-03-22 06:00 | $10,182.37 | -$4,149.37 | -$34.82 |
| 2026-03-22 05:00 | $10,094.86 | -$4,205.08 | -$66.87 |
| 2026-03-22 04:00 | $10,094.86 | -$4,205.08 | -$66.87 |
| 2026-03-22 03:00 | $10,094.86 | -$4,205.08 | -$66.87 |
| 2026-03-22 02:00 | $10,094.86 | -$4,205.08 | -$66.87 |
| 2026-03-22 01:00 | $10,042.15 | -$4,304.67 | -$9.89 |
| 2026-03-22 00:00 | $10,103.41 | -$4,186.61 | -$122.00 |
| 2026-03-21 23:00 | $10,102.28 | -$3,982.13 | $405.31 |
| 2026-03-21 17:00 | $10,020.61 | $41.41 | -$13.56 |
| 2026-03-21 16:00 | $9,958.03 | $41.53 | -$1.18 |
| 2026-03-21 15:00 | $9,981.88 | $43.16 | $16.85 |
| 2026-03-21 14:00 | $9,938.91 | $10.02 | $8.42 |
| 2026-03-21 13:00 | $9,946.93 | -$2.94 | $28.26 |
| 2026-03-21 12:00 | $10,195.43 | -$48.94 | -$20.87 |
| 2026-03-21 11:00 | $15,205.47 | -$2,821.72 | -$1,876.63 |
| 2026-03-21 10:00 | $13,914.31 | -$2,048.75 | -$1,295.21 |
| 2026-03-21 09:00 | $12,912.45 | -$1,589.97 | -$1,022.16 |
| 2026-03-21 08:00 | $12,332.37 | -$1,286.46 | -$920.38 |

**Key observation:** There is a data gap between 17:00 and 23:00 UTC on Mar 21 (6 hours missing). During this gap, realized PnL collapsed from +$41 to -$3,982 — a swing of **-$4,024**. This represents the bulk of all losses. The massive settlement batch from the previous report's evening run appears to have continued settling unfavorably.

After 23:00 UTC, the portfolio stabilized around $10,100 and has been relatively flat through the morning.

---

## Trading Activity (last 24h)

| Metric | Value |
|--------|-------|
| Total Trades Executed | 5,290 |
| Settled | 203 |
| Distinct Markets Traded | 1,653 |
| Total Fees (24h) | **$567.76** |
| Total Fees (all-time) | $725.63 |
| Fee Rate (daily, % of portfolio) | **5.6%** |

**Fee drag remains the critical issue.** At $568/day (5.6% of portfolio), fees alone would consume the entire portfolio in ~18 days. This is marginally worse than the $562/day reported last run. The all-time fee total of $726 across 8,491 trades averages $0.085 per trade.

**Active positions: 0.** The portfolio has fully unwound all positions. No open trades remain. This may indicate the optimizer is not finding opportunities meeting the tightened criteria, or that all positions have been settled/exited.

---

## Opportunity Quality (last 24h)

| Metric | Value |
|--------|-------|
| Total Opportunities Evaluated | 39,020 |
| Converged | 0 (0.0%) |
| Simulated | 1,504 (3.9%) |
| Expired | 3,699 (9.5%) |
| Skipped | 31,999 (82.0%) |
| Avg Bregman Gap | 0.001961 |
| Avg Estimated Profit | $0.046 |

**Zero convergences is concerning.** The Frank-Wolfe optimizer found no opportunities that fully converged in 24 hours. 1,504 were simulated (partial convergence), suggesting edges exist but are marginal.

### By Pair Type

| Type | Count | Avg Profit | Avg Gap | Simulated |
|------|-------|-----------|---------|-----------|
| conditional | 31,572 (80.9%) | $0.174 | 0.00193 | 59 |
| mutual_exclusion | 3,655 (9.4%) | $0.015 | 0.00316 | 266 |
| implication | 3,584 (9.2%) | $0.073 | 0.00121 | 1,137 |
| partition | 180 (0.5%) | $0.070 | 0.00238 | 40 |
| none | 29 (0.1%) | $0.077 | 0.00503 | 2 |

Conditional pairs dominate volume at 81% but only produced 59 simulated trades (0.2% conversion). Implication pairs are the most productive: 1,137 simulated from 3,584 evaluated (31.7% conversion rate) with decent average profit ($0.073). This suggests the system should potentially weight implication pairs higher in the pipeline.

---

## Market Environment

| Metric | Value |
|--------|-------|
| Markets Resolved (24h) | 2,781 |
| Active Markets | 34,352 |
| Total Markets | 51,549 |

High resolution churn continues at ~2,800/day. The active market universe is large at 34K markets, providing ample detection surface.

---

## Pair Verification Status

| Metric | Value |
|--------|-------|
| Total Pairs | 14,971 |
| Verified | 14,412 (96.3%) |
| Unverified | 559 (3.7%) |

**Verification rate: 96.3%** — up from 76.3% at last run. The verification pipeline has nearly completed its pass through the pair universe. This is excellent progress; the system is now trading almost exclusively on verified pairs.

---

## Key Concerns & Recommendations

1. **Fee drag is existential.** At 5.6%/day, the portfolio cannot survive. The system needs either larger position sizes (to amortize fixed per-trade fees) or fewer, higher-conviction trades. Consider raising `min_edge` further from 0.03 to 0.05.

2. **Zero open positions.** The portfolio has fully unwound. If the optimizer/simulator pipeline is still running, it's not finding actionable opportunities. Check service health.

3. **Realized PnL collapse.** The -$4,024 swing between 17:00-23:00 UTC on Mar 21 is the dominant loss event. Investigation should focus on what batch of settlements drove this — likely the same set of inflated-edge positions from before Bug #1/#2 fixes took effect.

4. **Win rate improving but still low.** 47W / 92L (cumulative) = 33.8% win rate on settlements. This is much better than the 1.2% reported at the AM run, suggesting recent trades (post-bugfix) are performing significantly better.

5. **Implication pairs outperform.** With 31.7% simulation conversion rate vs 0.2% for conditional pairs, the system should investigate why conditional pairs have such poor conversion despite high theoretical profit.

---

## Bug Regression Status

| # | Bug | Status | Notes |
|---|-----|--------|-------|
| 1 | estimated_profit double-counts edges | ✅ FIXED | `trades.py` line 26: `min_edge=0.03`. Lines 71+ use `max()` per market. |
| 2 | min_edge threshold too low | ✅ FIXED | `trades.py` line 26: default 0.03, configurable. |
| 3 | Conditional pairs have no real constraints | ✅ FIXED | `constraints.py` lines 129+ implement Frechet bounds + correlation. |
| 4 | GPT-4o-mini misclassifies crypto time-interval pairs | ✅ FIXED | `classifier.py` lines 115+ `_check_crypto_time_intervals()` with regex rules. |
| 5 | 0% pair verification rate | ✅ FIXED | `verification.py` exists and operational. DB: 96.3% verified. |
| 6 | Position sizing uses inflated edge | ✅ FIXED | `pipeline.py` lines 127-148 use Half-Kelly on `estimated_profit` with drawdown scaling. |
| 7 | `_implication_matrix()` only handles binary outcomes | ⚠️ OPEN | `constraints.py` lines 84-90: still only sets `matrix[0][1]=0` for binary. Multi-outcome gets all-ones. |

All 6 original bugs remain fixed. Bug #7 (multi-outcome implication constraints) remains open — medium severity, only affects non-binary implication pairs.
