# AFT Conference Review: Takeaways for PolyArb

**Date:** 2026-03-22
**Scope:** ACM Advances in Financial Technologies (AFT 2024–2025), plus closely related papers from SODA'25 and arXiv.
**Goal:** Identify concrete improvements to PolyArb's detector, optimizer, simulator, and overall architecture.

---

## Papers Reviewed

| # | Paper | Venue | Relevance |
|---|-------|-------|-----------|
| 1 | Saguillo et al. — "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets" | AFT 2025 (LIPIcs.AFT.2025.27) | **Direct** — Polymarket combinatorial arb |
| 2 | Chan, Wu, Shi — "Mechanism Design for Automated Market Makers" | AFT 2025 (LIPIcs.AFT.2025.7) | Batch MEV-resistant AMM design |
| 3 | Nadkarni, Kulkarni, Viswanath — "Adaptive Curves for Optimally Efficient Market Making" | AFT 2024 (LIPIcs.AFT.2024.25) | Kalman-filter adaptive pricing |
| 4 | Singh et al. — "Modeling Loss-Versus-Rebalancing via Continuous-Installment Options" | AFT 2025 (LIPIcs.AFT.2025.6) | LVR modeling for LP positions |
| 5 | Trotti et al. — "Strategic Analysis of Just-In-Time Liquidity in CLMMs" | AFT 2025 (LIPIcs.AFT.2025.8) | JIT LP strategies & fee competition |
| 6 | — "Measuring CEX-DEX Extracted Value and Searcher Profitability" | AFT 2025 (LIPIcs.AFT.2025.26) | Searcher strategy profiling |
| 7 | Fang, Yu et al. — "Designing AMMs for Combinatorial Securities: A Geometric Viewpoint" | SODA 2025 / arXiv:2411.08972 | Sublinear LMSR via partition trees |

---

## 1. Detector — Market Pair Discovery & Classification

### Current State
- pgvector cosine similarity (OpenAI `text-embedding-3-small`, 384-dim) with HNSW, threshold 0.82
- Rule-based heuristics → LLM fallback (`gpt-4.1-mini`) for dependency classification
- Binary-focused constraint matrices; conditional pairs skipped by default

### Paper #1: Saguillo et al. — Heuristic-Driven Reduction

**What they do differently:**
- Use **Linq-Embed-Mistral** for topical clustering (1024-dim, stronger MTEB scores than `text-embedding-3-small`)
- Three-filter pipeline: temporal alignment → topical embedding cluster → LLM dependency extraction
- **Top-4 condition reduction**: For multi-outcome markets, keep only top-4 by liquidity + "Other" bucket — captures 90% of liquidity while making the combinatorial explosion tractable
- LLM: **DeepSeek-R1-Distill-Qwen-32B** with chain-of-thought + tree-of-thoughts for resolution vector generation

**Key thresholds from their work:**
- Intra-market YES deviation: >0.05 (vs. PolyArb's implicit ≈0 tolerance via FW)
- Uncertainty filter: max outcome price <0.95 (ignore near-certain markets)
- VWAP carry-forward: 5,000 blocks (~2.5 hrs)
- Small-trade filter: exclude trades <$2

**Their finding:** Only ~$95K extracted from combinatorial arb across 13 viable pairs, vs. $28.9M from NegRisk intra-market. This suggests PolyArb should prioritize NegRisk-style rebalancing alongside cross-market arb.

### Actionable Changes for Detector

**HIGH PRIORITY:**

1. **Add NegRisk intra-market detection.** Saguillo et al. found NegRisk NO-buying is the dominant profit source ($28.9M vs $95K combinatorial). PolyArb currently only detects inter-market pairs. Add a single-market scan mode that checks:
   - Sum of YES prices deviating from 1.0 by >0.05
   - Individual NO-buying opportunities when a market set uses NegRisk adapter
   - This requires no new infrastructure — just a periodic query against existing `price_snapshots`

2. **Add uncertainty filter.** Skip markets where any outcome is priced >0.95. These are near-resolved and generate false signals. Trivial to add as a WHERE clause.

3. **Upgrade embedding model.** Switch from `text-embedding-3-small` (384-dim) to either:
   - Linq-Embed-Mistral (1024-dim) — what the AFT paper used, strong MTEB performance
   - Or `text-embedding-3-large` (3072-dim, reducible) — stays in OpenAI ecosystem
   - Re-embed existing markets as a one-time migration; update HNSW index accordingly

**MEDIUM PRIORITY:**

4. **Top-K condition reduction for multi-outcome markets.** When markets have >4 conditions, keep top-4 by liquidity + aggregate "Other." This makes the constraint matrix 5×5 max instead of N×N, dramatically reducing IP oracle solve time.

5. **LLM classifier upgrade.** Current `gpt-4.1-mini` for ambiguous cases. Consider:
   - DeepSeek-R1-Distill-Qwen-32B (what the paper used, self-hosted, free inference)
   - Chain-of-thought prompting to output resolution vectors (JSON of valid outcome combos)
   - Validation: their approach hit 81.45% accuracy on 128 election NegRisk markets

6. **Temporal alignment filter.** Before running embedding similarity, pre-filter by resolution date overlap. Markets that don't overlap temporally can't have combinatorial dependencies. This reduces the candidate set cheaply.

---

## 2. Optimizer — Frank-Wolfe & Trade Computation

### Current State
- FWMM (Dudik et al. 2016): KL-divergence projection onto marginal polytope
- OR-Tools CP-SAT for the IP oracle (per-iteration vertex finding)
- Max 200 iterations, gap tolerance 0.001, IP timeout 5s
- Min edge 0.03, sanity cap 0.20

### Paper #7: Fang & Yu — Geometric Approach to Combinatorial AMMs

**Key insight:** They connect combinatorial market scoring rules to range query problems in computational geometry. For markets with bounded VC dimension, they achieve **sublinear time** price queries and trade updates via partition trees. This is directly relevant to PolyArb's IP oracle bottleneck.

**What this means for PolyArb:**
- The current IP oracle reformulates every FW iteration as a fresh CP-SAT problem
- For binary market pairs, this is fast (~5ms), but for multi-outcome combinations it scales poorly
- Partition-tree structure could replace the IP oracle for specific market topologies (interval securities, subset hierarchies) where the VC dimension is bounded
- For PolyArb's typical binary-pair case, the current approach is already near-optimal

### Paper #2: Chan, Wu, Shi — Batch-Processed AMM Mechanism

**Key idea:** Process all trades in a block as a batch using a constant potential function, eliminating ordering-dependent MEV. While designed for on-chain AMMs, the batch-processing insight applies to PolyArb's simulator.

### Actionable Changes for Optimizer

**MEDIUM PRIORITY:**

1. **Warm-start Frank-Wolfe across re-scans.** Currently each optimization starts from scratch (deterministic feasible vertex). When re-scanning a pair whose prices shifted slightly, initialize from the previous solution. FW convergence is O(1/t) from cold start but can converge in 1-3 iterations from a warm start when the optimum hasn't moved much.

2. **Adaptive iteration limits.** Binary pairs converge in <50 iterations typically. Multi-outcome markets may need more. Replace fixed 200-iteration cap with an adaptive budget: start with 50, extend by 50 if gap is still decreasing, up to 500 max.

3. **Cache IP oracle solutions.** The LP relaxation vertex for a given gradient direction can be cached and reused when gradients are similar across consecutive iterations. Hash the quantized gradient direction and check cache before solving.

**LOW PRIORITY (FUTURE):**

4. **Partition-tree oracle for structured markets.** For interval/threshold markets (e.g., "BTC above $X" at different X values), these form a natural interval set system. A partition tree could replace CP-SAT with O(log n) queries. This is a research project, not a quick win.

5. **Multi-pair joint optimization.** Currently optimizes one pair at a time. When multiple pairs share a market (A-B, A-C), joint optimization over the shared marginal polytope could find better solutions. Requires extending the constraint matrix formulation.

---

## 3. Simulator — Execution, Sizing & Portfolio

### Current State
- VWAP execution from order book snapshots (120s max age)
- Half-Kelly sizing with drawdown scaling (linear 5-10%)
- Atomic multi-leg execution (all or nothing)
- Polymarket fee: p*(1-p)*0.015; Kalshi: ceil(7%*p*(1-p))
- Fixed 0.5% slippage fallback when no order book

### Paper #1: Saguillo et al. — Execution Realities

**Critical finding:** Their analysis assumes sequential order-book execution but acknowledges lack of slippage sensitivity analysis. They note that non-atomic execution across correlated markets creates real risk — prices can move between legs.

**Specific execution insights:**
- 75% of arbitrage profits are captured within ~1 hour execution windows
- Trades <$2 are noise (should be filtered)
- On-chain VWAP with 5,000-block carry-forward handles gaps better than PolyArb's 120s max age

### Paper #3: Nadkarni et al. — Adaptive Pricing with Kalman Filtering

**Core idea:** Use Kalman filtering to estimate the "true" price from noisy trade observations, then adapt market-maker curves accordingly. The filter needs only two parameters: price volatility (σ) and trader noise (η).

**PolyArb application:** Rather than using raw CLOB midpoints as "current price," apply a simple Kalman filter to the price stream per market. This gives:
- Smoothed price estimates that are more robust to wash trades / manipulation
- Confidence intervals on fair value (filter uncertainty)
- Better entry/exit timing by comparing CLOB price vs. filtered estimate

### Paper #5: Trotti et al. — JIT Liquidity & Fee Competition

**Insight:** JIT LPs who misjudge price impact lose money even with good timing. The framework models how fee competition between passive LPs and JIT providers affects profitability. Key takeaway: fee assumptions matter more than timing for net profitability.

### Paper #6: CEX-DEX Extracted Value

**Finding:** $233.8M extracted by just 19 searchers via CEX-DEX arb. Profitable searchers use: latency-optimized infrastructure, MEV-aware transaction routing, and multi-venue price monitoring. The distribution is highly concentrated — top searchers capture most value.

### Actionable Changes for Simulator

**HIGH PRIORITY:**

1. **Kalman-filtered fair value estimates.** Add a lightweight Kalman filter to the price stream in the ingestor. Two parameters per market: estimated volatility σ (from recent price variance) and observation noise η (from bid-ask spread). Use the filtered estimate as "fair price" in trade edge calculations instead of raw midpoint. This directly reduces false signals from noisy prices.

2. **Adaptive slippage model.** Replace fixed 0.5% fallback with a per-market estimate based on:
   - Recent realized slippage (from VWAP calculations where we have order books)
   - Bid-ask spread as a proxy (half-spread ≈ expected slippage for small orders)
   - Store as a rolling 24h metric per market

3. **Longer VWAP carry-forward.** Increase `MAX_SNAPSHOT_AGE_SECONDS` from 120s to something adaptive. For low-volume markets, 120s rejects too many valid opportunities. Use the Saguillo approach: carry forward the last known snapshot with a decay factor on confidence.

**MEDIUM PRIORITY:**

4. **NegRisk-aware execution logic.** NegRisk markets on Polymarket use a specific contract adapter where buying NO is the primary strategy. The simulator's trade execution should understand NegRisk mechanics:
   - Buy NO tokens when sum of YES prices > 1.0
   - Settlement is per the NegRisk adapter (complete set redemption)
   - This aligns with the dominant arb strategy ($28.9M extracted)

5. **Minimum trade filter.** Discard opportunities where the optimal trade per leg would be <$2. These are unprofitable after fees and provide negligible portfolio impact.

6. **Portfolio rebalancing on price moves.** Currently, once a position is entered, it's held until resolution. Add a rebalancing check: if a held position's edge has flipped (our side is now wrong), exit early via opposing trade. This limits drawdown on mispriced entries.

---

## 4. Architecture & Infrastructure

### Paper #2 Insight: Event Ordering

PolyArb uses Redis pub/sub which is unordered. The Chan et al. paper on batch-processed AMMs highlights that trade ordering matters for fairness. In PolyArb's context: if two arbitrage opportunities arrive simultaneously and share a market, the execution lock serializes them, but the first one processed gets better prices. Consider:
- Priority queue (by estimated profit) instead of FIFO for opportunity processing
- Batch evaluation: collect opportunities over a short window (e.g., 5s), then rank and execute best-first

### Paper #1 Insight: Data Pipeline

Saguillo et al. built their analysis on on-chain data (Polygon block-level). PolyArb uses the CLOB API which is off-chain. For backtesting fidelity:
- Consider supplementing CLOB data with on-chain settlement data for validation
- On-chain data provides ground truth for whether arb was actually extracted vs. just available

### Actionable Infrastructure Changes

**MEDIUM PRIORITY:**

1. **Opportunity prioritization.** Replace FIFO opportunity processing with a priority queue sorted by estimated_profit / risk_ratio. When multiple opportunities compete for the same capital, execute the highest-value first.

2. **Batch opportunity evaluation.** Accumulate opportunities for 5-10 seconds, deduplicate those sharing markets, then jointly evaluate. This prevents conflicting positions and improves capital allocation.

3. **On-chain data validation.** For backtesting, supplement CLOB API data with Polygon on-chain settlement events. This validates whether detected opportunities were actually captured by other traders (ground truth).

---

## 5. Summary: Priority-Ordered Roadmap

### Quick Wins (1-2 days each)

| Change | Component | Expected Impact |
|--------|-----------|----------------|
| NegRisk intra-market detection | Detector | Opens $28.9M/yr opportunity class |
| Uncertainty filter (>0.95) | Detector | Eliminates false signals from near-resolved markets |
| Minimum trade filter (<$2) | Simulator | Cleaner P&L, fewer noise trades |
| Kalman-filtered fair value | Ingestor/Simulator | More robust edge calculations |

### Medium Effort (1-2 weeks each)

| Change | Component | Expected Impact |
|--------|-----------|----------------|
| Embedding model upgrade | Detector | Better semantic clustering, fewer missed pairs |
| Warm-start Frank-Wolfe | Optimizer | 3-10x faster re-scans |
| Adaptive slippage model | Simulator | More accurate execution modeling |
| NegRisk execution logic | Simulator | Required for NegRisk arb strategy |
| Opportunity prioritization | Pipeline | Better capital allocation |
| Top-K condition reduction | Detector | Enables multi-outcome market support |

### Research Projects (weeks-months)

| Change | Component | Expected Impact |
|--------|-----------|----------------|
| Partition-tree IP oracle | Optimizer | Sublinear scaling for structured markets |
| Multi-pair joint optimization | Optimizer | Better solutions for overlapping market clusters |
| On-chain data pipeline | Ingestor | Ground truth backtesting |
| Self-hosted LLM classifier | Detector | Free inference, potentially better accuracy |

---

## References

1. Saguillo, O. et al. "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets." LIPIcs.AFT.2025.27. https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2025.27
2. Chan, T.-H.H., Wu, K., Shi, E. "Mechanism Design for Automated Market Makers." LIPIcs.AFT.2025.7. https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2025.7
3. Nadkarni, V., Kulkarni, S., Viswanath, P. "Adaptive Curves for Optimally Efficient Market Making." LIPIcs.AFT.2024.25. https://arxiv.org/abs/2406.13794
4. Singh, S.F. et al. "Modeling Loss-Versus-Rebalancing in AMMs via Continuous-Installment Options." LIPIcs.AFT.2025.6. https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2025.6
5. Trotti, B.L. et al. "Strategic Analysis of Just-In-Time Liquidity Provision in CLMMs." LIPIcs.AFT.2025.8. https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2025.8
6. "Measuring CEX-DEX Extracted Value and Searcher Profitability." LIPIcs.AFT.2025.26. https://drops.dagstuhl.de/storage/00lipics/lipics-vol354-aft2025/LIPIcs.AFT.2025.26/LIPIcs.AFT.2025.26.pdf
7. Fang, Y. et al. "Designing AMMs for Combinatorial Securities: A Geometric Viewpoint." SODA 2025 / arXiv:2411.08972. https://arxiv.org/abs/2411.08972
