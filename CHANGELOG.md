# Changelog

## 2026-03-21 — Profitability Fixes (Classifier + Optimizer + Simulator)

### Bug Fixes

**1. estimated_profit double-counting (optimizer/trades.py)**
- `estimated_profit` was summing `abs(edge)` across every outcome in both markets. For binary pairs this counted each mispricing 2× per market (once for Yes, once for No), inflating profit estimates ~4× vs actual capturable edge.
- Now takes `max(edge)` per market and subtracts estimated round-trip fees. Also passes through `theoretical_profit` from the constraint matrix for comparison.

**2. min_edge threshold too low (optimizer/trades.py, shared/config.py)**
- Hardcoded `0.005` (0.5 cent) threshold let through trades where fees alone exceeded the entire edge. With 2% fee rate on two legs, breakeven is ~$0.02.
- New configurable `OPTIMIZER_MIN_EDGE` setting, default **0.03** (3 cents). Also bumped `LIVE_TRADING_MIN_EDGE` default from 0.005 to 0.03.

**3. Conditional pairs produce no real edge (optimizer/pipeline.py)**
- `_conditional_matrix` returns all-ones (identical to unconstrained), so Frank-Wolfe projects back to roughly the original prices — producing noise-level edges that always lose to fees.
- New `OPTIMIZER_SKIP_CONDITIONAL` setting (default `true`). Conditional pairs now get `status = "skipped"` before FW runs.

**4. Crypto time-interval misclassification (detector/classifier.py)**
- GPT-4o-mini was labeling adjacent 15-minute crypto "Up or Down" windows (e.g., Bitcoin 3:15-3:30 vs 3:30-3:45) as `mutual_exclusion` when they're actually independent events.
- New rule-based filter `_check_crypto_time_intervals` matches the `"Asset Up or Down — Date, StartAM-EndAM ET"` pattern:
  - Same asset + same time window → `mutual_exclusion` (correct: can't be both up and down)
  - Same asset + different time window → `none` (independent events)
  - Runs before LLM, saving API calls for these 23+ pairs.

### Configuration Changes

| Setting | Old Default | New Default |
|---|---|---|
| `OPTIMIZER_MIN_EDGE` | 0.005 (hardcoded) | 0.03 |
| `OPTIMIZER_SKIP_CONDITIONAL` | N/A | true |
| `LIVE_TRADING_MIN_EDGE` | 0.005 | 0.03 |

### Files Changed

- `services/detector/classifier.py` — added `_check_crypto_time_intervals` rule
- `services/optimizer/trades.py` — fixed estimated_profit calculation, configurable min_edge
- `services/optimizer/pipeline.py` — conditional pair skip, pass fee_rate/min_edge/theoretical_profit
- `services/optimizer/main.py` — wire new settings into pipeline
- `shared/config.py` — added `optimizer_min_edge`, `optimizer_skip_conditional`, bumped `live_trading_min_edge`
- `scripts/backtest.py` — pass new params to `compute_trades`
- `.env.example` — documented new settings
