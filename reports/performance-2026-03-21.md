# PolyArb Performance Report — 2026-03-21

**Report generated:** 2026-03-21 ~08:45 UTC
**Period covered:** System launch (2026-03-20 13:46 UTC) through 2026-03-21 08:40 UTC (~19 hours of operation)
**Overall Rating: CRITICAL**

---

## Executive Summary

The system is **losing money**. Starting from $10,000 in capital, the portfolio has declined to **$12,328 in total value** despite holding **$13,473 in cash** — meaning open positions are deeply underwater with **-$924 in unrealized losses** and **-$1,286 in realized losses**. The win rate is an alarming **0.4%** (12 wins out of 2,969 trades). The optimizer is producing estimated profits far above theoretical profits, suggesting the optimization is **systematically overestimating edge**. Immediate intervention is needed.

---

## 24h Scorecard

| Metric | Value |
|---|---|
| Total trades executed | 2,969 (filled) + 486 (settled) = 3,455 |
| BUY / SELL / SETTLE | 1,485 / 1,484 / 486 |
| Win rate | **0.4%** (12 / 2,969) |
| Average trade size | $4.87 |
| Average entry price | $0.4951 |
| Average VWAP price | $0.4941 |
| Average slippage | 0.0043 (0.43%) |
| Total fees paid | $159.42 |
| Realized PnL | **-$1,286.46** |
| Unrealized PnL | **-$924.46** |
| Portfolio total value | **$12,328.29** (from $10,000 start) |
| Cash on hand | $13,473.35 |

> **Note:** The portfolio shows $13,473 cash (above starting capital) because SELL-side trades generate immediate cash inflow, but the corresponding short positions are underwater, producing the unrealized loss.

---

## Edge Analysis

### Theoretical vs. Estimated vs. Actual

The optimizer is producing **estimated profits dramatically higher than theoretical profits** for many opportunities:

- Average theoretical profit: **$0.102** per opportunity
- Average estimated profit (post-optimization): **$0.210** per opportunity
- Estimated/theoretical ratio: **2.06x** — the optimizer claims it can capture 2x the theoretical edge

This is a major red flag. The estimated profit should be *at most* equal to the theoretical profit (usually less, after accounting for execution costs). An estimated profit *exceeding* theoretical profit indicates the Frank-Wolfe optimization is **not converging properly** or the constraint matrix is misconfigured.

### Convergence Quality

| Metric | Value |
|---|---|
| Total opportunities | 2,880 |
| Optimized (converged) | 1,008 (35.0%) |
| Simulated (traded) | 1,025 (35.6%) |
| **Unconverged** | **847 (29.4%)** |

Nearly **30% of opportunities fail to converge**, hitting the 200-iteration cap with high Bregman gaps. Even the "converged" solutions show gaps well above zero in many cases. Samples show fw_iterations=200 (max) with bregman_gap ranging from 0.005 to 0.015 — these are NOT converged solutions being passed to the simulator.

### Settled Trade Analysis

486 positions have settled (markets resolved). Settled trades show entry_price of 0.0000 or 1.0000 with zero fees, indicating these are resolution events, not new trades. The settlements have no linked opportunity_id, suggesting the settlement path doesn't reconnect to the original opportunity for PnL attribution.

---

## Opportunity Funnel

| Stage | Count | Conversion |
|---|---|---|
| Market pairs detected | 3,138 | — |
| Arbitrage opportunities (24h) | 2,880 | 91.8% of pairs produced at least one opp |
| Opportunities optimized | 1,008 | 35.0% of detected |
| Opportunities simulated/traded | 1,025 | 35.6% of detected |
| Unconverged (discarded) | 847 | 29.4% of detected |
| Profitable trades | 12 | **0.4% of traded** |

The funnel shows a catastrophic drop at the final stage: of 2,969 executed trades, only 12 were profitable. This means the system is executing trades on opportunities that do not represent real arbitrage.

---

## Portfolio Trend (Hourly)

| Time (UTC) | Cash | Total Value | Realized PnL | Unrealized PnL | Trades | Wins |
|---|---|---|---|---|---|---|
| Mar 20 13:00 | $10,239 | $10,239 | $0 | $0 | 226 | 0 |
| Mar 20 14:00 | $11,756 | $11,756 | $0 | $0 | 876 | 0 |
| Mar 20 15:00 | $12,354 | $10,944 | $0 | -$938 | 1,466 | 0 |
| Mar 20 16:00 | $12,492 | $11,093 | $0 | -$987 | 2,059 | 0 |
| Mar 20 17:00 | $13,605 | $11,753 | $0 | -$1,265 | 2,533 | 0 |
| Mar 20 18:00 | $14,614 | $12,473 | $0 | -$1,472 | 2,969 | 0 |
| Mar 20 19:00 | $13,740 | $12,368 | -$931 | -$1,087 | 2,969 | 5 |
| Mar 20 22:00 | $13,687 | $12,343 | -$1,003 | -$1,077 | 2,969 | 10 |
| Mar 21 00:00 | $13,585 | $12,319 | -$1,117 | -$1,038 | 2,969 | 10 |
| Mar 21 04:00 | $13,548 | $12,331 | -$1,196 | -$974 | 2,969 | 12 |
| Mar 21 08:00 | $13,473 | $12,328 | -$1,286 | -$924 | 2,969 | 12 |

**Trajectory: Declining.** The portfolio peaked at ~$12,473 total value at 18:00 UTC on Mar 20 and has been slowly eroding since. No new trades have been placed since 18:00 UTC (trade count stuck at 2,969), but settlements continue to realize losses. The realized PnL has worsened from -$931 to -$1,286 over the past 12 hours as positions resolve unfavorably.

---

## Market Type Analysis

| Dependency Type | Trades | Avg Theoretical | Avg Estimated | Avg Fees | Avg Slippage |
|---|---|---|---|---|---|
| mutual_exclusion | 2,721 | $0.110 | $0.228 | $0.058 | $0.005 |
| conditional | 246 | $0.001 | $0.015 | $0.006 | $0.005 |
| partition | 2 | $1.000 | $0.015 | $0.007 | $0.005 |

**Mutual exclusion** pairs dominate trading (91.6% of trades) and show the largest estimated-vs-theoretical discrepancy (2.07x). **Conditional** pairs have a near-zero theoretical profit ($0.001) but the optimizer inflates this to $0.015 — these should not be traded at all given fees of $0.006 per leg. **Partition** pairs show a theoretical profit of $1.00 (likely a calculation error or extreme outlier) but estimated profit of only $0.015.

---

## Optimizer Quality

The Frank-Wolfe optimizer is severely underperforming:

- **29.4% of opportunities fail to converge** (hit 200-iteration cap)
- Many "converged" solutions have Bregman gaps of 0.005–0.015, indicating poor-quality solutions
- The optimizer consistently produces estimated profits **above** theoretical profits, which is mathematically suspect — the estimated profit should account for execution costs and be *lower* than theoretical
- Only trades from "simulated" status opportunities were actually executed (2,969 trades from 1,025 opportunities ≈ 2.9 trades per opportunity)

---

## Competition Detection

With only ~19 hours of data, long-term trend analysis is limited. However:

- **Theoretical profit is volatile** across hours: ranging from $0.012 to $0.042 average per opportunity
- **No new trades since ~18:00 UTC Mar 20** — the system appears to have stopped finding tradeable opportunities after the initial burst, though it continued finding and evaluating opportunities (2,880 total)
- **Slippage is flat at 0.50%** across all trades — this appears to be a fixed simulation parameter rather than actual market-derived slippage, which limits the usefulness of slippage analysis for competition detection

---

## Recommendations

1. **URGENT — Fix the optimizer overestimation bug.** Estimated profit should never systematically exceed theoretical profit. Investigate whether the constraint matrix is being applied correctly in the Frank-Wolfe optimization. The 2x ratio suggests costs/constraints are being inverted or ignored.

2. **URGENT — Increase minimum edge threshold.** Conditional pairs with $0.001 theoretical profit are being traded despite fees of $0.006 per leg. Set `min_edge` to at least **$0.02** to filter out noise. Trades below this threshold have essentially zero chance of profitability.

3. **Fix convergence rate.** 29.4% unconverged is too high. Consider increasing `fw_max_iterations` beyond 200 or lowering the convergence tolerance. Alternatively, examine whether the constraint matrices for unconverged pairs are degenerate or ill-conditioned.

4. **Audit the win rate calculation.** A 0.4% win rate across 2,969 trades is extraordinarily low and suggests either (a) the system is trading on phantom arbitrage, (b) the win/loss classification is broken, or (c) slippage and fees are consuming all edge. Given that slippage appears to be a fixed 0.50% parameter, verify this is calibrated against actual Polymarket order book depth.

5. **Add per-trade PnL tracking.** Settled trades have no linked `opportunity_id`, making it impossible to compute edge capture ratios. Wire the settlement path back to the original opportunity for full PnL attribution.

6. **Reduce position concentration in mutual_exclusion pairs.** 91.6% of trades are in mutual_exclusion pairs. Diversifying across dependency types (especially well-converged partition pairs if more can be found) would reduce systematic risk.

7. **Investigate why trading stopped.** No new trades have been placed in ~14 hours despite the system continuing to evaluate opportunities. Check if the simulator hit a risk limit, ran out of capital allocation, or encountered an error.

---

*Report generated automatically by PolyArb Performance Monitor*
