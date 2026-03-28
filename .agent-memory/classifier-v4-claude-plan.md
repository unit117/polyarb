# Claude V4 Plan: Merge & Deploy

Last updated: 2026-03-24

## Approach

Merge-first. Both implementations are complementary — GPT did analysis/planning + prompt infrastructure, Claude did implementation + data artifacts. Merge best of both into main, test, deploy, run eval.

## Branch Topology
```
          7a67626 (stale Claude branch)
         /
5ee6abd--+-- 5235e13 (codex/classifier-v4) -- 8d909ca (main)
                 ↑
            Claude worktree (+ uncommitted V4 files)
```

## What Each Side Built

### GPT/Codex (main at 8d909ca)
- `services/detector/prompt_specs.py` — PromptSpec dataclasses, dual renderers, adapter auto-dispatch
- `services/detector/classifier.py` — `_supports_json_response_format()` for Qwen + MiniMax
- Round 3 eval reports (8-model comparison, deep inspection, V4 plan)
- `scripts/eval_classifier.py` — `analyze` subcommand, `none_candidate` normalization
- `scripts/export_goldset_v4.py` — negative family tracking, SAFE_NONE_FAMILIES allowlist
- 168-pair labeled gold set (58.9% accuracy, zero surviving partition in ground truth)
- 24 focused tests

### Claude (worktree at 5235e13 + uncommitted)
- `scripts/export_goldset_v4.py` — 667 lines, 18 market shape patterns, hard-negative mining via pgvector
- `scripts/analyze_goldset.py` — quality metrics + gate check
- `scripts/curate_silver_dataset.py` — silver dataset curation with noisy-sports filter
- `scripts/run_v4_eval.sh` — 4-phase eval orchestrator for 8 models
- 150-pair labeled gold set (72% accuracy, ground truth: impl=76, ME=41, part=23, cond=3, none=7)
- `scripts/backtest.py` — settle-before-detect + `--pair-ids`/`--pair-file` flags
- 95 tests (76 goldset + 13 analyzer + 12 curator + integration tests)

## Merge Strategy

### Step 1: Copy Claude files into main
New files (no conflict): analyze_goldset.py, run_v4_eval.sh, silver_pairs_v4.json, test files

### Step 2: Keep GPT's classifier.py
`_supports_json_response_format()` correctly handles both Qwen and MiniMax. Claude's simplified check misses Qwen.

### Step 3: Reconcile backtest.py
Main has resolved-market fix. Add Claude's `--pair-file` flag (needed by run_v4_eval.sh).

### Step 4: Reconcile eval_classifier.py
Merge GPT's analyze + none normalization with Claude's confusion matrix + macro F1.

### Step 5: Use Claude's export_goldset_v4.py
More mature family classification, broader test coverage, produced the higher-quality labeled set.

### Step 6: Test, deploy, smoke test, full 8-model eval

## Key Decision
Use Claude's 150-pair gold set as canonical (72% accuracy baseline, well-distributed types).
GPT's 168-pair set has quality issues (zero partition in ground truth, 40 conditional, 100% FPR on none).

## Estimated Cost & Time
- Smoke test: ~$0.76, ~45 min
- Full eval: ~$90, ~4 hours
