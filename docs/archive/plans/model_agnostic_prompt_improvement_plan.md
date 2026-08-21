# Model-Agnostic Prompt Improvement Plan for PolyArb

**Date:** 2026-03-24
**Status:** In progress — shared prompt specs, examples, and adapter selection are in code
**Primary sources:**
- Anthropic, "Prompting best practices"  
  https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- OpenAI, "Prompt engineering"  
  https://developers.openai.com/api/docs/guides/prompt-engineering

---

## 1. Goal

Create a prompt strategy that works across Claude, GPT, Gemini, DeepSeek, Qwen, and other OpenRouter-served models without changing PolyArb's underlying classification task.

The target is to improve:

- classification accuracy
- JSON parse reliability
- resolution-vector quality
- non-trivial feasibility-matrix yield
- verified opportunity quality
- backtest PnL per token and per second

---

## 2. Core Principle

Do **not** maintain completely different prompt semantics per model.

Instead, use:

1. one **shared prompt spec**
2. one **shared eval scorecard**
3. thin **provider/model adapters** only for formatting and API quirks

This keeps the classification logic stable while still letting each model perform well.

OpenAI's docs reinforce the same pattern from a different angle:

- use high-authority instructions / message roles for stable behavior
- pin production apps to specific model snapshots for consistency
- build evals so prompt changes and model upgrades are measurable
- keep reusable prompt content early so prompt caching can reduce cost and latency

---

## 3. Shared Prompt Spec

Every model should receive the same logical task:

- classify the relationship between two markets
- output strict structured data
- distinguish hard logical constraints from softer conditional relationships
- prefer exact feasibility information when possible

### Shared components

The base prompt should always include:

- role
- objective
- why the task is strict
- dependency definitions
- hard rules and edge cases
- 3-5 realistic examples
- market payload
- output schema
- final instruction to return exactly one structured object

The OpenAI docs suggest a practical order for structured prompts that also generalizes well here:

- identity / role
- instructions
- examples
- context

That order maps cleanly onto PolyArb's classifier prompts.

### Shared success criteria

A prompt is good only if it improves at least one of:

- exact type accuracy
- correlation-direction accuracy
- resolution-vector exact match rate
- non-trivial matrix rate
- verified opportunity quality
- backtest PnL / Sharpe

Raw `conditional` count alone is not a success metric.

---

## 4. Architecture: Base Prompt + Adapters

### Layer 1: Base semantic prompt

This is the canonical meaning of the task. It should be model-neutral and stored once.

Suggested sections:

```text
ROLE
OBJECTIVE
WHY THIS MATTERS
DEFINITIONS
HARD RULES
EDGE CASES
EXAMPLES
INPUT
OUTPUT SCHEMA
FINAL INSTRUCTION
```

This base spec should also be split conceptually into:

- **stable reusable prefix**: role, taxonomy, hard rules, shared examples
- **request-specific suffix**: market A, market B, any per-call metadata

That split is useful across providers and directly supports OpenAI-style prompt caching.

### Layer 2: Provider adapter

This is where model-specific packaging lives.

Examples:

- Claude adapter: XML tags, concise system role, strict final JSON instruction
- GPT/OpenAI adapter: `instructions` or high-authority system/developer guidance, JSON mode / structured outputs when available, reusable prefix placed early for caching
- Gemini adapter: structured prompt with explicit schema reminders
- open-weight adapter: simpler formatting, stronger repetition of output contract, lower ambiguity

The adapter should change presentation, not task semantics.

---

## 5. What Is Universal vs Model-Specific

### Universal techniques

These should help almost all models:

- explicit instructions
- ordered decision steps
- concrete edge-case rules
- few-shot examples
- short schema-first outputs
- minimizing ambiguity
- consistent field names
- keeping the live prompt tight

### Often model-specific

These should live in adapters:

- XML vs plain structured blocks
- `instructions` parameter vs message-role layout
- JSON mode / response-format flags
- reasoning / thinking controls
- stop-sequence handling
- token-budget tuning
- how much example density a model tolerates before performance drops

---

## 6. PolyArb-Specific Prompt Families

PolyArb should standardize two prompt families.

### Family A: Resolution-vector prompt

Purpose:

- enumerate valid joint outcomes for binary pairs
- recover hard feasibility structure
- support direct matrix construction

Primary metric:

- exact vector match

Secondary metrics:

- parse rate
- non-trivial matrix rate
- backtest impact

### Family B: Label fallback prompt

Purpose:

- classify pairs where vectors fail or are unsupported
- handle more semantic cases

Primary metric:

- exact dependency-type accuracy

Secondary metrics:

- conditional-direction accuracy
- verified opportunity quality

---

## 7. Shared Prompt Design Rules

### Rule 1: Keep semantics stable

Do not let each model drift into its own taxonomy. All models must map to the same output fields and dependency types.

### Rule 2: Prefer hard constraints over prose

When a model can provide usable vectors or a directly actionable classification, prefer that over richer reasoning text.

### Rule 3: Keep reasoning short in the live path

Use short reasoning strings for auditability. Do not pay for long explanations in the detector hot loop unless they materially improve accuracy.

### Rule 4: Separate soft signals from optimizer inputs

If a model can report probabilistic correlation but not hard feasibility structure, store it separately. Do not feed it into Frank-Wolfe as if it were a proven constraint.

### Rule 5: Normalize outputs after generation

The parser should enforce:

- canonical dependency labels
- canonical outcome ordering
- nullability rules
- numeric confidence parsing

Prompt quality and parser robustness should improve together.

### Rule 6: Pin model versions in eval and production

OpenAI explicitly recommends pinning production applications to specific model snapshots so behavior stays stable over time. The same policy should be used for every provider where pinned versions are available.

### Rule 7: Keep reusable prompt content first

Put repeated instructions, taxonomy, and examples at the beginning of the prompt payload, and append only the pair-specific market data later. This helps with caching and keeps prompt iteration measurable.

---

## 8. Recommended Prompt Format

Use a canonical internal representation and render it differently per model.

### Canonical internal prompt object

```json
{
  "role": "...",
  "objective": "...",
  "why_this_matters": "...",
  "definitions": ["..."],
  "hard_rules": ["..."],
  "examples": ["..."],
  "input": {
    "market_a": "...",
    "market_b": "..."
  },
  "output_schema": {
    "...": "..."
  },
  "final_instruction": "..."
}
```

Recommended physical layout:

1. reusable prompt prefix
2. examples
3. request-specific market context
4. final response instruction

Then render to:

- XML-ish tagged text for Claude
- structured plain text for GPT/Gemini
- even simpler plain text for weaker open models if needed

---

## 9. Evaluation Plan

Use one cross-model scorecard.

### Core offline metrics

- JSON parse success rate
- exact dependency-type accuracy
- conditional-direction accuracy
- resolution-vector exact match rate
- non-trivial matrix rate
- verification survival rate

### Trading metrics

- opportunities generated
- optimized opportunities
- trades executed
- PnL
- Sharpe
- token cost
- runtime

### Cross-model comparison table

| Model | Prompt variant | Parse % | Exact type % | Vector exact % | Non-trivial matrix % | Verified opps | PnL | Cost | Runtime |
|---|---|---|---|---|---|---|---|---|---|

This table should drive prompt decisions, not subjective output quality.

Add two operational columns when possible:

- pinned model version / snapshot
- cacheable prompt prefix size

---

## 10. Rollout Plan

### Step 1

Create a shared prompt spec in code.

Example structure:

- `shared_prompt_spec.py`
- `render_claude_prompt(...)`
- `render_openai_prompt(...)`
- `render_generic_prompt(...)`

Implementation status on 2026-03-24:

- started in `services/detector/prompt_specs.py`
- Tier 2 and Tier 3 prompt semantics extracted into versioned prompt specs
- generic OpenAI-compatible and Claude-oriented renderers added
- explicit prompt adapter selection added (`auto`, `openai_generic`, `claude_xml`)
- detector classifier wired through adapter-aware rendering with prompt version metadata
- shared few-shot examples added to both prompt families

### Step 2

Version prompts explicitly:

- `resolution_v1`
- `resolution_v2`
- `label_v1`
- `label_v2`

Also record the exact model build used in each eval where the provider exposes one.

### Step 3

Run the same eval set across:

- Sonnet
- GPT
- Gemini
- DeepSeek
- Qwen

### Step 4

Compare:

- same base semantics, different adapters
- different example sets
- different prompt lengths
- reusable-prefix-first vs mixed-order prompt layout

### Step 5

Promote only variants that improve scorecard metrics without unacceptable token or latency cost.

---

## 11. Recommended Initial Work Order

1. Extract current prompt semantics into a shared base spec
2. Split the base prompt into a reusable cached prefix and a per-request suffix
3. Build a Claude renderer and a generic OpenAI-compatible renderer
4. Add 5 real PolyArb examples shared across both
5. Tighten output schema wording
6. Run offline eval on current benchmark sets with pinned model versions
7. Compare models using the same scorecard
8. Only then consider per-model specializations

Progress note:

- items 1-4 are now in code
- the next meaningful step is pinned cross-model evaluation on the same scorecard

---

## 12. Practical Decision Rule

Use this order of preference:

1. same semantics + same examples + different adapters
2. same semantics + small model-specific formatting tweaks
3. same semantics + small model-specific example ordering
4. only as a last resort, materially different prompts for a specific model

If a model requires a totally different prompt to perform well, treat that as an exception and document why.

---

## 13. What To Do Next In PolyArb

The next concrete step should be:

1. define a shared prompt spec for Tier 2 and Tier 3
2. implement two renderers:
   - Claude-oriented
   - generic OpenAI-compatible
3. put shared taxonomy/examples in a reusable prompt prefix and pair-specific data in a suffix
4. run Sonnet vs GPT vs DeepSeek/Qwen on the same prompt semantics with pinned model versions
5. compare matrix quality and backtest performance, not just label counts

That will tell you whether prompt engineering generalizes across models in this task, and where provider-specific tuning is actually worth the complexity.
