# Backtest Findings Tracker

Last updated: 2026-03-22

Scope:
- E1 historical backtest
- Dashboard: `http://$NAS_HOST:8082`
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
- The loss is overwhelmingly a `mutual_exclusion` problem, not a fee-only problem.

## Summary Table

| ID | Status | Severity | Area | Finding |
|---|---|---|---|---|
| BT-001 | Confirmed | Critical | Backtest engine | `scripts/backtest.py` still calls missing `portfolio.mark_winner()` |
| BT-002 | Confirmed | Critical | Pair quality | Invalid `mutual_exclusion` pairs dominate E1 losses |
| BT-003 | Confirmed | High | Execution shape | Wrong `mutual_exclusion` pairs naturally produce destructive double-sell trades |
| BT-004 | Confirmed | High | Classification data | Some `mutual_exclusion` pairs use identical question text across different events |
| BT-005 | Confirmed | High | Verification | `mutual_exclusion` verification is too weak to reject wrong-event pairs |
| BT-006 | Confirmed-Code | High | Settlement | Default backtest mode settles heuristically at `price >= 0.98` |
| BT-007 | Confirmed-Code | Medium | Valuation | Missing prices default to `0` in portfolio valuation, distorting short exposure |
| BT-008 | Hypothesis | Medium | Execution economics | Small edge sizing plus fees/slippage may make marginal trades negative |
| BT-009 | Confirmed | High | Strategy expression | E1 opportunities are all `rebalancing` and overwhelmingly `SELL/SELL` in practice |

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
- Fix `mark_winner()` call in `scripts/backtest.py`
- Add a regression test for profitable exit handling in the backtest path
- Decide whether heuristic settlement should remain the default at all

### 2. Pair quality and verification
- Tighten `mutual_exclusion` verification to require same-event identity
- Add explicit guards for recurring sports fixtures and same-team cross-game pairs
- Rebuild or invalidate stale bad pairs already stored in DB

### 3. Valuation and reporting
- Decide how missing prices should be handled for open positions
- Surface snapshot quality metrics so "missing price" valuation gaps are visible

### 4. Risk controls
- Add concentration limits per `market_id:outcome`
- Consider refusing repeated same-outcome short accumulation when pair quality is uncertain

## Open Questions To Fill In Later

- How much of the final E1 loss is directly attributable to BT-001?
- Did the specific E1 run on `:8082` use `--authoritative` or heuristic settlement?
- Which pairing rule produced the wrong sports/esports `mutual_exclusion` pairs in the first place?
- How many stale pairs in the DB were created before later classifier fixes landed?
- Should E1 be rerun only after a DB rebuild, or can bad pairs be invalidated in place?
