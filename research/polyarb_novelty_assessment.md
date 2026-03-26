# PolyArb: Novelty Assessment & Paper Potential

## Executive Summary

**Bottom line: You didn't fully reinvent the wheel, but you built a meaningfully differentiated vehicle.** The Frank-Wolfe optimizer is a faithful implementation of Kroer, Dudík, Lahaie & Balakrishnan (2016), so the core optimization isn't new. But the *end-to-end system* — semantic discovery → rule-based + LLM classification → FW optimization → VWAP paper trading — is a novel engineering contribution, and several individual components have no direct precedent in the literature. With enough backtest/paper-trade data, there is absolutely a publishable paper here.

---

## Component-by-Component Breakdown

### 1. Frank-Wolfe Optimizer — ⚙️ Reinvented Wheel

**What you did:** KL-divergence Bregman projection onto the marginal polytope using Frank-Wolfe with a CP-SAT integer programming oracle. Standard FW step schedule (γ = 2/(t+2)), duality gap convergence criterion, Duchi et al. simplex projection.

**Prior art:** This is essentially the FWMM algorithm from Kroer et al. (2016, ACM EC '16), which you correctly cite. That paper demonstrated it on NCAA tournament brackets (2^63 outcome space). Your implementation is clean and correct, but the *algorithm itself* is not novel.

**What's different in your version:**
- You apply it to *pairwise* arbitrage (2-market constraint matrices) rather than the full combinatorial market maker setting Kroer et al. target. Their formulation handles N markets with exponential outcome spaces; yours handles pairs with small feasibility matrices. This is a simplification, not an extension.
- Your IP oracle uses OR-Tools CP-SAT rather than a general MIP solver — a practical choice but not algorithmically different.

**Verdict:** Solid implementation of known algorithm. Not publishable on its own.

---

### 2. Semantic Market Pairing (pgvector + embeddings) — 🟡 Partially Novel

**What you did:** Embed market questions with OpenAI text-embedding-3-small (384-dim), store in pgvector, use HNSW cosine KNN to find candidate pairs. O(k·log n) instead of O(n²).

**Prior art:**
- The **"Semantic Trading"** paper (arxiv:2512.02436, Dec 2025) independently developed a very similar idea — LLM-based semantic clustering to find correlated prediction markets. They use clustering + statistical validation rather than KNN, but the core insight (use text embeddings to find related markets) is shared.
- The **"Unravelling the Probabilistic Forest"** paper (AFT 2025) also uses LLM heuristics for topical similarity.

**What's different in your version:**
- You use **vector database infrastructure** (pgvector HNSW) for real-time, incremental search rather than batch clustering. This is an engineering distinction with practical consequences — your system can discover new pairs within seconds of market creation.
- Your threshold (0.82 cosine similarity) is tunable and continuously applied, vs. one-shot clustering.
- Neither prior paper uses a production vector database for this purpose.

**Verdict:** The *idea* was independently discovered (you and Semantic Trading converged). Your *implementation approach* (pgvector KNN for continuous discovery) is novel infrastructure.

---

### 3. Hybrid Rule-Based + LLM Dependency Classification — 🟢 Novel

**What you did:** A two-tier classifier where hand-crafted regex rules handle structured market types (price thresholds, crypto intervals, rankings, O/U lines, milestone thresholds) with 0.95 confidence, and GPT-4.1-mini handles ambiguous cases. Seven distinct rule-based classifiers covering Polymarket-specific market structures.

**Prior art:**
- Semantic Trading uses LLM for relationship discovery but doesn't describe domain-specific rule engines.
- "Unravelling" uses LLM heuristics but without the rule-based fast path.
- No published system has a taxonomy of Polymarket market types (price thresholds, crypto time intervals, milestone thresholds, ranking markets, O/U lines) with regex-based classification.

**What's novel:**
- The **domain-specific rule engine** is genuinely new. Nobody has published a systematic taxonomy of prediction market dependency types with deterministic classifiers for each type.
- The **hybrid architecture** (rules first, LLM fallback) is a practical contribution — it's faster, cheaper, more auditable, and has higher precision for structured markets.
- The five dependency types (implication, partition, mutual_exclusion, conditional, cross_platform) with explicit constraint matrix generation is a clean formalization that doesn't appear in the literature.

**Verdict:** This is your strongest novelty claim. The taxonomy + rule engine + LLM fallback is a genuine contribution.

---

### 4. Constraint Matrix Formalization — 🟢 Novel (in this context)

**What you did:** Binary feasibility matrices encoding logical relationships between market outcomes, with closed-form profit bounds for each dependency type. The conditional pair handling (price divergence threshold, sum bounds) is particularly interesting.

**Prior art:** Kroer et al. use feasibility constraints but in the context of full combinatorial markets, not pairwise cross-market arbitrage with dependency-typed constraints.

**What's novel:**
- The mapping from {implication, partition, mutual_exclusion, conditional, cross_platform} → specific binary matrices is a clean contribution.
- The conditional pair constraints using price divergence thresholds (0.15) and sum bounds (0.85, 1.15) are heuristic but novel.
- Closed-form profit bounds per dependency type are useful and not in the literature.

**Verdict:** Nice formalization. Publishable as part of a system paper.

---

### 5. VWAP Paper Trading with Circuit Breakers — 🟡 Engineering Contribution

**What you did:** Order-book-walking VWAP simulation, two-phase validate-all-then-execute atomic trades, half-Kelly sizing with drawdown scaling, portfolio state restoration from trade history, circuit breaker with auto-cooldown.

**Prior art:**
- VWAP execution is well-studied in equities/crypto (arxiv:2502.13722). Paper trading methodology is standard.
- Half-Kelly sizing is textbook.
- Circuit breakers are standard in production trading systems.

**What's different:**
- Application to **thin prediction markets** where order books are sparse and price impact is significant — most VWAP research assumes liquid markets.
- The **two-phase atomic execution** (validate all legs before executing any) is a practical innovation for multi-leg arbitrage.
- Backtest infrastructure with **day-by-day pipeline replay** (not just signal replay) is more rigorous than typical prediction market backtests.

**Verdict:** Standard techniques applied to a novel domain. Not independently publishable but supports the system contribution.

---

### 6. Cross-Platform Arbitrage (Polymarket ↔ Kalshi) — 🟡 Partially Novel

**What you did:** Cross-platform identity constraints, venue-specific fee models, embedding-based matching across venues.

**Prior art:**
- Eventarb and Polytrage already offer cross-platform monitoring.
- The "Unravelling" paper documents cross-platform arbitrage.

**What's different:**
- Your system integrates cross-platform into the same FW optimization framework rather than treating it as simple spread monitoring.
- Venue-specific fee functions in the profit bound computation.

**Verdict:** Incremental over existing tools but nicely unified into the optimization framework.

---

### 7. End-to-End Reactive Architecture — 🟢 Novel System Design

**What you did:** Ingestor → Detector → Optimizer → Simulator pipeline with Redis pub/sub event bus, 8 channels, debounced rescans, periodic + reactive triggers, and the full cycle from market creation to settlement.

**Prior art:** No published system describes a full reactive pipeline for prediction market arbitrage. Existing tools are either monitoring-only or black-box bots.

**What's novel:**
- The reactive architecture where a price snapshot triggers a lightweight detector rescan, which triggers optimization, which triggers paper trading — all within seconds.
- Full lifecycle management including market resolution and position settlement.

**Verdict:** Strong systems contribution. Publishable as part of a system paper.

---

## Paper Potential: What You Could Write

### Option A: Full Systems Paper (Best Fit)

**Title idea:** "PolyArb: Semantic Discovery and Optimization of Combinatorial Arbitrage in Prediction Markets"

**Venue:** ACM Conference on Economics and Computation (EC), Advances in Financial Technologies (AFT), or The Journal of Prediction Markets

**Contributions you can claim:**

1. **A taxonomy of cross-market dependency types** in prediction markets (implication, partition, mutual exclusion, conditional, cross-platform) with formal constraint matrix representations — this is new.

2. **A hybrid rule-based + LLM classification pipeline** that handles structured market types (price thresholds, time intervals, rankings) deterministically while using LLM for ambiguous cases — first published system to do this.

3. **Application of Frank-Wolfe Bregman projection** to *pairwise* cross-market arbitrage detection in live prediction markets — Kroer et al. demonstrated it for market making; you're using it for arbitrage detection, which is a different application.

4. **End-to-end system** from semantic discovery through optimization to simulated execution, with empirical evaluation on live Polymarket/Kalshi data.

5. **Empirical results** — this is the key missing piece. You need:
   - Backtest results across multiple market types (crypto, politics, sports)
   - Paper trading P&L over a meaningful time period (3-6 months)
   - Classification accuracy (rule-based vs. LLM, false positive rates)
   - Execution quality (VWAP slippage, fill rates)
   - Comparison to naive strategies (simple spread monitoring)

### Option B: Focused Methodology Paper

**Title idea:** "Classifying Logical Dependencies in Prediction Markets: A Hybrid Rule-Based and LLM Approach"

**Venue:** Workshop paper at EC or AAAI, or short paper at AFT

**Contributions:** Just the classification system + constraint matrix formalization, with evaluation on labeled market pairs.

### Option C: Empirical Paper (if trading results are strong)

**Title idea:** "How Much Arbitrage Exists in Prediction Markets? Evidence from Automated Cross-Market Detection"

**Venue:** Journal of Prediction Markets, or finance workshop

**Contributions:** Empirical characterization of arbitrage frequency, magnitude, duration, and execution feasibility across dependency types.

---

## What You Need to Do to Make the Paper Happen

### Critical Missing Pieces

1. **Labeled evaluation dataset** — Manually label 500+ market pairs with ground-truth dependency types to measure classifier precision/recall. This is the most important piece.

2. **Extended backtest** — Run the full pipeline on 6+ months of historical data. Report:
   - Number of opportunities detected per dependency type
   - Theoretical profit vs. realized profit (after slippage + fees)
   - Execution success rate and reasons for failure
   - Comparison of FW-optimal trades vs. naive heuristic trades

3. **Paper trading track record** — 3-6 months of live paper trading with real-time market data. Report:
   - Cumulative P&L curve
   - Sharpe ratio, max drawdown
   - Win rate by dependency type
   - Average hold time and settlement outcomes

4. **Ablation studies** — Show that each component matters:
   - Embedding similarity threshold sensitivity
   - Rule-based vs. LLM-only classification accuracy
   - FW optimization vs. simple profit bound
   - VWAP vs. midpoint execution quality

5. **Comparison to the "Unravelling" paper's findings** — They report combinatorial arbitrage is only 0.24% of prediction market profits with a 62% failure rate. Your system should either confirm or challenge this finding with better data.

---

## Honest Assessment

| Component | Novelty | Publishable Alone? |
|-----------|---------|-------------------|
| Frank-Wolfe optimizer | Low (known algorithm) | No |
| Semantic pairing (pgvector) | Medium (concurrent discovery) | No |
| Hybrid classifier + taxonomy | High | Maybe (workshop) |
| Constraint matrices | Medium-High | No (but supports system paper) |
| VWAP paper trading | Low (standard techniques) | No |
| Cross-platform integration | Low-Medium | No |
| End-to-end reactive system | High | Yes (system paper) |
| **Combined system + empirical results** | **High** | **Yes — this is the paper** |

**The paper isn't about any single component — it's about the complete pipeline and the empirical evidence it produces.** The literature has theory (Kroer et al.), monitoring tools (Polytrage, Eventarb), and recent semantic approaches (Semantic Trading) — but nobody has published a complete, evaluated system that goes from discovery through optimization to simulated execution with real market data.

If your backtest and paper trading results show positive risk-adjusted returns, you have a strong paper. If results are mixed or negative, you still have a valuable empirical contribution ("here's how much combinatorial arbitrage actually exists and why it's hard to capture").

---

## Recommended Next Steps

1. Run extended backtest (scripts/backtest.py) across all available historical data
2. Start a 3-month paper trading period with detailed logging
3. Build the labeled evaluation dataset for classifier accuracy
4. Draft the paper structure around your strongest results
5. Target AFT 2027 or EC 2027 (submission deadlines typically 3-6 months before conference)
