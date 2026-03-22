# PolyArb — Research Sources & Reading List

All papers and resources that directly relate to, inform, or could improve the PolyArb system. Organized by relevance to each system component.

---

## CORE ALGORITHM — Frank-Wolfe / Bregman Projection

### 1. Arbitrage-Free Combinatorial Market Making via Integer Programming
**Kroer, Dudík, Lahaie & Pennock (2016)** — ACM EC '16
- **Link:** https://arxiv.org/abs/1606.02825
- **Relevance:** This is the paper your Frank-Wolfe optimizer implements. FWMM algorithm: Bregman projection via Frank-Wolfe with IP oracle onto the marginal polytope. Demonstrated on NCAA brackets (2^63 outcomes).
- **How it helps:** You're already using this. Could cite more precisely in a paper. Their convergence analysis (Section 4) gives you theoretical backing for your gap_tolerance parameter.

### 2. Designing Automated Market Makers for Combinatorial Securities: A Geometric Viewpoint
**Frongillo, Kash & Waggoner (2024)**
- **Link:** https://arxiv.org/abs/2411.08972
- **Relevance:** Extends the combinatorial market maker theory with a geometric/VC-dimension approach. Shows when sublinear-time algorithms exist for combinatorial markets.
- **How it helps:** Could inform whether your pairwise approach (small constraint matrices) is theoretically justified vs. scaling to N-way arbitrage. Their framework might reveal tractability boundaries for extending PolyArb to 3+ market groups.

### 3. Efficient Projections onto the ℓ₁-Ball for Learning in High Dimensions
**Duchi, Shalev-Shwartz, Singer & Chandra (2008)** — ICML '08
- **Link:** https://www.semanticscholar.org/paper/ed7c7c079c8c54d3b82e016cc52a7a2c3a61f237
- **Relevance:** The simplex projection algorithm you use in `bregman.py` (project_to_simplex). O(n) expected time.
- **How it helps:** Already implemented. Cite in paper for the projection step.

---

## SEMANTIC DISCOVERY — Embedding-Based Market Pairing

### 4. Semantic Trading: Agentic AI for Clustering and Relationship Discovery in Prediction Markets
**Capponi, Gliozzo & Zhu (Columbia / IBM, Dec 2025)**
- **Link:** https://arxiv.org/abs/2512.02436
- **Relevance:** DIRECTLY RELEVANT. Independently developed the same core idea — using LLM embeddings to find correlated prediction markets. Uses clustering + statistical validation on Polymarket. Reports ~60-70% accuracy and ~20% average returns over week-long horizons.
- **How it helps:** Compare your pgvector KNN approach against their clustering approach. Their accuracy numbers are a benchmark. Their trading strategy results are a direct comparison point. If your FW-optimized trades beat their simple strategy, that's a strong paper contribution.

### 5. Semantic Non-Fungibility and Violations of the Law of One Price in Prediction Markets
**Gebele & Matthes (Jan 2026)**
- **Link:** https://arxiv.org/abs/2601.01706
- **Relevance:** DIRECTLY RELEVANT. Built the first human-validated cross-platform dataset of aligned prediction markets across 10 venues (100K+ events, 2018-2025). Found ~6% of events are listed across platforms with persistent 2-4% price deviations.
- **How it helps:** Their dataset could validate your cross-platform detector. Their 2-4% deviation finding tells you the expected magnitude of cross-platform arbitrage. Their "semantic non-fungibility" framing is exactly the problem your embedding-based matching solves. You should cite this prominently and potentially use their dataset for evaluation.

### 6. LLM as a Risk Manager: LLM Semantic Filtering for Lead-Lag Trading in Prediction Markets
**arXiv:2602.07048 (Feb 2026)**
- **Link:** https://arxiv.org/abs/2602.07048
- **Relevance:** Uses LLM semantic analysis as a filter on top of statistical (Granger causality) lead-lag discovery in Kalshi markets. Hybrid statistical + LLM approach mirrors your hybrid rule-based + LLM classifier. Shows win rate improvement from 51.4% to 54.5%.
- **How it helps:** Their two-stage statistical→LLM pipeline validates your architectural choice of rules-first, LLM-fallback. Their Kalshi-specific results could inform your Kalshi integration. The "LLM as risk manager" framing could apply to your LLM classifier too.

---

## EMPIRICAL STUDIES — Prediction Market Arbitrage

### 7. Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets
**Saguillo, Ghafouri, Kiffer & Suarez-Tangil (AFT 2025, Flashbots)**
- **Link:** https://arxiv.org/abs/2508.03474
- **Relevance:** CRITICAL BENCHMARK. The most comprehensive empirical study of Polymarket arbitrage. Uses LLM + heuristic approach similar to yours. Found $40M total arbitrage profit extracted. Combinatorial arbitrage = 0.24% of profits with 62% failure rate. Market rebalancing arbitrage is the dominant form.
- **How it helps:** Your results should be compared against their findings. If your system captures more combinatorial arbitrage or has a lower failure rate, that's a major contribution. Their methodology section describes similar detection approaches. Their failure rate analysis (why arbs fail) could inform your circuit breaker design.

### 8. The Anatomy of Polymarket: Evidence from the 2024 Presidential Election
**arXiv:2603.03136 (March 2026)**
- **Link:** https://arxiv.org/abs/2603.03136
- **Relevance:** Transaction-level analysis of Polymarket using 124M+ trades. Volume decomposition (exchange-matched vs claim issuance/redemption). Documents market efficiency, liquidity evolution, and participant behavior.
- **How it helps:** Understanding Polymarket's microstructure improves your VWAP simulation. Their liquidity findings inform realistic slippage assumptions. Their efficiency analysis tells you which market types are most/least efficient (where arbitrage is most likely to persist).

### 9. How Manipulable Are Prediction Markets?
**arXiv:2503.03312 (March 2025)**
- **Link:** https://arxiv.org/abs/2503.03312
- **Relevance:** Experimental study of prediction market manipulation. Relevant because manipulation creates temporary mispricings that your system might detect as "arbitrage."
- **How it helps:** Understanding manipulation patterns helps distinguish real arbitrage from manipulation-induced price dislocations. Could inform a filter to avoid trading into manipulated markets (reduce false positives).

### 10. Manipulation in Prediction Markets: An Agent-Based Modeling Experiment
**arXiv:2601.20452 (Jan 2026)**
- **Link:** https://arxiv.org/abs/2601.20452
- **Relevance:** Agent-based model of how high-budget agents distort prediction market prices. Studies persistence of price distortions.
- **How it helps:** Informs whether the mispricings you detect are likely to persist long enough to trade, or whether they're manipulation artifacts that revert before execution.

---

## BACKTESTING & BENCHMARKING

### 11. PredictionMarketBench: A SWE-bench-Style Framework for Backtesting Trading Agents on Prediction Markets
**arXiv:2602.00133 (Jan 2026)**
- **Link:** https://arxiv.org/abs/2602.00133
- **GitHub:** https://github.com/Oddpool/PredictionMarketBench
- **Relevance:** DIRECTLY USEFUL. Standardized backtesting framework for prediction market trading agents. Event-driven replay of historical limit-order-book data from Kalshi. Includes fee-aware execution simulation.
- **How it helps:** Could adopt their benchmarking methodology for your backtest. Their episodes (crypto, weather, sports) could supplement your backfill data. Reporting results in their format would make your paper directly comparable. Their execution simulator validates (or challenges) your VWAP simulation approach.

---

## POSITION SIZING & RISK MANAGEMENT

### 12. Application of the Kelly Criterion to Prediction Markets
**arXiv:2412.14144 (Dec 2024)**
- **Link:** https://arxiv.org/abs/2412.14144
- **Relevance:** Applies Kelly criterion specifically to prediction markets (bounded prices). Analyzes how mean beliefs differ from prices and uses KL divergence for strategy performance. Directly relevant to your half-Kelly sizing.
- **How it helps:** Your half-Kelly implementation is heuristic. This paper provides the formal treatment for bounded-price markets. Could justify your 0.5 scaling factor or suggest a better one. Their KL divergence analysis connects directly to your FW optimizer's objective.

### 13. Optimal Betting: Beyond the Long-Term Growth
**arXiv:2503.17927 (March 2025)**
- **Link:** https://arxiv.org/abs/2503.17927
- **Relevance:** Shows every fractional Kelly strategy can be realized using a CLT-based risk measure. Introduces asymptotic variance of long-term growth rate.
- **How it helps:** Could replace your linear drawdown scaling (100%→50% across 5-10% drawdown) with a theoretically grounded risk-adjusted Kelly fraction.

### 14. Kelly Betting as Bayesian Model Evaluation
**arXiv:2602.09982 (Feb 2026)**
- **Link:** https://arxiv.org/abs/2602.09982
- **Relevance:** Shows how to calculate unique odds where Kelly-following bettors agree, and how to update bet sizes as probabilities change.
- **How it helps:** Relevant if you want to dynamically adjust position sizes as prices move between detection and execution.

---

## MARKET STRUCTURE & INFRASTRUCTURE

### 15. Polymarket CLOB Documentation
- **Link:** https://docs.polymarket.com/developers/CLOB/introduction
- **Relevance:** Official API docs. Hybrid-decentralized CLOB with off-chain matching, on-chain settlement.
- **How it helps:** Reference for accurate fee modeling. Every BUY for outcome 1 at price X is a SELL for outcome 2 at (100¢ - X) — this affects your constraint matrix interpretation for binary markets.

### 16. Prediction Laundering: The Illusion of Neutrality, Transparency, and Governance in Polymarket
**arXiv:2602.05181 (Feb 2026)**
- **Link:** https://arxiv.org/abs/2602.05181
- **Relevance:** Qualitative analysis of how whale activity and strategic hedges create noise in Polymarket prices. Introduces "prediction laundering" concept.
- **How it helps:** Understanding capital asymmetries and strategic behavior helps interpret why certain mispricings exist and persist. May explain why some detected "arbitrage" is actually informed positioning.

---

## VECTOR SEARCH INFRASTRUCTURE

### 17. pgvector — Open-Source Vector Similarity Search for Postgres
- **Link:** https://github.com/pgvector/pgvector
- **Relevance:** Your HNSW index implementation for embedding-based market pairing.
- **How it helps:** Track updates for performance improvements. Current HNSW benchmarks show ~1.5ms query time at 58K documents — useful for your scalability claims.

### 18. HNSW: Hierarchical Navigable Small World Graphs
**Malkov & Yashunin (2018)**
- **Link:** https://arxiv.org/abs/1603.09320
- **Relevance:** The original HNSW paper. Explains the algorithm behind pgvector's approximate nearest neighbor search.
- **How it helps:** Cite for the theoretical backing of your O(k·log n) similarity search claim.

---

## SUGGESTED READING ORDER

**If writing a paper (priority):**
1. #7 (Unravelling) — your primary comparison point
2. #4 (Semantic Trading) — independent validation of your approach
3. #5 (Semantic Non-Fungibility) — cross-platform dataset + framing
4. #1 (Kroer et al.) — reread for precise citation
5. #12 (Kelly in prediction markets) — formalize your sizing
6. #11 (PredictionMarketBench) — adopt their benchmarking format

**If improving the system (priority):**
1. #5 (Semantic Non-Fungibility) — their 100K event dataset for validation
2. #6 (LLM as Risk Manager) — improve your LLM classifier with lead-lag filtering
3. #8 (Anatomy of Polymarket) — calibrate VWAP/slippage assumptions
4. #2 (Geometric AMM design) — assess feasibility of N-way arbitrage
5. #11 (PredictionMarketBench) — standardize your backtest methodology
6. #13 (Optimal Betting) — replace heuristic drawdown scaling with theory
