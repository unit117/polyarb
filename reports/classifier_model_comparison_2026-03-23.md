# Classifier Model Comparison — Round 1 (INVALID)

**Date:** 2026-03-23
**Backtest period:** 2024-09-24 to 2026-01-25 (489 days)
**Initial capital:** $10,000
**Dataset:** 597 market pairs from Polymarket
**Code baseline:** commit `ba95b26` (missing critical fixes — see section 8)

> **WARNING: All backtest results in this report are INVALID.**
> Three commits landed after these runs (`366efe1`, `292d3dc`, `696b935`) fixing:
> implication direction defaulting, Kelly sizing, unconstrained matrix profit bounds,
> and restore replay fees. A clean re-run using the eval guideline
> (`reports/model_eval_guideline.md`) is required.

---

## 1. Testing History

### Phase 1: gpt-4.1-mini baseline (commit `188c224`)
- Reclassified 597 pairs via OpenRouter (`openai/gpt-4.1-mini`)
- 443/597 pairs changed from original LLM labels
- Backtest: +1.72%, Sharpe 6.52, 0.09% max DD, 392 trades

### Phase 2: MiniMax M2.7 (commit `ba95b26`)
- Hit M2.7 `content: null` bug — mandatory `<think>` exhausts token budget
- Fixed: bumped max_tokens to 1024/2048, added model_extra fallback
- First run SSH dropped at 309/597 — re-ran with `nohup`
- Full reclassification: 6 hours, 62/597 changed from gpt-4.1-mini baseline
- Backtest: +8.87%, Sharpe 1.13, 8.80% max DD, 1,224 trades

### Phase 3: Haiku 3.5 (commit `ba95b26`)
- Fast run (~22 min), clean JSON, no parse failures
- Very conservative: 467/597 classified as `none`, only 8 implications
- Backtest: +0.16%, Sharpe 1.65, 0.01% max DD, 32 trades — barely trading

### Phase 4: Sonnet 4, Gemini 2.5 Flash, DeepSeek V3 (commit `ba95b26`)
- Ran as automated pipeline (reclassify + backtest sequentially)
- **Sonnet 4**: Reclassified 514/597. Aggressive — 248 `conditional`, only 57 `none`. Backtest: +1.49%, Sharpe 2.32, 0.78% max DD, 164 trades
- **Gemini 2.5 Flash**: Reclassified 349/597. Moderate profile — 333 `none`, 146 ME, 74 implication. Backtest not completed (pipeline killed)
- **DeepSeek V3**: Never started (pipeline killed before reaching it)

### Phase 5: Bug discovery
- Found 3 new commits (`366efe1`, `292d3dc`, `696b935`) fixing critical backtest bugs
- All previous results invalidated — need clean re-run with latest code

---

## 2. Reclassification Results (VALID — classifier-only, not affected by backtest bugs)

| Model | none | impl | ME | part | cond | cross | Non-none | Vec Rate | Time |
|-------|------|------|----|------|------|-------|----------|----------|------|
| gpt-4.1-mini | 318 | 111 | 98 | 64 | 3 | 3 | 279 | ~47% | ~40 min |
| M2.7 | 305 | 118 | 101 | 69 | 1 | 3 | 292 | 54% | ~6 hr |
| Haiku 3.5 | 467 | 8 | 49 | 73 | 0 | 0 | 130 | 33% | ~22 min |
| Sonnet 4 | 57 | 83 | 165 | 40 | 248 | 4 | 540 | 33% | ~30 min |
| Gemini 2.5 Flash | 333 | 74 | 146 | 23 | 15 | 6 | 264 | 33% | ~15 min |
| DeepSeek V3 | — | — | — | — | — | — | — | — | not run |

### Source Breakdown

| Model | llm_vector | llm_label | rule_based |
|-------|-----------|-----------|------------|
| gpt-4.1-mini | ~280 | ~312 | 5 |
| M2.7 | 319 | 273 | 5 |
| Haiku 3.5 | 195 | 397 | 5 |
| Sonnet 4 | 196 | 396 | 5 |
| Gemini 2.5 Flash | 194 | 398 | 5 |

### Operational Quality

| Model | Parse Fails | Degenerate Vecs | Reasoning-Only | JSON Reliability |
|-------|------------|-----------------|----------------|-----------------|
| gpt-4.1-mini | ~0 | moderate | 0 | Excellent |
| M2.7 | 7 | 204 | frequent | Poor — needs label fallback |
| Haiku 3.5 | 0 | many | 0 | Good |
| Sonnet 4 | 0 | many | 0 | Good |
| Gemini 2.5 Flash | 0 | many | 0 | Good |

---

## 3. Backtest Results (INVALID — pre-bug-fix, do not use for decisions)

| Model | Return | PnL | Sharpe | Max DD | Trades |
|-------|--------|-----|--------|--------|--------|
| gpt-4.1-mini | +1.72% | $176 | 6.52 | 0.09% | 392 |
| M2.7 | +8.87% | $893 | 1.13 | 8.80% | 1,224 |
| Haiku 3.5 | +0.16% | $16 | 1.65 | 0.01% | 32 |
| Sonnet 4 | +1.49% | $149 | 2.32 | 0.78% | 164 |
| Gemini 2.5 Flash | — | — | — | — | — |
| DeepSeek V3 | — | — | — | — | — |

---

## 4. Key Observations (from classification data — still valid)

### Model Personalities
- **gpt-4.1-mini**: Balanced. Finds moderate dependencies. Good vector success rate. Production baseline.
- **M2.7**: Slightly more aggressive than 4.1-mini (+13 non-none). Highest vector rate (54%) but worst JSON reliability. Very slow (6 hr). Uses reasoning well but often fails to produce structured output.
- **Haiku 3.5**: Ultra-conservative. Barely finds dependencies (130 non-none). Fastest and cheapest. Not useful as a standalone classifier.
- **Sonnet 4**: Most aggressive by far (540 non-none). Overuses `conditional` (248 — suspicious). May hallucinate dependencies.
- **Gemini 2.5 Flash**: Similar profile to gpt-4.1-mini but finds more ME (+48) and fewer implications (-37). Moderate and fast.

### Consensus Patterns
- All models agree on ~5 rule-based pairs
- Independent sports matchups (different games) are universally classified as `none` — degenerate vector path works correctly
- The implication vs partition boundary is the main disagreement zone (M2.7 flipped 28 pairs between these types)
- Sonnet's 248 `conditional` classifications are an outlier — no other model finds more than 15

---

## 5. Infrastructure Notes

- All models ran via **OpenRouter** (`https://openrouter.ai/api/v1`)
- `nohup` required for long runs (M2.7) to survive SSH drops
- Automated pipeline script works but `set -euo pipefail` should be added (done in updated guideline)
- Backtest image must be rebuilt after code changes — stale images caused ingestor crash-loop (missing migration 012)
- Eval results should be saved to `eval_results/<timestamp>/` on NAS, not `/tmp/`

---

## 6. Fixes Applied During This Session

| Commit | Description |
|--------|-------------|
| `ba95b26` | P2: reasoning-only fails closed, `--force` flag for live DB guard, M2.7 max_tokens bump |

---

## 7. Fixes Discovered After Testing (Invalidate Backtests)

| Commit | Description | Impact |
|--------|-------------|--------|
| `366efe1` | Implication direction from pair column, unconstrained fallback, Kelly sizing | All implication pair results wrong |
| `292d3dc` | Restore replay for short covers, Python 3.9 compat | Simulator accuracy |
| `696b935` | Restore replay fee handling for short-basis | Simulator accuracy |

---

## 8. Next Steps

1. Deploy latest code (commit `696b935` or later) to NAS
2. Rebuild backtest image
3. Run full 6-model eval using `reports/model_eval_guideline.md` protocol
4. Include DeepSeek V3 (never ran) and re-run Gemini 2.5 Flash backtest
5. Compile final comparison report with valid results
