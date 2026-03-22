# PolyArb Settlement Monitor Report
**Date:** 2026-03-21 15:02 UTC | **Run #4**

---

## Portfolio Overview

| Metric | Value | Change vs Last Run |
|--------|-------|--------------------|
| Cash | $11,301.71 | +$524.48 |
| Total Value | $10,005.60 | +$53.20 |
| Realized PnL | +$49.03 | +$50.45 (was -$1.42) |
| Unrealized PnL | +$33.57 | +$19.60 |
| Active Positions | 1,158 markets | +187 |

The portfolio has turned a corner — realized PnL is now positive for the first time since the contamination purge. Total value sits just above the $10,000 post-purge starting capital at +0.06%.

---

## Settlement Activity

- **Markets settled (last 24h):** 2,045 (up from 1,628)
- **Total settled (all time):** 2,045
- **Settled trades in portfolio:** 12 (per snapshot)
- **Winning trades:** 1 (per snapshot counter)

Recent settlements are dominated by crypto price thresholds (Ethereum, Bitcoin, Solana, XRP — all resolved "Up" on March 21 8AM ET), weather markets, sports/esports outcomes, and geopolitical event markets (Iran ship targeting — all "No").

---

## Largest Settlements by Position Size

| Market | Outcome | Size |
|--------|---------|------|
| Ethereum above $2,120 on March 21, 2AM ET | Yes | 300.0 |
| Ethereum above $2,500 on March 25 | No | 300.0 |
| NYSE Composite close over 19,350 (Mar 16-20) | Yes | 288.7 |
| S&P 500 close over 6,000 (Mar 16-20) | Yes | 251.0 |
| Total Kills O/U 62.5 Game 2 | Over | 199.3 |
| NVIDIA close above $140 end of March | Yes | 187.2 |

The system's largest settled positions are in crypto thresholds and index/equity markets. These are binary yes/no resolution markets with high notional exposure.

---

## Trading Stats

| Metric | Value |
|--------|-------|
| Total Trades (all time) | 5,914 |
| Markets Traded | 1,480 |
| Total Volume | $29,826.57 |
| First Trade | 2026-03-20 13:46 UTC |
| Last Trade | 2026-03-21 15:01 UTC |

**By side:**

| Side | Count | Avg Entry Price |
|------|-------|-----------------|
| BUY | 1,748 | 0.2835 |
| SELL | 1,813 | 0.6969 |
| SETTLE | 554 | 0.4657 |
| PURGE | 1,799 | 0.4875 |

**Post-purge trades only:** 270 trades (99 BUY, 164 SELL, 7 SETTLE). The system is taking more SELL positions (short high-probability outcomes) than BUYs.

---

## Bug Regression Status

All 6 tracked bugs remain **FIXED**. No regressions detected.

| # | Bug | Status |
|---|-----|--------|
| 1 | estimated_profit double-counts edges | FIXED — uses max() per market + fee subtraction |
| 2 | min_edge too low (0.005) | FIXED — default 0.03, configurable |
| 3 | Conditional pairs return all-ones matrix | FIXED — Frechet bounds + correlation logic |
| 4 | Crypto time-interval misclassification | FIXED — rule-based _check_crypto_time_intervals() |
| 5 | 0% pair verification rate | FIXED — verify_pair() gates pipeline |
| 6 | Position sizing uses inflated edge | FIXED — refactored to half-Kelly with fee-adjusted input |

**Note on Bug #6:** The position sizing code has been refactored since last run. Previously used `profit_ratio = min(net_profit / 0.10, 1.0)`, now uses standard half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)`. Since `net_profit` is already fee-adjusted (Bug #1 fix), the original issue of inflated sizing remains resolved.

No new bugs discovered.

---

## Key Observations & Concerns

1. **Portfolio recovering**: Realized PnL turned positive (+$49.03) for the first time post-purge. Total value is marginally above starting capital.

2. **Winning trades counter still suspicious**: Portfolio snapshot shows 1 winning trade out of 12 settled (8.3%). This is better than 0/4 from last run, but the counter may still be underreporting wins given the positive realized PnL.

3. **Heavy deployment**: $11,302 cash vs $10,006 total value means ~$1,296 is locked in open positions across 1,158 markets. The unrealized PnL on these is only +$33.57, suggesting most positions are near breakeven.

4. **SELL-heavy strategy**: 164 SELLs vs 99 BUYs post-purge. The system is predominantly shorting high-probability outcomes (avg entry 0.6969), which aligns with the arbitrage strategy of selling overpriced certainties.
