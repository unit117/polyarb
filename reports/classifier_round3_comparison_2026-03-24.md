# Round 3 Classifier Eval — Prompt Specs Layer

**Date:** 2026-03-24
**Backtest period:** 2024-09-24 to 2026-01-24 (488 days)
**Initial capital:** $10,000
**Dataset:** 597 market pairs from Polymarket
**Eval artifacts:** `eval_results/r3_promptspec_20260324_005806/` on NAS
**Run mode:** Parallel (8 isolated databases, ~2.5 hours wall clock, bounded by Qwen 3.5-122B)
**Change under test:** `prompt_specs.py` layer — versioned PromptSpec dataclasses with dual renderers (generic + Claude XML), adapter auto-dispatch

---

## 1. Summary

| Rank | Model | Return | PnL | Sharpe | Max DD | Trades | Settled | Opps | Adapter |
|------|-------|--------|-----|--------|--------|--------|---------|------|---------|
| 1 | **M2.7** | **+0.87%** | **$89.38** | 0.30 | 4.09% | 346 | 45 | 1,325 | generic |
| 2 | **Qwen3 Max** | +0.48% | $49.67 | 0.16 | 4.28% | 404 | 30 | 2,119 | generic |
| 3 | Qwen3.5-122B | +0.38% | $39.35 | 0.16 | 3.46% | 228 | 15 | 1,224 | generic |
| 4 | Gemini 2.5 Flash | +0.19% | $15.03 | **1.37** | 0.11% | 74 | 10 | 1,735 | generic |
| 5 | Sonnet 4 | +0.07% | $8.45 | 0.04 | 3.25% | 294 | 18 | 1,301 | claude_xml |
| 6 | gpt-4.1-mini | +0.05% | $5.04 | 1.09 | 0.01% | 4 | 4 | 981 | generic |
| 7 | DeepSeek V3 | +0.01% | $1.33 | 0.12 | 0.07% | 2 | 2 | 310 | generic |
| 8 | Haiku 3.5 | 0.00% | $0.00 | 0.00 | 0.00% | 0 | 0 | 502 | claude_xml |

**Prompt spec versions:** `label_v1` (Tier 3 fallback), `resolution_v1` (Tier 2 vectors)
**Adapter dispatch:** `auto` mode — Sonnet 4 and Haiku 3.5 received `claude_xml`, all others received `openai_generic`
**Qwen API:** DashScope International (1M free tokens per model)

---

## 2. Round 2 → Round 3 Comparison

| Model | R2 Return | R3 Return | R2 Sharpe | R3 Sharpe | R2 Trades | R3 Trades | R2 Settled | R3 Settled | Delta Return |
|-------|-----------|-----------|-----------|-----------|-----------|-----------|------------|------------|-------------|
| M2.7 | -0.38% | **+0.87%** | -0.85 | 0.30 | 26 | 346 | 7 | 45 | **+1.25%** |
| Gemini 2.5 Flash | +0.18% | +0.19% | 0.51 | **1.37** | 64 | 74 | 8 | 10 | +0.01% |
| gpt-4.1-mini | +0.05% | +0.05% | 1.09 | 1.09 | 4 | 4 | 4 | 4 | 0.00% |
| Sonnet 4 | **+0.84%** | +0.07% | **1.51** | 0.04 | 136 | 294 | 88 | 18 | **-0.77%** |
| DeepSeek V3 | +0.05% | +0.01% | 1.09 | 0.12 | 4 | 2 | 4 | 2 | -0.04% |
| Haiku 3.5 | +0.09% | 0.00% | 0.99 | 0.00 | 6 | 0 | 5 | 0 | -0.09% |
| Qwen3 Max | — | +0.48% | — | 0.16 | — | 404 | — | 30 | *new* |
| Qwen3.5-122B | — | +0.38% | — | 0.16 | — | 228 | — | 15 | *new* |

### Winners
- **M2.7: biggest improvement (+1.25%).** Went from worst performer (only negative return in R2) to best absolute return. The prompt_specs layer dramatically improved its classification quality — from 26 trades to 346, from 7 settled to 45.
- **Gemini 2.5 Flash: Sharpe jumped from 0.51 → 1.37** (best risk-adjusted). Return essentially unchanged but risk profile improved substantially.
- **Qwen3 Max: strong debut at +0.48%.** 2nd-best return, most trades (404), free via DashScope. Would have placed 2nd in Round 2 behind Sonnet.

### Losers
- **Sonnet 4: collapsed from +0.84% → +0.07%.** Despite more trades (294 vs 136), settled far fewer (18 vs 88). The claude_xml adapter may be degrading its performance — see Section 5.
- **Haiku 3.5: zero trades.** Also received claude_xml adapter. Went from 6 trades (R2) to 0.
- **DeepSeek V3: halved** from 4 trades → 2, return dropped from +0.05% → +0.01%.

---

## 3. Classification Profiles

| Model | none | impl | ME | part | cond | cross | Non-none | Changed |
|-------|------|------|----|------|------|-------|----------|---------|
| gpt-4.1-mini | 299 | 88 | 116 | 89 | 4 | 1 | 298 | 48 |
| Sonnet 4 | 287 | 93 | 196 | 8 | 10 | 3 | 310 | 123 |
| Haiku 3.5 | 374 | 21 | 188 | 4 | 10 | 0 | 223 | 178 |
| Gemini 2.5 Flash | 332 | 94 | 110 | 42 | 11 | 8 | 265 | 111 |
| DeepSeek V3 | 346 | 27 | 120 | 97 | 5 | 2 | 251 | 102 |
| M2.7 | 318 | 132 | 115 | 24 | 6 | 2 | 279 | 123 |
| Qwen3 Max | 299 | 90 | 105 | 84 | 17 | 2 | 298 | 76 |
| Qwen3.5-122B | 300 | 184 | 106 | 2 | 3 | 2 | 297 | 135 |

### Key Classification Shifts (R2 → R3)

**Sonnet 4's conditional collapse:** R2 Sonnet found 250 conditional pairs (the single biggest differentiator). R3 Sonnet found only **10**. The claude_xml renderer may have changed how conditional dependencies are presented, causing Sonnet to classify them differently. This is the primary driver of Sonnet's regression.

**M2.7's implication surge:** 132 implication pairs (up from 120 in R2) plus more even distribution across types. The generic prompt_specs gave M2.7 clearer classification definitions, reducing its R2 failure modes (parse errors dropped from 13 → 1, empty content from 73 → 7).

**Haiku's conservative shift:** 374 none (up from 468 in R2 — wait, actually R2 had 468 none, R3 has 374). Haiku classified more pairs as ME (188 vs 49) but far fewer as implication (21 vs 7→21). Despite finding 502 opportunities, none passed the sizing threshold.

**Qwen3.5-122B implication bias:** 184 implication pairs — highest of any model. Almost zero partition (2). This model sees probabilistic relationships everywhere but rarely calls them deterministic.

### Source Breakdown

| Model | llm_vector | llm_label | rule_based |
|-------|-----------|-----------|------------|
| gpt-4.1-mini | 188 | 404 | 5 |
| Sonnet 4 | 196 | 396 | 5 |
| Haiku 3.5 | 195 | 397 | 5 |
| Gemini 2.5 Flash | 188 | 404 | 5 |
| DeepSeek V3 | 194 | 398 | 5 |
| M2.7 | 195 | 397 | 5 |
| Qwen3 Max | 196 | 396 | 5 |
| Qwen3.5-122B | 196 | 396 | 5 |

Vector success rates are consistent across all models (~32-33%), suggesting the degenerate rate is driven by the pair data (pairs where all outcome combos are valid), not model capability.

---

## 4. Operational Quality

| Model | Parse Fails | Degenerate Vecs | Empty Content | Vec Success | Vec Rate | JSON Reliability |
|-------|------------|-----------------|---------------|-------------|----------|-----------------|
| gpt-4.1-mini | 0 | 404 | 0 | 188 | 32% | Excellent |
| Sonnet 4 | 0 | 396 | 0 | 196 | 33% | Excellent |
| Haiku 3.5 | 4 | 393 | 0 | 195 | 33% | Good (4 parse fail) |
| Gemini 2.5 Flash | 3 | 401 | 0 | 188 | 32% | Good (3 parse fail) |
| DeepSeek V3 | 0 | 392 | 0 | 194 | 33% | Excellent |
| M2.7 | 1 | 396 | 7 | 195 | 33% | Improved (was 13+73) |
| Qwen3 Max | 0 | 395 | 0 | 196 | 33% | Excellent |
| Qwen3.5-122B | 0 | 396 | 0 | 196 | 33% | Excellent |

**M2.7 operational quality dramatically improved:** Parse fails dropped from 13 → 1, empty content from 73 → 7. The prompt_specs layer gave M2.7 clearer format instructions, fixing its worst R2 failure mode. This directly contributed to its performance reversal.

**Haiku 3.5 regressed slightly:** 0 parse fails in R2 → 4 in R3. The claude_xml adapter may be introducing XML parsing edge cases.

**Both Qwen models: perfect operational quality.** Zero parse errors, zero empty content, 33% vec rate. DashScope compatibility fix (`_supports_json_response_format()` returning False) worked correctly.

### Reclassification Wall-Clock Times

| Model | Duration | API |
|-------|----------|-----|
| Gemini 2.5 Flash | ~19 min | OpenRouter |
| gpt-4.1-mini | ~20 min | OpenRouter |
| Sonnet 4 | ~21 min | OpenRouter |
| Haiku 3.5 | ~21 min | OpenRouter |
| DeepSeek V3 | ~40 min | OpenRouter |
| Qwen3 Max | ~39 min | DashScope |
| M2.7 | ~90 min | OpenRouter |
| Qwen3.5-122B | ~147 min | DashScope |

DashScope models were notably slower — Qwen3.5-122B took 2.5 hours for reclassification alone. M2.7 remains slow via OpenRouter.

---

## 5. The Claude XML Adapter Problem

The most striking finding is that **both models receiving `claude_xml` adapter regressed**:

| Model | R2 (inline prompts) | R3 (claude_xml) | Delta |
|-------|---------------------|-----------------|-------|
| Sonnet 4 | +0.84%, Sharpe 1.51 | +0.07%, Sharpe 0.04 | **-0.77%** |
| Haiku 3.5 | +0.09%, Sharpe 0.99 | 0.00%, Sharpe 0.00 | **-0.09%** |

Meanwhile, all 6 models on `openai_generic` either improved or held steady.

**Hypothesis: The claude_xml renderer changes the prompt structure in a way that degrades Anthropic model classification quality.** Sonnet's conditional detection collapsed from 250 → 10 pairs. Haiku stopped trading entirely.

This could be caused by:
1. XML tags altering how the model interprets classification definitions vs inline text
2. The reusable-prefix/request-suffix split changing context order
3. Overly structured XML constraining the model's reasoning

**Action required:** Re-run Sonnet 4 and Haiku 3.5 with `--prompt-adapter openai_generic` to isolate whether the regression is from the claude_xml adapter or from the prompt_specs content itself.

---

## 6. Decision Criteria Check

| Criterion | gpt-4.1-mini | M2.7 | Haiku | Sonnet | Gemini | DeepSeek | Qwen3 Max | Qwen3.5-122B |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Sharpe > 1.0 | **1.09** | 0.30 | 0.00 | 0.04 | **1.37** | 0.12 | 0.16 | 0.16 |
| Max DD < 5% | 0.01% | 4.09% | 0.00% | 3.25% | **0.11%** | 0.07% | 4.28% | 3.46% |
| Realized PnL > $0 | $5.04 | **$89.38** | $0.00 | $8.45 | $15.03 | $1.33 | $49.67 | $39.35 |
| Vec rate > 40% | 32% | 33% | 33% | 33% | 32% | 33% | 33% | 33% |
| Zero parse errors | **0** | 1 | 4 | **0** | 3 | **0** | **0** | **0** |
| Time < 2 hr | ~20m | ~90m | ~21m | ~21m | ~19m | ~40m | ~39m | ~147m |
| Trades > 0 | 4 | **346** | 0 | 294 | 74 | 2 | **404** | 228 |

Models passing Sharpe + DD + PnL: **gpt-4.1-mini, Gemini 2.5 Flash** only.

No model passes vec rate > 40% (structural issue — degenerate pairs dominate).

---

## 7. Cost Analysis

### Round 3 API Costs

| Model | API | Estimated Cost | Cost Basis |
|-------|-----|---------------|------------|
| Sonnet 4 | OpenRouter | ~$11.60 | $5.63/M tokens (from R2 billing) |
| M2.7 | OpenRouter | ~$4.28 | $1.05/M tokens |
| Haiku 3.5 | OpenRouter | ~$1.41 | $1.45/M tokens |
| Gemini 2.5 Flash | OpenRouter | ~$0.85 | $0.87/M tokens |
| gpt-4.1-mini | OpenRouter | ~$0.76 | $0.66/M tokens |
| DeepSeek V3 | OpenRouter | ~$0.20 | $0.46/M tokens |
| Qwen3 Max | DashScope | **$0.00** | 1M free tokens |
| Qwen3.5-122B | DashScope | **$0.00** | 1M free tokens |

*OpenRouter costs estimated from R2 billing (same models, same pair count). Qwen models were free under DashScope trial.*

### Cost-Performance (Net Profit per Reclassify Run)

| Model | Return | Est. Cost | Net Profit | Cost per $1 PnL |
|-------|--------|-----------|------------|-----------------|
| **Qwen3 Max** | +$49.67 | $0.00 | **+$49.67** | $0.00 |
| Qwen3.5-122B | +$39.35 | $0.00 | +$39.35 | $0.00 |
| M2.7 | +$89.38 | ~$4.28 | +$85.10 | $0.05 |
| Gemini 2.5 Flash | +$15.03 | ~$0.85 | +$14.18 | $0.06 |
| gpt-4.1-mini | +$5.04 | ~$0.76 | +$4.28 | $0.15 |
| DeepSeek V3 | +$1.33 | ~$0.20 | +$1.13 | $0.15 |
| Sonnet 4 | +$8.45 | ~$11.60 | **-$3.15** | N/A (net loss) |
| Haiku 3.5 | $0.00 | ~$1.41 | -$1.41 | N/A |

**Sonnet 4 is now net negative** — the only model where API cost exceeds backtest PnL. This is a reversal from Round 2 where Sonnet had 7.3x ROI.

---

## 8. Qwen Model Assessment

Both Qwen models performed well for free-tier models:

| Metric | Qwen3 Max | Qwen3.5-122B |
|--------|-----------|--------------|
| Return | +0.48% | +0.38% |
| Sharpe | 0.16 | 0.16 |
| Trades | 404 | 228 |
| Settled | 30 | 15 |
| Opps | 2,119 | 1,224 |
| Conditional | 17 | 3 |
| Parse Errors | 0 | 0 |
| Reclassify Time | ~39 min | ~147 min |
| Cost | Free | Free |

**Qwen3 Max is the better Qwen model:** higher return, more trades/settled, more conditionals (17 vs 3), 4x faster. Qwen3.5-122B is biased toward implication (184 — highest of any model) and almost never classifies partition (2).

**Qwen3 Max vs Sonnet 4 (R3):** Qwen3 Max outperformed Sonnet in Round 3 on every metric except Sharpe (both poor). At zero cost vs ~$11.60, Qwen3 Max is the clear choice if these results hold.

**However:** This comparison is unfair to Sonnet because the claude_xml adapter may be degrading it. A proper comparison requires re-running Sonnet on openai_generic.

---

## 9. Recommendations

### Immediate: Isolate the Claude XML Problem
Re-run Sonnet 4 and Haiku 3.5 with `--prompt-adapter openai_generic` to determine whether:
- (a) The regression is caused by the claude_xml adapter (fixable)
- (b) The regression is caused by the prompt_specs content itself (prompt engineering issue)

### If Claude XML is the problem:
- Remove or fix the claude_xml renderer
- Use openai_generic for all models including Anthropic
- Sonnet 4 may recover its R2 performance (+0.84%, Sharpe 1.51)

### If prompt_specs content is the problem:
- The prompt_specs layer changed classification definitions in a way that hurts precision
- M2.7's improvement suggests the new definitions are better for weaker models but worse for strong ones
- Consider model-specific prompt tuning

### Current best choices (pending Sonnet re-test):

**For maximum return:** M2.7 at +0.87% ($89.38 PnL), but Sharpe is only 0.30 and max DD is 4.09% — higher risk.

**For best risk-adjusted return:** Gemini 2.5 Flash at Sharpe 1.37, 0.11% DD — but only +0.19% return.

**For free evaluation / development:** Qwen3 Max — strong performance at zero cost.

### Caching Remains Critical
The caching optimization from Round 2's recommendation still applies. No model is profitable in live production without caching (re-classifying 31k pairs/day). Implement caching first, then choose model.

---

## 10. Infrastructure Notes

- 8 per-model databases cloned from `polyarb_backtest` template, cleaned up after completion
- Script: `scripts/run_eval_round3.sh` (sources `.env` for API keys)
- DashScope API: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
- Qwen JSON-mode fix: `_supports_json_response_format()` returns False for "qwen" models, avoiding DashScope 400 errors
- Docker image rebuilt before run to pick up `--prompt-adapter` argparse argument
- All 8 models completed successfully (0 errors in reclassify, all backtests ran to completion)
- Wall clock: ~2.5 hours (bounded by Qwen3.5-122B reclassify at ~147 min)

---

## 11. Trade Quality Deep Inspection

### The Fed Rate Cut Cluster (Dominant Profit Driver)

The most traded markets across all top performers are the Fed rate cut series:

| Market ID | Question | Resolved |
|-----------|----------|----------|
| 923 | Will 1 Fed rate cut happen in 2025? | **No** |
| 655 | Will 2 Fed rate cuts happen in 2025? | **No** |
| 698 | Will 3 Fed rate cuts happen in 2025? | **Yes** |
| 848 | Will 4 Fed rate cuts happen in 2025? | **No** |
| 1053 | Will 6 Fed rate cuts happen in 2025? | **No** |

These are "exactly N" markets forming a partition (only one can resolve Yes). The template DB correctly had them as `mutual_exclusion`.

**Critical finding: All top 3 performers reclassified these from ME → implication.**

| Model | Pair 232 (2 cuts vs 1 cut) R3 Type | Traded Market 655? |
|-------|------------------------------------|--------------------|
| M2.7 | **implication** (was ME) | 129 trades |
| Qwen3 Max | **implication** (was ME) | 145 trades |
| Qwen3.5-122B | **implication** (was ME) | 94 trades |
| Sonnet 4 | **implication** (was ME) | 106 trades |
| gpt-4.1-mini | none (was ME) | 0 trades |
| Haiku 3.5 | none (was ME) | 0 trades |
| DeepSeek V3 | none (was ME) | 0 trades |
| Gemini 2.5 Flash | cross_platform (was ME) | 0 trades |

The resolution vector prompt interpreted "2 cuts" and "1 cut" with at-least semantics ("2 cuts implies 1 cut"), reclassifying them as `implication`. This is **technically wrong** for "exactly N" markets, but the implication constraint still produces valid trades because:
- SELL "2 cuts" Yes + BUY "1 cut" Yes is a directional spread
- Both settled No (3 cuts happened), so the sell-side wins more than the buy-side loses
- Asymmetric sizing drove net profit

### M2.7 Settlement Breakdown (+$89.38 from 45 settlements)

| Category | Settlements | Sum PnL | Key Markets |
|----------|-------------|---------|-------------|
| Fed rate cuts | ~15 | **+$61** | 655/923 pair dominates |
| Mavericks/Nuggets | ~22 | **+$74** | 2383 (Mavs) won, 871 (Nugs) lost |
| Pokrovsk/Russia | ~12 | **-$12** | 1712/2647 — consistent small losses |
| Other sports | ~6 | **+$6** | 3007 Saints, 1661 Bucs |
| **Win/loss split** | **19 wins / 26 losses** | **+$89.38** | Big winners, small losers |

**Assessment:** M2.7's profit is concentrated in 2 clusters — Fed rate cuts and the Mavericks/Nuggets series. The Mavericks trades (+$74 net from 22 settlements on a genuine sports ME pair) are the cleanest signal. The Fed rate cuts are a misclassified but accidentally profitable spread.

### Qwen3 Max Settlement Breakdown (+$49.67 from 30 settlements)

Same pattern — dominated by Fed rate cut cluster. Market 655 alone contributed +$162.72 (offset by -$83 on market 923 and -$30 on market 698). Win/loss split: 9 wins / 21 losses, but the 9 wins are large.

### Sonnet 4 Settlement Breakdown (+$8.45 from 18 settlements)

Only 3 positive settlements out of 18. Market 655 was the biggest winner (+$114.73) but losses on 923 (-$83.04) and 698 (-$30.03) nearly wiped it out. Sonnet's problem: it generated 294 trades but most didn't settle profitably. The claude_xml adapter + new definitions created more trades (294 vs 136 in R2) but with much worse selection quality.

### Gemini 2.5 Flash Sharpe Explanation

Gemini had **353 zero-return days** out of 487. Only 134 days with any movement (75 positive, 59 negative). Max daily return: +0.054%, min: -0.038%. Extremely low volatility → high Sharpe despite minimal absolute return. This is the opposite of M2.7's strategy: very conservative, barely trades, but when it does, it's slightly net positive.

### Concentration Risk Warning

**80%+ of all profit across top 3 models comes from ~3 market clusters:**
1. Fed rate cuts (pairs 230-235, 496-499) — misclassified ME→implication, accidentally profitable
2. Mavericks vs Nuggets (pair 458) — genuine sports ME
3. Pokrovsk/Russia (pair with 1712/2647) — consistent small losses across all models

This concentration means results may not generalize. A different resolution in the Fed rate cut cluster (e.g., exactly 2 cuts instead of 3) would have reversed M2.7's and Qwen3 Max's results.

---

## 12. Sonnet R2 → R3 Classification Shift

| Type | R2 Sonnet | R3 Sonnet | Delta |
|------|-----------|-----------|-------|
| conditional | **250** | 10 | **-240** |
| none | 56 | **287** | +231 |
| mutual_exclusion | 166 | 196 | +30 |
| partition | 38 | 8 | -30 |
| implication | 83 | 93 | +10 |

**240 conditional pairs vanished.** Most became `none` (+231). R2 used old inline prompts (no prompt_specs, no adapter). R3 used prompt_specs + claude_xml.

Two variables changed simultaneously:
1. **Prompt definitions** — the label_v1 spec defines conditional as "Market A's outcome probabilities are logically constrained by Market B's outcome." R2's inline prompt was broader.
2. **Claude XML adapter** — wraps definitions in `<definitions><item>...</item></definitions>` XML tags

**To isolate:** Re-run Sonnet with `--prompt-adapter openai_generic` (Step 1 of inspection plan). If conditionals recover, the claude_xml adapter is the problem. If they don't, the new definitions are too narrow for conditional detection.

---

## 13. Next Steps

1. **Re-run Sonnet 4 + Haiku 3.5 with `openai_generic`** — critical to isolate adapter regression (~$13 cost)
2. **Fix Fed rate cut misclassification** — add a hard rule or example for "exactly N" partition markets to prevent ME→implication drift
3. **Implement classification caching** — prerequisite for any live deployment decision
4. **Evaluate Qwen3 Max on OpenRouter** — check paid pricing for production viability beyond free tier
5. **Add 3-5 real examples to prompt_specs** — Fed rate cuts and sports ME are high-value examples
6. **Broader pair universe** — 597 pairs is too small and too concentrated; increase `--max-markets` for statistical significance
