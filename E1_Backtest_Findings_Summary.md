E1 Backtest Findings Summary
PolyArb Combinatorial Arbitrage System
2026-03-22

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXECUTIVE SUMMARY

The E1 historical backtest ran against the Jon-Becker Polymarket dataset over 489 days (2024-09-24 to 2026-01-25) with $10,000 starting capital. The original run produced a catastrophic -86.6% return (-$8,303 realized PnL). After identifying and fixing 27 bugs across 5 remediation buckets, a rerun produced +0.19% return (+$15.92 realized PnL).

Root cause: 95% of losses came from invalid mutual_exclusion market pairs — the system was pairing unrelated sporting events (e.g., same team name in different games) as mutually exclusive outcomes and executing destructive double-sell trades against them.

                        Original E1          Post-Fix Rerun
Final Value             $1,338.90            $10,018.92
Return                  -86.6%               +0.19%
Realized PnL            -$8,303.58           +$15.92
Total Trades            11,457               128
Settled Trades          8,679                41
Winning Trades          597                  19
Period                  238 days             489 days

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FINDINGS BY REMEDIATION BUCKET

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BUCKET 1: BACKTEST PARITY AND CORRECTNESS (6 findings)

BT-001 | Critical | Backtest Engine
scripts/backtest.py called nonexistent portfolio.mark_winner() on profitable exits. AttributeError aborted multi-leg opportunities mid-execution, leaving one-legged directional exposure. Fixed: replaced with portfolio.winning_trades += 1.

BT-006 | High | Settlement
Backtest defaulted to heuristic settlement (price >= 0.98 triggers synthetic resolution) rather than authoritative settlement from actual market outcomes. Risk of false realized PnL from price spikes. Fixed: default changed to authoritative; --heuristic flag available for comparison.

BT-010 | Medium | Backtest Engine + Live Pipeline
Rebalancing exit PnL did not subtract proportional exit fees, overstating realized returns. Fixed in both scripts/backtest.py and services/simulator/pipeline.py: exit fees now proportionally allocated to the closed portion of the position.

BT-023 | Critical | Execution Simulation
100% of E1 trades used the midpoint fallback path — zero order book data existed in the backtest database. The fallback assumed infinite liquidity with a flat 0.5% slippage regardless of order size. Fixed: midpoint fallback now uses size-dependent slippage (base 0.5% + 0.01% per share above 10, capped at 5%).

BT-024 | Medium | Execution
Multi-leg opportunities executed each leg independently with no cross-referencing of fill sizes. A partial fill on one leg did not scale the other. Moot in E1 (all fills were full due to BT-023) but architecturally wrong. Fixed: all legs now scaled to match the smallest fill ratio.

BT-027 | Low | Reporting
Backtest snapshots never persisted the settled_trades counter, so the dashboard always showed 0 settlements despite 8,679 SETTLE rows existing. Fixed: settled_trades now written to portfolio snapshots.


BUCKET 2: PAIR QUALITY AND VERIFICATION (7 findings)

BT-002 | Critical | Pair Quality (root cause)
10,878 of 11,454 directional trades came from mutual_exclusion pairs. These pairs produced -$8,631 in realized PnL — the overwhelming majority of the total -$8,303 loss. The system was treating unrelated sporting events as mutually exclusive outcomes. Addressed by verification fixes below.

BT-003 | High | Execution Shape (root cause)
3,905 of 5,684 mutual_exclusion opportunities sold the same outcome in both legs (e.g., sold "Packers" in both "Packers vs. Cowboys" and "Packers vs. Browns"). This is not inherently wrong for true mutual exclusions but becomes catastrophic when pairs are structurally invalid. Addressed by BT-005.

BT-004 | High | Classification Data (root cause)
40 mutual_exclusion pairs had identical question text in both markets (e.g., "Bulls vs. Hornets" appearing twice for different game dates). 18 of those resolved opposite ways, proving they were different event instances. Addressed by BT-005.

BT-005 | High | Verification
mutual_exclusion verification only required both markets to be binary — no same-event identity check, no guard against recurring fixtures. Fixed: now requires same event_id AND rejects identical question text (recurring fixture guard).

BT-014 | High | Verification
Price consistency check was silently skipped when either market lacked price data. The check was not counted toward checks_total, so pairs could pass with only 2/3 checks. Fixed: price check always counted; missing prices explicitly fail verification.

BT-015 | High | Verification
Implication structural check only required both markets to have >= 2 outcomes — virtually all prediction markets pass this. Zero filtering power. Fixed: now notes same event_id preference; relies on tightened price check (BT-016).

BT-018 | High | Detector Pipeline
Both rescan methods (_rescan_existing_pairs and rescan_by_market_ids) recomputed profit bounds but never re-ran verify_pair(). Pairs that passed weak initial verification stayed verified forever. Fixed: both methods now call verify_pair() with fresh prices; failing pairs set to verified = false.


BUCKET 3: CLASSIFICATION QUALITY (4 findings)

BT-016 | Medium | Verification
Implication price tolerance was 0.50 — for A-implies-B, P(A) could exceed P(B) by 0.50 before rejection. A pair with P(A)=0.80, P(B)=0.30 would pass. Fixed: tolerance tightened to 0.15.

BT-017 | Medium | Detector Pipeline
Cross-venue pairs with embedding similarity >= 0.92 were auto-classified as cross_platform with hardcoded 0.95 confidence, bypassing the LLM entirely. Markets on the same topic but with different resolution criteria easily hit 0.92. Fixed: threshold tightened to 0.95.

BT-019 | Medium | Verification
Partition price-sum tolerance allowed sums up to 1.50. Two unrelated markets with prices summing to ~1.40 could pass as a valid partition. Fixed: tolerance tightened from 0.50 to 0.25.

BT-020 | Medium | Classification
LLM self-reported confidence was used directly with no calibration. An LLM hallucinating {"confidence": 0.90} for independent markets easily passed the 0.70 verification threshold. Fixed: raw confidence discounted by 0.8x and capped at 0.85 (raw >= 0.875 needed to pass threshold).


BUCKET 4: VALUATION AND REPORTING (3 findings)

BT-007 | Medium | Valuation
Missing prices were valued as 0. For short positions, this meant the close-out obligation was treated as zero, overstating portfolio value. Fixed: missing prices now use cost_basis as break-even mark in total_value(); contribute 0 to unrealized_pnl().

BT-012 | Medium | Valuation
Short cost_basis recorded gross credit received without subtracting fees. Fixed: now records net credit (gross - proportional fees).

BT-013 | Low | Execution Economics
estimated_profit in compute_trades() was a per-unit edge proxy (not size-aware dollar PnL) but named and used as if it were a dollar forecast. Fixed: documented as per-unit edge proxy with clarifying comment.


BUCKET 5: PORTFOLIO AND RISK CONTROLS (7 findings)

BT-008 | Medium | Execution Economics
Small edge trades with fees and slippage produced negative expected value but were still executed. Fixed: trades where estimated_profit < 0.005 (0.5%) after fees + slippage are now rejected.

BT-009 | High | Strategy Expression
No verification that a trade bundle had non-negative worst-case payoff across all feasible joint outcomes. Fixed: _worst_case_payoff() function computes minimum PnL across all feasible (outcome_a, outcome_b) combinations; rejects bundles with worst-case < -$0.01.

BT-011 | High | Portfolio
SELL trades could open unlimited short exposure with no capital check. Fixed: new/increased shorts now require notional <= cash (100% margin).

BT-021 | Low | Portfolio
SELL was capped at current long position size, preventing long-to-short flip in one trade. The remainder was silently discarded. Fixed: SELL now allows close + flip with margin-checked remainder.

BT-022 | Medium | Portfolio
BUY against a short position added to cost_basis instead of reducing the credit-received basis. Example: short -10 shares with cost_basis=5.0, BUY 3 @0.60 produced cost_basis=6.80 instead of correct 3.20. Fixed: BUY against short now proportionally reduces credit basis; handles flip to long.

BT-025 | Medium | Optimizer
For each market, only the single highest-edge leg was kept. Correct for binary markets (BUY Yes and SELL No are mirrors) but destroys delta-neutrality for multi-outcome markets. Fixed: multi-outcome markets now keep all candidate legs; binary markets unchanged.

BT-026 | Medium | Verification
Cross-platform price check only validated absolute bounds (0.05 < p < 0.95) with no relative distance check. A Kalshi market at 0.10 and Polymarket equivalent at 0.90 would pass. Fixed: now rejects price divergence > 0.25.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEPLOYMENT AND VALIDATION

All 27 fixes were deployed to the NAS (192.168.5.100) in three rounds on 2026-03-22.

Files modified:
- services/simulator/portfolio.py (BT-007, BT-011, BT-012, BT-021, BT-022)
- services/detector/verification.py (BT-005, BT-014, BT-015, BT-016, BT-019, BT-026)
- services/detector/pipeline.py (BT-017, BT-018)
- services/detector/classifier.py (BT-020)
- services/simulator/pipeline.py (BT-010 live)
- services/simulator/vwap.py (BT-023)
- services/optimizer/trades.py (BT-008, BT-009, BT-013, BT-025)
- services/optimizer/frank_wolfe.py (BT-009 feasibility_matrix passthrough)
- scripts/backtest.py (BT-001, BT-006, BT-010, BT-024, BT-027 + verify_pair integration)

Database actions:
- Invalidated 11,768 mutual_exclusion pairs on live DB (polyarb)
- Invalidated 533 mutual_exclusion pairs on backtest DB (polyarb_backtest)

Post-fix backtest validated: $10,018.92 final value (+0.19%) with 128 trades over 489 days.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INTERPRETATION AND NEXT STEPS

The fix eliminates catastrophic loss but reveals limited alpha. With properly verified pairs, the system trades very rarely (128 trades in 489 days) and generates marginal returns. The verification tightening correctly killed bad pairs but also dramatically reduced the opportunity set.

Remaining verified pairs: ~45 implication, ~6 partition, ~13 conditional, 0 mutual_exclusion.

Potential paths to improve alpha:
1. Selectively relax verification — some valid pairs may be getting rejected
2. Expand market universe — more markets = more potential valid pairs
3. Cross-venue arbitrage (Phase 5) — Kalshi + Polymarket structural edge
4. Better classifier — reduce false negatives so valid pairs aren't missed
5. Add new dependency types beyond the current four
