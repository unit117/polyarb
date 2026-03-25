# V4 Accuracy Leaderboard — Final Recommendation

**Date:** 2026-03-25  
**Canonical gold set:** `scripts/eval_data/labeled_pairs_v4.json` (`168` hand-labeled pairs)  
**Run mode:** 8-model accuracy-only evaluation on NAS via `scripts/run_v4_eval.sh --skip-backtest`  
**NAS artifacts:** `/volume1/docker/polyarb/eval_results/v4_eval_20260325_015021/`

---

## Summary

The V4 model decision should be based on the canonical 168-row gold set, not the older backtest-era comparison.

**Recommendation**
- **Production model:** `anthropic/claude-sonnet-4`
- **Fallback / shadow candidate:** `qwen3-max`

Why:
- `anthropic/claude-sonnet-4` had the best macro F1 and `0.0%` false-positive rate on `none` pairs.
- `gpt-4.1-mini` edged it by one correct answer on raw accuracy, but its `16.7%` FPR is worse for production.
- `qwen3-max` was the strongest low-cost option with `0.0%` FPR and competitive F1.

## Leaderboard

| Rank | Model | Correct | Accuracy | Macro F1 | FPR (`none`) | Recommendation |
|------|-------|---------|----------|----------|---------------|----------------|
| 1 | `anthropic/claude-sonnet-4` | `129/168` | `76.8%` | `0.681` | `0.0%` | Production |
| 2 | `openai/gpt-4.1-mini` | `130/168` | `77.4%` | `0.669` | `16.7%` | Not production-safe |
| 3 | `qwen3-max` | `125/168` | `74.4%` | `0.673` | `0.0%` | Fallback / shadow |
| 4 | `qwen3.5-122b-a10b` | `125/168` | `74.4%` | `0.616` | `0.0%` | Secondary fallback |
| 5 | `google/gemini-2.5-flash` | `124/168` | `73.8%` | `0.544` | `8.3%` | Lower-quality backup |
| 6 | `minimax/minimax-m2.7` | `123/168` | `73.2%` | `0.646` | `0.0%` | Too slow for preferred use |
| 7 | `anthropic/claude-3.5-haiku` | `97/168` | `57.7%` | `0.538` | `16.7%` | Reject |
| 8 | `deepseek/deepseek-chat` | `96/168` | `57.1%` | `0.543` | `8.3%` | Reject |

## Interpretation

- **Best overall:** `anthropic/claude-sonnet-4`
  - Highest macro F1
  - Zero false positives on independent pairs
  - Best production safety/quality tradeoff

- **Why not `gpt-4.1-mini`:**
  - Highest raw accuracy by one example
  - But materially worse FPR (`16.7%`)
  - In this system, false positives on `none` pairs are more dangerous than missing one true dependency

- **Best cheap option:** `qwen3-max`
  - Competitive F1 (`0.673`)
  - Zero FPR
  - Good candidate for fallback or shadowing

- **Not viable:** `anthropic/claude-3.5-haiku`, `deepseek/deepseek-chat`
  - Both clustered near the stored-label baseline and are not production-quality classifiers here

## Operational Notes

- The V4 smoke pipeline was fixed to:
  - wait for Postgres readiness after `CREATE DATABASE ... WITH TEMPLATE ...`
  - write machine-readable accuracy JSON per model
  - populate `summary.md` from JSON instead of brittle grep parsing

- The V4 silver backtest remained **non-informative**:
  - `0` trades
  - `0` settlements
  - flat PnL
  - likely because most candidate silver pairs fail verification at detection time

This means the model choice above is a **classification-quality decision**, not a trading-PnL decision.

## Artifact Paths

NAS directory:

```text
/volume1/docker/polyarb/eval_results/v4_eval_20260325_015021/
```

Key files:

- `summary.md`
- `metadata.txt`
- `goldset_analysis.log`
- `{model}_reclassify.log`
- `{model}_accuracy.log`
- `{model}_accuracy.json`

Machine-readable JSON fields observed in accuracy outputs:

- `model`
- `correct`
- `total`
- `accuracy_pct`
- `macro_f1`
- `fpr_pct`

## Follow-Up Backlog

1. Diagnose why the silver dataset yields `0` opportunities / trades.
2. Reduce live classifier cost by caching previously classified pairs.
3. Decide whether `qwen3-max` should run as a shadow classifier in production.
