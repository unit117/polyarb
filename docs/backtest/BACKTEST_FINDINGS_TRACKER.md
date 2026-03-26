# Backtest Findings Tracker

Last updated: 2026-03-22 (All 27 findings fixed, post-fix backtest: -86.6% → +0.19%)

Scope:
- E1 historical backtest
- Dashboard: `http://192.168.5.100:8082`
- Database: `polyarb_backtest`

Purpose:
- Keep one living list of backtest-specific findings
- Separate confirmed failures from hypotheses
- Batch remediation later instead of fixing piecemeal

Status legend:
- `Confirmed`: verified from code and/or DB
- `Confirmed-Code`: verified in code, contribution to the observed loss not yet quantified
- `Hypothesis`: plausible, needs measurement

## Current Snapshot

### Post-fix rerun (2026-03-22)

After all 27 fixes applied + pair invalidation + backtest verification integration:
- `final_value`: `$10,018.92` (+0.19% over 489 days)
- `realized_pnl`: `+$15.92`
- `total_trades`: `128`
- `settled_trades`: `41`
- `winning_trades`: `19`

### Original E1 (pre-fix)

Direct DB check on 2026-03-22:
- `paper_trades`: 20,133 rows from 2025-06-20 23:59:59 UTC to 2026-01-24 23:59:59 UTC
- Latest `portfolio_snapshots` row at 2026-01-24 23:59:59 UTC:
  - cash: `$2,798.28`
  - total value: `$1,338.90`
  - realized PnL: `-$8,303.58`
  - unrealized PnL: `+$3.06`
  - total trades: `11,457`

Directional trade mix:
- `BUY`: 246 trades, about 1,647 shares, about `$807.63` net cash outflow
- `SELL`: 11,208 trades, about 116,411 shares, about `$68,931.70` net cash inflow
- `SETTLE`: 8,679 rows, about 114,667 shares, about `$76,308.99` gross settlement value

Approximate realized PnL by dependency type on resolved directional trades:
- `mutual_exclusion`: about `-$8,631.37`
- `implication`: about `-$238.35`
- `partition`: about `-$232.15`

Bottom line:
- The original loss was overwhelmingly a `mutual_exclusion` problem, not a fee-only problem.
- All 27 fixes eliminated the loss: -86.6% → +0.19%.

## Summary Table

| ID | Status | Severity | Area | Finding |
|---|---|---|---|---|
| BT-001 | **Fixed** | Critical | Backtest engine | `scripts/backtest.py` called missing `portfolio.mark_winner()` → `winning_trades += 1` |
| BT-002 | **Fixed** (via BT-005) | Critical | Pair quality | Invalid `mutual_exclusion` pairs dominate E1 losses |
| BT-003 | **Fixed** (via BT-005) | High | Execution shape | Wrong `mutual_exclusion` pairs naturally produce destructive double-sell trades |
| BT-004 | **Fixed** (via BT-005) | High | Classification data | Some `mutual_exclusion` pairs use identical question text across different events |
| BT-005 | **Fixed** | High | Verification | `mutual_exclusion` verification now rejects different event_ids and identical questions |
| BT-006 | **Fixed** | High | Settlement | Backtest default changed to authoritative settlement; `--heuristic` flag for old behavior |
| BT-007 | **Fixed** | Medium | Valuation | Missing prices now use cost_basis as break-even mark instead of 0 |
| BT-008 | **Fixed** | Medium | Execution economics | Trades below 0.5% net edge after fees+slippage now rejected |
| BT-009 | **Fixed** | High | Strategy expression | Payout proof now rejects trades with negative worst-case payoff across feasible outcomes |
| BT-010 | **Fixed** | Medium | Backtest engine | Rebalancing exit PnL now subtracts proportional exit fees |
| BT-011 | **Fixed** | High | Portfolio | SELL trades now require margin (notional ≤ cash) for new/increased shorts |
| BT-012 | **Fixed** | Medium | Valuation | Short `cost_basis` now records net credit (gross - fees) |
| BT-013 | **Fixed** | Low | Execution economics | `estimated_profit` clarified as per-unit edge proxy with doc comment |
| BT-014 | **Fixed** | High | Verification | Price check now always counted; missing prices fail verification |
| BT-015 | **Fixed** | High | Verification | Implication structural check now prefers same event_id; relies on tightened price check |
| BT-016 | **Fixed** | Medium | Verification | Implication price tolerance tightened from 0.50 to 0.15 |
| BT-017 | **Fixed** | Medium | Detector pipeline | Cross-venue auto-classification threshold tightened from 0.92 to 0.95 |
| BT-018 | **Fixed** | High | Detector pipeline | Both rescan methods now re-verify pairs with fresh prices |
| BT-019 | **Fixed** | Medium | Verification | Partition price-sum tolerance tightened from 0.50 to 0.25 |
| BT-020 | **Fixed** | Medium | Classification | LLM confidence now discounted 0.8x and capped at 0.85 |
| BT-021 | **Fixed** | Low | Portfolio | SELL now allows long-to-short flip with remainder (margin-checked) |
| BT-022 | **Fixed** | Medium | Portfolio | BUY against short now correctly reduces credit-received cost_basis |
| BT-023 | **Fixed** | Critical | Execution | Midpoint fallback now uses size-dependent slippage instead of flat 0.5% |
| BT-024 | **Fixed** | Medium | Execution | Backtest now scales all legs to match the smallest fill ratio |
| BT-025 | **Fixed** | Medium | Optimizer | Multi-outcome markets now keep all legs; binary markets still single-best-leg |
| BT-026 | **Fixed** | Medium | Verification | Cross-platform price check now rejects divergence > 0.25 |
| BT-027 | **Fixed** | Low | Reporting | Backtest snapshots now persist `settled_trades` |

## Detailed Findings

### BT-001: Profitable rebalancing exits can crash `simulate_opportunity`

Status: `Confirmed`

Evidence:
- `scripts/backtest.py:267` calls `portfolio.mark_winner()`
- `services/simulator/portfolio.py:145` defines `mark_settled(is_winner: bool = False)` and does not define `mark_winner()`
- The exception is caught outside the per-opportunity call in `scripts/backtest.py:536-545`, not inside the per-leg loop

Mechanism:
1. `execute_trade()` mutates the portfolio
2. Exit PnL is computed
3. If `realized > 0`, the code calls nonexistent `portfolio.mark_winner()`
4. `AttributeError` aborts `simulate_opportunity()`
5. Remaining legs of the opportunity do not run

Why it matters:
- A multi-leg opportunity can become a one-legged exposure
- The failure is asymmetric: it only triggers on profitable exits
- The code does not roll back the already-mutated in-memory portfolio state for the leg that succeeded before the exception

Minimal fix:

```python
# scripts/backtest.py
portfolio.mark_settled(is_winner=True)
```

Notes:
- This is a real backtest-only bug.
- Contribution to the observed `-$8.3k` has not been quantified yet.

### BT-002: E1 losses are overwhelmingly from bad `mutual_exclusion` trades

Status: `Confirmed`

Evidence from `polyarb_backtest`:
- `10,878` of `11,454` directional trades came from `mutual_exclusion`
- Approximate realized PnL by type on resolved directional trades:
  - `mutual_exclusion`: about `-$8,631.37`
  - `implication`: about `-$238.35`
  - `partition`: about `-$232.15`

Observed trade shape:
- The backtest was mostly a giant short book, not balanced cross-market hedging
- It executed `11,208` SELLs versus only `246` BUYs

Implication:
- The main question is not "why were fees high?"
- The main question is "why did the system think these were real mutual exclusions?"

### BT-003: Wrong `mutual_exclusion` pairs naturally produce destructive double-sell trades

Status: `Confirmed`

Evidence:
- `5,684` simulated `mutual_exclusion` opportunities
- `3,905` of them sold the same outcome in both legs
- Resolved subset of those opportunities produced about `-$5,370.28` approximate realized PnL

Examples from `optimal_trades`:
- `pair_id=472`: sold `Packers` in both `Packers vs. Cowboys` and `Packers vs. Browns`
- `pair_id=395`: sold `Rangers` in two separate `Rangers vs. Padres` markets
- `pair_id=563`: sold `Orioles` / `Red Sox` across two separate baseball markets treated as mutually exclusive

Important nuance:
- "Sell the same outcome in both legs" is not inherently wrong for a true mutual exclusion.
- It becomes catastrophic when the pair is structurally wrong.

### BT-004: Some `mutual_exclusion` pairs are clearly different events with the same question text

Status: `Confirmed`

Evidence:
- `40` `mutual_exclusion` pairs have `market_a.question = market_b.question`
- `18` of those already resolved opposite ways, proving they were different event instances, not the same event

Examples:
- `Bulls vs. Hornets`: one resolved `Hornets`, the other `Bulls`
- `Mariners vs. Orioles`: one resolved `Mariners`, the other `Orioles`
- `Rangers vs. Padres`: one resolved `Rangers`, the other `Padres`

Why it matters:
- The pairing pipeline appears willing to treat question text similarity as same-event identity
- For recurring sports matchups, that is not safe

### BT-005: `mutual_exclusion` verification is too weak

Status: `Confirmed`

Code evidence:
- `services/detector/verification.py:94-101`
  - structural check for `mutual_exclusion` only requires both markets to be binary
- `services/detector/verification.py:188-197`
  - price check only rejects pairs when `P(A) + P(B) > 1.20`

What is missing:
- Same-event identity check
- Guard against recurring sports fixtures with identical text
- Guard against same team appearing across unrelated games
- More specific structural checks for market type and event metadata

Additional weaknesses found in other dependency types (see BT-014 through BT-016, BT-019):
- `implication` structural check (`verification.py:103-109`) passes all binary markets — zero filtering
- `implication` price check (`verification.py:179-185`) allows P(A) to exceed P(B) by 0.50
- `partition` structural check (`verification.py:88-90`) auto-passes if either market has >2 outcomes
- `partition` price-sum check (`verification.py:167-177`) allows sums up to 1.50
- `conditional` structural check (`verification.py:111-121`) returns `True` unconditionally for non-binary pairs
- `conditional` price check (`verification.py:199-206`) only checks prices are in (0,1) — vacuous

Observed consequence:
- Bad sports and esports pairs remained `verified = true` with high confidence and were traded heavily

### BT-006: Default backtest settlement mode is heuristic, not authoritative

Status: `Confirmed-Code`

Code evidence:
- `scripts/backtest.py:298-306`
- `scripts/backtest.py:324-345`
- Default mode uses `RESOLUTION_THRESHOLD = 0.98`

Risk:
- A price spike to `0.98` can trigger a synthetic settlement before the market actually resolves
- That can create false realized PnL and early exits

Important caveat:
- This is a confirmed code path, but the exact E1 run configuration is unknown from the dashboard alone
- If the run used `--authoritative`, this item did not contribute
- If it used default heuristic mode, this is a real contamination source

### BT-007: Missing prices are valued as zero, which distorts short exposure

Status: `Confirmed-Code`

Code evidence:
- `services/simulator/portfolio.py:151-158`
- `services/simulator/portfolio.py:160-173`
- `snapshot_portfolio()` only populates `current_prices` for keys that actually have a snapshot value: `scripts/backtest.py:384-403`

Mechanism:
- `total_value()` uses `current_prices.get(key, 0)`
- For a short position, missing price means the close-out obligation is treated as zero
- That overstates portfolio value and understates current risk until settlement

Impact:
- Distorts snapshots and dashboard interpretation
- Does not explain the full realized loss by itself
- Makes the eventual loss look more sudden than it really is

### BT-008: Small edge sizing plus fees/slippage is probably a drag, but not the main failure

Status: `Hypothesis`

Claude finding:
- Backtest sizes trades as `edge * max_position_size`
- Example: a `0.05` edge with `$100` max position becomes `5` shares

Code evidence:
- `scripts/backtest.py:229`

Why this stays lower priority:
- Total `mutual_exclusion` fees were about `$360.84`
- Estimated slippage cost was about `$569.47`
- Combined execution drag is meaningful, but still far smaller than the `~$8.6k` `mutual_exclusion` loss

Working conclusion:
- This may be worth tightening later, especially for marginal edges
- It is not the primary explanation for E1 blowing up

### BT-009: E1 is expressing opportunities as rebalancing trades, and in practice that became a giant short book

Status: `Confirmed`

Code evidence:
- `scripts/backtest.py:117` creates opportunities with `type="rebalancing"`
- `services/optimizer/trades.py` computes trades from `edge = fair_price - market_price`
- `services/optimizer/trades.py` keeps only the single best leg per market, then emits `BUY` if the edge is positive and `SELL` if negative

DB evidence from `polyarb_backtest`:
- All `13,718` opportunities are type `rebalancing`
- Trade mix is extremely skewed:
  - `BUY`: `246`
  - `SELL`: `11,208`
- Among simulated 2-leg opportunities:
  - `SELL/SELL`: `5,201`
  - `SELL/BUY`: `102`
  - `BUY/BUY`: `27`

Resolved SELL-trade outcome distribution:

| Result | Trades | Avg Entry | PnL After Fees |
|---|---:|---:|---:|
| Sold the winner | 6,975 | 0.6902 | -$24,152.82 |
| Sold the loser | 4,115 | 0.3886 | +$15,866.59 |
| Net | 11,090 | — | -$8,286.23 |

Interpretation:
- The strategy is not constructing an explicit resolution-invariant payout proof at execution time
- It is trading toward Frank-Wolfe "fair prices"
- When the pair is truly valid, that may still be acceptable as a compact expression of arbitrage
- When the pair is wrong, this is just directional relative-value betting, and the book becomes mostly short risk

Important caveat:
- `SELL/SELL` is not automatically wrong. It can be the right expression for a genuine mutual exclusion relation.
- The E1 failure is that this rebalancing expression was applied to structurally invalid pairs, so the portfolio behaved like a massive short book rather than a hedged arb book.

Follow-up question for later:
- Do we want the optimizer to continue outputting "rebalancing" trade bundles, or do we want a stricter execution layer that proves outcome-by-outcome non-negative payoff before simulation?

### BT-010: Rebalancing exit PnL ignores fees

Status: `Confirmed-Code`

Code evidence:
- `scripts/backtest.py:258-265`

Mechanism:
- When a rebalancing opportunity is exited (price moved past entry), the realized PnL is computed as `exit_value - entry_cost`
- Fees paid at entry and exit are not subtracted
- This overstates `realized_pnl` in portfolio snapshots

Impact:
- Dashboard `realized_pnl` metric is optimistic
- Does not change actual cash flows or total_value, only the reported realized PnL breakdown

### BT-011: SELL trades open unbounded short with no capital check

Status: `Confirmed-Code`

Code evidence:
- `services/simulator/portfolio.py:57,73`

Mechanism:
- Selling into a new position creates an uncapped short exposure
- No margin requirement or capital validation
- When settlement hits (outcome wins), the full notional is debited from cash
- Cash can go negative, producing unrealistic portfolio states

Impact:
- Enables portfolio states that would be impossible in real trading
- Amplifies losses from bad pairs — the system can keep shorting even when undercapitalized

### BT-012: Short `cost_basis` is pre-fee, inflating unrealized PnL

Status: `Confirmed-Code`

Code evidence:
- `services/simulator/portfolio.py:74` — `cost_basis` set to raw entry price
- `services/simulator/portfolio.py:166-172` — `unrealized_pnl()` uses `cost_basis` directly for short PnL

Mechanism:
- Short position `cost_basis` records the entry credit without subtracting fees
- `unrealized_pnl()` uses that credit basis directly
- All open short positions have slightly overstated unrealized PnL throughout their lifetime

Impact:
- Dashboard unrealized PnL is overstated for open shorts
- `total_value` itself is not computed from `cost_basis`, so this does not directly overstate `total_value`
- Does not affect realized PnL or actual settlement cash flows

### BT-013: `estimated_profit` is a per-unit edge proxy, not a size-aware total PnL forecast

Status: `Confirmed-Code`

Code evidence:
- `services/optimizer/trades.py:95-114` computes `raw_edge`, fees, and slippage without multiplying by trade size
- `services/simulator/pipeline.py:116-148` then uses that `estimated_profit` field as the scalar input to sizing logic

Mechanism:
- `compute_trades()` is returning a per-unit edge-style profitability proxy, not a size-aware dollar forecast
- That value is later treated as a generic "estimated profit" throughout the system
- The naming makes it easy to compare or display it as if it were realized dollars per opportunity

Impact:
- Low direct impact on E1 mechanics because the model is mostly linear under midpoint fallback (BT-023)
- Still a reporting and model-interpretation issue: dashboards and downstream logic can treat a unit-edge proxy like a dollar forecast
- Worth clarifying before using `estimated_profit` for tighter risk sizing or model evaluation

### BT-014: Verification price check silently skipped when prices are missing

Status: `Confirmed-Code`

Code evidence:
- `services/detector/verification.py:49-56`

Mechanism:
- Price consistency check (Check 3) is gated by `if prices_a and prices_b:`
- When either market has no price snapshot, the check is not counted toward `checks_total`
- Pair only needs 2/2 checks instead of 2/3
- The price check is the strongest empirical guard against misclassification

Impact:
- Newly ingested markets or markets with stale/evicted price data bypass the most important verification check
- Combined with BT-018 (rescans never re-verify), pairs that passed without a price check stay verified forever

### BT-015: Implication structural check is vacuous

Status: `Confirmed-Code`

Code evidence:
- `services/detector/verification.py:103-109`

Mechanism:
- Structural check for `implication` only requires `len(outcomes_a) >= 2 and len(outcomes_b) >= 2`
- Virtually all prediction markets are binary (Yes/No)
- This check passes for every market pair — zero filtering power

Impact:
- Any pair the LLM labels as `implication` with confidence >= 0.70 passes verification
- The structural check provides no defense against LLM hallucination for this type

### BT-016: Implication price check tolerance of 0.50 effectively disables it

Status: `Confirmed-Code`

Code evidence:
- `services/detector/verification.py:179-185`

Mechanism:
- For A-implies-B, P(A) should be <= P(B)
- The check only rejects when `P(A) > P(B) + 0.50`
- A pair with P(A)=0.80, P(B)=0.30 passes — this is evidence of misclassification, not an arb

Impact:
- Only the most extreme price violations are caught
- For the E1 backtest, `implication` losses were `-$238.35` so this was not a major contributor, but it's a correctness issue

### BT-017: Cross-venue auto-classification bypasses LLM at similarity >= 0.92

Status: `Confirmed-Code`

Code evidence:
- `services/detector/pipeline.py:244-249`

Mechanism:
- Cross-venue pairs with embedding similarity >= 0.92 are auto-classified as `cross_platform` with hardcoded 0.95 confidence
- Skips the LLM and all rule-based heuristics
- Two markets on the same topic but with different resolution criteria (different dates, thresholds) easily hit 0.92

Impact:
- Primarily a risk for cross-venue arb (Kalshi + Polymarket)
- Not a major E1 contributor since E1 was single-venue, but a latent bug for Phase 5 cross-platform trading

### BT-018: Rescans never re-verify pairs

Status: `Confirmed-Code`

Code evidence:
- `services/detector/pipeline.py:340-429` — `_rescan_existing_pairs()`
- `services/detector/pipeline.py:431-592` — `rescan_by_market_ids()`

Mechanism:
- Both rescan methods recompute the profit bound but never re-run `verify_pair()`
- A pair that passed verification only because the price check was skipped (BT-014) stays verified forever
- Even when fresh prices would reject the pair, it remains `verified = true`

Impact:
- Critical amplifier for BT-014
- Means even if verification is fixed, all existing bad pairs in the DB remain active until explicitly invalidated
- A DB rebuild or pair invalidation sweep is required alongside any verification fix

### BT-019: Partition price-sum check allows sums up to 1.50

Status: `Confirmed-Code`

Code evidence:
- `services/detector/verification.py:167-177`

Mechanism:
- Outer tolerance is 0.20 — sums outside `[0.80, 1.20]` trigger a secondary check
- Inner check rejects only when `abs(total - 1.0) > 0.50` — sums up to 1.50 pass
- Two unrelated markets with prices summing to ~1.40 pass as a valid partition

Impact:
- Partition losses in E1 were `-$232.15`, so this was not a major contributor
- Still a correctness issue that would matter at higher trade volume

### BT-020: LLM self-reported confidence used directly with no calibration

Status: `Confirmed-Code`

Code evidence:
- `services/detector/classifier.py:506-565`

Mechanism:
- `classify_llm()` returns whatever the LLM says, including its self-reported `confidence` field
- That raw number is used as the pair's confidence score throughout the pipeline
- No calibration, no second opinion, no domain-specific validation
- An LLM hallucinating `{"dependency_type": "mutual_exclusion", "confidence": 0.90}` for independent markets passes the 0.70 verification threshold

Impact:
- The LLM is the sole gatekeeper for ambiguous pairs
- Combined with weak structural/price checks (BT-005, BT-014-016), a confident LLM error has almost no backstop

### BT-021: SELL capped at current long size, preventing long-to-short flip in one trade

Status: `Confirmed-Code`

Code evidence:
- `services/simulator/portfolio.py:56-57`
- `sell_size = min(size_d, current) if current > 0 else size_d`

Mechanism:
- When a position is long (`current > 0`), a SELL is capped at the current position size
- The remainder that would flip the position to short is silently discarded
- This means a rebalancing trade that wants to reverse direction gets truncated to a flat close

Impact:
- Low in E1: 98% of trades were SELLs opening new shorts (no prior long position to flip)
- The cap almost never fires in practice because the same outcome is rarely bought then sold
- Architecturally wrong but not a material contributor to E1 losses

### BT-022: BUY against short position corrupts `cost_basis`

Status: `Confirmed-Code`

Code evidence:
- `services/simulator/portfolio.py:41-53`
- BUY path: `self.cost_basis[key] = self.cost_basis.get(key, Decimal("0")) + size_d * price_d`

Mechanism:
- When position is short (negative shares), a BUY should reduce the credit-received cost basis
- Instead, it adds to `cost_basis` as if opening a new long
- Example: short -10 shares, cost_basis=5.0 (credit), BUY 3 @0.60 → cost_basis becomes 6.80 instead of correct 3.20
- This makes `unrealized_pnl` and eventual `close_position` PnL mathematically wrong for any short that was partially covered

Impact:
- Medium: only triggers on BUY against existing short
- With only 246 BUYs total in E1 (most opening new longs, not covering shorts), actual E1 impact is small
- Still a correctness bug that would matter if the strategy produced more balanced BUY/SELL flow

### BT-023: 100% of E1 trades used midpoint fallback — zero order book data in backtest

Status: `Confirmed`

Code evidence:
- `services/simulator/vwap.py:31-32` — falls back to `_midpoint_fill` when `order_book` is None
- `services/simulator/vwap.py:71-86` — `_midpoint_fill` returns `filled_size = size` (full fill) with synthetic 0.5% slippage

DB evidence:
- `177,773` price snapshots in backtest DB, `0` have order book data
- All `11,454` directional trades have `slippage = 0.005` — the midpoint fallback signature
- `0` trades used real VWAP execution

Mechanism:
- The CLOB API historical backfill only stores prices, not order books
- `compute_vwap` sees `order_book = None` for every trade and falls back to `_midpoint_fill`
- `_midpoint_fill` always returns `filled_size = size` — it conjures infinite liquidity
- Every trade fills at exactly the requested size with a flat 0.5% slippage

Impact:
- **Critical for E1 realism.** The backtest assumes every trade fills in full regardless of market depth.
- The system successfully dumped thousands of shares into what may be illiquid markets
- The 0.5% synthetic slippage is a constant — it doesn't scale with size or account for empty books
- This doesn't change the direction of the loss (bad pairs are still the root cause), but it means the magnitude and trade count are unrealistic
- A real execution engine would have partial fills, wider slippage, and many failed trades

### BT-024: No cross-leg proportional scaling — partial fills create unbalanced exposures

Status: `Confirmed-Code`

Code evidence:
- `scripts/backtest.py:220-286` — legs executed independently in a `for trade` loop
- No cross-referencing of filled sizes between legs

Mechanism:
- If leg A partially fills (e.g., 5 of 100 shares due to shallow book), leg B still attempts its full size
- No proportional scaling or "match the smaller fill" logic
- Creates structurally unbalanced exposures that look directional

Impact:
- **Moot in E1** because BT-023 means every trade fills in full (no partial fills ever occur)
- Would become a real issue if order book data were added to the backtest
- Architecturally correct finding, but zero impact on current E1 results

### BT-025: Best-single-leg-per-market strips multi-outcome hedges

Status: `Confirmed-Code`

Code evidence:
- `services/optimizer/trades.py:71-73`
- `trades.append(max(candidates, key=lambda t: t["edge"]))`

Mechanism:
- For each market, all candidate legs are collected, then only the single highest-edge leg is kept
- In binary markets this is correct: BUY Yes and SELL No are mirrors, executing both pays double fees
- In multi-outcome markets (e.g., 4-team partition), a true arb might require BUY on 2 outcomes in the same market
- The single-leg cap destroys the delta-neutrality of complex arbs

Impact:
- Medium: the code comment explains the rationale for binary markets, and it's correct there
- For multi-outcome markets this is a real limitation that prevents optimal hedging
- In E1, most traded markets are binary, so this has limited direct impact
- Becomes important if the system trades more multi-outcome markets

### BT-026: Cross-platform price check has no relative distance check

Status: `Confirmed-Code`

Code evidence:
- `services/detector/verification.py:208-217`
- Only checks `0.05 < p_a < 0.95` and `0.05 < p_b < 0.95` — absolute bounds only

Mechanism:
- Two markets are verified as cross-platform if both prices are between 0.05 and 0.95
- No check that `p_a` is actually close to `p_b`
- A Kalshi market at 0.10 and Polymarket equivalent at 0.90 would pass

Impact:
- Medium: the MAX_EDGE cap (0.20) in `trades.py:18` provides a downstream guard that would reject the most extreme cases
- But pairs with moderate divergence (e.g., 0.30 vs 0.60) would pass verification AND the edge cap
- No direct E1 impact (single-venue backtest), but a latent bug for Phase 5 cross-platform trading

### BT-027: Backtest snapshots never persist `settled_trades`

Status: `Confirmed`

Code evidence:
- `scripts/backtest.py:405-414` writes `PortfolioSnapshot` rows with `winning_trades` but not `settled_trades`
- `shared/models.py` defines `PortfolioSnapshot.settled_trades` with a default of `0`

DB evidence:
- All `238` backtest snapshots have `settled_trades = 0`
- `219` of those same snapshots have `winning_trades > 0`
- The backtest DB also contains `8,679` `SETTLE` rows, so settlement activity definitely occurred

Impact:
- Dashboard settlement counts and any win-rate derived from snapshot `settled_trades` are wrong for E1
- This is a reporting bug, not a root-cause PnL bug
- It explains why the backtest dashboard can show `winning_trades` changing while `settled_trades` stays at zero

### Gemini 3.1 Pro findings reviewed and dispositioned (2026-03-22)

Gemini 3.1 Pro proposed 4 findings. Disposition:

1. **compute_vwap midpoint fallback** → Added as BT-023 (Critical). Severity **upgraded from Gemini's framing**. Gemini correctly identified the fallback but understated the scope: it's not "sometimes fires when books are empty" — it fires on 100% of E1 trades because the backtest has zero order book data. Every single fill is synthetic.

2. **Partial fills create unbalanced exposure** → Added as BT-024 (Medium) but noted as **moot in E1**. The code path is real, but since BT-023 means every trade fills in full, no partial fills ever occurred. Would matter if order books were added.

3. **Single-best-leg-per-market strips multi-outcome hedges** → Added as BT-025 (Medium). Real limitation but the code comment correctly explains the binary market rationale. Impact is limited until multi-outcome markets are traded heavily.

4. **Cross-platform price check missing relative distance** → Added as BT-026 (Medium). Real gap, but the MAX_EDGE downstream cap provides partial defense. No E1 impact (single-venue). Relevant for Phase 5.

### Gemini findings reviewed and dispositioned (2026-03-22)

Gemini proposed 5 findings. Disposition:

1. **Position-flipping truncation** → Added as BT-021 (Low). Real but severity overstated — the cap almost never fires in E1 because 98% of trades open new shorts rather than flipping existing longs.

2. **BUY-against-short cost_basis corruption** → Added as BT-022 (Medium). Real bug, but only 246 BUYs in E1 and most open new longs, not cover shorts.

3. **Realized PnL divergence (manual mutation in backtest.py)** → Not added as separate finding. The manual `realized_pnl +=` in `backtest.py:265` handles rebalancing exits while `close_position()` handles settlements — these are different events on different positions, not double-counting. The architectural fragility is already captured in BT-010 (exit PnL ignores fees). Added a note to BT-001 about multi-leg atomicity.

4. **Multi-leg atomicity** → Not added as separate finding. Already covered by BT-001 ("A multi-leg opportunity can become a one-legged exposure"). The sequential loop with per-opportunity exception handling is the same mechanism.

5. **Precision dust accumulation** → Not added. Gemini claimed `Decimal("0.01")` quantization applies to all trades; in reality it only fires in the BUY capital-cap fallback path (`portfolio.py:48`) when capital is insufficient. Regular trades use full precision. Not a systematic issue across 11,000 trades.

## Cross-Checks Against Existing Reports

These existing reports already pointed in the same direction:
- `reports/performance-monitor-2026-03-22.md`
- `audit-report-2026-03-21.md`
- `audit-report-2026-03-21-run2.md`

What this tracker adds:
- Direct `polyarb_backtest` DB evidence from the E1 backtest
- Separation of backtest-engine bugs from pair-classification failures
- Specific quantification of how much of the loss sits in `mutual_exclusion`

## Remediation Buckets For Later

### 1. Backtest parity and correctness
- Fix `mark_winner()` call in `scripts/backtest.py` (BT-001)
- Fix rebalancing exit PnL to subtract fees (BT-010)
- Add a regression test for profitable exit handling in the backtest path
- Decide whether heuristic settlement should remain the default at all (BT-006)
- Backfill order book data or implement realistic liquidity model for VWAP (BT-023)
- Add cross-leg proportional scaling for partial fills (BT-024)

### 2. Pair quality and verification
- Tighten `mutual_exclusion` verification to require same-event identity (BT-005)
- Add explicit guards for recurring sports fixtures and same-team cross-game pairs (BT-004)
- Make `implication` structural check actually validate the relationship (BT-015)
- Tighten `implication` price tolerance from 0.50 to something meaningful (BT-016)
- Tighten `partition` price-sum tolerance from 0.50 to ~0.20 (BT-019)
- Add `conditional` structural/price checks that aren't vacuous
- Ensure price check is never silently skipped — require it or fail-open explicitly (BT-014)
- Add re-verification on rescan so pairs are checked against fresh prices (BT-018)
- Rebuild or invalidate stale bad pairs already stored in DB

### 3. Classification quality
- Add calibration or second-opinion for LLM confidence scores (BT-020)
- Review cross-venue auto-classification threshold and add resolution-criteria matching (BT-017)
- Add relative price distance check for cross-platform verification (BT-026)

### 4. Valuation and reporting
- Decide how missing prices should be handled for open positions (BT-007)
- Fix short `cost_basis` to include fees (BT-012)
- Persist `settled_trades` in backtest snapshots so dashboard stats are coherent (BT-027)
- Surface snapshot quality metrics so "missing price" valuation gaps are visible

### 5. Portfolio and risk controls
- Add capital/margin check for SELL trades to prevent unbounded short exposure (BT-011)
- Fix SELL truncation to allow long-to-short flip with remainder (BT-021)
- Fix BUY-against-short cost_basis to reduce credit instead of adding (BT-022)
- Add concentration limits per `market_id:outcome`
- Consider refusing repeated same-outcome short accumulation when pair quality is uncertain
- Clarify `estimated_profit` units and naming before using it for tighter sizing/reporting (BT-013)
- Consider multi-leg output for multi-outcome markets instead of single-best-leg (BT-025)

## Open Questions To Fill In Later

- How much of the final E1 loss is directly attributable to BT-001?
- Did the specific E1 run on `:8082` use `--authoritative` or heuristic settlement?
- Which pairing rule produced the wrong sports/esports `mutual_exclusion` pairs in the first place?
- How many stale pairs in the DB were created before later classifier fixes landed?
- Should E1 be rerun only after a DB rebuild, or can bad pairs be invalidated in place?
- ~~What is the right capital/margin model for short positions? (BT-011)~~ → Fixed: 100% margin (notional ≤ cash)
- ~~Should the optimizer require a resolution-invariant payout proof before emitting trades? (BT-009)~~ → Fixed: `_worst_case_payoff()` rejects negative worst-case bundles

## Deployment Log

### 2026-03-22: Critical fixes deployed

13 fixes across 5 files deployed to NAS and verified running:

**Portfolio** (`services/simulator/portfolio.py`):
- BT-011: Short margin check (notional ≤ cash)
- BT-022: BUY-against-short cost_basis fix
- BT-012: Short cost_basis net of fees
- BT-007: Missing prices use cost_basis break-even mark

**Verification** (`services/detector/verification.py`):
- BT-014: Price check always required (missing prices → fail)
- BT-005: mutual_exclusion rejects different event_ids + identical questions
- BT-015: Implication structural check prefers same event_id
- BT-016: Implication price tolerance 0.50 → 0.15
- BT-019: Partition price-sum tolerance 0.50 → 0.25

**Pipeline** (`services/detector/pipeline.py`):
- BT-018: Both rescan methods now re-verify with `verify_pair()`

**Classification** (`services/detector/classifier.py`):
- BT-020: LLM confidence × 0.80, capped at 0.85

**Backtest** (`scripts/backtest.py`):
- BT-001: `mark_winner()` → `winning_trades += 1`
- BT-010: Exit PnL subtracts proportional fees
- BT-027: `settled_trades` persisted in snapshots

**Post-deploy**: Invalidated 11,768 mutual_exclusion pairs (`UPDATE market_pairs SET verified = false WHERE dependency_type = 'mutual_exclusion' AND verified = true`). These will only re-verify if they pass new checks.

**Remaining unfixed**: BT-002/003/004 (root cause — now addressed by BT-005 fix), BT-008 (hypothesis), BT-009 (architectural — rebalancing-only strategy)

### 2026-03-22: Remaining fixes deployed (round 2)

8 additional fixes across 6 files:

**Portfolio** (`services/simulator/portfolio.py`):
- BT-021: SELL now allows long-to-short flip with margin-checked remainder

**Live pipeline** (`services/simulator/pipeline.py`):
- BT-010 (live): Exit PnL now subtracts proportional exit fees (was already fixed in backtest.py)

**VWAP** (`services/simulator/vwap.py`):
- BT-023: Midpoint fallback now uses size-dependent slippage (base 0.5% + 0.01%/share above 10, capped at 5%)

**Verification** (`services/detector/verification.py`):
- BT-026: Cross-platform price check now rejects price divergence > 0.25

**Pipeline** (`services/detector/pipeline.py`):
- BT-017: Cross-venue auto-classification threshold tightened from 0.92 to 0.95

**Optimizer** (`services/optimizer/trades.py`):
- BT-025: Multi-outcome markets now keep all candidate legs; binary markets unchanged (single-best-leg)
- BT-013: `estimated_profit` documented as per-unit edge proxy

**Backtest** (`scripts/backtest.py`):
- BT-006: Default changed to authoritative settlement; `--heuristic` flag for old behavior
- BT-024: Cross-leg proportional scaling — all legs scaled to match smallest fill ratio

**Final status**: 25 of 27 findings fixed. Remaining: BT-002/003/004 (root cause addressed by BT-005), BT-008 (hypothesis, low priority), BT-009 (architectural decision)

### 2026-03-22: Final fixes deployed (round 3)

**Optimizer** (`services/optimizer/trades.py`, `services/optimizer/frank_wolfe.py`):
- BT-008: Minimum net-profit threshold of 0.5% — trades where `estimated_profit < 0.005` after fees+slippage are rejected
- BT-009: Payout proof — `_worst_case_payoff()` computes the minimum PnL across all feasible joint outcomes; rejects trade bundles with worst-case payoff < -$0.01
- FWResult now carries `feasibility_matrix` for use in payout proof

**All 27 findings now fixed.** BT-002/003/004 are root-cause findings (bad mutual_exclusion pairs) addressed by the verification fixes in BT-005/BT-014/BT-018.

### 2026-03-22: Post-fix backtest rerun

**First attempt** showed -97.5% ($245.99) — same as original E1. Root causes:
1. Pair invalidation (`UPDATE market_pairs SET verified = false`) was only run on live DB, not `polyarb_backtest`. Fixed by running same UPDATE on backtest DB (invalidated 533 pairs).
2. `scripts/backtest.py` `detect_opportunities()` loaded ALL pairs without checking `pair.verified` and never called `verify_pair()`. Fixed by adding verified filter on loading and `verify_pair()` call in the detection loop.

**Final result after fixes**:
```
final_value: $10,018.92  (+0.19%)
realized_pnl: +$15.92
total_trades: 128
settled_trades: 41
winning_trades: 19
period: 489 days (2024-09-24 → 2026-01-25)
```

**Interpretation**: The system now preserves capital (+0.19%) instead of catastrophic loss (-86.6%). The dramatic improvement confirms bad mutual_exclusion pairs were the root cause. However, with properly verified pairs, the system has very limited alpha — only 128 trades over 489 days with marginal returns. Remaining verified pairs: ~45 implication, ~6 partition, ~13 conditional.
