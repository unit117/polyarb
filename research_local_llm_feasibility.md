# Research Plan: Local LLM Feasibility for PolyArb

**Date:** 2026-03-23
**Status:** Research plan — no decisions made yet

---

## 1. How PolyArb Uses AI Today

PolyArb uses LLMs in exactly one place: the **dependency classifier** in the detector service. The classifier determines the logical relationship between pairs of prediction markets (e.g., "are these mutually exclusive?", "does one imply the other?"). This is the single most important decision in the pipeline — a wrong classification causes the system to trade on a non-existent arbitrage, which is how the original -86.6% backtest loss happened.

### The Classification Pipeline (3 Tiers)

```
Tier 1: Rule-based heuristics (no LLM, instant, ~5 pairs)
  ↓ if no match
Tier 2: Resolution vector LLM call (structured JSON, ~195-336 pairs)
  ↓ if parse fails or non-binary markets
Tier 3: Label-based LLM call (unstructured fallback, confidence capped at 0.70)
```

For a typical run of 597 market pairs:
- **~5 pairs** are handled by deterministic rules (no LLM needed)
- **~195 pairs** go through Tier 2 (resolution vector — structured JSON output)
- **~397 pairs** go through Tier 3 (label-based fallback)

### What the LLM Actually Does

**Tier 2 (the important one):** Given two market questions like "Will Arsenal win the Champions League?" and "Will Arsenal reach the semifinal?", the LLM must enumerate which outcome combinations are logically possible:
- (Yes, Yes) — possible ✓
- (Yes, No) — impossible ✗ (winning requires reaching semis)
- (No, Yes) — possible ✓
- (No, No) — possible ✓

The code then deterministically derives the dependency type from these vectors. The LLM's job is purely logical reasoning about real-world constraints — no creative generation, no long-form text.

**Tier 3 (fallback):** Directly classifies the dependency type and correlation. Used when Tier 2 JSON parsing fails or for non-binary markets. Confidence is hard-capped at 0.70.

### API Parameters

- Temperature: 0.0 (Tier 2) / 0.1 (Tier 3) — deterministic
- Max tokens: 512 (Tier 2) / 256 (Tier 3) — short responses
- JSON mode enabled for Tier 2
- OpenAI-compatible chat completions API (works with any provider via `openai.AsyncOpenAI`)
- Input: ~200-400 tokens per call (two market questions + prompt)
- Output: ~50-150 tokens per call (JSON with 4 outcome combos + reasoning)

### Current Live Usage

The detector runs classification on every candidate pair every ~2 minutes:

| Metric | Value |
|--------|-------|
| Detection cycles | ~97 per 3 hours (~1 every 2 min) |
| LLM calls (label path) | ~2,304 per 3 hours |
| Resolution vector calls | ~1,590 per 3 hours |
| **Total LLM calls** | **~3,894 per 3 hours** |
| **~31,000 per day** | |
| New pairs per cycle | ~10 |
| Candidates per cycle | ~20 |

**Critical note:** The vast majority of these calls are redundant — the detector re-classifies already-known pairs every cycle. Implementing classification caching would reduce daily calls from ~31,000 to perhaps a few dozen (only genuinely new pairs). This is the single biggest optimization regardless of API vs local.

---

## 2. Current API Costs

### What Was Actually Measured

**Only Sonnet 4 was observed live.** It ran in live paper trading on the NAS for ~3 hours on 2026-03-23, then was shut down because of the token burn rate. All other models were only run against the static 597-pair backtest dataset — never live.

| Model | What Was Measured | Cost | Tokens | $/1M tok |
|-------|-------------------|------|--------|----------|
| **Sonnet 4** | **3 hours live paper trading** (actual) | **$11.60** | 2.06M | $5.63 |
| Gemini 2.5 Flash | Backtest reclassify only (597 pairs) | $0.85 | 979K | $0.87 |
| gpt-4.1-mini | Backtest reclassify only (597 pairs) | $0.76 | 1.16M | $0.66 |
| DeepSeek V3 | Backtest reclassify only (597 pairs) | $0.20 | 438K | $0.46 |

**Nothing is running live right now** — paper trading is stopped.

### Live Cost Reality (Sonnet 4 — the only real data point)

In 3 hours of live trading, the detector made ~3,894 LLM calls (re-classifying the same pairs every ~2 minute cycle). That's ~31,000 calls/day if left running, burning **~$90/day** extrapolated (or ~$11-12/day if the 3-hour window is representative of a full day's billing — the report noted $11.60 in that single billing period).

The key problem: **no classification caching exists**, so the detector re-classifies every candidate pair every cycle whether it's changed or not.

### Backtest Quality Results (597-pair static eval)

These are the backtest returns per model — useful for comparing classification quality, but the "daily cost" for non-Sonnet models is **not a live measurement**, it's just the backtest run cost:

| Model | Backtest Return | Sharpe | Trades | Conditionals Found | Reclassify Cost |
|-------|-----------------|--------|--------|--------------------|----|
| **Sonnet 4** | **+$84.18 (+0.84%)** | **1.51** | 136 | **250** | $11.60 |
| Gemini 2.5 Flash | +$18.30 (+0.18%) | 0.51 | 64 | 14 | $0.85 |
| gpt-4.1-mini | +$5.04 (+0.05%) | 1.09 | 4 | 4 | $0.76 |
| DeepSeek V3 | +$5.04 (+0.05%) | 1.09 | 4 | 4 | $0.20 |

**Sonnet 4 is the clear quality winner** — it found 250 conditional pairs where others found 0-14. It generated 1,141 opportunities and 136 trades vs 3-64 for others. Its Sharpe ratio (1.51) was the only one clearly above 1.0.

### Projected Costs If Running Live (estimated, not measured)

If each model were deployed live with the same ~31,000 calls/day pattern (no caching):

| Model | Est. Daily Live Cost | Est. Annual Cost | Backtest Annual PnL ($10k) | Net ($10k) |
|-------|---------------------|------------------|---------------------------|------------|
| Sonnet 4 | ~$11-90/day* | ~$4,000-33,000 | ~$63 | **deep negative** |
| Gemini 2.5 Flash | ~$0.85-7/day* | ~$310-2,500 | ~$14 | negative |
| gpt-4.1-mini | ~$0.76-6/day* | ~$280-2,200 | ~$4 | negative |
| DeepSeek V3 | ~$0.20-2/day* | ~$73-600 | ~$4 | negative |

*Wide ranges because the live call pattern may differ from the backtest reclassification ratio. Sonnet's $11.60/3hr is the only real data point.*

### With Caching (projected)

With caching, ongoing cost drops dramatically (only genuinely new pairs hit the LLM — perhaps 5-50 new pairs/day instead of 31,000 re-classifications):

| Model | Annual API Cost (cached) | Annual PnL ($10k) | Annual PnL ($100k) | Net ($100k) |
|-------|--------------------------|--------------------|--------------------|-------------|
| Sonnet 4 | ~$35-350 | ~$63 | ~$630 | **+$280-595** |
| Gemini 2.5 Flash | ~$3-25 | ~$15 | ~$135 | +$110-132 |
| DeepSeek V3 | ~$1-6 | ~$4 | ~$37 | +$31-36 |

*Cached range assumes 5-50 genuinely new pairs/day at ~$0.019/pair (Sonnet). Mature markets trend toward the low end.*

**Key takeaway:** Caching alone makes Sonnet 4 viable on API. The local LLM question is really about whether you can replicate Sonnet 4's classification quality locally — because if you can't, and you have to fall back to a weaker model anyway, the API cost with caching is very manageable.

---

## 3. The Core Question: Can a Local Model Match Sonnet 4?

### What Makes Sonnet 4 Special

Sonnet 4's advantage appears to be in **conditional dependency detection** — recognizing relationships like "Over 2.5 goals makes Both Teams to Score more likely." It found 250 conditional pairs; the next best (Gemini Flash) found 14; most found 0-4.

However, the research folder and the current optimizer implementation narrow what that means in practice: a high conditional count only matters when those classifications can be turned into **non-trivial feasibility constraints** (excluded joint outcomes or otherwise defensible matrix structure). Soft "these markets are correlated" answers are not the same thing as optimizer-ready arbitrage inputs.

This is a nuanced reasoning task that requires:
1. Understanding sports/prediction market semantics
2. Distinguishing logical impossibility from mere correlation
3. Knowing when to break Tier 2's own instruction ("only exclude if LOGICALLY IMPOSSIBLE") for borderline cases
4. Producing clean, parseable JSON every time

### Local Model Candidates

| Model | Parameters | VRAM Required | Can Run On | Quality Tier |
|-------|-----------|---------------|------------|-------------|
| Qwen3-235B-A22B (MoE) | 235B (22B active) | ~48GB Q4 | Mac Studio 192GB, 2x 5090 | Unknown — eval needed |
| Qwen3.5-72B | 72B dense | ~40GB Q4 | Mac Studio 128GB, 2x 5090 (tight) | Unknown |
| Qwen3-30B-A3B (MoE) | 30.5B (3.3B active) | ~18GB Q4 | Single RTX 5090 (32GB) | Likely too weak |
| DeepSeek V3 (671B MoE) | 671B (37B active) | ~350GB Q4 | Mac Studio 192GB only | Matched gpt-4.1-mini in eval |
| Llama 3.3 70B | 70B dense | ~40GB Q4 | Mac Studio 128GB, 2x 5090 | Unknown |

**The honest assessment:** No open-source model has been shown to match Sonnet 4's conditional detection. DeepSeek V3 — the most capable open model — produced identical results to gpt-4.1-mini in the backtest (4 trades, +$5.04). It found only 4 conditional pairs vs Sonnet's 250.

### What Needs to Be Tested

Before any hardware purchase, run these models through the existing eval pipeline:

```bash
# The eval infrastructure already supports arbitrary models via OpenRouter
docker compose run --rm backtest python -m scripts.reclassify_pairs \
  --model qwen/qwen3-235b-a22b --base-url https://openrouter.ai/api/v1 \
  --api-key $OPENROUTER_KEY --batch-size 3
```

**Cost to eval 4 Qwen models on OpenRouter: < $3 total** (free tiers available). This tells you whether any open model can match Sonnet before spending thousands on hardware.

---

## 4. Hardware Options and ROI

### Option A: RTX 5090 Workstation

| Component | Cost |
|-----------|------|
| RTX 5090 (32GB GDDR7) | ~$2,000-3,600 (MSRP $1,999, street price higher) |
| System (CPU, RAM, PSU, case) | ~$800-1,200 |
| **Total** | **~$3,000-5,000** |

**What it runs:** Any model up to ~30B dense or ~70B quantized (Q4). Qwen3-30B-A3B (3.3B active MoE) would fly at 80+ tok/s. A 70B model would be tight at ~15-25 tok/s.

**What it can't run:** DeepSeek V3 (671B), Qwen3-235B in full precision. Anything needing >32GB VRAM.

**Performance:** For the classification task (~200 tok input, ~100 tok output), a 30B model on RTX 5090 would do ~80-100 tok/s = ~1-2 seconds per classification. A 70B model: ~15-25 tok/s = ~4-7 seconds per call.

**Break-even vs Sonnet 4 API (no caching):** $4,000-33,000/year (wide range — only 3hr of live data) → could pay back in under a year, but the true live cost is uncertain.
**Break-even vs Sonnet 4 API (with caching):** ~$35-350/year → **never breaks even** (hardware depreciates faster than savings accumulate).

### Option B: Mac Studio M3 Ultra (current top)

| Configuration | Price | Memory | Bandwidth |
|---------------|-------|--------|-----------|
| M3 Ultra, 192GB | ~$6,999+ | 192GB unified | 819 GB/s |
| M4 Max, 128GB | ~$3,999+ | 128GB unified | 546 GB/s |

**Note:** There is no M4 Ultra Mac Studio yet (Apple skipped it). The M3 Ultra is the current high-end. An M5 Ultra is rumored for mid-2026.

**What it runs:** Everything. DeepSeek V3 (671B) fits in 192GB. Qwen3-235B easily. The unified memory architecture means no model-splitting complexity.

**Performance:** Memory-bandwidth-limited. At 819 GB/s with a Q4 model:
- 70B model: ~20-30 tok/s
- DeepSeek V3 (671B): ~5-10 tok/s
- Qwen3-235B: ~15-25 tok/s

For the classification task, this means 2-20 seconds per call depending on model size.

**Break-even vs Sonnet 4 API (no caching):** $4,000-33,000/year → $7,000 machine pays back in 3-21 months (uncertain — only 3hr of live Sonnet data).
**Break-even vs Sonnet 4 API (with caching):** **Never breaks even.**

### Option C: Cloud GPU (RunPod)

| GPU | Price | VRAM |
|-----|-------|------|
| RTX 5090 | $0.69/hr | 32GB |
| A100 80GB | $1.39/hr | 80GB |

**Usage model:** Spin up only when needed. With caching, you'd need the GPU for perhaps 1-2 hours/day max (for new pair classifications).

**Monthly cost at 2 hr/day:** $0.69 × 2 × 30 = ~$41/month ($492/year) for RTX 5090.

**Break-even vs Sonnet 4 API (no caching):** Saves immediately ($504 vs $4,000-33,000/year).
**Break-even vs Sonnet 4 API (with caching):** **Loses** ($504 vs ~$35-350/year).

---

## 5. The Decision Matrix

| Scenario | Best Choice | Why |
|----------|-------------|-----|
| **No caching, Sonnet-quality model exists locally** | RTX 5090 workstation or cloud GPU | Saves $4,000+/year vs Sonnet API (possibly much more) |
| **No caching, no local model matches Sonnet** | DeepSeek V3 on API ($73/year) | Cheapest option; accept lower quality |
| **With caching, any model** | **Sonnet 4 on API** | ~$35-350/year; no hardware needed; best quality |
| **Want to run many experiments/evals** | Cloud GPU (RunPod) | Pay-per-hour, no commitment, any model size |
| **Also need local LLM for other projects** | Mac Studio M3 Ultra 192GB | Future-proof, runs everything, dual purpose |

---

## 6. Recommended Research Plan

### Phase 1: Implement Caching (1-2 days, $0 cost)
**This is the highest-ROI action regardless of any hardware decision.**

Cache classification results for already-seen market pairs. The detector currently re-classifies ~31,000 pairs/day that it has already classified. With caching, ongoing API costs drop from ~$4,200/year (Sonnet) to ~$15-50/year.

Implementation: Store classification results keyed by `(market_a_id, market_b_id)` hash. Invalidate when market metadata changes. This is a straightforward DB lookup before calling the LLM.

### Phase 2: Eval Open Models on API (~$3-5, 1 day)
Run the Qwen3 family through the existing eval pipeline via OpenRouter:

| Model | OpenRouter ID | Cost Estimate |
|-------|---------------|---------------|
| Qwen3-235B-A22B | `qwen/qwen3-235b-a22b:free` | Free |
| Qwen3-30B-A3B | `qwen/qwen3-30b-a3b:free` | Free |
| Qwen3.5 Plus | `qwen/qwen3.5-plus-02-15` | ~$1-2 |
| Qwen3.5 Flash | `qwen/qwen3.5-flash-02-23` | ~$0.50 |

**Key metric to watch:** How many `conditional` pairs does each model find? If any model finds 100+ conditionals (vs Sonnet's 250), it's a viable local candidate.

### Phase 3: Decision Gate
After Phase 2, one of three outcomes:

**A) An open model matches Sonnet's conditional detection:**
→ Evaluate hardware. If the model fits on a single RTX 5090 (32GB), a ~$3-5K workstation is the cheapest path. Otherwise, consider the Mac Studio if you have other uses for it, or cloud GPU for flexibility.

**B) No open model comes close:**
→ Stay on Sonnet 4 API with caching. Total annual cost: ~$15-50. No hardware needed. Re-evaluate when new open models launch (Qwen4, Llama 4, etc.).

**C) An open model is "good enough" (e.g., 60-70% of Sonnet's conditional detection):**
→ Hybrid approach: Use the open model locally for Tier 2 (resolution vectors — pure logic) and Sonnet for Tier 3 fallback (where nuance matters more). This minimizes API calls while preserving quality where it counts.

### Phase 4 (if hardware is justified): Local Deployment
If Phase 2 finds a viable model:
1. Set up vLLM or llama.cpp serving with OpenAI-compatible API endpoint
2. Point PolyArb's `classifier_base_url` at the local endpoint
3. Run parallel eval: local model vs Sonnet API on 597 pairs
4. If backtest shows comparable returns, switch to local
5. Keep Sonnet as fallback for pairs that fail local parsing

---

## 7. Honest Assessment

**The financial case for dedicated hardware is weak right now**, for three reasons:

1. **Caching largely solves the cost problem.** With caching, Sonnet 4 costs ~$35-350/year depending on new pair volume. That's hard for any hardware purchase to compete with.

2. **No open model has matched Sonnet's classification quality.** DeepSeek V3 (671B, the most capable open model tested) produced the same results as gpt-4.1-mini — both found only 4 conditional pairs. Sonnet found 250. Until an open model can detect conditionals at even half Sonnet's rate, local inference means accepting significantly worse trading performance.

3. **The system's returns are modest.** At +0.84% on $10k over 489 days, the absolute PnL ($84.18) doesn't justify significant infrastructure investment. Even at $100k capital, annual PnL of ~$628 barely covers a decent GPU.

**When hardware WOULD make sense:**
- If you scale to many more markets (10k+ pairs) where even cached Sonnet costs become meaningful
- If an open model emerges that matches Sonnet's conditional detection (eval it via Phase 2)
- If you have other uses for the hardware (other AI projects, general compute)
- If you want to run rapid experimental iterations without API billing anxiety

**The NAS you already have** (Synology at $NAS_HOST) is not suitable for LLM inference — it lacks a GPU. The classification task is too latency-sensitive for CPU-only inference.

---

## 8. Full Dataset Backtest Cost Estimate

The current eval used 5,000 markets → 597 pairs. The full Becker dataset has ~53,000 markets. How much would it cost to reclassify at full scale?

### Per-Pair Cost (the base unit)

| Model | $/pair | Tokens/pair |
|-------|--------|-------------|
| Sonnet 4 | $0.0194 | 3,451 |
| Gemini 2.5 Flash | $0.0014 | 1,640 |
| gpt-4.1-mini | $0.0013 | 1,943 |
| DeepSeek V3 | $0.0003 | 734 |
| Haiku 3.5 | $0.0024 | 1,631 |
| M2.7 | $0.0072 | 6,801 |

### Scaled Estimates

**Pair count is the big unknown.** More markets means more semantic overlap, but also more niche/unique markets that don't pair with anything. The 597 pairs from 5,000 markets gives a ratio of ~0.12 pairs/market, but this won't scale linearly. Estimates below use conservative pair counts.

| Scale | Est. Pairs | Sonnet 4 | Gemini Flash | gpt-4.1-mini | DeepSeek V3 |
|-------|-----------|----------|-------------|-------------|-------------|
| **5k markets (current)** | 597 | **$11.60** / 2M tok | $0.85 / 1M | $0.76 / 1.2M | $0.20 / 438K |
| **10k markets** | ~1,500 | **$29** / 5.2M tok | $2.14 / 2.5M | $1.91 / 2.9M | $0.50 / 1.1M |
| **20k markets** | ~4,000 | **$78** / 13.8M tok | $5.70 / 6.6M | $5.09 / 7.8M | $1.34 / 2.9M |
| **53k markets (full)** | ~12,000 | **$233** / 41M tok | $17 / 19.7M | $15 / 23.3M | $4 / 8.8M |

**Estimated wall-clock time at full scale (serial, batch-size 3):**

| Model | 5k (current) | 53k (full) |
|-------|-------------|-----------|
| Sonnet 4 | ~30 min | ~10 hr |
| Gemini 2.5 Flash | ~25 min | ~8 hr |
| gpt-4.1-mini | ~25 min | ~8 hr |
| DeepSeek V3 | ~40 min | ~13 hr |
| M2.7 | ~2.2 hr | ~45 hr |

### Key Takeaways for Full-Scale Backtest

**Sonnet 4 at full scale: ~$233 per reclassification run.** That's a one-time cost to reclassify all ~12,000 pairs. The backtest simulation itself (scripts/backtest) is free — it reads the classifications from the DB and runs the trading sim with no LLM calls.

**DeepSeek V3 at full scale: ~$4.** If you just want to see what the full dataset looks like and don't need Sonnet-quality conditional detection, DeepSeek is essentially free.

**A reasonable approach:** Run DeepSeek V3 first ($4, ~13 hr) to understand pair distribution at scale, then selectively run Sonnet on the interesting subsets (e.g., only pairs DeepSeek classified as non-none, or only sports markets where conditionals cluster).

**Embedding cost is separate but negligible:** Generating pgvector embeddings for 53k markets via OpenAI text-embedding-3-small costs ~$0.50-1.00 total.

---

## 9. Research-Based Correction: Probability Signals vs Arbitrage Constraints

The research folder changes the interpretation of the Sonnet-vs-cheap-model gap.

- **Dudik, Lahaie & Pennock (2016)** and PolyArb's actual optimizer are about projecting prices onto a **marginal polytope** defined by hard feasibility constraints. The optimizer needs excluded joint outcomes, not just "these markets move together."
- **Wolfers & Zitzewitz (2004, 2006)** support treating prediction-market prices as useful approximations to probabilities in practice, but not as exact structural probabilities.
- **Manski (2006)** is the cautionary note: market prices need not equal mean beliefs because of risk preferences and heterogeneous traders.
- The AFT review already in this repo points to **NegRisk detection, candidate-recall fixes, and warm-start Frank-Wolfe** as higher-confidence optimizations than inventing more soft conditional labels.

**Implication:** A cheap model answering "these markets are probabilistically correlated" is **not** the same as generating an optimizer-ready arbitrage constraint.

### Why This Matters In The Current Code

Today, the detector/optimizer pipeline behaves like this:

- `classify_llm_resolution()` returns `none` when all 4 binary outcome combinations are valid.
- `build_constraint_matrix_from_vectors()` only helps when the model excludes at least one joint cell.
- `OptimizerPipeline` skips conditional pairs that are unconstrained / all-ones matrices.
- `scripts/validate_correlations.py` already treats observed correlation as a **post-hoc validation signal**, not proof of arbitrage.

So a new `probabilistic_dependency` field or a second-pass "are these correlated?" prompt might be useful for research or ranking, but it is **not a drop-in replacement** for a feasibility matrix.

### What The Ground Truth Data Still Suggests

Analysis of the 316-pair labeled eval set:

| Conditional Pattern | Count | % of All Conditionals | Rule-Detectable? |
|---|---|---|---|
| O/U vs BTTS (same match) | 14 | 50% | Partially |
| O/U vs Spread (same match) | 2 | 7% | Partially |
| Spread vs BTTS (same match) | 2 | 7% | Partially |
| Tournament progression | 3 | 11% | Partially |
| Other | 7 | 25% | No |

This is still useful, but the correct framing is narrower:

- These patterns are promising **candidate-discovery and labeling shortcuts**
- They are **not automatically hard arbitrage constraints**
- Any rule added here must be evaluated by whether it produces non-trivial matrices, survives verification, and improves realized backtest PnL

### Reframed Cheap-Model Plan

| Change | Purpose | Works with current optimizer? | Confidence |
|---|---|---|---|
| Classification caching | Eliminate redundant LLM spend | **Yes** | **High** |
| Better Tier 2 few-shot / prompting for true resolution vectors | Recover missed excluded cells | **Yes** | Medium |
| Rule-based sports heuristics | Faster candidate labeling; maybe some conservative constraints | **Maybe** | Medium |
| `probabilistic_dependency` field | Research metadata / ranking only | **No, not directly** | Low |
| Two-pass correlation follow-up | Research metadata / audit only | **No, not directly** | Low |
| Warm-start Frank-Wolfe | Faster repeated optimization | **Yes** | **High** |
| Candidate-recall fixes (KNN fanout, cap split) | More pair coverage per cycle | **Yes** | **High** |

### Revised Priority

1. **Classification caching first** — this directly solves the cost problem regardless of model choice
2. **Candidate-recall fixes second** — the `research/GRAPHRAG_INTEGRATION.md` findings suggest current recall is bottlenecked before any LLM/hardware discussion
3. **Warm-start / adaptive Frank-Wolfe third** — directly supported by the optimizer research and improves repeated scans
4. **Prompt and rule improvements fourth** — but focus on recovering **hard excluded outcomes**, not just generating more "conditional" prose
5. **Soft probability metadata only as a shadow metric** — do not feed it into the optimizer until it proves incremental PnL in backtests

### How This Changes The Hardware Question

This makes the hardware decision even less urgent than it first appeared:

- If caching + recall fixes + optimizer improvements already move the needle, API costs become trivial and hardware ROI collapses
- If cheap models improve only at reporting **soft correlations**, that still does not justify local deployment, because the current optimizer cannot use that signal directly
- A local model only becomes strategically important if it can match Sonnet on the thing that matters: **recovering usable feasibility structure**, not merely producing more conditional labels

**Revised punchline:** The best near-term investment is not "teach a cheap model to assert more probabilistic conditionals." It is to cache classifications, improve candidate recall, optimize Frank-Wolfe, and only add classifier heuristics that can be converted into defensible constraints or proven profitable as a separate signal.

---

## 10. Immediate Next Steps

1. **Implement classification caching** — highest ROI, eliminates 99%+ of redundant API calls
2. **Fix candidate-recall bottlenecks** — especially the KNN fanout / cap issues documented in `research/GRAPHRAG_INTEGRATION.md`
3. **Add warm-start / adaptive Frank-Wolfe** — research-backed optimizer improvement with no model risk
4. **Run Qwen3 eval on OpenRouter** — but score models on usable vector/matrix quality, not raw conditional count
5. **Treat probabilistic-dependency ideas as a shadow experiment** — useful for ranking or audit, not optimizer input, until backtests prove otherwise

---

## Appendix: PolyArb's Complete AI Footprint

| Component | Uses AI? | Details |
|-----------|----------|---------|
| **Detector → Classifier** | ✅ LLM | Sonnet 4 via OpenRouter. ~3,900 calls/3hr (uncached). Resolution vectors + label fallback. |
| **Detector → Embeddings** | ✅ Embeddings | OpenAI `text-embedding-3-small` for pgvector similarity search. Used to find candidate pairs. Low cost (~$0.02/M tokens). |
| **Optimizer** | ❌ | Frank-Wolfe convex optimization. Pure math, no AI. |
| **Simulator** | ❌ | VWAP slippage model, Kelly sizing, circuit breakers. Pure math. |
| **Ingestor** | ❌ | API polling + WebSocket streaming. No AI. |
| **Dashboard** | ❌ | React frontend. No AI. |

The classifier is the only component where local LLM is relevant. Embeddings are too cheap to bother self-hosting (~$0.02/M tokens via OpenAI).
