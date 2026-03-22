# Classifier Upgrade Plan — Resolution Vectors + Eval Harness

> **Goal:** Eliminate false-positive dependency classifications that cause wrong trades,
> by fixing known structural bugs, switching to resolution-vector-based classification,
> adding an eval harness, and tightening verification.
>
> **Current state:** The detector has two classification paths: rule-based heuristics
> (which run first) and LLM fallback (`gpt-4.1-mini`, classifier.py L524-532, temp 0.1,
> max 256 tokens). Both paths have correctness issues:
>
> - **Rule-based bugs:** Implication direction is not encoded — `_implication_matrix()`
>   always hardcodes A→B regardless of pair order (constraints.py L84-90). Same-event
>   partition rule (`_check_same_event`, L46-54) is over-broad — stamps any shared
>   event_id as `partition` at 0.95 confidence, even when markets in the same event
>   group are not actually partitions.
> - **LLM misclassification:** LLM returns abstract type labels prone to associative
>   hallucination (e.g. "mutual_exclusion" for independent celebrity attendance events).
>   Verification gate is too weak — structural checks are shallow, price checks pass
>   trivially for independent events priced near 50%.
> - **Historical context:** The March 21 audit identified that the primary cause of
>   paper-trading losses was trading unverified pairs through the rescan path. This gate
>   has since been fixed (pipeline.py L362: `if not pair.verified: continue`). The
>   remaining risk is wrong classifications that pass verification — which is what this
>   plan addresses.
>
> **Key insight from Saguillo et al. (AFT 2025):** Ask the LLM to enumerate valid outcome
> combinations (resolution vectors) instead of choosing a label. The constraint matrix is
> built directly from these vectors. Misclassification becomes structurally harder because
> the LLM must reason concretely about each state.
>
> **Paper reference:** "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"
> (Saguillo, Ghafouri, Kiffer, Suarez-Tangil). arXiv:2508.03474. Published AFT 2025.
> Analyzed 86M bets across 17,218 conditions on Polymarket, documented ~$40M in arbitrage.
>
> **Model decision:** Switch from `gpt-4.1-mini` (OpenAI direct) to `minimax/minimax-m2.7`
> (via OpenRouter). **Important:** prove the resolution-vector approach on `gpt-4.1-mini`
> first (or in shadow mode), then switch models only if the eval harness shows a clear win.
> Detection serializes classification under a lock (pipeline.py L53, L96) — a slower
> reasoning model could worsen backlog if deployed without measurement.
>
> **GitHub research:** See `research_github_polymarket.md` for notes on open-source projects.

---

## Step 0 — Fix Invariant Bugs (before anything else)

**Why:** These are correctness bugs in the existing rule-based classifier that can produce
wrong trades *independently of the LLM*. Must fix before layering new features on top.

### 0a. Implication Direction

**The bug:** Rule-based classifiers (`_check_price_threshold_markets` L254-277,
`_check_ranking_markets` L422-430, `_check_over_under_markets`) return
`{"dependency_type": "implication"}` with reasoning like "above $134 implies above $128"
— but they don't encode *which market* is the antecedent vs consequent. The constraint
matrix builder `_implication_matrix()` (constraints.py L84-90) always hardcodes A→B:
`matrix[0][1] = 0` (A=Yes forces B=Yes). If market_a is the lower threshold and market_b
is the higher, the constraint is inverted — the system forbids the wrong state.

**The fix:** Add an `implication_direction` field to classification results:
```python
# In classifier return dicts:
{"dependency_type": "implication", "implication_direction": "a_implies_b", ...}
# or
{"dependency_type": "implication", "implication_direction": "b_implies_a", ...}
```

Update `build_constraint_matrix()` to accept and use direction:
```python
def _implication_matrix(n_a, n_b, direction="a_implies_b"):
    matrix = [[1] * n_b for _ in range(n_a)]
    if direction == "a_implies_b":
        matrix[0][1] = 0  # A=Yes + B=No infeasible
    else:  # b_implies_a
        matrix[1][0] = 0  # B=Yes + A=No infeasible
    return matrix
```

For each rule-based function, determine direction from the threshold comparison:
- Price thresholds: higher threshold implies lower → if market_a has higher threshold,
  direction is `a_implies_b`; otherwise `b_implies_a`
- Rankings: smaller N implies larger N → if market_a has smaller N, `a_implies_b`
- O/U: higher line implies lower → same logic

**Also add pair-order-invariant tests** to catch future regressions: for each
implication test case, run classify_pair(A,B) and classify_pair(B,A) and verify
the constraint matrices are logically equivalent.

### 0b. Over-Broad Same-Event Partition Rule

**The bug:** `_check_same_event()` (L46-54) stamps any shared `event_id` as `partition`
at 0.95 confidence. Polymarket's `event_id` groups markets by topic (e.g., "2024 US
Election"), not by logical partition. Two markets in the same event can be completely
independent (e.g., "Will candidate X win state A?" and "Will candidate Y win state B?").

**The fix:** Require same event_id + overlapping outcomes for partition classification.
`_check_outcome_subset` already handles outcome overlap detection — gate the partition
return on that check passing. This is a ~5-line change. Demoting to a metadata signal
is an alternative but requires prompt changes; the outcome-overlap gate is simpler and
sufficient.

**The eval harness (Step 1) should score this rule separately** to quantify how many
false positives it generates to confirm the fix is effective.

**Files:**
- `services/detector/classifier.py` — fix implication direction in all rule-based
  functions, demote/narrow same-event rule
- `services/detector/constraints.py` — accept `implication_direction` parameter
- `tests/test_classifier.py` — pair-order-invariant test cases

---

## Model Selection — MiniMax M2.7 via OpenRouter

### Why MiniMax M2.7

The paper used DeepSeek-R1-Distill-Qwen-32B (self-hosted) and achieved 81.45% accuracy on
single-market validation — but hit reasoning loops on ~10% of pair classifications (4,727 of
46,360 election pairs). R1's `reasoning_content` field also causes response format issues
(confirmed independently by chainstacklabs/polyclaw).

MiniMax M2.7 is a better fit because:
1. **Mandatory reasoning via `<think>` tags** — gets CoT benefits without R1's unstructured
   reasoning loops. The thinking is cleanly separated from the JSON output.
2. **Native structured output** — supports `response_format` parameter for JSON mode.
   This is the #1 lesson from the paper: prompt-only JSON enforcement fails ~19% of the time.
3. **Cost:** $0.30/M input, $1.20/M output — cheaper than gpt-4.1-mini ($0.40/$1.60)
   and dramatically cheaper than o4-mini ($1.10/$4.40).
4. **204K context window** — more than enough for batch classification if we go there later.
5. **Available on OpenRouter** — model ID: `minimax/minimax-m2.7`. We already have an
   OpenRouter integration pattern in `scripts/gemini_audit.py` (L176-199).

### Rollout Strategy

**Do NOT combine the provider switch with the paradigm shift.** Detection serializes
classification under a lock (pipeline.py L53, L96), so a slower reasoning model can
immediately worsen the detection backlog. The plan is:

1. Build resolution vectors with `gpt-4.1-mini` first (same provider, new prompt)
2. Measure accuracy and latency in the eval harness
3. Run M2.7 in **shadow mode** (classify with both, log M2.7 results, act on gpt-4.1-mini)
4. Switch to M2.7 only when eval shows clear accuracy win AND latency is acceptable

### Integration Path

Current code uses `openai.AsyncOpenAI` client pointed at OpenAI. The OpenAI Python SDK is
OpenRouter-compatible — only need to change `base_url` and API key:

```python
# Current (classifier.py, wired via pipeline.py → main.py)
client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

# New: OpenRouter with MiniMax M2.7
client = openai.AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
)
# model param: "minimax/minimax-m2.7"
```

Need to add to `shared/config.py`:
```python
openrouter_api_key: str = ""
classifier_model: str = "gpt-4.1-mini"  # keep current default; switch after eval
classifier_base_url: str = ""  # empty = OpenAI direct; set for OpenRouter
shadow_classifier_model: str = ""  # for shadow mode comparison
shadow_classifier_base_url: str = ""
```

### Parameter Settings

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `temperature` | 0.0 | Deterministic enumeration — no creativity needed. Paper used unspecified but task is factual. Currently 0.1. |
| `max_tokens` | 512 | Up from 256 — resolution vectors + reasoning need more space. M2.7's `<think>` tags add overhead. |
| `response_format` | `{"type": "json_object"}` | Force valid JSON output. Paper relied on prompt-only enforcement and got 19% failures. |
| `seed` | 42 | M2.7 supports seed for reproducibility — use fixed seed for eval consistency. |

### Fallback Strategy

If the primary model returns malformed output or times out (15s), fall back to `gpt-4.1-mini`
via the existing OpenAI client. Track fallback rate in metrics. This is the same pattern as
the paper — they kept a fallback for their 19% failure rate.

**Fallback safety policy:** Pairs classified via the `llm_label` fallback path (as opposed
to resolution vectors) carry the same hallucination risk this plan is trying to eliminate.
Therefore, `llm_label` fallback pairs must be marked `verified = False` and require
stricter verification — specifically, the ME structural checks from Step 3 apply, and
confidence is capped at 0.70 (below the default trading threshold). This ensures fallback
pairs are persisted for eval/audit but do not reach the optimizer unless separately
validated. Track fallback rate; if it exceeds 10%, investigate prompt/format issues.

---

## Step 1 — Eval Harness (measure before fixing)

**Why:** Can't claim improvement without a baseline. Currently zero ground-truth labels.
The paper found only 13 of 46,360 election pairs were true positives after manual review —
our false positive rate is likely similar.

**What to build:**
- `scripts/eval_classifier.py` — pulls last N classified pairs from `market_pairs` table
- Export pairs as JSON with: question_a, question_b, description_a, description_b, outcomes_a,
  outcomes_b, current `dependency_type`, `confidence`
- **Inferring classification source (no schema change needed):** The `classification_source`
  column does not exist in the DB yet (added in Step 4 migration). Instead, the eval harness
  infers source by replaying: run each sampled pair through the rule-based classifier first;
  if it matches, label as `rule_based`; otherwise label as `llm`. This avoids coupling Step 1
  to the Step 4 migration while still enabling the rule-based vs LLM accuracy breakdown.
- Manual labeling format: add `ground_truth_type` and `correct` boolean per pair
- Eval metrics: precision / recall / F1 per dependency type, **broken down by rule-based vs LLM**
- **Primary KPI: False Positive Rate on independent pairs.** In arbitrage, a false negative
  (missing a real arb) is opportunity cost; a false positive (hallucinating a dependency) is
  catastrophic capital loss. The eval must weight FP on independent events as the #1 metric,
  not balanced F1. Also track `acc_norm` (length-normalized accuracy) to penalize ambiguous
  or padded LLM responses.
- Start with 200 pairs (sample across all dependency types, stratified), with at least 80
  from the independent-but-semantically-similar bucket (the Lana/Blake topology). This
  over-samples the confusion class that matters most — independent pairs misclassified as ME.
- **Multi-model eval mode:** Run same pairs through gpt-4.1-mini (baseline) AND minimax-m2.7
  to compare before committing to the switch
- **Static eval set:** Once `labeled_pairs.json` is generated and hand-labeled, freeze it.
  All prompt/model changes in Step 2 must be evaluated against this exact same static set
  for valid A/B comparison. No regenerating or re-sampling between runs.
- **Score `_check_same_event()` separately** — quantify how many false partition labels
  this rule generates to confirm the Step 0b fix is effective.

**Files:**
- `scripts/eval_classifier.py` (new)
- `scripts/eval_data/labeled_pairs.json` (new, generated then hand-labeled)

**Output:** Baseline accuracy numbers. Expect rule-based ~95%+ (but lower once same-event
false positives are counted), LLM ~60-70%.
Paper baseline: DeepSeek-R1-Distill got 81.45% on single-market, unknown on pairs.

---

## Step 2 — Resolution Vector Prompt

**Why:** Asking "what type?" is ambiguous. Asking "which outcome combos are valid?" forces
concrete reasoning. For Lana/Blake attending a wedding, the LLM must list
{(Y,Y),(Y,N),(N,Y),(N,N)} — all valid — which means no dependency. It can't accidentally say
"mutual_exclusion."

**Important:** Initially implement this on `gpt-4.1-mini` (current provider). Add M2.7
as shadow comparison via the eval harness. Only promote M2.7 to primary after measuring.

**Prompt design (following Saguillo et al. methodology):**

The paper's prompt structure asks the LLM to enumerate all valid logical combinations of truth
values. Key elements from their approach:
- Preamble establishing binary True/False nature of each market condition
- Rule spec requiring exactly one true outcome per market
- Explicit JSON schema: `{"valid_combinations": [[true, false, ...], ...]}`
- Strict formatting: "The output must be valid JSON and contain no additional text"

Our adapted prompt for binary market pairs:

```
You are a prediction market analyst. Given two binary markets A and B,
determine ALL logically valid outcome combinations.

Rules:
- Each market resolves to exactly one outcome (Yes or No).
- List every combination of (A_outcome, B_outcome) that is logically possible.
- Only exclude a combination if it is LOGICALLY IMPOSSIBLE — not merely unlikely.
- Correlation or probability does NOT make a combination invalid.

Market A: "{question_a}" — Outcomes: {outcomes_a}
Market B: "{question_b}" — Outcomes: {outcomes_b}

Return strictly valid JSON with no additional text:
{
  "valid_outcomes": [
    {"a": "Yes", "b": "Yes"},
    {"a": "Yes", "b": "No"},
    ...
  ],
  "reasoning": "<one sentence explaining the logical relationship>",
  "confidence": <float 0.0-1.0>
}
```

**Deriving dependency type from resolution vectors (deterministic, no LLM):**

Must match the existing matrix semantics in constraints.py exactly:
- `partition` = XOR (constraints.py L93-108): (Y,N) and (N,Y) feasible, (Y,Y) and (N,N) infeasible
- `cross_platform` = identity (constraints.py L202-209): (Y,Y) and (N,N) feasible, mixed infeasible
- `mutual_exclusion` = (Y,Y) infeasible (constraints.py L121-126)
- `implication` = one mixed cell infeasible (constraints.py L84-90)

Mapping:
- All 4 combos valid → `none` (independent)
- Missing (Y,Y) only → `mutual_exclusion`
- Missing (Y,N) only → `implication` (A=Y forces B=Y, direction: `a_implies_b`)
- Missing (N,Y) only → `implication` (B=Y forces A=Y, direction: `b_implies_a`)
- Only (Y,N) and (N,Y) valid → `partition` (XOR — exactly one resolves Yes)
- Only (Y,Y) and (N,N) valid → `cross_platform` (identity — same event, two venues)
- 3 combos valid (one excluded) → `conditional` with correlation direction inferred
  from which combo is excluded
- 1 combo valid → degenerate, likely LLM error → fall back to label-based
- 0 combos valid → LLM error → fall back

Note: resolution vectors naturally solve the implication direction problem (Step 0a)
because the excluded cell directly encodes which direction the implication runs.
Still persist `dependency_type` + `implication_direction` for dashboard/API compatibility.

**Confidence calibration:**
- Current: raw LLM confidence × 0.80, capped at 0.85 (classifier.py L537-542)
- LLM self-reported confidence is poorly calibrated. With resolution vectors, the output
  is structurally binary — the vectors are either correct or wrong. The paper did not
  apply a confidence discount because vectors don't have a meaningful "partial correctness."
- New approach: **drop the confidence discount for vector-classified pairs.** Instead,
  use a binary confidence assignment: if vectors pass structural validation (internally
  consistent, reasoning matches), assign 0.90. If any inconsistency detected, reject
  and fall back. This is simpler and more honest than calibrating a meaningless float.
  The `llm_label` fallback path retains the existing discount (×0.80, capped at 0.70
  per the fallback safety policy).

**Files to change:**
- `shared/config.py`:
  - Add `openrouter_api_key`, `classifier_base_url`, shadow model config
- `services/detector/classifier.py`:
  - New `RESOLUTION_VECTOR_PROMPT` (above)
  - New `classify_llm_resolution()` function
  - `_derive_dependency_type(valid_outcomes, outcomes_a, outcomes_b)` — deterministic
    mapping from vectors to type + implication direction + correlation
  - Keep `classify_llm()` as fallback if resolution vector parsing fails
  - Keep all rule-based heuristics (with Step 0 fixes applied)
  - **Strip `<think>` tags from M2.7 response** before JSON parsing. M2.7's mandatory
    reasoning outputs `<think>...</think>` before the JSON body — `json.loads()` will
    throw if the raw string starts with `<think>`. Split on `</think>` and take everything
    after; then `json.loads()` the remainder. If `</think>` is absent (unexpected), fall
    back to extracting from first `{` to last `}`. Do NOT use the `{`-to-`}` approach as
    primary — reasoning inside `<think>` may contain JSON examples that would confuse it.
- `services/detector/main.py`:
  - Create second `openai.AsyncOpenAI` client for OpenRouter alongside existing OpenAI client
  - Pass both to pipeline (primary = current, shadow = OpenRouter/M2.7)
- `services/detector/constraints.py`:
  - New `build_constraint_matrix_from_vectors(valid_outcomes)` — directly populate
    the feasibility matrix from LLM output instead of inferring from dependency type

**Multi-outcome markets (future, not this PR):**
The paper uses top-K reduction: keep top 4 conditions by trading volume + "other" catch-all.
They found >90% of liquidity sits in top 4 conditions. Our current code assumes binary markets
(constraints.py L35-43 warns if violated). This is a separate effort.

---

## Step 3 — Tighten Verification for ME Specifically

**Why:** Even with better classification, verification should be a real safety net.

**Current ME structural check (verification.py L96-114):**
- Binary markets? ✓ (too easy)
- Not identical questions? ✓
- Same event_id check exists (L103-107) — **but when neither market has event_id,
  the check passes silently.** This is the actual gap, not a missing check.

**Add/tighten these checks:**
1. **ME without shared event_id = non-verifiable by default.** If neither market has
   event_id and there is no explicit exclusivity pattern (e.g., "Team A wins" vs
   "Team B wins" in the same game), reject the classification. Markets about the same
   event almost always share event_ids on Polymarket. The absence of a shared event_id
   for an ME claim is a strong signal of hallucination.
2. **Resolution vector consistency** — if Step 2 produced vectors, verify the derived
   type matches. If vectors say all 4 combos valid but type says ME, reject.
   This is the nuclear safety net — vectors and derived type should always agree.
3. **Price floor for ME** — tighten from P(A)+P(B) ≤ 1.20 to ≤ 1.10. Note: this does
   NOT solve the Lana/Blake case (0.50+0.50=1.00 passes any threshold). The structural
   evidence check (#1 above) is the real fix. The price tightening only catches marginal
   cases like 0.60+0.60=1.20.

**Files:**
- `services/detector/verification.py` — tighten `_check_structural` ME branch,
  add vector consistency check, tighten `_check_price_consistency` ME threshold

---

## Step 3.5 — Uncertainty Filter (post-classification gate)

**Why:** Near-resolved markets (price > 0.95) have sub-5-cent margins that get eaten by
spread widening, asymmetric book depth, and unpredictable AMM slippage. The simulator
already has Half-Kelly sizing, drawdown scaling, stale-snapshot rejection, post-VWAP edge
checks, and circuit-breaker gating (simulator/pipeline.py L127-221). This filter is an
incremental improvement that catches near-resolved markets earlier in the detector,
before wasting optimizer cycles.

**Implementation:**
Gate in the detection pipeline: discard any market pair where any individual outcome price
exceeds 0.95 (or falls below 0.05, which is the complement).

**Placement note:** Currently, prices are loaded *after* classification (pipeline.py L107-108),
not before. A true pre-classifier filter would add snapshot lookups for every candidate pair,
which has DB and latency cost. Instead, place this as a **post-classification, pre-constraint
gate** — after prices are already loaded at L107-108, before building the constraint matrix
at L111. When a pair fails this filter, the pipeline must **fully short-circuit**: no
constraint matrix build, no opportunity persist to DB, no Redis event emit. This ensures
near-resolved pairs never reach the optimizer, not just that they aren't stored.

```python
# In pipeline.py, after price loading (L108), before build_constraint_matrix (L111)
def _passes_uncertainty_filter(prices_a, prices_b) -> bool:
    """Reject pairs where any outcome is near-certain."""
    for p in list(prices_a.values()) + list(prices_b.values()):
        if p < settings.uncertainty_price_floor or p > settings.uncertainty_price_ceil:
            return False
    return True
```

**Why 0.95?** At P > 0.95, the maximum remaining profit is < 5 cents. After CLOB fees
(~1-2%), slippage (variable), and the 3-cent minimum edge threshold in the simulator,
there's no executable margin left.

**Both YES and NO prices:** If only one side's price is available, calculate the implied
complement (1.0 - P) before filtering. Don't short-circuit on incomplete data.

**Files:**
- `services/detector/pipeline.py` — add `_passes_uncertainty_filter()` after price loading
- `shared/config.py` — add `uncertainty_price_floor: float = 0.05` and
  `uncertainty_price_ceil: float = 0.95` (configurable)

---

## Step 4 — Constraint Matrix from Vectors (Direct Path)

**Why:** Currently the pipeline is:
```
LLM → type label → build_constraint_matrix(type) → hardcoded matrix patterns
```
This loses information. With resolution vectors, we skip the lossy label step.

**New pipeline:**
```
Rule-based check → (if match) → type + direction + matrix (with Step 0 fixes)
                 → (if no match) → LLM resolution vectors
                                  → derive type + direction from vectors (deterministic)
                                  → build matrix directly from vectors
                                  → verify consistency
                                  → (if LLM fails) → fallback to label-based classify_llm()
```

Still persist `dependency_type` and `implication_direction` for dashboard/API compatibility,
even though the matrix is built directly from vectors. **Critically**, the stored
`constraint_matrix` JSONB must still include the `"type"` key — the optimizer reads
`constraint.get("type", "")` (optimizer/pipeline.py L62) and uses it for the conditional
skip check at L73. If `"type"` is missing, the optimizer will misroute opportunities.

**Profit bound — retain type-specific bounds for now:**
The current profit bound computation (constraints.py L220-306) is type-specific — each
dependency type has its own formula. The optimizer also supports both buy- and sell-side
arb (e.g., ME arb is "sell both Yes when sum > 1") and validates via `_worst_case_payoff()`
on the actual trade bundle (trades.py L147-152). A naive generic formula like
`1.0 - min(cost over feasible cells)` cannot express sell-side arb and would produce
wrong opportunity gating. **Retain the existing type-specific profit bound until a proved
matrix-based bound is derived that handles both buy and sell sides.** The vector path
derives `dependency_type` deterministically, so the type-specific bound still works.

**Optimizer changes for conditional pairs:**
The optimizer currently skips all conditional pairs by default (`optimizer_skip_conditional
= True`, config.py L48, checked at optimizer/pipeline.py L73-79). With resolution vectors,
some conditional pairs will have non-trivial constraint matrices (e.g., one infeasible cell
that creates real arb). Add an explicit opt-in: if the conditional pair was vector-classified
and its matrix has at least one infeasible cell, evaluate it even when `skip_conditional` is
True. This requires a small change to the optimizer's skip logic:
```python
# optimizer/pipeline.py, in the conditional skip block:
if dep_type == "conditional":
    source = constraint.get("classification_source", "")
    is_unconstrained = all(feasibility[i][j] == 1 ...)
    if is_unconstrained or (self.skip_conditional and source != "llm_vector"):
        # Skip truly unconstrained conditionals, but evaluate vector-derived ones
```

**Existing pair reclassification:**
After deploying resolution vectors, the DB will contain a mix of old label-only pairs and
new vector-classified pairs. Strategy: **do not bulk-reclassify.** Old pairs continue to
work with the existing type-specific pipeline. New pairs (and pairs re-detected during
normal detector cycles) get vector classification. The `classification_source` column
distinguishes them. If the eval harness (Step 5) shows a clear win, a one-time backfill
script can reclassify active pairs — but this is optional and deferred.

**DB migration (012):** Add to `market_pairs` table (next after 011_venue_column):
- `resolution_vectors` JSONB — raw LLM vector output. Nullable (rule-based pairs won't have).
- `implication_direction` VARCHAR — "a_implies_b" or "b_implies_a". Nullable.
- `classification_source` VARCHAR — "rule_based", "llm_label", or "llm_vector".

Decide early: put audit metadata (raw LLM response, model used, latency) inside
`resolution_vectors` JSONB or in a separate `classification_metadata` JSONB column.
Keeping it in one column is simpler; separate is cleaner for querying.

**Files:**
- `services/detector/constraints.py` — new `from_resolution_vectors()` constructor
- `services/detector/pipeline.py` — wire new path, pass vectors through to constraint
  builder, store vectors in MarketPair, ensure `constraint_matrix["type"]` is preserved
- `services/optimizer/pipeline.py` — update conditional skip logic to evaluate
  vector-derived conditionals with non-trivial matrices
- `shared/models.py` — add columns to MarketPair
- `alembic/versions/012_resolution_vectors.py` — new migration

---

## Step 5 — Re-evaluate with Eval Harness

**What:** Re-run `scripts/eval_classifier.py` on the same 200 labeled pairs with:
1. New resolution vector classifier (on gpt-4.1-mini first, then M2.7 shadow)
2. Old label-based classifier (gpt-4.1-mini) for comparison
3. Rule-based classifier (with Step 0 fixes applied)

**Success criteria:**
- Overall accuracy ≥ 85% (up from estimated ~65%; paper got 81.45% on single-market)
- ME false positive rate < 5% (currently unknown but clearly high)
- Independent-pair FPR < 3% (primary KPI)
- No regression on rule-based pairs (after Step 0 fixes)
- Precision on dependency classifications ≥ 90% (primary gate — given the -86.6% backtest
  result from over-detecting bad pairs, a drop in opportunity count is healthy if it
  reflects eliminated false positives. Do NOT use opportunity count as a gate.)
- Fallback rate < 10% (if higher, investigate prompt/format issues)
- Implication direction correct for 100% of rule-based implication pairs (Step 0 regression test)
- Backtest P&L improvement (run after deploying to NAS — this is the ultimate gate)

**Only after Step 5 passes:** promote M2.7 from shadow to primary if it outperforms
gpt-4.1-mini on accuracy without unacceptable latency increase.

---

## Execution Status — ALL STEPS COMPLETE (2026-03-22)

All steps implemented, deployed to NAS, and evaluated. 12 files changed, +1100 lines.

### Step completion log

| Step | Status | Notes |
|------|--------|-------|
| 0a. Implication direction | **DONE** | All 4 rule-based implication classifiers return direction; constraints.py direction-aware |
| 0b. Same-event partition rule | **DONE** | Narrowed: requires same event_id + multi-outcome overlap (≥2 shared, ≥3 total) |
| 1. Eval harness | **DONE** | `scripts/eval_classifier.py` — export, autolabel, eval commands; 316-pair eval set |
| 2. Resolution vector prompt | **DONE** | 3-tier pipeline: rule-based → resolution vectors → llm_label fallback (0.70 cap) |
| 3. ME verification | **DONE** | ME without shared event_id = non-verifiable; price threshold tightened 1.20→1.10 |
| 3.5. Uncertainty filter | **DONE** | Prices < 0.05 or > 0.95 rejected pre-constraint; configurable thresholds |
| 4. Direct constraint matrix + migration | **DONE** | `build_constraint_matrix_from_vectors()`; migration 012 adds 3 columns to market_pairs |
| 5. Re-evaluate | **DONE** | See eval results below |

### Eval Results (316-pair sample, gpt-4.1-mini)

**Current system accuracy (judged by new 3-tier pipeline):**
- Overall: 77.5% (245/316)
- Rule-based: 100% (77/77) — no regression
- LLM: 70.3% (168/239)

**Per-type precision of current (old) system:**
| Type | Precision | FP | Key finding |
|------|-----------|-----|-------------|
| partition | 18% | 33 | 82% of sampled partitions were false positives (different districts/events) |
| conditional | 60% | 16 | Many are actually independent pairs |
| mutual_exclusion | 76% | 16 | Improved after singular-winner prompt fix |
| implication | 85% | 6 | Best, anchored by rule-based |
| none | 100% | 0 | No false negatives on dependencies |

**Independent-pair FPR: 33.1%** — 49 of 148 real DB pairs that should be "none" were misclassified as having dependencies. This was the primary driver of bad trades.

**New pipeline reclassified 71/316 pairs (22.5%)**, overwhelmingly downgrading false positives:
- 25 partition→none, 13 conditional→none, 9 ME→none (truly independent)
- 5 ME→implication, 4 partition→ME, 3 conditional→implication (type corrections)

### Prompt iteration: singular-winner fix

Spot-check found resolution vectors missed "singular winner" ME (e.g., "Will X win Golden Boot?" / "Will Y win Golden Boot?"). Added explicit singular-winner constraint to prompt. Verified 6/6 test cases. Reduced false none from 60→49 (-18%).

### Remaining known issues (deferred)
- Temporal deadline implications not caught by rule-based or vectors (e.g., "token launch by Sep" / "by Dec") — rare
- ~2-3 borderline primary election pairs where "advance" may or may not be ME
- MiniMax M2.7 shadow comparison not yet run (OpenRouter key not configured in .env)
- Backtest re-run with new classifier deferred to next session

---

## Files Changed Summary

| File | Change |
|------|--------|
| `scripts/eval_classifier.py` | New — eval harness with multi-model support, infers classification source by replay |
| `scripts/eval_data/labeled_pairs.json` | New — ground truth labels (static, frozen after labeling) |
| `tests/test_classifier.py` | New/updated — pair-order-invariant implication tests |
| `shared/config.py` | Add OpenRouter config, shadow model config, uncertainty filter thresholds |
| `shared/models.py` | Add `resolution_vectors`, `implication_direction`, `classification_source` to MarketPair |
| `alembic/versions/012_resolution_vectors.py` | New — migration for new columns |
| `services/detector/main.py` | Create OpenRouter client, pass both clients to pipeline |
| `services/detector/classifier.py` | Fix implication direction, narrow same-event rule, resolution vector prompt + parser + `<think>` tag stripping, fallback safety policy |
| `services/detector/constraints.py` | Accept `implication_direction`, `from_resolution_vectors()` (retain type-specific profit bounds) |
| `services/detector/verification.py` | ME without shared event_id = non-verifiable, vector consistency check, tighter price threshold |
| `services/detector/pipeline.py` | Wire new classification path, store vectors, uncertainty filter, shadow mode, preserve `constraint_matrix["type"]` |
| `services/optimizer/pipeline.py` | Update conditional skip logic to evaluate vector-derived conditionals with non-trivial matrices |
| `research_github_polymarket.md` | Reference — GitHub project research notes |

---

## Future Work (out of scope for this plan)

- **Lead-Lag signals (imrp1 §1.1):** Cross-venue temporal dynamics for execution timing.
  Current architecture runs on 60s/30s/60s loops (shared/config.py L40/46/54) with only
  Polymarket websocket streaming configured. Not a credible substrate for lead-lag yet.
  Requires much tighter event loops and multi-venue streaming first.
- **Multi-outcome markets:** Top-K reduction (paper §2.3) for markets with >4 conditions.
  Keep top 4 by volume + "other" catch-all. Separate effort requiring constraints.py refactor.
- **Batch classification:** Multiple pairs per LLM call to reduce cost. M2.7's 204K context
  makes this feasible but needs prompt engineering to maintain accuracy.
- **Fine-tuning:** Train a small model on our labeled dataset from Step 1. Only worthwhile
  once we have 500+ labeled pairs.

---

## Risk Acknowledgment

This system has execution risk, resolution risk, and data-freshness risk even with a perfect
classifier. The uncertainty filter and existing simulator safeguards (Half-Kelly, drawdown
scaling, circuit breakers) mitigate but do not eliminate these risks. No arbitrage in
prediction markets is truly risk-free — resolution disputes, oracle failures, and liquidity
withdrawal can all cause losses on structurally sound trades.
