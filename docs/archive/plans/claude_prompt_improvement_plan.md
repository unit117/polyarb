# Claude Prompt Improvement Plan for PolyArb

**Date:** 2026-03-24
**Status:** Separate prompt-engineering plan
**Primary source:** Anthropic, "Prompting best practices"  
https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices

---

## 1. Goal

Improve PolyArb's classifier prompts using Anthropic's current Claude prompting guidance, but evaluate success using **PolyArb metrics**, not generic prompt quality.

The target is not "nicer explanations." The target is:

- more correct resolution vectors
- fewer JSON / parsing failures
- more non-trivial feasibility matrices
- better verified-pair quality
- better backtest PnL per dollar and per second

---

## 2. Scope

This plan applies to:

- `services/detector/classifier.py`
- the Tier 2 resolution-vector prompt
- the Tier 3 label-based fallback prompt
- the eval / reclassification workflow used in `scripts/reclassify_pairs.py` and `scripts/eval_classifier.py`

This plan does **not** assume that soft probability judgments should go straight into the optimizer. The optimizer still needs hard constraints or a separately validated scoring path.

---

## 3. What Claude Best Practices Mean Here

Anthropic's guidance maps well onto PolyArb's prompt problems:

1. **Be clear and direct**
   The current prompts mix taxonomy, edge cases, and output requirements in one block. Rewrite them as explicit ordered instructions.

2. **Add context**
   Tell the model why the task is strict: a wrong dependency type creates a false arbitrage and bad trades.

3. **Use examples effectively**
   Add 3-5 few-shot examples that match real PolyArb failure modes, not generic toy examples.

4. **Structure prompts with XML tags**
   Separate rules, market data, examples, decision criteria, and output schema so the model does not blur them together.

5. **Give Claude a role**
   Use a precise role such as "prediction-market dependency analyst focused on logical feasibility."

6. **Long-context structure**
   Put the market data and examples before the final query, especially if descriptions or market metadata are long.

7. **Control the output positively**
   Specify the exact JSON object and required fields instead of telling the model what not to do.

---

## 4. Current Weaknesses in PolyArb

### Tier 2: Resolution vector prompt

Current issues in [`services/detector/classifier.py`](/Users/unit117/Dev/polyarb/services/detector/classifier.py#L642):

- Plain-text prompt with no structural separation
- No few-shot examples
- The "only exclude logically impossible combos" rule is clear, but it is not paired with enough domain-specific examples
- The output schema is present but not reinforced with field-level requirements

### Tier 3: Label fallback prompt

Current issues in [`services/detector/classifier.py`](/Users/unit117/Dev/polyarb/services/detector/classifier.py#L21):

- The taxonomy is defined, but not shown through examples
- Edge cases like threshold chains, same-award exclusivity, same-event non-independence, and time-window disambiguation are embedded in prose
- The model is asked to both interpret market semantics and emit strict JSON without much scaffolding

### Evaluation weakness

The current discussion often uses "conditionals found" as the headline metric. That is incomplete. PolyArb should score prompts by:

- exact classification quality
- parse success rate
- useful matrix rate
- verified opportunity rate
- backtest PnL and Sharpe

---

## 5. Prompt Rewrite Strategy

### Phase 1: Restructure prompts without changing logic

Rewrite both prompts into this shape:

```xml
<role>
You are a prediction-market dependency analyst.
</role>

<objective>
Determine the logical relationship between two markets.
</objective>

<why_this_matters>
Incorrect classifications create false arbitrage signals and bad trades.
</why_this_matters>

<definitions>
...
</definitions>

<hard_rules>
...
</hard_rules>

<examples>
  <example>...</example>
  <example>...</example>
</examples>

<market_a>
...
</market_a>

<market_b>
...
</market_b>

<output_schema>
...
</output_schema>

<final_instruction>
Return exactly one valid JSON object.
</final_instruction>
```

Why first: this is low risk and directly follows Claude guidance on clarity, context, examples, and XML structure.

### Phase 2: Add task-specific examples

Add 3-5 examples for each prompt family.

Tier 2 example set should cover:

- implication via thresholds
- mutual exclusion via singular winner markets
- partition
- true 3-of-4 logical vector
- true 2-of-4 logical vector

Tier 3 example set should cover:

- same-event but independent
- same asset, different dates
- same asset, different time windows
- sports matchup conditional
- tournament progression

Rule: examples must be close to actual misclassifications seen in the eval set.

### Phase 3: Make output requirements stricter

For Tier 2:

- require canonical ordering for `valid_outcomes`
- require the reasoning field to be one sentence
- require confidence to be a numeric literal

For Tier 3:

- require `correlation` to be null unless `dependency_type == "conditional"`
- require a short reasoning phrase instead of a paragraph

This reduces parse brittleness and normalization work in code.

### Phase 4: Optional Claude-specific experiments

Only after the basic rewrite works:

- test a slightly stronger reasoning-oriented Claude model for offline reclassification
- test whether a private "think first, answer in JSON" instruction improves vector quality without hurting latency too much
- do not put heavy reasoning or long outputs into the live hot path until evals justify it

---

## 6. Concrete Prompt Changes

### Tier 2: Resolution vector prompt

Keep the core requirement: only exclude logically impossible combinations.

Improve it by:

- adding a role block
- moving market payload into separate tags
- adding a definitions block for the four canonical outcome pairs
- adding examples that show what counts as impossible versus merely correlated
- adding a schema block with field descriptions
- placing the final question at the end

Important: do **not** add a vague `probabilistic_dependency` field to the live prompt until there is a separate code path that uses it safely. Keep Tier 2 focused on hard logical vectors.

### Tier 3: Label fallback prompt

Improve it by:

- converting the taxonomy into ordered decision steps
- separating "hard exclusion" cases from "soft conditional" cases
- adding explicit examples for threshold/time-window edge cases
- adding examples of when to return `none`

Tier 3 is where nuanced conditionals should be improved, but it still needs strict output control.

---

## 7. Evaluation Plan

Use the existing eval pipeline, but report more than one metric.

### Offline eval metrics

- JSON parse success rate
- exact dependency-type accuracy
- correlation-direction accuracy for conditional pairs
- resolution-vector exact match rate
- non-trivial matrix rate
- downgrade rate after verification

### Trading metrics

- opportunities generated
- optimized opportunities
- verified opportunities
- trades executed
- total PnL
- Sharpe
- token cost
- wall-clock runtime

### Prompt scorecard

Every prompt variant should get a table like:

| Variant | Parse % | Exact type % | Vector exact % | Non-trivial matrix % | Verified opps | Backtest PnL | Cost |
|---|---|---|---|---|---|---|---|

Do not promote a prompt just because it produces more `conditional` labels.

---

## 8. Rollout Plan

### Step 1

Create prompt variants in code behind versioned constants:

- `CLASSIFIER_SYSTEM_PROMPT_V2`
- `RESOLUTION_VECTOR_PROMPT_V2`

### Step 2

Run offline reclassification on the labeled eval set and the 597-pair backtest set.

### Step 3

Compare against current prompts on:

- accuracy
- matrix usefulness
- cost
- runtime

### Step 4

If V2 wins offline, run a shadow live test with classifications logged but not trusted for trading.

### Step 5

Promote only after shadow results show:

- no parse regressions
- no spike in low-quality conditional labels
- equal or better verified opportunity quality

---

## 9. Proposed Work Order

1. Rewrite Tier 2 prompt into XML-structured V2
2. Add 5 real examples to Tier 2
3. Rewrite Tier 3 prompt into XML-structured V2
4. Add 5 real examples to Tier 3
5. Add eval scorecard output for parse / matrix / backtest metrics
6. Run Claude V2 offline eval
7. Compare against Sonnet current prompt and cheap-model current prompt
8. Decide whether prompt changes reduce the need for local LLM work

---

## 10. Risks

- Overfitting examples to the 316-pair labeled set
- Improving explanation quality without improving matrix quality
- Raising latency or token cost too much in the live loop
- Accidentally making prompts more verbose and less parseable
- Confusing logical constraints with probabilistic correlation

Mitigation:

- keep prompts short after restructuring
- optimize for exact JSON and matrix quality
- treat any new soft signal as shadow-only until backtests prove value

---

## 11. Decision Rule

Prompt improvement is successful if it achieves **at least one** of these without materially worsening cost or latency:

- higher exact classification accuracy
- higher resolution-vector exact match rate
- higher non-trivial matrix rate
- better verified opportunity quality
- better backtest PnL / Sharpe

If it only increases the raw count of `conditional` labels, it is not a win.

---

## 12. Recommended Next Action

Start with a **Tier 2 V2 rewrite** using:

- XML tags
- 3-5 real examples
- explicit ordered rules
- exact output schema
- no added soft-probability fields

That is the cleanest Claude-style improvement with the highest signal-to-risk ratio.
