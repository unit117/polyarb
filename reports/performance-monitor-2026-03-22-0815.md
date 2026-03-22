# PolyArb Performance Monitor Report
**Run: 2026-03-22 ~08:15 UTC**

---

## Executive Summary

The portfolio sits at **$10,275 total value** (+2.75% since the March 21 purge, from $10,000 initial capital). Realized PnL is **-$4,189**, stabilizing after the steep drop from +$43 to -$4,183 in the previous 12 hours. Unrealized PnL has recovered to **+$98** (was -$82 last run). The system has 609 open positions across 609 unique markets.

Post-purge win rate is **33.3%** (49 wins / 147 settlements). March 21 was 41.4%, March 22 has degraded to 33.3%. The 06:00-12:00 UTC window showed recovery to 42.9% win rate, though the simulation pipeline stalled during 07:00-08:00 UTC (0 simulations from 10,243 opportunities — likely a circuit breaker trip or cash constraint).

**The system is not yet profitable.** The core issue remains misclassified pairs generating phantom edges, compounded by position concentration on losing markets.

---

## Key Metrics

| Metric | Value | Trend |
|--------|-------|-------|
| Total Value | $10,275 | +$175 since purge |
| Cash | $13,324 | — |
| Realized PnL | -$4,189 | Stabilizing (was -$4,183) |
| Unrealized PnL | +$98 | Improved (was -$82) |
| Post-purge Win Rate | 33.3% (49/147) | Down from 30.8% (28/91) — denominator grew |
| Open Positions | 609 | — |
| Pair Verification | 96.4% (14,918/15,479) | Up from 76% |
| Edge Cap Blocks | 1,085 | Effective |

### Trade Volume (Post-Purge)

| Side | Count | Fees | Slippage | Avg Size |
|------|-------|------|----------|----------|
| BUY | 1,087 | $42.05 | $58.28 | 10.72 |
| SELL | 1,633 | $82.32 | $82.03 | 10.05 |
| **Total** | **2,720** | **$124.37** | **$140.31** | — |

Fee drag and slippage are modest relative to estimated profits. These are not the primary loss drivers.

### Performance by Pair Type

| Type | Opps | Simulated | Avg Est | Avg Theo | Est/Theo |
|------|------|-----------|---------|----------|----------|
| implication | 3,546 | 1,076 | 0.068 | 0.164 | 0.41 |
| mutual_exclusion | 2,728 | 225 | 0.018 | 0.040 | 0.45 |
| partition | 167 | 35 | 0.058 | 1.000 | 0.06 |
| conditional | 42,245 | 1 | 0.008 | 0.494 | 0.02 |

Implication pairs dominate simulated volume (1,076 of 1,337 simulated, 80%). Conditional pairs self-suppress through low estimated profit. **Partition pairs are the red flag: avg theo=1.0 means all 167 are likely misclassified** (true partitions rarely have theo=1.0 — that implies one side is priced at 0).

### Settlement by Market Category

| Category | Settlements | W/L | Shares Lost |
|----------|-------------|-----|-------------|
| Weather | 18 | 0W / 18L | 105.8 |
| Election | 12 | 0W / 12L | 91.3 |
| Threshold | 5 | 3W / 2L | 108.3 |
| O/U | 57 | 32W / 25L | 63.1 |
| Crypto | 10 | 1W / 9L | 12.6 |
| Other | 33 | 16W / 17L | varies |

Weather and election markets are 100% loss rate — these are likely from misclassified pairs generating phantom edges that the system confidently bets on.

### Win Rate Trend (6-Hour Windows)

| Window | Settlements | Wins | Win Rate |
|--------|-------------|------|----------|
| Mar 21 12:00-18:00 | 16 | 5 | 31.2% |
| Mar 21 18:00-00:00 | 42 | 19 | **45.2%** |
| Mar 22 00:00-06:00 | 56 | 16 | 28.6% |
| Mar 22 06:00-12:00 | 28 | 12 | **42.9%** |

Win rate oscillates between ~29-45%. The 45% windows suggest the system CAN find profitable trades when it avoids misclassified pair traps.

---

## Root Cause Analysis

### Loss Driver #1: Weather & Election Market Blowups (0% win rate)

Munich weather 16°C (market 130470): 10 settlements, 0 wins, 100.4 shares lost. The system repeatedly bought "Yes" on this market across multiple opportunities. Slovenian election turnout 75% (market 120924): 12 settlements, 0 wins, 91.3 shares lost.

**Root cause:** These markets are paired with other markets in the same event space, misclassified by the LLM. The optimizer then sees phantom edges and the system enters repeatedly due to Bug #17 (position concentration bypass). The circuit breaker's 200-share cap should prevent this but is being bypassed in rapid-fire scenarios.

### Loss Driver #2: Partition Misclassification (Bug #16, #20)

All 167 partition opps post-purge have theo=1.0, and 35 were simulated. Examples:
- "Iran conflict ends by March 31" vs "by June 30" — these are deadline-nested implications, not partitions
- "Villarreal top 4" vs "Real Sociedad top 4" — independent events, not partitions

When the partition constraint is applied, the optimizer computes that the prices should sum to 1.0. If they don't (and they won't, because the constraint is wrong), the optimizer sees a massive phantom edge.

### Loss Driver #3: Stale Misclassified O/U and Esports Pairs (Bug #13, #14)

71 O/U pairs and 52 esports game-winner pairs remain classified as mutual_exclusion. Down from 520 O/U pairs (markets are resolving/expiring), but still generating trades. The edge cap catches the worst cases (>20¢ phantom edges) but moderate phantom edges (10-19¢) still pass through.

### Loss Driver #4: Simulation Pipeline Stall (Bug #19)

The pipeline produced 0 simulations during the 07:00 UTC hour despite 10,243 opportunities. This could indicate the circuit breaker tripped on drawdown (>10% from initial capital) or that cash is exhausted. The portfolio is at $10,275 with $13,324 cash — the drawdown from $10,000 initial is ~-2.75% (portfolio is above initial), so this isn't a drawdown trip. More likely: many opportunities failed VWAP/edge validation or the system was restarting.

---

## Bug Regression Status

| # | Bug | Status | Change |
|---|-----|--------|--------|
| 1-11 | Original classification/sizing bugs | **FIXED** | No regressions |
| 12 | Phantom edges from misclassified ME pairs | **PARTIALLY FIXED** | MAX_EDGE=0.20 cap blocks worst cases |
| 13 | Stale O/U pairs as ME | **OPEN (improving)** | 71 remain (was 520), expiring naturally |
| 14 | Esports game-winner pairs as ME | **OPEN** | 52 remain, no rule added |
| 15 | Conditional est/theo ratio | **LOW RISK** | Self-suppresses: only 1/42,245 simulated |
| 16 | Deadline-nested partition misclassification | **OPEN** | 35 simulated, Iran/Abbas pairs active |
| 17 | Position concentration bypass | **PARTIALLY FIXED** | Circuit breaker has 200 cap but 6 markets exceed it |
| 18 | Win rate deterioration | **OPEN** | 33.3% overall, weather/election 0% |
| 19 | 🆕 Simulation pipeline stall | **OPEN** | 0 sims in 07:00 hour |
| 20 | 🆕 La Liga placement partition misclass | **OPEN** | LLM misclassifies independent placement events |

---

## Recommendations (Priority Order)

1. **Add rule-based handler for deadline-nested pairs** (Bugs #16, #20): Detect "by [date]" patterns and classify as implication (shorter deadline implies longer). This would eliminate the largest category of misclassified partitions. Also add a rule that same-league placement markets are NOT partitions unless they're the same team.

2. **Re-classify stale pairs** (Bug #13): Run a one-time migration to re-classify the 71 O/U + 52 esports pairs through the updated rule-based classifier. Without this, they'll keep generating phantom trades until they expire.

3. **Fix position concentration race condition** (Bug #17): The circuit breaker checks position before execution, but rapid sequential opportunities can stack up. Consider: (a) lowering `max_position_per_market` to 100, (b) adding a per-market semaphore, or (c) checking position AFTER execution and rolling back if exceeded.

4. **Investigate pipeline stall** (Bug #19): Check simulator logs around 07:00 UTC for circuit breaker trips, errors, or resource exhaustion. The 0-simulation hour during active opportunity flow suggests a systemic blockage.

5. **Add market category blacklist**: Weather and election turnout markets have 0% win rate across 30 settlements. Consider either blacklisting these categories or requiring higher confidence thresholds for non-financial markets.
