# Classifier V4 Handoff Memory

Last updated: 2026-03-25

## Canonical Worktree

- Continue in: `/Users/unit117/Dev/polyarb`
- Treat the main checkout as the canonical Codex V4 workspace.
- Active V4 branch: `codex/classifier-v4`
- The old V4 worktrees were removed after consolidation into this branch.

## Current Modified Files

- `scripts/export_goldset_v4.py`
- `tests/unit/test_export_goldset_v4.py`
- `scripts/eval_data/LABELING_GUIDE_v4.md`
- `scripts/eval_data/labeled_pairs_v4.json`
- `scripts/eval_classifier.py`

## What Is Finished

- V4 exporter exists and is usable.
- `eval_classifier.py` supports `--data-file` for export/eval/autolabel.
- V4 labeled dataset draft has been generated:
  `scripts/eval_data/labeled_pairs_v4.json`
- Manual labeling is complete for all 168 V4 rows.
- V4 evaluation has been run on the completed gold set.
- V4 failure analysis tooling and report now exist:
  - command: `python -m scripts.eval_classifier analyze --data-file scripts/eval_data/labeled_pairs_v4.json`
  - report: `/Users/unit117/Dev/polyarb/reports/classifier_v4_failure_analysis_2026-03-24.md`
- Exporter now:
  - prefers verified resolved pairs but falls back to resolved unverified pairs when a dependency type would otherwise underfill
  - uses hard-negative signature caps to avoid one-topic domination
  - seeds sparse negative families so they survive final selection
  - uses question text, not description boilerplate, for family-shape detection
  - avoids crypto false positives like `Solana Sierra`
  - splits `none` into explicit negative families instead of one catch-all tag
  - only admits conservative hard-negative families into the V4 `none` bucket (`same_team_nearby_match_negative` and `other`)
  - keeps the structured negative tags for diagnostics, but excludes them from `none` export after V4 manual review showed they were all mislabeled
  - prints a warning if the conservative none pool underfills instead of silently backfilling with structured pairs

## Current V4 Gold Set

- File:
  `/Users/unit117/Dev/polyarb/scripts/eval_data/labeled_pairs_v4.json`
- Total rows: `168`
- Ground-truth counts after manual labeling:
  - `implication`: 63
  - `mutual_exclusion`: 53
  - `conditional`: 40
  - `none`: 12
- Current-system correctness on the labeled set:
  - `correct=true`: 99
  - `correct=false`: 69
- Important relabel finding:
  - many exporter-seeded `none` negatives were actually real `implication` or `mutual_exclusion` pairs once reviewed manually
  - all 23 system `partition` predictions were relabeled to other classes; none survived as true `partition`

## Fresh Re-Export After None-Gate Tightening

- New export file:
  `/Users/unit117/Dev/polyarb/scripts/eval_data/labeled_pairs_v4_reexport_2026-03-24.json`
- Export completed against the live NAS DB with no none-bucket underfill warning.
- Type counts remained:
  - `implication`: 45
  - `mutual_exclusion`: 35
  - `partition`: 23
  - `conditional`: 25
  - `none`: 40
- Key change:
  - all 40 `none` rows are now `same_team_nearby_match_negative`
  - the old structured negative families no longer appear in the exported none bucket
- New follow-up risk:
  - `same_team_nearby_match_negative` is still too broad and is now absorbing many same-entity scalar/bracket pairs that are likely structured rather than true `none`

## Exporter Negative Family Mix

- These were the exporter-seeded negative families before manual review.
- Many were relabeled to `implication`, `mutual_exclusion`, or `conditional` during annotation.
- Export-time mix:
  - `weather_temp_ladder_negative`: 12
  - `sports_ou_ladder_negative`: 12
  - `social_post_window_negative`: 6
  - `geopolitical_window_negative`: 3
  - `ai_model_horizon_negative`: 2
  - `sports_spread_ladder_negative`: 2
  - `event_timing_negative`: 1
  - `intraday_direction_negative`: 1
  - `scalar_threshold_negative`: 1

## Verification Status

- Focused tests pass:
  - `python -m pytest tests/unit/test_export_goldset_v4.py -q`
  - result at handoff: `20 passed`
- CLI help verified:
  - `python scripts/export_goldset_v4.py --help`
  - `python -m scripts.eval_classifier export --help`
- V4 evaluation run completed:
  - `source /tmp/polyarb-v4-export-venv/bin/activate`
  - `set -a && source /Users/unit117/Dev/polyarb/.env && set +a`
  - `python -m scripts.eval_classifier eval --data-file scripts/eval_data/labeled_pairs_v4.json`
  - result:
    - overall accuracy: `99/168` (`58.9%`)
    - rule-based: `35/36` (`97.2%`)
    - llm: `64/132` (`48.5%`)
    - independent-pair FPR: `12/12` (`100.0%`)
- V4 analysis run completed:
  - `python -m scripts.eval_classifier analyze --data-file scripts/eval_data/labeled_pairs_v4.json`
  - saved findings:
    - `none -> mutual_exclusion`: `16`
    - `none -> implication`: `14`
    - `partition -> none`: `12`
    - `none -> conditional`: `10`
    - `partition -> conditional`: `7`

## How Export Was Run

- Disposable venv used:
  `/tmp/polyarb-v4-export-venv`
- NAS DB override used for live export:
  - `POSTGRES_HOST=192.168.5.100`
  - `POSTGRES_PORT=5434`
- Typical command:

```bash
source /tmp/polyarb-v4-export-venv/bin/activate
set -a && source /Users/unit117/Dev/polyarb/.env && set +a
export POSTGRES_HOST=192.168.5.100 POSTGRES_PORT=5434
python scripts/export_goldset_v4.py
```

## Important Heuristic State

- `scripts/export_goldset_v4.py` now contains:
  - negative family constants and boosts
  - `_hard_negative_signature()`
  - `_seed_family_coverage()`
  - `_select_balanced(..., preselected=...)`
- Do not revert the resolved-unverified fallback unless the DB verification population changes materially; the live DB currently has `0` verified resolved `mutual_exclusion` pairs, so a verified-only filter collapses that class.

## What Is Not Finished

- No shadow-model comparison has been run yet on the completed V4 gold set.
- Fresh export has been run after tightening the hard-negative `none` allowlist, but `same_team_nearby_match_negative` is still too broad and is contaminating the `none` bucket.
- No follow-up exporter pass has been done yet for the mislabeled persisted `partition` families that manual review exposed.
- No classifier heuristic patch has been attempted yet beyond the exporter-side hard-negative fix.

## Claude V4 Snapshot

- Claude workspace:
  `/Users/unit117/Dev/polyarb/.claude/worktrees/claude-v4-implementation`
- Claude branch:
  `worktree-claude-v4-implementation`
- Reviewed Claude V4 files of interest:
  - `scripts/export_goldset_v4.py`
  - `scripts/eval_classifier.py`
  - `scripts/backtest.py`
  - `scripts/curate_silver_dataset.py`
  - `scripts/analyze_goldset.py`
  - `scripts/run_v4_eval.sh`
  - `tests/integration/test_backtest_resolved_markets.py`
  - `tests/unit/test_goldset_v4.py`
- Claude worktree also has uncommitted V4 artifacts:
  - `tests/unit/test_analyze_goldset.py`
  - `tests/unit/test_silver_curator.py`
  - local dataset files in that worktree

## Reviewed Code Comparison

- Codex V4 is currently stronger on the manual-review feedback loop:
  - the exporter was tightened after V4 annotation so structured negative families no longer enter the exported `none` bucket
  - `scripts/eval_classifier.py` has `analyze` support and normalizes `none_candidate -> none` in scoring
- Claude V4 is currently stronger on breadth of tooling and tests:
  - adds `scripts/curate_silver_dataset.py`
  - adds `scripts/analyze_goldset.py`
  - adds `scripts/run_v4_eval.sh`
  - adds much broader V4 test coverage
- Important behavioral differences by subsystem:
  - `scripts/export_goldset_v4.py` differs materially and must be compared by exported output quality, not by file diff alone
  - `scripts/eval_classifier.py` differs mostly in reporting surface; bare `eval` is not enough to compare branch behavior because it primarily scores the dataset’s stored labels
  - `scripts/backtest.py` differs in workflow behavior; Claude adds settle-before-detect and pair filtering while Codex already has resolved-market skip guards
  - `services/detector/classifier.py` differs only in one material runtime detail relevant to model comparison:
    - Codex disables JSON response-format mode for both `minimax` and `qwen`
    - Claude disables it only for `minimax`
    - this matters for Qwen comparisons and should be treated as runtime compatibility, not taxonomy quality
- Current focused test status after review:
  - Codex V4 focused tests: `24 passed`
  - Claude V4 focused tests: `95 passed`

## Comparison-First Plan

1. Keep the canonical labeled V4 gold set immutable and use it for every branch comparison:

```bash
CANONICAL_V4_GOLD=/Users/unit117/Dev/polyarb/scripts/eval_data/labeled_pairs_v4.json
```

- Do not overwrite the canonical labeled file.
- When running from the Claude worktree, point `--data-file` at the absolute canonical path above.

2. Compare exporter behavior first, because exporter quality is where the two V4 efforts differ most right now.

```bash
source /tmp/polyarb-v4-export-venv/bin/activate
set -a && source /Users/unit117/Dev/polyarb/.env && set +a
export POSTGRES_HOST=192.168.5.100 POSTGRES_PORT=5434

cd /Users/unit117/Dev/polyarb
python scripts/export_goldset_v4.py \
  --output /Users/unit117/Dev/polyarb/scripts/eval_data/labeled_pairs_v4_codex_reexport.json

cd /Users/unit117/Dev/polyarb/.claude/worktrees/claude-v4-implementation
python scripts/export_goldset_v4.py \
  --output /Users/unit117/Dev/polyarb/scripts/eval_data/labeled_pairs_v4_claude_reexport.json
```

- Compare:
  - total/type counts
  - `none` bucket family mix
  - whether same-entity scalar/bracket pairs are leaking into `none`
  - whether any dependency type underfills
  - whether `partition` families still look systematically suspect

3. Compare classifier behavior only with explicit reclassification runs.

- Do not use bare `python -m scripts.eval_classifier eval --data-file ...` as the branch-comparison method.
- Reason:
  - bare `eval` mostly scores the dataset’s stored `current_dependency_type`
  - that is useful for the labeled-set baseline, but not enough to compare the two codebases as implementations
- Use explicit `--model` runs from both worktrees on the same gold set.
- Semantic comparison models:
  - `openai/gpt-4.1-mini`
  - `anthropic/claude-sonnet-4`
- Compatibility comparison model:
  - `qwen3-max`

```bash
source /tmp/polyarb-v4-export-venv/bin/activate
set -a && source /Users/unit117/Dev/polyarb/.env && set +a

cd /Users/unit117/Dev/polyarb
python -m scripts.eval_classifier eval --data-file "$CANONICAL_V4_GOLD" --model openai/gpt-4.1-mini
python -m scripts.eval_classifier eval --data-file "$CANONICAL_V4_GOLD" --model anthropic/claude-sonnet-4
python -m scripts.eval_classifier eval --data-file "$CANONICAL_V4_GOLD" --model qwen3-max

cd /Users/unit117/Dev/polyarb/.claude/worktrees/claude-v4-implementation
python -m scripts.eval_classifier eval --data-file "$CANONICAL_V4_GOLD" --model openai/gpt-4.1-mini
python -m scripts.eval_classifier eval --data-file "$CANONICAL_V4_GOLD" --model anthropic/claude-sonnet-4
python -m scripts.eval_classifier eval --data-file "$CANONICAL_V4_GOLD" --model qwen3-max
```

- Record for each branch/model:
  - overall accuracy
  - independent-pair FPR
  - per-type precision/recall
  - runtime or JSON parsing failures
- Interpret Qwen results separately as adapter/runtime behavior because the reviewed classifier delta is specifically the Qwen JSON-response-format guard.

4. Compare eval/reporting and backtest workflow as separate merge lanes, not as proof that one branch “wins” overall.

- Eval/reporting merge candidates:
  - keep Codex `analyze` and label-transition failure analysis
  - consider merging Claude confusion matrix, macro F1, and family-level reclassification reporting
- Backtest/workflow merge candidates:
  - review Claude settle-before-detect logic
  - review Claude `--pair-ids` / `--pair-file`
  - review Claude silver-dataset curation and V4 orchestration scripts
  - do not rank a branch higher on classifier quality just because it has more orchestration tooling

5. Produce one decision document before any merge plan.

- Required outputs:
  - exporter comparison summary
  - model comparison table for `gpt-4.1-mini`, `claude-sonnet-4`, and `qwen3-max`
  - keep/merge/defer recommendation for:
    - exporter core
    - eval/reporting
    - classifier runtime compatibility
    - backtest/silver tooling
- Do not make a merge recommendation until all four comparison lanes above have been reviewed.

## Comparison Results (2026-03-24)

Full comparison document: `.agent-memory/v4_comparison_2026-03-24.md`

### Exporter Comparison

- **Codex exporter: 168 rows, all 5 types filled.** Falls back to resolved unverified pairs for ME (DB has 0 verified resolved ME).
- **Claude exporter: 117 rows, GATE FAIL.** 0 ME due to verified-only policy. Also only 7 partition.
- **Winner: Codex exporter** for output quality. Claude has richer taxonomy but collapses ME.

### Model Reclassification on Canonical 168-Row Gold Set

| Model | Accuracy | FPR (none) |
|-------|----------|------------|
| claude-sonnet-4 | **130/168 (77.4%)** | **0/12 (0.0%)** |
| gpt-4.1-mini | 129/168 (76.8%) | 2/12 (16.7%) |
| qwen3-max (Codex branch) | 126/168 (75.0%) | 0/12 (0.0%) |
| qwen3-max (Claude branch) | **FAILURE** | DashScope JSON response_format incompatibility |

### Model Reclassification on Secondary 150-Row Gold Set

| Model | Accuracy | FPR (none) |
|-------|----------|------------|
| gpt-4.1-mini | **124/150 (82.7%)** | 1/7 (14.3%) |
| qwen3-max (Codex branch) | 123/150 (82.0%) | 1/7 (14.3%) |
| claude-sonnet-4 | 112/150 (74.7%) | 1/7 (14.3%) |

Do not compare 168-set and 150-set accuracy directly — label distributions differ materially.

### Selective Merge Decision

**Keep from Codex:**
- `services/detector/classifier.py` — `_supports_json_response_format()` for Qwen + MiniMax
- `scripts/export_goldset_v4.py` — resolved-unverified fallback fills all 5 types
- `scripts/eval_data/labeled_pairs_v4.json` — canonical 168-row gold set
- `scripts/eval_classifier.py` — `analyze` subcommand, `_normalize_current_type()`

**Merge from Claude:**
- `scripts/backtest.py` — settle-before-detect + `--pair-ids`/`--pair-file`
- `scripts/eval_classifier.py` — confusion matrix, macro F1, per-family breakdown
- `scripts/analyze_goldset.py` — gold set quality analyzer (new file)
- `scripts/curate_silver_dataset.py` — silver curator (verify present)
- `scripts/run_v4_eval.sh` — eval orchestrator (new file)
- `scripts/eval_data/silver_pairs_v4.json` — 172 curated pairs (new file)
- Tests: `test_analyze_goldset.py`, `test_silver_curator.py`, `test_backtest_resolved_markets.py`

**Do not merge:** Claude's simplified `if “minimax” not in model` (breaks Qwen on DashScope).

## Final Outcome (2026-03-25)

Final source of truth:
- report: `/Users/unit117/Dev/polyarb/reports/classifier_v4_accuracy_leaderboard_2026-03-25.md`
- NAS artifacts: `/volume1/docker/polyarb/eval_results/v4_eval_20260325_015021/`

### Final 8-Model Accuracy Leaderboard

| Rank | Model | Correct | Accuracy | Macro F1 | FPR (none) |
|------|-------|---------|----------|----------|------------|
| 1 | `anthropic/claude-sonnet-4` | `129/168` | `76.8%` | `0.681` | `0.0%` |
| 2 | `openai/gpt-4.1-mini` | `130/168` | `77.4%` | `0.669` | `16.7%` |
| 3 | `qwen3-max` | `125/168` | `74.4%` | `0.673` | `0.0%` |
| 4 | `qwen3.5-122b-a10b` | `125/168` | `74.4%` | `0.616` | `0.0%` |
| 5 | `google/gemini-2.5-flash` | `124/168` | `73.8%` | `0.544` | `8.3%` |
| 6 | `minimax/minimax-m2.7` | `123/168` | `73.2%` | `0.646` | `0.0%` |
| 7 | `anthropic/claude-3.5-haiku` | `97/168` | `57.7%` | `0.538` | `16.7%` |
| 8 | `deepseek/deepseek-chat` | `96/168` | `57.1%` | `0.543` | `8.3%` |

### Production Decision

- **Production model:** `anthropic/claude-sonnet-4`
- **Fallback / shadow candidate:** `qwen3-max`

Rationale:
- Sonnet 4 had the best macro F1 and `0.0%` FPR.
- GPT-4.1-mini won raw accuracy by one example, but its `16.7%` FPR is too risky for production trading.
- Qwen3-max is the strongest low-cost fallback with `0.0%` FPR and competitive F1.

### Pipeline Status

- V4 eval pipeline now supports:
  - postgres readiness wait after DB cloning
  - model-specific accuracy scoring in Phase 2b
  - machine-readable accuracy JSON outputs
  - populated `summary.md` without brittle grep-only parsing
- Smoke pipeline passed on NAS end-to-end.
- The V4 silver backtest remained non-informative (`0` trades), so the model decision is based on gold-set accuracy metrics, not V4 trading PnL.

### Remaining Follow-Up

1. Diagnose why the silver dataset yields `0` opportunities / trades.
2. Add classifier caching so live operation does not repeatedly spend on already-seen pairs.
3. Decide whether `qwen3-max` should run in shadow mode in production.

## If Another Export Pass Is Needed

- Stay in the canonical worktree above.
- Keep `sample_markets=2500` unless runtime becomes a real problem.
- Re-check the `none` family mix after any heuristic change.
- Re-run the focused test file before exporting.
