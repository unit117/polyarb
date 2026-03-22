# PolyArb Daily Report — 2026-03-21 (Evening)

**Report generated:** 2026-03-21 ~18:00 UTC
**Reporting period:** Last 24 hours
**Starting capital:** $10,000.33

---

## Portfolio Summary

| Metric | Current | 24h Ago | Change |
|--------|---------|---------|--------|
| Total Value | $10,119.69 | $12,349.12 | -$2,229.43 (-18.1%) |
| Cash | $13,041.60 | $13,721.83 | -$680.23 |
| Unrealized PnL | +$70.81 | -$1,089.31 | +$1,160.12 |
| Realized PnL | +$43.16 | -$966.49 | +$1,009.65 |
| Total Trades | 1,065 | 2,969 | — |
| Win Rate | 5 / 1,065 (0.5%) | 9 / 2,969 (0.3%) | — |
| Settled Trades | 21 | — | — |

**Net return since inception:** +$119.36 (+1.2%) over ~28 hours of operation.

> **Note:** The 24h-ago snapshot shows a higher total_value ($12,349) than today ($10,120). This appears to be driven by large position churn — many positions were purged (1,799 trades) and settled (563 trades), reducing gross exposure. Unrealized PnL swung from -$1,089 to +$71 as losing positions were flushed out. Realized PnL improved from -$966 to +$43 as settlements resolved favorably.

---

## Trading Activity (Last 24 Hours)

| Action | Count | Fees |
|--------|-------|------|
| Filled (entries/exits) | 2,040 | $565.52 |
| Purged (cancelled) | 1,799 | $0.00 |
| Settled (market resolved) | 563 | $0.00 |
| **Total** | **4,402** | **$565.52** |

### Daily Fee Trend

| Date | Trades | Fees |
|------|--------|------|
| 2026-03-21 | 3,562 | $534.63 |
| 2026-03-20 | 3,163 | $157.87 |

### Lifetime Totals

- **Total trades:** 6,725
- **Total fees paid:** $692.50
- **Fee drag concern:** Fees of $535/day on 2026-03-21 are extremely high relative to portfolio size. This is ~5.3% of portfolio value spent on fees in a single day. The previous run flagged $258/day as concerning — fees have now **doubled**.

---

## Opportunity Pipeline

| Status | Count | Avg Est. Profit |
|--------|-------|-----------------|
| Skipped | 8,012 | $0.00 |
| Detected | 716 | $0.047 |
| Unconverged | 815 | $0.001 |
| Optimized | 1,348 | $0.009 |
| Simulated | 1,650 | $0.183 |
| Expired | 2,590 | $0.001 |
| **Active** | **0** | — |

**Key finding:** There are currently **zero active opportunities**. All 15,131 historical opportunities have been processed to terminal states. The most recent opportunities (IDs 15638–15642) are in "detected" state as of 17:58 UTC, meaning the pipeline is still finding and processing candidates but none are currently active/trading.

### Opportunity Quality

No active opportunities to evaluate. Historical simulated opportunities averaged $0.18 estimated profit — the strongest cohort. The pipeline's yield from detected → simulated is roughly 1,650 / 716 ≈ 2.3x (some detected become simulated via optimization), but the majority (8,012) are skipped at the filter stage.

---

## Pair Verification Status

| Verified | Count | Percentage |
|----------|-------|------------|
| True | 4,896 | 64.4% |
| False | 2,706 | 35.6% |
| **Total** | **7,602** | — |

Verification rate improved from 13.9% (previous run) to **64.4%** — a major jump. This suggests the verification pipeline is working through the backlog effectively.

---

## Market Universe

- **Total markets tracked:** 46,892
- **Total pairs:** 7,602
- **Markets resolved (24h):** 2,578

The high resolution rate (2,578 markets in 24h) explains the large number of settled trades (563) and purged positions (1,799).

---

## Risk Assessment

1. **Fee drag is critical.** At $535/day in fees against a $10,120 portfolio, the system needs to generate >5.3% daily to break even on fees alone. Current realized PnL of +$43 over ~28h is far below this threshold on a daily basis, though the realized improvement from -$966 to +$43 suggests the position quality is improving post-bugfixes.

2. **Win rate is extremely low (0.5%).** Only 5 winning trades out of 1,065 filled trades. This could indicate the edge calculation or trade selection still needs work, or it could reflect the settlement-driven nature of the PnL (where many small losses are offset by fewer large wins on resolution).

3. **Position count is high.** 369 non-zero positions is a large book for a $10K portfolio. Average position size is approximately $27, which is very small and contributes to fee drag (fixed per-trade costs eat into tiny positions).

4. **No active opportunities.** The pipeline is detecting candidates but nothing is actively being traded. This could be healthy (no good arb exists right now) or indicate a filter is too aggressive post-bugfixes.

---

## Bug Regression Status

All 6 previously identified bugs remain **FIXED** as of this run. No regressions detected.

| # | Bug | Status | Notes |
|---|-----|--------|-------|
| 1 | estimated_profit double-counts edges | ✅ FIXED | `max()` per market + fee subtraction in place |
| 2 | min_edge threshold too low (0.005) | ✅ FIXED | Default 0.03 in trades.py and config.py |
| 3 | Conditional pairs return all-ones matrix | ✅ FIXED | Frechet bounds + correlation logic implemented |
| 4 | GPT-4o-mini misclassifies crypto time pairs | ✅ FIXED | Rule-based `_check_crypto_time_intervals()` in place |
| 5 | 0% pair verification rate | ✅ FIXED | verification.py exists, pipeline gates on `verified` |
| 6 | Position sizing uses inflated edge | ✅ FIXED | Half-Kelly on net_profit, with drawdown scaling |

### New Bug Discovered

| # | Bug | Location | Severity |
|---|-----|----------|----------|
| 🆕 7 | `_implication_matrix()` only handles binary (2×2) outcomes — multi-outcome implications (e.g., "Top 10 implies Top 20") get no constraints | `services/detector/constraints.py` lines 44-46 | Medium — affects ranking/tiered markets only |

---

*Report generated autonomously by polyarb-daily-report scheduled task.*
