# V4 Classifier Branch Comparison

**Date:** 2026-03-24
**Branches:** Codex (`codex/classifier-v4` at `5235e13` + uncommitted) vs Claude (worktree at same base + uncommitted)
**Canonical gold set:** Codex 168-row (`/Users/unit117/Dev/polyarb/scripts/eval_data/labeled_pairs_v4.json`)
**Secondary gold set:** Claude 150-row (`/Users/unit117/Dev/polyarb/.claude/worktrees/claude-v4-implementation/scripts/eval_data/labeled_pairs_v4.json`)

---

## Lane 1: Exporter Quality

| Metric | Codex Exporter | Claude Exporter |
|--------|---------------|-----------------|
| Total pairs | 168 | 117 (GATE FAIL) |
| implication | 45 | 45 |
| mutual_exclusion | 35 | **0** |
| partition | 23 | 7 |
| conditional | 25 | 25 |
| none | 40 | 40 |
| Verified pairs | 75/168 | 77/117 |
| Families | 8 distinct | 6 distinct |

**Root cause of Claude ME collapse:** The backtest DB has **0 verified resolved ME pairs**. Claude's exporter uses a verified-only policy. Codex falls back to resolved unverified pairs when a type would underfill. This is a policy difference, not an implementation bug.

**None bucket:** Both fill entirely from one family — Codex: `same_team_nearby_match_negative` (40); Claude: `same_entity_negative` (40). Both exporters have the same contamination risk in the none bucket (same-entity scalar/bracket pairs leaking in as "none").

**Codex exporter advantages:**
- Resolved-unverified fallback gives ME and partition coverage
- Structured negative families preserved for diagnostics but blocked from none bucket after V4 manual review
- `SAFE_NONE_FAMILIES` allowlist prevents mislabeled structured negatives from entering none

**Claude exporter advantages:**
- Broader family taxonomy (election_political, tech_milestone, fed_rate, economic_indicator)
- `_has_enough_text_for_type()` relaxed filter for partition/conditional (short sports questions pass)
- 76 unit tests vs Codex's 24

**Winner: Codex exporter for output quality** (fills all 5 types). Claude exporter for taxonomy richness and test coverage. The verified-only policy must be relaxed before Claude's exporter is usable for ME.

---

## Lane 2: Classifier / Model Results

### Codex 168-row gold set (canonical)

| Model | Branch | Accuracy | FPR (none) | Notes |
|-------|--------|----------|------------|-------|
| claude-sonnet-4 | Codex | **130/168 (77.4%)** | **0/12 (0.0%)** | Best on canonical set |
| gpt-4.1-mini | Codex | 129/168 (76.8%) | 2/12 (16.7%) | Close second, cheaper |
| qwen3-max | Codex | 126/168 (75.0%) | 0/12 (0.0%) | Free tier, good FPR |
| qwen3-max | Claude | **FAILURE** | — | DashScope 400: JSON response_format not supported |

### Claude 150-row gold set (secondary cross-check)

| Model | Branch | Accuracy | FPR (none) | Notes |
|-------|--------|----------|------------|-------|
| gpt-4.1-mini | Codex | **124/150 (82.7%)** | 1/7 (14.3%) | Best on secondary set |
| qwen3-max | Codex | 123/150 (82.0%) | 1/7 (14.3%) | Nearly tied with GPT |
| claude-sonnet-4 | Codex | 112/150 (74.7%) | 1/7 (14.3%) | Worse than GPT here |

### Current system (stored labels, no reclassification)

| Gold Set | Accuracy | Notes |
|----------|----------|-------|
| Codex 168 | 99/168 (58.9%) | Baseline before reclassify |
| Claude 150 | 108/150 (72.0%) | Higher because fewer hard negatives |

**Interpretation notes:**
- Do NOT compare 168-set and 150-set accuracy as one leaderboard. Label distributions differ materially: Codex has 0 partition/40 conditional/12 none; Claude has 23 partition/3 conditional/7 none.
- Sonnet wins on the canonical 168-row set (77.4%, 0% FPR). GPT-4.1-mini wins on the 150-row set (82.7%).
- All three models improve substantially over the stored labels (59-72% baseline → 75-83% reclassified).
- Qwen on Claude branch is a confirmed runtime failure. The `_supports_json_response_format()` guard in Codex's classifier.py is required for DashScope compatibility.

---

## Lane 3: Reporting / Eval Tooling

| Feature | Codex | Claude | Merge recommendation |
|---------|-------|--------|---------------------|
| `analyze` subcommand | YES — label transitions, worst families, sample disagreements | NO — removed | **Keep from Codex** |
| `_normalize_current_type()` (`none_candidate` → `none`) | YES | NO | **Keep from Codex** |
| `_summarize_labeled_pairs()` | YES — family-level error patterns | NO | **Keep from Codex** |
| Confusion matrix in scoring | NO | YES — in both `_score_classifications` and `_score_reclassifications` | **Keep from Claude** |
| Macro F1 | NO | YES | **Keep from Claude** |
| Per-family accuracy breakdown | NO | YES — in both scoring functions | **Keep from Claude** |
| `_score_reclassifications()` depth | Minimal (accuracy + FPR only) | Full (matches `_score_classifications` depth) | **Keep from Claude** |
| Optional Path parameters | `Path = DEFAULT` | `Path | None = None` | Minor — Claude slightly more Pythonic |

**Summary:** Codex has the standalone `analyze` subcommand for failure-mode exploration. Claude has richer inline scoring (confusion matrix, macro F1, per-family breakdown in both current and reclassified output). These are complementary reporting features, not classifier quality differences. Both should be merged.

---

## Lane 4: Backtest / Silver Workflow

| Feature | Main/Codex (8d909ca) | Claude | Merge recommendation |
|---------|---------------------|--------|---------------------|
| Resolved-market guard | `_market_is_resolved_as_of()` + `_resolved_pair_markets()` — returns full dicts with outcome/timestamp | `is_resolved_as_of()` + `check_pair_resolved()` — returns market IDs only | Both functionally equivalent; Codex logs more detail |
| Daily loop order | Detect → Optimize → Simulate → **Settle last** | **Settle first** → Detect → Optimize → Simulate | **Claude's settle-first prevents same-day resolution exploit** |
| `--pair-ids` / `--pair-file` CLI | NO | YES — supports JSON list, dict list, or plain text | **Keep from Claude** — required by `run_v4_eval.sh` |
| Silver dataset curator | NO | YES — `curate_silver_dataset.py` (205 lines) with noisy-sports filter | **Keep from Claude** |
| Eval orchestrator | NO | YES — `run_v4_eval.sh` (283 lines), 4-phase, 8 models | **Keep from Claude** |
| Gold set analyzer | NO | YES — `analyze_goldset.py` (218 lines) with gate check | **Keep from Claude** |
| Resolved-market logging | Verbose (full dict with outcome, timestamp, market IDs) | Concise (market IDs only) | Codex better for debugging |
| Integration tests | NO | YES — `test_backtest_resolved_markets.py` (15 tests) | **Keep from Claude** |

**Critical finding:** Claude's settle-before-detect ordering prevents opening new positions on markets that resolve the same day. This is a correctness fix, not a preference.

---

## Selective Merge Recommendation

### Keep from Codex (do not overwrite)
1. `services/detector/classifier.py` — `_supports_json_response_format()` for Qwen + MiniMax (confirmed by runtime failure)
2. `scripts/export_goldset_v4.py` — resolved-unverified fallback fills all 5 dependency types
3. `scripts/eval_classifier.py` — `analyze` subcommand, `_normalize_current_type()`, `_summarize_labeled_pairs()`
4. `scripts/eval_data/labeled_pairs_v4.json` — canonical 168-row labeled gold set (do not overwrite)

### Merge from Claude
1. `scripts/backtest.py` — settle-before-detect ordering + `--pair-ids`/`--pair-file` flags
2. `scripts/eval_classifier.py` — confusion matrix, macro F1, per-family breakdown into `_score_classifications()` and `_score_reclassifications()`
3. `scripts/analyze_goldset.py` — new file, gold set quality analyzer
4. `scripts/curate_silver_dataset.py` — already committed, verify present on main
5. `scripts/run_v4_eval.sh` — new file, eval orchestrator
6. `scripts/eval_data/silver_pairs_v4.json` — new file, 172 curated pairs
7. `tests/unit/test_analyze_goldset.py` — new tests
8. `tests/unit/test_silver_curator.py` — new tests
9. `tests/integration/test_backtest_resolved_markets.py` — new tests

### Defer (do not merge yet)
1. Claude's `export_goldset_v4.py` taxonomy improvements — useful but cannot replace Codex's exporter until verified-only policy is relaxed for ME
2. Claude's 150-row gold set — keep as secondary cross-check file, do not promote to canonical
3. Full 8-model eval deployment — merge first, revalidate tests, then deploy

### Do not merge
1. Claude's simplified `if "minimax" not in model` check — breaks Qwen on DashScope
2. Claude's exporter as drop-in replacement — loses ME coverage

---

## Open Questions for Next Step

1. Should the Codex exporter adopt Claude's broader family taxonomy (election_political, tech_milestone, etc.) without changing the verified-only policy?
2. Should the canonical gold set be expanded to include Claude's 150-row pairs (38 unique pairs not in Codex set)?
3. Should Sonnet be retested with `openai_generic` adapter (bypassing `claude_xml`) to check if the R3 regression is resolved?
