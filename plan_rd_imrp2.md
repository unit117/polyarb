# plan_rd_imrp2 — AFT-Derived Improvements

**Status:** Draft
**Source:** `research/aft-review-2025.md` (AFT 2024–2025 conference review)
**Branch:** `feat/aft-improvements` (create from `main`)

---

## Phase 1 — Quick Wins (detector + simulator filters)

These are small, low-risk changes that can ship independently. Each is a single PR.

### 1.1 NegRisk Intra-Market Detection

**Paper:** Saguillo et al. (AFT 2025) — $28.9M extracted via NegRisk rebalancing vs $95K combinatorial.

**What:** Add a new scan mode to the detector that identifies single-market arbitrage within NegRisk market sets. When the sum of YES prices for all conditions in a NegRisk group deviates from 1.0 by more than a threshold, emit an arbitrage opportunity where the trade is to buy NO on the overpriced condition(s).

**Files to change:**
- `services/detector/pipeline.py` — add `_scan_negrisk()` periodic task alongside existing `_scan_pairs()`
- `services/detector/negrisk.py` — **new file**: query latest `price_snapshots` grouped by `event_id`, compute YES-sum deviation, emit opportunities when deviation > 0.05 after fees
- `shared/models.py` — add `ArbitrageType.NEGRISK_REBALANCE` enum value (or extend existing `type` column)
- `shared/events.py` — add `CHANNEL_NEGRISK_ARB` or reuse `CHANNEL_ARBITRAGE_FOUND` with a type discriminator
- `alembic/versions/012_*.py` — migration if schema changes needed for new arb type

**Config (`.env`):**
- `NEGRISK_DEVIATION_THRESHOLD=0.05` — minimum YES-sum deviation to flag
- `NEGRISK_SCAN_INTERVAL=30` — seconds between scans

**Acceptance criteria:**
- On backtest DB, finds NegRisk opportunities that Saguillo et al. documented
- Emits to Redis, simulator can pick up and paper-trade them
- Does not interfere with existing pair-based detection

**Estimated effort:** 1-2 days

---

### 1.2 Uncertainty Filter

**Paper:** Saguillo et al. — max outcome <0.95 filter to ignore near-resolved markets.

**What:** Skip markets from pair detection and NegRisk scanning when any outcome is priced above 0.95. These are effectively resolved and generate false arbitrage signals.

**Files to change:**
- `services/detector/similarity.py` — add WHERE clause to the anchor query: exclude markets where latest snapshot has any outcome > 0.95
- `services/detector/pipeline.py` — apply same filter in rescan path
- `services/detector/negrisk.py` — filter in NegRisk scan query

**Config:**
- `UNCERTAINTY_CEILING=0.95`

**Acceptance criteria:**
- Markets with a 0.97 outcome are excluded from detection
- Existing pairs involving near-resolved markets stop generating new opportunities
- Log the number of markets filtered per cycle for observability

**Estimated effort:** 0.5 days

---

### 1.3 Minimum Trade Filter

**Paper:** Saguillo et al. — trades <$2 are noise.

**What:** In the simulator, reject opportunities where any leg's optimal size (after Kelly + drawdown scaling) would be below $2.

**Files to change:**
- `services/simulator/pipeline.py` — add check after sizing, before execution: if any leg < $2, skip with log
- `shared/config.py` — add `MIN_TRADE_SIZE=2.0`

**Acceptance criteria:**
- Tiny trades no longer clutter paper_trades table
- P&L reporting is cleaner (fewer sub-penny wins/losses)

**Estimated effort:** 0.5 days

---

### 1.4 Kalman-Filtered Fair Value

**Paper:** Nadkarni et al. (AFT 2024) — adaptive pricing via Kalman filter on trade stream.

**What:** Add a per-market Kalman filter to the ingestor's price stream. Maintain a smoothed "fair value" estimate alongside raw CLOB prices. The optimizer and simulator use the filtered estimate for edge calculations instead of noisy midpoints.

**Files to change:**
- `services/ingestor/kalman.py` — **new file**: lightweight 1D Kalman filter class
  - State: estimated price (μ), uncertainty (σ²)
  - Parameters: process noise Q (from recent price variance), observation noise R (from bid-ask spread / 2)
  - Update on each price snapshot
  - Expose `filtered_price` and `confidence` (1/σ²)
- `services/ingestor/ws_client.py` — after writing `price_snapshot`, update Kalman filter; publish filtered price alongside raw
- `services/ingestor/polling.py` — same integration for poll-based updates
- `shared/models.py` — add `filtered_price` and `price_confidence` columns to `price_snapshots` (nullable, backfill not required)
- `services/optimizer/trades.py` — use `filtered_price` when available for edge calculation
- `services/simulator/pipeline.py` — use `filtered_price` for VWAP edge validation
- `alembic/versions/012_*.py` or `013_*.py` — migration for new columns

**Config:**
- `KALMAN_PROCESS_NOISE=0.001` — Q parameter (tune from backtest)
- `KALMAN_OBSERVATION_NOISE=0.01` — R default (overridden by half-spread when available)

**Acceptance criteria:**
- Filtered prices are within ±2% of raw for stable markets, significantly smoother for volatile ones
- Edge calculations use filtered price; false-positive arb signals decrease measurably on backtest
- Dashboard shows both raw and filtered price (optional stretch)

**Estimated effort:** 2-3 days

---

## Phase 2 — Detector Upgrades

### 2.1 Temporal Alignment Pre-Filter

**Paper:** Saguillo et al. — three-filter pipeline starts with temporal alignment.

**What:** Before running embedding similarity, pre-filter market candidates by resolution date overlap. Two markets that don't overlap in time cannot have combinatorial dependencies. This reduces the candidate set passed to pgvector KNN, cutting both query time and LLM classification costs.

**Files to change:**
- `services/detector/similarity.py` — add a CTE or subquery that joins on `markets.end_date` overlap with the anchor's date range (±7 days tolerance for markets without exact dates)
- `shared/models.py` — ensure `end_date` / `resolution_date` is populated (may need ingestor changes to parse from Gamma API)

**Config:**
- `TEMPORAL_OVERLAP_DAYS=7` — tolerance window

**Acceptance criteria:**
- Candidate set for KNN is 30-50% smaller on typical market snapshots
- No valid pairs missed (validate against existing `market_pairs` table)

**Estimated effort:** 1-2 days

---

### 2.2 Embedding Model Upgrade

**Paper:** Saguillo et al. used Linq-Embed-Mistral (1024-dim, stronger MTEB scores).

**What:** Switch from `text-embedding-3-small` (384-dim) to `text-embedding-3-large` (3072-dim, reducible to 1024 via Matryoshka). This stays in the OpenAI ecosystem (no new infra) while significantly improving semantic clustering quality.

**Files to change:**
- `services/ingestor/embedder.py` — change model string, update dimension parameter, add `dimensions=1024` to reduce output size
- `shared/models.py` — update `Vector(384)` → `Vector(1024)` on `markets.embedding`
- `alembic/versions/NNN_*.py` — migration to alter column type (requires re-embedding)
- `scripts/reembed_markets.py` — **new script**: batch re-embed all existing markets
- `services/detector/similarity.py` — update HNSW index parameters if needed (larger dim may need different `ef_construction`)
- `shared/config.py` — add `EMBEDDING_MODEL=text-embedding-3-large` and `EMBEDDING_DIMENSIONS=1024`

**Rollout:**
1. Deploy with dual-write (embed with both models, store new dim)
2. Run `reembed_markets.py` to backfill
3. Rebuild HNSW index
4. Switch detector to new column
5. Drop old column

**Acceptance criteria:**
- Cosine similarity scores on known-good pairs are higher than before
- New pairs discovered that were missed at 384-dim
- No regression in detection latency (HNSW at 1024 is still fast)

**Estimated effort:** 3-5 days (including re-embedding + validation)

---

### 2.3 Top-K Condition Reduction

**Paper:** Saguillo et al. — top-4 conditions + "Other" captures 90% liquidity.

**What:** For multi-outcome markets (>4 conditions), reduce to top-4 by liquidity plus an aggregated "Other" bucket. This caps constraint matrices at 5×5 and makes the IP oracle tractable for markets that currently blow up (e.g., "Who wins the primary?" with 20+ candidates).

**Files to change:**
- `services/detector/constraints.py` — add reduction step before matrix generation: sort outcomes by latest price (proxy for liquidity), keep top-4, merge rest into "Other" with aggregated probability
- `services/optimizer/ip_oracle.py` — no changes needed (already handles arbitrary matrix sizes)
- `services/optimizer/trades.py` — map trades back from reduced outcomes to original market outcomes

**Config:**
- `MAX_OUTCOMES_PER_MARKET=5` — including "Other"

**Acceptance criteria:**
- Markets with 10+ outcomes now produce valid constraint matrices
- IP oracle solve time drops from timeout to <100ms on these markets
- Trade mapping correctly identifies which original outcome to trade

**Estimated effort:** 2-3 days

---

### 2.4 LLM Classifier Upgrade

**Paper:** Saguillo et al. — DeepSeek-R1-Distill-Qwen-32B with chain-of-thought for resolution vectors.

**What:** Upgrade the LLM classifier from `gpt-4.1-mini` to a model that outputs resolution vectors (JSON of valid outcome combinations) rather than just dependency type labels. This gives the constraint matrix generator richer input and handles edge cases better.

**Options (pick one):**
- **Option A:** Keep OpenAI, upgrade to `gpt-4.1` with structured output (JSON mode) and resolution-vector prompting. Higher cost but zero infra change.
- **Option B:** Self-host DeepSeek-R1-Distill-Qwen-32B on the NAS (requires ~20GB VRAM, may not fit). Free inference, matches paper methodology.
- **Option C:** Use Anthropic Claude (claude-sonnet-4-5-20250514) via API with resolution-vector prompting. Good reasoning, moderate cost.

**Files to change:**
- `services/detector/classifier.py` — new prompt template that requests resolution vector output; parse JSON response into constraint matrix directly
- `services/detector/constraints.py` — add `from_resolution_vector()` constructor that builds the feasibility matrix from the LLM's output (list of valid outcome tuples)
- `shared/config.py` — `CLASSIFIER_MODEL` and `CLASSIFIER_PROVIDER` settings

**Acceptance criteria:**
- Accuracy on a held-out set of 50 manually-classified pairs ≥ 85%
- Resolution vectors correctly enumerate valid outcome combos
- Fallback to rule-based classification if LLM output is malformed

**Estimated effort:** 3-5 days (including prompt engineering + validation)

---

## Phase 3 — Optimizer Improvements

### 3.1 Warm-Start Frank-Wolfe

**What:** Cache the last FW solution per pair. When re-scanning, initialize from the cached solution instead of from a deterministic feasible vertex. Expected to converge in 1-5 iterations when prices haven't moved much.

**Files to change:**
- `services/optimizer/pipeline.py` — maintain `_solution_cache: dict[int, np.ndarray]` keyed by pair_id; pass to FW solver as `initial_point`
- `services/optimizer/frank_wolfe.py` — accept optional `initial_point` parameter; validate it's still feasible before using; fall back to cold start if not
- `shared/config.py` — `FW_WARM_START=true`, `FW_SOLUTION_CACHE_TTL=600` (expire stale solutions)

**Acceptance criteria:**
- Re-scans of unchanged pairs converge in ≤5 iterations (vs ~30-50 cold)
- No correctness regression (solutions within 0.001 gap of cold-start solutions)
- Cache eviction works; memory usage bounded

**Estimated effort:** 1-2 days

---

### 3.2 Adaptive Iteration Budget

**What:** Replace fixed 200-iteration cap with an adaptive budget. Start at 50; if gap is still decreasing at 50, extend by 50 up to 500 max. This lets binary pairs finish fast while giving multi-outcome pairs room to converge.

**Files to change:**
- `services/optimizer/frank_wolfe.py` — replace `range(max_iterations)` with a while loop that checks convergence rate every 50 iterations; break early or extend
- `shared/config.py` — `FW_MIN_ITERATIONS=50`, `FW_MAX_ITERATIONS=500`, `FW_EXTENSION_BLOCK=50`

**Acceptance criteria:**
- Binary pairs terminate in ~30-50 iterations (same as before)
- Multi-outcome pairs that were hitting 200-iteration ceiling now converge properly
- Log iteration count per solve for monitoring

**Estimated effort:** 0.5 days

---

### 3.3 IP Oracle Caching

**What:** Cache the LP relaxation vertex for quantized gradient directions. When two consecutive FW iterations have similar gradients, reuse the cached vertex instead of re-solving.

**Files to change:**
- `services/optimizer/ip_oracle.py` — add LRU cache keyed by quantized gradient hash (round to 2 decimal places); cache size ~1000 entries
- `services/optimizer/frank_wolfe.py` — pass cache to oracle; log cache hit rate

**Acceptance criteria:**
- Cache hit rate >30% on typical binary pairs
- Solve time per FW run decreases by 20-40%
- No correctness regression

**Estimated effort:** 1 day

---

## Phase 4 — Simulator & Execution

### 4.1 Adaptive Slippage Model

**What:** Replace fixed 0.5% slippage fallback with a per-market rolling estimate derived from recent VWAP calculations and bid-ask spreads.

**Files to change:**
- `services/simulator/vwap.py` — after each VWAP calculation, record realized slippage to a per-market rolling window (in-memory, 24h window)
- `services/simulator/slippage.py` — **new file**: `SlippageEstimator` class that maintains rolling stats per market; returns `estimated_slippage(market_id)` as max(half-spread, rolling_median_slippage, 0.1%)
- `services/simulator/pipeline.py` — use `SlippageEstimator` instead of hardcoded 0.5%
- `shared/config.py` — `SLIPPAGE_FLOOR=0.001`, `SLIPPAGE_WINDOW_HOURS=24`

**Acceptance criteria:**
- Liquid markets get lower slippage estimates (closer to 0.1-0.2%)
- Illiquid markets get higher estimates (0.5-2%)
- Backtest P&L is more realistic (fewer phantom profits on illiquid markets)

**Estimated effort:** 2 days

---

### 4.2 NegRisk Execution Logic

**What:** Teach the simulator how to execute NegRisk rebalancing trades. The key difference: instead of buying YES on one market and NO on another, NegRisk arb buys NO tokens on the overpriced condition(s) within a single market set, profiting when the YES-sum reverts to 1.0.

**Files to change:**
- `services/simulator/pipeline.py` — add `_execute_negrisk_opportunity()` handler that routes NegRisk arb opportunities to the correct execution path
- `services/simulator/portfolio.py` — handle NegRisk positions: track NO-token holdings per condition; settlement via NegRisk adapter (complete set redemption when one condition resolves YES)
- `services/simulator/vwap.py` — NegRisk trades go through the same CLOB order book but on the NO side

**Dependencies:** Requires 1.1 (NegRisk detection) to be complete.

**Acceptance criteria:**
- Paper-trades NegRisk opportunities detected by 1.1
- Correct P&L accounting: NO position settles at 1.0 if the condition resolves NO, 0.0 if YES
- Portfolio snapshot includes NegRisk positions

**Estimated effort:** 2-3 days

---

### 4.3 Adaptive Snapshot Age

**What:** Replace fixed `MAX_SNAPSHOT_AGE_SECONDS=120` with a per-market adaptive TTL based on trading activity. Active markets keep tight TTLs; low-volume markets get longer carry-forward (up to 30 min) with a confidence decay factor.

**Files to change:**
- `services/simulator/pipeline.py` — replace hardcoded age check with `snapshot_is_valid(market_id, snapshot_age)` that considers market activity
- `services/ingestor/ws_client.py` — track last-seen timestamp per market; expose via Redis or shared state
- `shared/config.py` — `MIN_SNAPSHOT_AGE=60`, `MAX_SNAPSHOT_AGE=1800`, `SNAPSHOT_CONFIDENCE_HALFLIFE=300`

**Acceptance criteria:**
- High-volume markets still reject snapshots >2 min old
- Low-volume markets accept snapshots up to 30 min with decayed confidence
- Edge calculations discount by confidence factor

**Estimated effort:** 1-2 days

---

### 4.4 Portfolio Rebalancing

**What:** Add a periodic check for held positions whose edge has flipped. If the filtered price now indicates our position is wrong-sided, exit via an opposing trade.

**Files to change:**
- `services/simulator/pipeline.py` — add `_check_rebalance()` periodic task (every 60s); for each open position, compare current filtered_price vs. entry_price; if edge has reversed by >0.03, generate exit trade
- `services/simulator/portfolio.py` — `exit_position(market_id, outcome, current_price)` method

**Config:**
- `REBALANCE_CHECK_INTERVAL=60`
- `REBALANCE_EDGE_REVERSAL_THRESHOLD=0.03`

**Acceptance criteria:**
- Positions with reversed edge are exited within one check cycle
- Realized PnL on rebalanced exits is tracked separately for analysis
- Drawdown on mispriced entries is reduced vs. hold-to-resolution

**Estimated effort:** 2 days

---

## Phase 5 — Infrastructure

### 5.1 Opportunity Priority Queue

**What:** Replace FIFO opportunity processing with a priority queue sorted by estimated_profit descending. When capital is limited, the highest-value opportunity executes first.

**Files to change:**
- `services/simulator/pipeline.py` — replace direct event handling with a `heapq`-based priority queue; accumulate opportunities for a configurable window, then process in profit order
- `shared/config.py` — `OPPORTUNITY_BATCH_WINDOW=5` (seconds)

**Acceptance criteria:**
- When two opportunities arrive within the batch window, the higher-profit one executes first
- Capital allocation to first opportunity doesn't starve the second if both can be funded
- No increase in latency for isolated opportunities (batch window only applies when multiple are pending)

**Estimated effort:** 1-2 days

---

## Sequencing & Dependencies

```
Phase 1 (parallel, no deps):
  1.1 NegRisk Detection ──────────┐
  1.2 Uncertainty Filter           │
  1.3 Min Trade Filter             │
  1.4 Kalman Filter                │
                                   │
Phase 2 (after 1.2):              │
  2.1 Temporal Pre-Filter          │
  2.2 Embedding Upgrade            │
  2.3 Top-K Reduction              │
  2.4 LLM Classifier Upgrade      │
                                   │
Phase 3 (independent):            │
  3.1 Warm-Start FW               │
  3.2 Adaptive Iterations          │
  3.3 IP Oracle Cache              │
                                   │
Phase 4 (after 1.1, 1.4):        │
  4.1 Adaptive Slippage ←──── 1.4 │
  4.2 NegRisk Execution ←──── 1.1─┘
  4.3 Adaptive Snapshot Age
  4.4 Portfolio Rebalancing

Phase 5 (after Phase 4):
  5.1 Priority Queue
```

All Phase 1 items can be developed in parallel. Phase 3 is independent of Phase 2. Phase 4.2 depends on 1.1; Phase 4.1 benefits from 1.4's Kalman filter data. Phase 5 goes last as it's an architectural change that benefits from stable execution logic.

---

## Validation Plan

After each phase, run the backtest suite to measure impact:

```bash
# Backtest with new features
docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest python -m scripts.backtest --capital 10000
```

**Key metrics to compare across phases:**
- Total opportunities detected (expect increase from NegRisk + uncertainty filter)
- False positive rate (expect decrease from Kalman + uncertainty filter)
- Simulated P&L (expect improvement from all changes)
- Average FW iterations per solve (expect decrease from warm-start + adaptive)
- Detection latency p50/p99 (expect decrease from temporal filter + embedding upgrade)

Track these in a `research/backtest_results/` directory with timestamped CSV outputs per phase.
