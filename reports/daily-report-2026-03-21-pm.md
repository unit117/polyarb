# PolyArb Daily Report — 2026-03-21 (PM)

Generated: 2026-03-21 ~10:15 UTC | Source: paper trading

---

## Portfolio Summary

| Metric | Value |
|--------|-------|
| Total Value | $13,446.33 |
| Cash | $14,557.55 |
| Unrealized PnL | -$1,239.30 |
| Realized PnL | -$1,881.11 |
| Total Trades (all-time) | 3,675 |
| Winning Trades | 13 |
| Source | Paper |

The portfolio is down from yesterday's close of $12,320.38, though the total value figure rose due to ongoing position rebalancing. Realized losses deepened from -$1,092.12 to -$1,881.11 (a $789 increase in realized loss over the day). Unrealized losses also widened from -$1,051.53 to -$1,239.30.

### 2-Day Trend

| Date | Close Value | Realized PnL | Unrealized PnL | Cash |
|------|-------------|-------------|----------------|------|
| 2026-03-20 | $12,320.38 | -$1,092.12 | -$1,051.53 | $13,605.33 |
| 2026-03-21 | $13,446.33 | -$1,881.11 | -$1,239.30 | $14,557.55 |

**Note:** The system has been live for approximately 2 days. The starting capital was $10,000 based on the backtest configuration, but portfolio snapshots reflect accumulated paper trade activity. Cash exceeds total value because positions carry net negative unrealized PnL.

---

## Trading Activity (Last 24 Hours)

| Metric | Value |
|--------|-------|
| Trades Executed | 3,675 |
| Unique Markets Traded | 1,125 |
| Total Fees Paid | $258.58 |
| Avg Trade Size | $7.33 |
| Avg Slippage | 0.43% |
| Trade Status: Filled | 3,165 |
| Trade Status: Settled | 510 |

All trades are classified as either BUY or SELL legs of rebalancing opportunities. The system has executed high-volume, small-size rebalancing trades across 1,125 distinct markets.

### Recent Trades (Sample)

| Market | Side | Outcome | Size | Price | Fees |
|--------|------|---------|------|-------|------|
| Predict.fun FDV above $300M one day after launch? | SELL | Yes | 95.00 | 0.42 | $0.79 |
| Predict.fun FDV above $100M one day after launch? | BUY | No | 95.00 | 0.305 | $0.58 |
| Predict.fun FDV above $300M one day after launch? | BUY | No | 95.00 | 0.58 | $1.11 |
| Predict.fun FDV above $100M one day after launch? | SELL | Yes | 95.00 | 0.695 | $1.31 |
| Spread: EC Juventude (-2.5) | BUY | Cuiabá EC | 12.49 | 0.47 | $0.12 |
| Sharks vs. Blue Jackets: O/U 7.5 | BUY | Under | 100.00 | 0.47 | $0.94 |

---

## Market Settlements (Last 24 Hours)

**1,271 markets resolved** in the last 24 hours — a large batch settlement. Notable settlements include:

- Valorant: Riddle vs Insomnia (BO3) → **Insomnia**
- Will Saudi Aramco be largest company by market cap on April 30? → **No**
- Will Silver (SI) hit $115–$170 by end of March? → **No** (series of 6 silver price markets all resolved No)
- Various political/leadership markets → **No**

---

## Opportunity Quality (Last 24 Hours)

| Metric | Value |
|--------|-------|
| Opportunities Detected | 3,498 |
| Type | 100% rebalancing |
| Avg Bregman Gap | 0.00583 |
| Min Bregman Gap | -0.00001 (converged) |
| Max Bregman Gap | 0.03157 |
| Avg Estimated Profit | $0.053 |
| Max Estimated Profit | $1.998 |
| Avg FW Iterations | 158.8 |
| Last Hour | 360 opps |

The optimizer is running steadily at ~360 opportunities/hour. All opportunities are "rebalancing" type. The average Bregman gap of 0.0058 indicates reasonable convergence (below the typical 0.01 threshold). Average estimated profit per opportunity is modest at $0.053, consistent with the small edge sizes after the min_edge fix raised the threshold to 0.03.

---

## Pair Verification Status

| Dependency Type | Total | Verified | Verification Rate |
|-----------------|-------|----------|-------------------|
| mutual_exclusion | 3,120 | 447 | 14.3% |
| conditional | 669 | 78 | 11.7% |
| partition | 26 | 7 | 26.9% |
| **Total** | **3,815** | **532** | **13.9%** |

**Market Coverage:** 44,701 markets tracked, 1,271 resolved.

Verification rate has improved from the initial 0% (bug #5) to 13.9% overall. The verification module is operational but is working through the backlog — only pairs that have been re-processed since the fix went live are verified. The `mutual_exclusion` type dominates the pair universe (81.8%).

---

## Bug Regression Status

All 6 previously identified bugs remain **FIXED** as of this check:

| # | Bug | Status |
|---|-----|--------|
| 1 | estimated_profit double-counts edges | FIXED — uses `max()` per market, subtracts fees |
| 2 | min_edge threshold too low (0.005) | FIXED — raised to 0.03, configurable |
| 3 | Conditional pairs return all-ones matrix | FIXED — Frechet bounds + correlation constraints |
| 4 | GPT-4o-mini crypto time-interval misclassification | FIXED — rule-based `_check_crypto_time_intervals()` |
| 5 | 0% pair verification rate | FIXED — `verification.py` module operational, 13.9% verified |
| 6 | Position sizing uses inflated edge | FIXED — uses `net_profit` / 0.10 ratio scaling |

No new bugs discovered in this run.

---

## Key Observations

1. **High trade volume, small edges:** 3,675 trades across 1,125 markets with an average size of $7.33 — the system is actively rebalancing but individual edge capture is small ($0.053 avg profit per opportunity).

2. **Realized losses growing:** Realized PnL went from -$1,092 to -$1,881 in 24 hours. This bears watching — fees ($258.58/day) are a significant drag on a system capturing $0.05 edges on $7 positions.

3. **Fee drag analysis:** At 3,675 trades × $0.07 avg fee = ~$258/day in fees. With avg estimated profit of $0.053 × 3,498 opps = ~$185/day in theoretical edge. **Fees are exceeding captured edge**, which explains the growing realized losses.

4. **Large settlement batch:** 1,271 markets resolved suggests a bulk resolution event. The 510 settled trades vs 3,165 filled suggests ~16% of trades have reached settlement.

5. **Verification backlog:** At 13.9% verification rate, the system is still trading on many unverified pairs. As verification catches up, some currently-traded pairs may be rejected, potentially reducing volume but improving quality.
