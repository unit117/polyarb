# PolyArb Performance Monitor Report

**Run:** 2026-03-21 ~11:15 UTC | **System uptime:** ~21.5 hours (first trade: Mar 20 13:46 UTC)

---

## Executive Summary

The portfolio stands at **$14,972 total value** from $10,000 initial capital, but this headline number masks severe underlying problems. Realized PnL is **-$2,579** and unrealized PnL is **-$1,702**, meaning the system has actually lost $4,281 on a mark-to-market basis. The apparent "profit" comes from holding positions whose current market prices happen to exceed their entry prices — but the 0.38% win rate on settled trades (13 wins out of 3,389) strongly suggests these unrealized gains will not materialize.

Three new bugs were discovered this run, all related to misclassification of implication pairs as mutual_exclusion. This is the **primary driver of post-fix losses** — the optimizer generates phantom 50¢+ edges on pairs where both outcomes are priced near $1.00 but are wrongly constrained as mutually exclusive.

---

## Portfolio State

| Metric | Value |
|--------|-------|
| Cash | $16,495 |
| Total Value (cash + positions) | $14,972 |
| Realized PnL | -$2,579 |
| Unrealized PnL | -$1,702 |
| Total Trades | 3,389 (excl. settlements) |
| Winning Trades | 13 |
| Win Rate | 0.38% |
| Total Fees Paid | $466 |
| Total Slippage Cost | $233 |

---

## Pre-Fix vs Post-Fix Comparison

| Metric | Pre-Fix (<06:00 UTC) | Post-Fix (>06:00 UTC) |
|--------|----------------------|-----------------------|
| Opportunities | 2,880 | 1,240 |
| Simulated (traded) | 1,025 | 126 |
| Est > Theo anomaly rate | 35.6% | 3.5% |
| Avg Estimated Profit | $0.055 | $0.043 |
| Avg Theoretical Profit | $0.032 | $0.070 |
| Est Dollar Profit (paper) | $18,746 | $12,406 |
| Total Fees | $159 | $306 |
| Settlements | 472 | 56 |

The bug fixes for estimated_profit double-counting (#1) and min_edge threshold (#2) are clearly working — the Est>Theo anomaly rate dropped from 35.6% to 3.5%. However, post-fix fees are 2x higher despite fewer trades, because position sizes are larger (driven by the large phantom edges from misclassified pairs).

---

## Performance by Pair Type (Post-Fix)

| Type | Opps | Simulated | Trades | Avg Est | Avg Theo | Est/Theo Ratio | Total Fees |
|------|------|-----------|--------|---------|----------|----------------|------------|
| mutual_exclusion | 1,034 | 71 | 272 | $0.325 | $0.347 | 0.84x | $160 |
| conditional | 187 | 50 | 128 | $0.464 | $0.360 | 2.08x | $128 |
| partition | 18 | 5 | 20 | $0.449 | $1.000 | 0.45x | $18 |
| implication | 1 | 0 | 0 | $0.000 | $0.012 | — | — |

**Key observations:**

- **Conditional pairs** have an Est/Theo ratio of 2.08x, meaning the optimizer systematically overestimates edges by 2x. The conditional constraint matrix is too loose — divergence thresholds of 0.15 don't capture enough of the price relationship.
- **Mutual exclusion** dominates trading volume but many are misclassified implication pairs (see Bug #10-12 below).
- **Partition** pairs show Theo=1.00 (the theoretical maximum for a partition violation), suggesting these are correctly identified but the edges are still large.
- **Implication** — only 1 opp detected post-fix, 0 traded. The rule-based handler exists but its regex misses common patterns.

---

## Edge Capture Efficiency

Post-fix edge distribution shows a bimodal pattern:

| Edge Bucket | Count | % of Total | Avg Theo |
|-------------|-------|------------|----------|
| Zero/Negative | 1,005 | 81.0% | $0.032 |
| 1-3¢ | 4 | 0.3% | $0.060 |
| 3-5¢ | 9 | 0.7% | $0.170 |
| 5-10¢ | 14 | 1.1% | $0.101 |
| >10¢ | 208 | 16.8% | $0.214 |

81% of opportunities correctly show zero estimated profit after fee deduction (the min_edge fix is working). But 16.8% show >10¢ edges — these are overwhelmingly the misclassified pairs producing phantom edges. There's almost nothing in the realistic 1-5¢ range where genuine arb should live.

---

## Slippage and Fee Analysis

- **Avg slippage per trade:** 0.50¢ (0.005 per share)
- **Slippage is constant** at 0.005 across all trades — this is a flat model, not actual order book simulation. The `FETCH_ORDER_BOOKS=false` setting means VWAP falls back to midpoint + fixed slippage.
- **Fee rate:** 2% of notional (matching the 0.02 FEE_RATE setting)
- **Avg fee per trade:** $0.72 (post-fix), reflecting larger position sizes
- **Fee drag on a typical 2-trade opp:** ~$2.00 on $200 notional = 1% round-trip cost

Fees and slippage together consume ~$3 per opportunity on ~$200 notional. For a genuine arb edge of 3-5¢ per share, the dollar profit would be $6-10, making the system profitable. But the system rarely finds edges in this range — it either finds nothing (81%) or phantom edges >10¢ (17%).

---

## Settlement Analysis

528 total settlements, with a deeply negative profile:

- **Winning shares (settled at $1):** -2,202 (negative = short positions that resolved Yes, meaning LOSSES)
- **Losing shares (settled at $0):** 3,224 (positive = long positions that resolved No, meaning LOSSES)

Both categories are losses: the system was long on outcomes that went to $0, and short on outcomes that went to $1. This is consistent with the mutual_exclusion misclassification — when the optimizer wrongly believes two near-certain outcomes can't both be true, it sells one (which then resolves Yes = loss) and buys the other's complement (which resolves No = loss).

---

## Bug Regression Status

### Fixed Bugs (6/12)

| # | Bug | Status |
|---|-----|--------|
| 1 | estimated_profit double-counting | FIXED — uses max() per market |
| 2 | min_edge too low (0.005) | FIXED — raised to 0.03 |
| 3 | Conditional constraints all-ones | FIXED — Frechet bounds + correlation logic |
| 4 | Crypto time-interval misclassification | FIXED — rule-based handler |
| 5 | 0% verification rate | FIXED — verification.py gates trading |
| 6 | Position sizing on inflated edge | FIXED — uses profit_ratio |

### Partially Fixed Bugs (2/12)

| # | Bug | Status | Notes |
|---|-----|--------|-------|
| 7 | Price-threshold as mutual_exclusion | PARTIALLY FIXED | `_check_price_threshold_markets()` exists but regex misses patterns without `$` (see #10) |
| 8 | Same-date-different-threshold misclass | PARTIALLY FIXED | Time-interval patterns handled; date-only patterns rely on LLM prompt guidance |

### Open Bugs (4/12)

| # | Bug | Severity | Impact |
|---|-----|----------|--------|
| 9 | Portfolio contamination — purge never ran | HIGH | Portfolio carries -$2,579 RPnL from pre-fix. 0 PURGE trades, 0 resets. |
| 10 | 🆕 `_PRICE_THRESHOLD_RE` misses numbers without `$` sign | CRITICAL | "SPX close over 5,625" and "O/U 227.5" patterns don't match, fall to LLM which misclassifies. Evidence: Opp IDs 2954-2956. |
| 11 | 🆕 No rule-based handler for Over/Under sports markets | CRITICAL | "O/U 227.5" vs "O/U 228.5" are implication pairs but classified as ME. Evidence: Opp ID 2886. |
| 12 | 🆕 Phantom 50¢+ edges from misclassified ME pairs | CRITICAL | When two $0.999 outcomes are wrongly ME-constrained, optimizer halves fair prices to ~$0.50, creating phantom edges. System takes 400-share positions that are guaranteed losers on settlement. |

---

## Root Cause Analysis

The **single root cause** of ongoing losses is: **implication pairs misclassified as mutual_exclusion**.

The chain of failure:

1. Questions like "SPX close over 5,625" and "SPX close over 6,000" are implication pairs (above $6,000 implies above $5,625)
2. The `_PRICE_THRESHOLD_RE` regex requires `$` before the number and doesn't match these
3. They fall to the LLM, which despite improved prompt guidance, still classifies them as mutual_exclusion
4. Verification passes because both markets are binary with prices in valid ranges
5. The optimizer sees two outcomes both priced at ~$0.999 that "can't both be Yes"
6. It computes fair prices of ~$0.50 each, generating a phantom ~50¢ edge
7. Position sizing gives this max size (profit_ratio = min(0.98/0.10, 1.0) = 1.0 → $100/share)
8. The system takes 400-share positions (4 trades × $100)
9. When both markets resolve Yes (as they should — SPX was above both thresholds), the short positions lose ~$100/share

---

## Recommendations (Priority Order)

1. **IMMEDIATE: Extend `_PRICE_THRESHOLD_RE` to match numbers without `$`** — change regex to make `\$` optional. Also add an "O/U" pattern for sports Over/Under markets.

2. **IMMEDIATE: Add a sanity check on estimated_profit > 0.20** — no genuine binary arb should have a 20%+ edge in liquid Polymarket markets. Flag and skip these.

3. **HIGH: Run the contamination purge** — `purge_contaminated_positions()` exists in pipeline.py but was never triggered. Execute it to reset the portfolio and get clean post-fix metrics.

4. **MEDIUM: Tighten conditional constraint thresholds** — the 2.08x Est/Theo ratio for conditional pairs suggests the DIVERGENCE_THRESHOLD of 0.15 is too generous. Consider 0.25 or a dynamic threshold.

5. **MEDIUM: Add a max_estimated_profit cap** — reject opportunities where estimated_profit exceeds some reasonable ceiling (e.g., 0.15) as likely misclassification artifacts.

---

## Trend Detection

The system is producing 200-600 opportunities per hour, with 23-57 being simulated. The rate has been stable over the last 6 hours. There was a ~14-hour gap between pre-fix (last trade 18:49 Mar 20) and post-fix (first trade 09:07 Mar 21), likely a service restart for the bug fixes.

Post-fix improvements are real: the Est>Theo anomaly rate dropped from 35.6% to 3.5%, verification is gating at 100%, and position sizing uses fee-adjusted profits. But the new classification bugs (#10-12) mean the system is still taking catastrophically wrong positions on misclassified pairs, which will dominate the PnL picture as these positions settle.
