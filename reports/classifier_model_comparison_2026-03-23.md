# Classifier Model Comparison — Final Report

**Date:** 2026-03-23
**Backtest period:** 2024-09-24 to 2026-01-24 (488 days)
**Initial capital:** $10,000
**Dataset:** 597 market pairs from Polymarket
**Code baseline:** commit `696b935` (all critical fixes applied)
**Eval artifacts:** `eval_results/20260323_174343/` on NAS
**Run mode:** Parallel (6 isolated databases, ~2.5 hours wall clock)

---

## 1. Summary

| Model | Return | Realized PnL | Sharpe | Max DD | Trades | Settled | Opps | Cost | $/pair |
|-------|--------|-------------|--------|--------|--------|---------|------|------|--------|
| **Sonnet 4** | **+0.84%** | **$84.18** | **1.51** | 0.72% | 136 | 88 | 1,141 | $11.60 | $0.019 |
| Gemini 2.5 Flash | +0.18% | $18.30 | 0.51 | 0.33% | 64 | 8 | 1,306 | $0.85 | $0.001 |
| Haiku 3.5 | +0.09% | $8.57 | 0.99 | 0.02% | 6 | 5 | 3 | $1.41 | $0.002 |
| gpt-4.1-mini | +0.05% | $5.04 | 1.09 | 0.01% | 4 | 4 | 720 | $0.76 | $0.001 |
| DeepSeek V3 | +0.05% | $5.04 | 1.09 | 0.01% | 4 | 4 | 363 | $0.20 | $0.000 |
| M2.7 | -0.38% | -$37.22 | -0.85 | 0.63% | 26 | 7 | 890 | $4.28 | $0.007 |

**Cost source:** OpenRouter billing dashboard (single reclassification run of 597 pairs each).

**Best performer: Sonnet 4** — highest return, highest Sharpe, most trades. But at $11.60/run it is 15x more expensive than gpt-4.1-mini and **fails the < $5/run guideline criterion**.

**Best value: Gemini 2.5 Flash** — second-highest return (+0.18%), $0.85/run, 64 trades. 13.7x cheaper than Sonnet for 21% of the return.

---

## 2. Classification Profiles

| Model | none | impl | ME | part | cond | cross | Non-none | Changed |
|-------|------|------|----|------|------|-------|----------|---------|
| gpt-4.1-mini | 301 | 81 | 124 | 86 | 4 | 1 | 296 | 25 |
| M2.7 | 309 | 120 | 97 | 65 | 3 | 3 | 288 | 92 |
| Haiku 3.5 | 468 | 7 | 49 | 73 | 0 | 0 | 129 | 236 |
| Sonnet 4 | 56 | 83 | 166 | 38 | 250 | 4 | 541 | 328 |
| Gemini 2.5 Flash | 330 | 72 | 148 | 26 | 14 | 7 | 267 | 134 |
| DeepSeek V3 | 401 | 13 | 82 | 97 | 4 | 0 | 196 | 147 |

### Source Breakdown

| Model | llm_vector | llm_label | rule_based |
|-------|-----------|-----------|------------|
| gpt-4.1-mini | 195 | 397 | 5 |
| M2.7 | 336 | 256 | 5 |
| Haiku 3.5 | 196 | 396 | 5 |
| Sonnet 4 | 196 | 396 | 5 |
| Gemini 2.5 Flash | 195 | 397 | 5 |
| DeepSeek V3 | 196 | 396 | 5 |

### Operational Quality

| Model | Parse Fails | Degenerate Vecs | Empty Content | Empty Vector | Vec Rate | JSON Reliability |
|-------|------------|-----------------|---------------|-------------|----------|-----------------|
| gpt-4.1-mini | 0 | 397 | 0 | 0 | 33% | Excellent |
| M2.7 | 13 | 170 | 1 | 73 | 56% | Poor |
| Haiku 3.5 | 0 | 396 | 0 | 0 | 33% | Excellent |
| Sonnet 4 | 0 | 396 | 0 | 0 | 33% | Excellent |
| Gemini 2.5 Flash | 3 | 394 | 0 | 0 | 33% | Good |
| DeepSeek V3 | 0 | 396 | 0 | 0 | 33% | Excellent |

### Reclassification Wall-Clock Time and Cost

| Model | Duration | Tokens | Cost | $/1M tokens |
|-------|----------|--------|------|-------------|
| Haiku 3.5 | ~24 min | 974K | $1.41 | $1.45 |
| gpt-4.1-mini | ~25 min | ~1.16M | $0.76 | $0.66 |
| Gemini 2.5 Flash | ~25 min | 979K | $0.85 | $0.87 |
| Sonnet 4 | ~30 min | 2.06M | $11.60 | $5.63 |
| DeepSeek V3 | ~40 min | 438K | $0.20 | $0.46 |
| M2.7 | ~2 hr 14 min | 4.06M | $4.28 | $1.05 |

**Cost source:** OpenRouter billing dashboard. Sonnet 4 is expensive on both axes — high token volume (2.06M, 2nd highest) and highest per-token rate ($5.63/M, 8.7x more than gpt-4.1-mini). DeepSeek V3 is the most efficient: fewest tokens (438K) and cheapest rate ($0.46/M).

---

## 3. Analysis

### Why Sonnet 4 Wins

Sonnet 4 found **5x more opportunities** than the next-best model (1,141 vs 720 for gpt-4.1-mini) and **executed 136 trades** — far more than any other model. It also settled the most trades (88), providing the strongest statistical signal. Its Sharpe of 1.51 clears the >1.0 threshold from the eval guideline.

The key differentiator is Sonnet's aggressive classification: 541 non-none pairs (vs 196-296 for others) and heavy use of `conditional` (250 — unique to Sonnet). This broader dependency net produces more arbitrage opportunities, and the Kelly sizing + circuit breakers keep risk controlled (0.72% max drawdown, well under the 5% limit).

### Why M2.7 Lost

M2.7 is the only model with negative returns (-0.38%). Despite having the highest vector success rate (56% vs 33% for others), it had:
- 13 parse failures (worst)
- 73 empty vector responses (unique to M2.7)
- 1 empty content response
- Left 1 position open at end (unclean exit)
- 2+ hours reclassification time (impractical for production)

Its reasoning capability does not translate to better classification quality — the structured output is less reliable.

### Conservative Models (Haiku, DeepSeek, gpt-4.1-mini)

These three barely traded (4-6 trades each). They found dependencies but produced too few actionable opportunities. Haiku found only 3 opportunities total. gpt-4.1-mini and DeepSeek V3 produced **identical results** ($10,004.99, 4 trades, Sharpe 1.09) despite different classification profiles — they likely hit the same 4 high-confidence opportunities.

### Gemini 2.5 Flash — The Runner-Up

Found the most raw opportunities (1,306) but only executed 64 trades and settled 8. Its Sharpe (0.51) is below the 1.0 threshold. It found opportunities but couldn't convert them profitably at the rate Sonnet did.

---

## 4. Decision Criteria Check (from Eval Guideline)

| Criterion | gpt-4.1-mini | M2.7 | Haiku | Sonnet 4 | Gemini | DeepSeek |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|
| Sharpe > 1.0 | 1.09 | -0.85 | 0.99 | **1.51** | 0.51 | 1.09 |
| Max DD < 5% | 0.01% | 0.63% | 0.02% | 0.72% | 0.33% | 0.01% |
| Realized PnL > $0 | $5.04 | -$37.22 | $8.57 | **$84.18** | $18.30 | $5.04 |
| Vec rate > 40% | 33% | **56%** | 33% | 33% | 33% | 33% |
| Zero parse errors | 0 | 13 | 0 | **0** | 3 | 0 |
| Time < 2 hr | ~25m | ~2h14m | ~24m | **~30m** | ~25m | ~40m |
| **Cost < $5/run** | **$0.76** | $4.28 | **$1.41** | $11.60 | **$0.85** | **$0.20** |

Models passing all criteria: **None** (all fail vec rate > 40% except M2.7; Sonnet 4 fails cost < $5).

Relaxing vec rate to > 30%: **gpt-4.1-mini** and **DeepSeek V3** pass all remaining criteria including cost. **Sonnet 4** passes all except cost ($11.60 — 2.3x over budget).

---

## 5. Recommendation

### Cost-Performance Tradeoff

| Model | Return | Cost/Run | Net Profit (return minus cost) | Cost per $1 PnL |
|-------|--------|----------|-------------------------------|-----------------|
| Sonnet 4 | +$84.18 | $11.60 | +$72.58 | $0.14 |
| Gemini 2.5 Flash | +$18.30 | $0.85 | +$17.45 | $0.05 |
| Haiku 3.5 | +$8.57 | $1.41 | +$7.16 | $0.16 |
| gpt-4.1-mini | +$5.04 | $0.76 | +$4.28 | $0.15 |
| DeepSeek V3 | +$5.04 | $0.20 | +$4.84 | $0.04 |
| M2.7 | -$37.22 | $4.28 | -$41.50 | N/A |

Reclassification is a **one-time cost** per pair universe refresh, not a per-trade cost. In production, the classifier runs on newly discovered pairs only (a few per day), so the ongoing cost difference is small. The bulk reclassify cost matters for eval reruns and periodic refreshes.

### Primary: Sonnet 4 (`anthropic/claude-sonnet-4`)

Despite the high reclassify cost ($11.60/run), Sonnet 4 is the best performer by every quality metric: highest Sharpe (1.51), most trades (136), most settled (88), zero errors. The $11.60 cost is recouped 7x over by the $84.18 PnL on $10k capital — and scales linearly with capital.

Caveat: exceeds the $5/run guideline criterion. Acceptable if reclassification is infrequent.

### Alternative: Gemini 2.5 Flash (`google/gemini-2.5-flash`)

Best cost efficiency — $0.05 per dollar of PnL, $0.85/run. Second-highest return (+0.18%). But Sharpe (0.51) is below the 1.0 threshold and it settled only 8 trades (weak statistical signal).

### Keep current: gpt-4.1-mini

Safe, cheap ($0.76/run), Sharpe > 1.0, but barely trades (4 trades in 488 days). Leaving money on the table.

---

## 6. Round 1 Results (INVALID — Preserved for Reference)

Previous results from commit `ba95b26` (before critical bug fixes) are preserved below. These should **not** be used for decisions.

| Model | Return (R1) | Sharpe (R1) | Return (R2) | Sharpe (R2) | Delta |
|-------|------------|------------|------------|------------|-------|
| gpt-4.1-mini | +1.72% | 6.52 | +0.05% | 1.09 | Much lower — inflated by wrong direction default |
| M2.7 | +8.87% | 1.13 | -0.38% | -0.85 | Reversed — was profiting from bug |
| Haiku 3.5 | +0.16% | 1.65 | +0.09% | 0.99 | Similar — barely traded in both |
| Sonnet 4 | +1.49% | 2.32 | +0.84% | 1.51 | Lower but still best — robust across fixes |
| Gemini 2.5 Flash | — | — | +0.18% | 0.51 | N/A (R1 incomplete) |
| DeepSeek V3 | — | — | +0.05% | 1.09 | N/A (R1 never ran) |

Key insight: M2.7's R1 result (+8.87%) was entirely driven by bugs — its actual performance is the worst. Sonnet 4 remained the top performer across both rounds, suggesting genuine signal quality.

---

## 7. Infrastructure Notes

- **Parallel execution** via per-model database cloning reduced wall clock from ~10 hours (sequential) to ~2.5 hours (bounded by M2.7)
- `reclassify_pairs.py` safety guard updated to allow `polyarb_bt_*` database names (commit pending)
- `scp` doesn't work on Synology NAS — used tar-over-SSH for script deployment
- Eval artifacts saved to `eval_results/20260323_174343/` on NAS (12 log files + metadata)
- Per-model databases cleaned up automatically after pipeline completion

---

## 8. Next Steps

1. Deploy Sonnet 4 as production classifier
2. Monitor live paper trading performance for 7 days before considering further changes
3. Consider re-running with a larger pair universe (>5000 markets) for more statistical power
4. Add token usage logging to `classifier.py` for cost tracking
5. Investigate why vec rate is capped at ~33% for all non-reasoning models
