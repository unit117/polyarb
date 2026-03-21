# PolyArb Daily Report — March 21, 2026

## Portfolio Summary

| Metric | Value |
|---|---|
| **Total Portfolio Value** | $12,328.29 |
| **Cash** | $13,473.35 |
| **Total PnL** | -$2,210.93 |
| **Realized PnL** | -$1,286.46 |
| **Unrealized PnL** | -$924.46 |
| **Open Positions** | 1,471 |

**24h Change** (since Mar 20 13:46 UTC): Portfolio value increased by **+$2,327.97** (from $10,000.33 to $12,328.29). This period covers the bulk of the system's initial trading activity — 2,967 trades were executed during this window.

Note: The portfolio value ($12,328) exceeds cash ($13,473) minus unrealized losses ($924), indicating the system holds significant open positions. The negative realized PnL of -$1,286 reflects settlement losses, primarily from large directional positions that resolved unfavorably.

## Trading Activity

**Today (Mar 21):** 46 trades, all settlements. No new BUY/SELL orders placed today.

**Yesterday (Mar 20):** 454 trades — 7 buys, 7 sells, 440 settlements.

Active trades yesterday were paired arbitrage plays across sports O/U lines and golf Top-N markets, with position sizes of 0.50–1.27 shares, consistent 0.50¢ slippage, and fees averaging ~1% of notional.

**Notable Settlements Today:**

- **Project Hail Mary (Rotten Tomatoes ≥94):** Settled 72.6 shares (No side, entry $0.00) and -40.4 shares (Yes side, entry $1.00) — significant exposure, appears to be a losing settlement on the Yes side.
- **Bitcoin >$68K (Mar 22):** Settled ±69.7 shares — large position, short Yes at $1.00 entry, indicating a loss if BTC resolved above $68K.
- **Israel military action in Beirut (Mar 21):** Settled ±18.7 shares.
- **Devils vs. Capitals:** Settled 8.7 shares on Capitals side.

These large settlements are the primary driver of realized losses.

## Opportunity Analysis

| Metric | Value |
|---|---|
| **Total Opportunities (last 500)** | 500 |
| **Optimized (converged)** | 179 (35.8%) |
| **Simulated** | 174 (34.8%) |
| **Unconverged** | 147 (29.4%) |
| **All Types** | Rebalancing |

**Bregman Gap:** avg 0.0055, converged avg 0.0007, unconverged avg 0.0085.

**Estimated Profit:** avg $0.08 per opportunity, best opportunities at $2.00 (theoretical $1.00). The top-5 opportunities all hit the max estimated profit of ~$2.00 but had unconverged gaps (~0.01), suggesting these edge estimates may not be reliable.

The convergence rate of ~36% indicates the Frank-Wolfe optimizer is finding valid solutions for roughly a third of detected pairs, with another 35% making it to simulation.

## Pair Analysis

| Metric | Value |
|---|---|
| **Total Pairs (API)** | 3,138 (system-wide) / 200 (returned) |
| **Mutual Exclusion** | 168 (84%) |
| **Conditional** | 30 (15%) |
| **Partition** | 2 (1%) |
| **Verified** | 0/200 (0%) |
| **With Opportunities** | 6/200 (3%) |
| **Avg Confidence** | 0.87 |

The zero verification rate and low opportunity yield (3% of pairs) suggest the pair detection is casting a wide net but the optimizer filters aggressively. The dominant dependency type is mutual exclusion (correct scores, ranked outcomes), which is expected for Polymarket's structure.

## System Health

| Component | Status |
|---|---|
| **Live Trading** | Disabled (dry run) |
| **Paper Trading** | Active |
| **Active Markets** | 36,322 |
| **Total Trades (all time)** | 3,455 |
| **Winning Trades** | 12 / 2,969 evaluated |

**Concerns:**

1. **Very low win rate (0.4%):** Only 12 winning trades out of 2,969 is a significant red flag. The system is consistently losing on settlements, suggesting the arbitrage edges detected are not translating to profitable trades after fees and slippage.

2. **No new trades today:** The system has only processed settlements today with zero new positions opened. This could indicate the detector/optimizer pipeline has stalled, or that no opportunities met execution thresholds.

3. **Large concentrated positions:** The Bitcoin and Project Hail Mary settlements involved 40–73 share positions, far exceeding the typical 0.5–1.3 share size of active trades. These appear to be inherited or accumulated positions that dominate PnL.

4. **Zero pair verification:** None of the 200 returned pairs are verified, which means the system is trading on unverified relationship assumptions.

5. **Portfolio math:** Starting capital was $10,000. Current value is $12,328 (+23.3%), but this is driven by unrealized positions that currently show -$924 in mark-to-market losses. Realized losses of -$1,286 suggest the settlement trend is negative.

---

*Report generated automatically at 2026-03-21 ~08:45 UTC. Data sourced from PolyArb dashboard API at $NAS_HOST:8081.*
