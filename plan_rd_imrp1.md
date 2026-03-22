# plan_rd_imrp1 — R&D Improvement Plan for PolyArb

> Research-informed system improvements, grounded in literature gaps and current codebase audit.
> Each item maps to a specific paper from `research_sources.md` and a specific code gap.

---

## Phase 0: Instrumentation & Baselines (Week 1-2)

Before improving anything, measure what you have. You can't claim improvement without a baseline.

### 0.1 — Backtest Metrics Overhaul

**Gap:** `scripts/backtest.py` reports 8 summary stats but no per-dependency-type breakdown, no win rate in summary, no Sortino, no trade efficiency ratio.

**What to do:**
- Add per-dependency-type breakdown: opportunities detected / optimized / executed / settled / P&L for each of {implication, partition, mutual_exclusion, conditional, cross_platform}
- Add win rate, payoff ratio (avg win / avg loss), Sortino ratio, trade efficiency (executed / detected)
- Add slippage accuracy: compare VWAP estimate at validation time vs. actual fill price
- Log constraint violation rate (edge disappeared between detection and execution)
- Output all metrics to a JSON summary alongside the human-readable log

**Files:** `scripts/backtest.py` (lines 423-709), `services/simulator/pipeline.py`

**Paper:** [#11 PredictionMarketBench](https://arxiv.org/abs/2602.00133) — adopt their reporting format so results are directly comparable to other prediction market trading agents.

### 0.2 — Classifier Accuracy Dataset

**Gap:** No ground-truth labels for market pair dependency types. Can't measure classifier precision/recall.

**What to do:**
- Export the last 1000 classified pairs from the DB (market_pairs table)
- Manually label 500 pairs with ground-truth dependency type + correctness flag
- Build a simple eval harness: run classifier on labeled pairs, report precision/recall/F1 per type
- Track rule-based vs. LLM-classified separately (measure how much the LLM fallback contributes)

**Files:** `services/detector/classifier.py`, new `scripts/eval_classifier.py`

**Paper:** [#4 Semantic Trading](https://arxiv.org/abs/2512.02436) reports ~60-70% accuracy on their semantic clustering. Your classifier should beat this since you have domain-specific rules.

### 0.3 — Extended Backtest Run

**Gap:** Need 6+ months of historical data through the full pipeline.

**What to do:**
- Run `scripts/backfill_history.py` with `--max-markets 5000` to maximize coverage
- Execute full backtest with `--capital 10000` over the longest available window
- Save the JSON metrics from 0.1 as your baseline
- This becomes the "before" in every A/B comparison below

**Files:** `scripts/backfill_history.py`, `scripts/backtest.py`

---

## Phase 1: Smarter Detection (Week 3-5)

### 1.1 — Lead-Lag Detection Module

**Gap:** ZERO time-series analysis in the codebase. No lead-lag detection, no Granger causality, no rolling correlations. This is the single biggest missing capability.

**What to do:**
- New module: `services/detector/leadlag.py`
- For each verified market pair, compute rolling Pearson correlation on 1h/6h/24h windows from price_snapshots
- Implement Granger causality test (statsmodels `grangercausalitytests`) on price time series
- If market A Granger-causes B with p < 0.05: flag the pair with lead_lag metadata (leader, lag_minutes, significance)
- Feed this into the classifier as an additional signal: lead-lag pairs with high correlation are likely conditional dependencies
- New Redis channel or metadata field on MarketPair for lead-lag results

**Why it matters:** If market A moves first, you can trade market B before the price catches up. This is the highest-alpha improvement possible — it turns your system from a static arbitrage detector into a statistical arbitrage engine.

**Paper:** [#6 LLM as Risk Manager](https://arxiv.org/abs/2602.07048) — they showed a two-stage Granger→LLM pipeline improved Kalshi win rate from 51.4% to 54.5%. Implement the Granger layer; use your existing LLM classifier as the semantic filter.

### 1.2 — Enriched Embeddings (Behavioral Features)

**Gap:** `similarity.py` uses only text embeddings (market question + description). No price dynamics, volume, or microstructure in the similarity search.

**What to do:**
- Extend the embedding vector with a small behavioral feature tail (8-16 dims):
  - 24h price return, 7d price return
  - Log daily volume (normalized)
  - Bid-ask spread (from latest order book snapshot)
  - Price volatility (rolling 24h stdev)
- Concatenate with text embedding (384 + 16 = 400 dims), re-normalize
- Update pgvector index to new dimensionality
- A/B test: does behavioral enrichment find pairs that pure text similarity misses?

**Files:** `services/ingestor/embedder.py`, `services/detector/similarity.py`, pgvector index DDL

**Paper:** [#5 Semantic Non-Fungibility](https://arxiv.org/abs/2601.01706) — their dataset of 100K aligned events across 10 venues could be used to evaluate whether enriched embeddings improve cross-platform matching recall vs. text-only.

### 1.3 — Manipulation Filter

**Gap:** No detection of wash trading, sudden volume spikes, or anomalous price moves. The system treats all mispricings as arbitrage, but some are manipulation artifacts that revert before you can trade.

**What to do:**
- New module: `services/detector/manipulation.py`
- Flag markets where in the last 1h: volume > 5× rolling 24h average, or price moved > 15% in < 10 minutes
- Add a `manipulation_risk` score (0-1) to MarketPair
- In the simulator validation phase: reject opportunities where either leg has manipulation_risk > 0.7
- Log rejection reasons for later analysis

**Papers:**
- [#9 How Manipulable Are Prediction Markets?](https://arxiv.org/abs/2503.03312) — patterns of successful manipulation
- [#10 Manipulation in Prediction Markets: ABM](https://arxiv.org/abs/2601.20452) — persistence of manipulation-induced distortions
- [#16 Prediction Laundering](https://arxiv.org/abs/2602.05181) — whale activity creating noise

---

## Phase 2: Better Optimization (Week 6-8)

### 2.1 — N-Way Arbitrage (3+ Markets)

**Gap:** The entire pipeline is hardcoded to pairwise: constraint_matrix is 2D (n_a × n_b), frank_wolfe.py concatenates two price vectors, trades.py assumes "market A" vs "market B". This misses cyclic and multi-way opportunities.

**What to do:**
- Generalize constraint representation from 2D matrix to a hypergraph:
  - `constraint_tensor[i][j][k] = 1` if outcome (i, j, k) across markets (A, B, C) is feasible
  - For pairwise, this reduces to current behavior
- Extend Frank-Wolfe to N marginals:
  - Price vector: `np.concatenate([p_a, p_b, p_c, ...])`
  - IP oracle: N sets of binary variables with joint feasibility constraints
  - Marginal projection: project each market's slice independently
- Start with N=3 (triplets), where the detector finds chains: A↔B and B↔C → evaluate A↔B↔C
- Trade extraction: best leg per market (already generalizes)

**Files:** `services/detector/constraints.py`, `services/optimizer/frank_wolfe.py`, `services/optimizer/ip_oracle.py`, `services/optimizer/trades.py`

**Paper:** [#2 Geometric AMM Design](https://arxiv.org/abs/2411.08972) — their VC-dimension framework tells you when N-way optimization is tractable. For N=3 with small outcome spaces (binary), CP-SAT should still converge in <1s.

**Risk:** IP oracle solve time grows combinatorially. For N=3 binary markets, outcome space is 2³=8 — trivial. For N=5, it's 32 — still fine. For N=10+, need approximation. Start with N=3 and measure.

### 2.2 — Adaptive Slippage Estimation

**Gap:** `trades.py` uses flat 0.5% slippage estimate regardless of order book depth. VWAP simulation in `vwap.py` is better but only used at execution time, not during optimization.

**What to do:**
- At optimization time, fetch latest order book for both markets
- Run VWAP simulation at proposed trade size to get estimated fill price
- Use the VWAP-adjusted price (not midpoint) as input to profit calculation
- Reject opportunities where VWAP slippage eats >50% of theoretical edge
- Track estimated vs. actual slippage for calibration

**Files:** `services/optimizer/trades.py` (line 112), `services/simulator/vwap.py`

**Paper:** [#8 Anatomy of Polymarket](https://arxiv.org/abs/2603.03136) — their liquidity analysis across 124M trades tells you realistic order book depth distributions. Use their findings to calibrate the slippage threshold.

---

## Phase 3: Smarter Sizing & Risk (Week 9-11)

### 3.1 — Theoretically Grounded Kelly Sizing

**Gap:** Current sizing is `kelly_fraction = edge * 0.5` (line 135, pipeline.py) — a heuristic half-Kelly with no theoretical justification for the 0.5 factor or the linear drawdown scaling.

**What to do:**
- Implement the bounded-price Kelly formula from the literature:
  - For a binary market with probability q* (from FW) and price p:
    `f* = (q* - p) / (1 - p)` for buys, `f* = (p - q*) / p` for sells
  - Apply fractional Kelly with a principled scaling factor derived from estimation uncertainty
- Replace linear drawdown scaling with CLT-based risk measure:
  - Compute asymptotic variance of growth rate across current portfolio
  - Scale Kelly fraction to maintain target variance, not target drawdown level
- Add correlation-aware position limits:
  - If you hold long positions in markets A and B, and A↔B are positively correlated, the combined risk is higher than the sum
  - Compute pairwise position correlations from lead-lag data (Phase 1.1)
  - Reduce sizing when portfolio correlation exceeds threshold

**Files:** `services/simulator/pipeline.py` (lines 127-148), `shared/circuit_breaker.py`

**Papers:**
- [#12 Kelly Criterion in Prediction Markets](https://arxiv.org/abs/2412.14144) — formal derivation for bounded-price markets using KL divergence (directly connects to your FW objective)
- [#13 Optimal Betting Beyond Long-Term Growth](https://arxiv.org/abs/2503.17927) — CLT-based risk measure replaces your heuristic drawdown scaling
- [#14 Kelly Betting as Bayesian Model Evaluation](https://arxiv.org/abs/2602.09982) — dynamic bet adjustment as prices move

### 3.2 — Portfolio-Level Optimization

**Gap:** Current system evaluates each opportunity independently (greedy). Doesn't consider how a new trade interacts with existing positions.

**What to do:**
- Before executing a new opportunity, compute portfolio-level metrics:
  - Total exposure by dependency type
  - Net directional exposure (are we long prediction markets overall?)
  - Correlation with existing positions
- Implement a simple portfolio constraint: max 30% of capital in any single dependency type
- Implement anti-correlation preference: favor opportunities that diversify the existing book
- Track portfolio-level Sharpe in real-time (not just at backtest end)

**Files:** `services/simulator/portfolio.py`, `services/simulator/pipeline.py`

---

## Phase 4: Hardened Execution (Week 12-14)

### 4.1 — Partial Fill Recovery

**Gap:** Two-phase execution validates all legs then executes all legs, but if execution of leg 2 fails after leg 1 succeeds, you're left with a one-sided position.

**What to do:**
- Track execution state per leg: {pending, filled, failed}
- If any leg fails after another succeeded:
  - Option A: Immediately unwind the filled leg(s) at market
  - Option B: Hold the position if it has positive expected value standalone (check FW marginal)
  - Option C: Queue for retry within a time window (30s)
- Log all partial fill events for post-mortem analysis
- Add partial_fill_rate to backtest metrics

**Files:** `services/simulator/pipeline.py` (lines 150-249)

### 4.2 — Cross-Platform Execution Timing

**Gap:** For cross-platform trades (Polymarket ↔ Kalshi), execution on both venues needs to be near-simultaneous. Current system executes sequentially.

**What to do:**
- For cross-platform opportunities: fire both legs concurrently (asyncio.gather)
- Add latency monitoring per venue (rolling p50/p99)
- If one venue's latency > 2s, defer the opportunity
- For the paper: report cross-platform execution gap (time between leg fills)

**Paper:** [#5 Semantic Non-Fungibility](https://arxiv.org/abs/2601.01706) — their 2-4% persistent deviations suggest cross-platform arb is slow to close, so timing pressure may be lower than expected.

---

## Phase 5: Validation & Paper Prep (Week 15-18)

### 5.1 — Ablation Study Framework

**What to do:**
- Run the improved backtest with each improvement toggled on/off:
  - Lead-lag detection ON vs. OFF
  - Enriched embeddings vs. text-only
  - Manipulation filter ON vs. OFF
  - N-way (N=3) vs. pairwise only
  - Adaptive slippage vs. flat 0.5%
  - Kelly-optimal sizing vs. heuristic half-Kelly
- Report delta in: total return, Sharpe, Sortino, max drawdown, win rate
- Each ablation answers: "does this component matter?"

### 5.2 — Head-to-Head vs. Semantic Trading

**What to do:**
- Implement a simplified version of the Semantic Trading strategy (cluster-based, no FW optimization, simple spread threshold)
- Run both strategies on the same backtest window
- Report: return, Sharpe, number of trades, avg hold time, max drawdown
- If PolyArb outperforms: that's the paper's punchline

**Paper:** [#4 Semantic Trading](https://arxiv.org/abs/2512.02436) — ~20% returns over week-long horizons is your target to beat.

### 5.3 — Comparison to "Unravelling" Findings

**What to do:**
- Reproduce their key statistics on your data:
  - Total arbitrage volume detected
  - Combinatorial vs. rebalancing split
  - Failure rate (detected but couldn't execute profitably)
- If your failure rate < their 62%, explain why (better classification? better timing? manipulation filter?)

**Paper:** [#7 Unravelling](https://arxiv.org/abs/2508.03474) — their 0.24% combinatorial arbitrage share and 62% failure rate are the numbers to beat.

### 5.4 — 3-Month Paper Trading Run

**What to do:**
- Deploy the improved system on the NAS (192.168.5.100)
- Run live paper trading for 12+ weeks
- Daily automated snapshots to DB
- Weekly manual review of: new pair discoveries, false positives, missed opportunities
- Compile results into paper-ready tables and charts

---

## Priority Matrix

| Improvement | Impact | Effort | Research Novelty | Do First? |
|---|---|---|---|---|
| 0.1 Metrics overhaul | High | Low | Required for paper | **YES** |
| 0.2 Classifier eval | High | Medium | Required for paper | **YES** |
| 0.3 Extended backtest | High | Low | Required for paper | **YES** |
| 1.1 Lead-lag detection | Very High | Medium | High (stat arb angle) | **YES** |
| 1.2 Enriched embeddings | Medium | Medium | Medium | Maybe |
| 1.3 Manipulation filter | Medium | Low | Medium | Yes |
| 2.1 N-way arbitrage | Very High | High | Very High | Yes (but hard) |
| 2.2 Adaptive slippage | Medium | Low | Low | Yes |
| 3.1 Kelly sizing | Medium | Medium | Medium | After baseline |
| 3.2 Portfolio optimization | Medium | High | Medium | After baseline |
| 4.1 Partial fill recovery | Low (paper trading) | Medium | Low | Later |
| 4.2 Cross-platform timing | Low | Low | Low | Later |
| 5.1-5.4 Validation | Critical | Medium | Required for paper | After improvements |

---

## Timeline Summary

```
Week 1-2:   Phase 0 — Instrument, measure, get baselines
Week 3-5:   Phase 1 — Lead-lag, enriched embeddings, manipulation filter
Week 6-8:   Phase 2 — N-way arbitrage, adaptive slippage
Week 9-11:  Phase 3 — Kelly sizing, portfolio optimization
Week 12-14: Phase 4 — Execution hardening
Week 15-18: Phase 5 — Ablations, comparisons, paper trading, write-up
```

Target: AFT 2027 or EC 2027 submission (deadlines typically Feb-April).

---

## Source → Improvement Map

| Source | Improvement It Informs |
|---|---|
| [#2 Geometric AMM](https://arxiv.org/abs/2411.08972) | 2.1 N-way arbitrage tractability |
| [#4 Semantic Trading](https://arxiv.org/abs/2512.02436) | 5.2 Head-to-head comparison, 0.2 accuracy benchmark |
| [#5 Semantic Non-Fungibility](https://arxiv.org/abs/2601.01706) | 1.2 Cross-platform eval dataset, 4.2 timing expectations |
| [#6 LLM as Risk Manager](https://arxiv.org/abs/2602.07048) | 1.1 Lead-lag + LLM pipeline design |
| [#7 Unravelling](https://arxiv.org/abs/2508.03474) | 5.3 Benchmark comparison, 1.3 failure rate analysis |
| [#8 Anatomy of Polymarket](https://arxiv.org/abs/2603.03136) | 2.2 Slippage calibration, liquidity assumptions |
| [#9 How Manipulable](https://arxiv.org/abs/2503.03312) | 1.3 Manipulation pattern design |
| [#10 Manipulation ABM](https://arxiv.org/abs/2601.20452) | 1.3 Distortion persistence timing |
| [#11 PredictionMarketBench](https://arxiv.org/abs/2602.00133) | 0.1 Reporting format, 0.3 backtest methodology |
| [#12 Kelly in Prediction Markets](https://arxiv.org/abs/2412.14144) | 3.1 Bounded-price Kelly derivation |
| [#13 Optimal Betting](https://arxiv.org/abs/2503.17927) | 3.1 CLT-based risk measure |
| [#14 Kelly Bayesian](https://arxiv.org/abs/2602.09982) | 3.1 Dynamic bet adjustment |
| [#16 Prediction Laundering](https://arxiv.org/abs/2602.05181) | 1.3 Whale noise interpretation |
