# PolyArb Constraint Audit — 2026-03-21

## Summary

**3 issues flagged, 1 critical.** The system has structural classification problems with crypto time-window markets and a very low solver convergence rate.

---

## 1. Pair Classification Audit

**3,138 total pairs** (500 sampled). Breakdown: 414 mutual_exclusion, 82 conditional, 4 partition.

### CRITICAL — Crypto Up/Down time-window pairs misclassified as `mutual_exclusion` (23 pairs)

Markets like "Bitcoin Up or Down — March 21, 3:15AM-3:30AM ET" vs "Bitcoin Up or Down — March 21, 3:30AM-3:45AM ET" are classified as `mutual_exclusion`. These cover **non-overlapping time windows** and are actually **independent events** — Bitcoin going up in one 15-minute window does not preclude it going up in the next. The same asset being tracked (BTC, BNB, DOGE, Hyperliquid) across adjacent time slots does not make the outcomes mutually exclusive. 16 of these 23 pairs have active opportunities, meaning the constraint solver is operating on incorrect constraints.

Identical-looking crypto pairs are inconsistently split between `mutual_exclusion` and `conditional` — e.g., pairs of adjacent BNB time windows appear as both types. The classifier is not stable on these.

### WARN — Partition pairs with identical question text (2 pairs)

Pairs 3127 and 3128 both map "Map 1: Odd/Even Total Kills?" to another market with the same question text but different market IDs (120387→134902 and 119927→134902). These look like duplicate markets on different matches rather than a true partition. Pair 2681 ("Over $8M committed" vs "Over $1M committed") is a valid conditional/implication, not a partition — $8M committed implies $1M committed, but not vice versa.

### OK — Core mutual_exclusion pairs

Exact score markets (e.g., Toulouse 1-1 vs Toulouse 1-0), richest-person rankings, and top-scorer markets are correctly classified as mutual_exclusion. Conditional pairs like "Celtics win Conference Finals" → "Celtics win Atlantic Division" are logically sound.

---

## 2. Confidence Check

No pairs below 0.7 confidence. Minimum confidence is 0.70, maximum 1.00. **No issues here.**

---

## 3. Unverified Pairs with Active Opportunities

**All 500 sampled pairs are unverified** (verified=0), and 246 of them have active opportunities. The verification pipeline appears to be non-functional or not yet implemented. This means the system is trading entirely on auto-classified pairs with no human or secondary validation.

---

## 4. Opportunity Convergence

**Convergence rate is low: 35.8%** (179 optimized out of 500 sampled). 29.4% (147) are unconverged, and 34.8% (174) are in simulated status.

| Metric | Unconverged | Optimized |
|---|---|---|
| Avg Bregman gap | 0.008511 | 0.000723 |
| Max Bregman gap | 0.018421 | 0.000991 |

The unconverged average gap of ~0.0085 is about 12× the optimized average, and all opportunities hit the 200-iteration FW cap (avg 163 iterations). The solver may benefit from a higher iteration budget or better initialization, especially for the misclassified crypto pairs which are likely poisoning the constraint matrix.

All 500 sampled opportunities are type `rebalancing` with very low theoretical profit (avg $0.047, max $1.00).

---

## 5. Stale Pairs

254 of 500 sampled pairs have zero opportunities. Given the dataset was fetched with `limit=500` (likely most recent), many of these are newly detected pairs that haven't been processed yet. No obvious staleness issue — this looks normal for a rolling detection window.

---

## Portfolio Health (context)

Live trading is **disabled** (dry_run mode). Current portfolio: $12,343 total value on $13,687 cash, with **-$2,080 total PnL** (10 winning trades out of 2,969). The poor PnL may be partly attributable to the constraint issues above.

---

## Recommended Actions

1. **Fix crypto time-window classifier**: Non-overlapping time windows on the same asset should be classified as `independent` (or a new `temporal_sequence` type), not `mutual_exclusion`. Overlapping windows (e.g., 5:15-5:30 vs 5:25-5:30) have a valid conditional relationship.
2. **Audit partition classification**: Review the Odd/Even and threshold-style pairs; most look like they should be `conditional` or `implication`.
3. **Implement or enable pair verification**: 0% verification rate with active trading is high-risk.
4. **Increase FW iteration budget** or improve warm-starting for the solver — 35.8% convergence is low.
