# Classifier Technical Reference

**Purpose:** How the PolyArb classifier uses LLM models — architecture, API contract, prompts, and what a model needs to perform well. Use this alongside the [model comparison report](classifier_model_comparison_2026-03-23.md) when evaluating new models.

---

## 1. Classification Pipeline

Every market pair goes through a 3-tier pipeline (`classifier.py:classify_pair`):

```
Tier 1: Rule-based heuristics (no LLM, instant)
  ↓ if no match
Tier 2: Resolution vector LLM call (structured, JSON output)
  ↓ if parse fails or non-binary markets
Tier 3: Label-based LLM call (unstructured, confidence capped at 0.70)
```

**Source breakdown across models (597 pairs):**
- Rule-based: ~5 pairs (same across all models — deterministic)
- LLM vector (Tier 2): ~195-336 pairs
- LLM label (Tier 3): ~256-397 pairs

Models that produce cleaner JSON in Tier 2 get classified there (higher confidence). Models that fail JSON parsing fall through to Tier 3 (capped at 0.70 confidence, which limits trade sizing).

---

## 2. Tier 1: Rule-Based Heuristics

These run first, need no LLM, and return high-confidence (0.95) results:

| Heuristic | What it detects | Example |
|-----------|----------------|---------|
| `_check_same_event` | Same event_id + overlapping outcomes → partition | "Biden wins Iowa" / "Biden wins NH" (same election event) |
| `_check_outcome_subset` | Outcome containment → partition | Market A outcomes are a subset of Market B |
| `_check_crypto_time_intervals` | Same asset, different time windows → none/ME/impl | "BTC > $100k by March" / "BTC > $100k by June" |
| `_check_price_threshold_markets` | Price threshold chains → implication | "PLTR > $128" / "PLTR > $134" |
| `_check_ranking_markets` | Top-N rankings → implication | "Top 3 scorer" / "Top 5 scorer" |
| `_check_over_under_markets` | Nested O/U lines → implication | "O/U 2.5" / "O/U 3.5" same match |

Only ~5 pairs per run hit these. The rest go to Tier 2.

---

## 3. Tier 2: Resolution Vector Classification

**What the model does:** Given two binary markets, enumerate ALL logically valid outcome combinations from {(Yes,Yes), (Yes,No), (No,Yes), (No,No)}.

**Prompt** (full text in `classifier.py:RESOLUTION_VECTOR_PROMPT`):
```
You are a prediction market analyst. Given two binary markets A and B,
determine ALL logically valid outcome combinations.

Rules:
- Each market resolves to exactly one outcome.
- List every combination that is logically possible.
- Only exclude a combination if it is LOGICALLY IMPOSSIBLE — not merely unlikely.
- Correlation or probability does NOT make a combination invalid.
- IMPORTANT: If both markets ask whether different entities will achieve
  the SAME singular outcome (e.g., "Will X win the award?" and "Will Y win
  the award?"), then both cannot be Yes simultaneously. Exclude (Yes, Yes).

Market A: "{question_a}" — Outcomes: {outcomes_a}
Market B: "{question_b}" — Outcomes: {outcomes_b}

Return strictly valid JSON with no additional text:
{"valid_outcomes": [{"a": "Yes", "b": "Yes"}, ...],
 "reasoning": "<one sentence>", "confidence": <float 0.0-1.0>}
```

**Expected JSON response:**
```json
{
  "valid_outcomes": [
    {"a": "Yes", "b": "Yes"},
    {"a": "Yes", "b": "No"},
    {"a": "No", "b": "Yes"},
    {"a": "No", "b": "No"}
  ],
  "reasoning": "These markets are independent.",
  "confidence": 0.85
}
```

**Deterministic type derivation** (`_derive_dependency_type`): The code maps the valid outcome set to a dependency type — the model doesn't choose the type directly:

| Valid combos | Derived type |
|-------------|-------------|
| All 4 | `none` |
| 3 combos, missing (Yes,Yes) | `mutual_exclusion` |
| 3 combos, missing (Yes,No) | `implication` (a→b) |
| 3 combos, missing (No,Yes) | `implication` (b→a) |
| 2 combos: (Yes,No)+(No,Yes) | `partition` |
| 2 combos: (Yes,Yes)+(No,No) | `cross_platform` |
| 2 combos with (Yes,Yes) but not (No,No) | `conditional` (positive) |
| 2 combos without (Yes,Yes) | `conditional` (negative) |
| 1 combo | `implication` (deterministic) |

**Key insight for model selection:** The model's job in Tier 2 is purely logical — enumerate valid combos. It does NOT name dependency types or estimate probabilities. Models that are good at logical reasoning about real-world constraints perform best here.

**API parameters:**
- `temperature: 0.0`
- `max_tokens: 512` (2048 for reasoning models with `<think>` blocks)
- `response_format: {"type": "json_object"}` — **only for models that support it** (currently skipped for MiniMax models)
- Standard OpenAI chat completions endpoint

**Confidence handling:** Raw LLM confidence is discounted: `min(raw * 0.80, 0.85)`. This prevents overconfidence from driving oversized positions.

**Only works for binary markets** (2 outcomes each). Non-binary pairs skip to Tier 3.

---

## 4. Tier 3: Label-Based Classification (Fallback)

**What the model does:** Directly classify the dependency type and correlation between two markets.

**System prompt** (full text in `classifier.py:CLASSIFIER_SYSTEM_PROMPT`):
```
You classify the logical dependency between two prediction markets.

Given two markets with their questions, descriptions, and outcomes, determine:
1. dependency_type: one of "implication", "partition", "mutual_exclusion",
   "conditional", or "none"
2. confidence: float 0-1
3. correlation: "positive" or "negative" (REQUIRED when conditional)

Definitions:
- implication: If A resolves Yes, B must resolve a specific way
- partition: A and B together form an exhaustive partition
- mutual_exclusion: A and B cannot both resolve Yes
- conditional: A's outcome probabilities are constrained by B's outcome
  - positive: A=Yes makes B=Yes more likely
  - negative: A=Yes makes B=Yes less likely

CRITICAL — price-threshold markets:
- "X above $A" and "X above $B" where A > B: IMPLICATION, not ME
- Different dates/time windows: INDEPENDENT (none)
- Only use ME when events truly cannot BOTH happen
```

**User prompt:** Market questions, descriptions, and outcomes for both markets.

**Expected JSON response:**
```json
{
  "dependency_type": "conditional",
  "confidence": 0.85,
  "correlation": "positive",
  "reasoning": "O/U 2.5 Over makes BTTS Yes more likely"
}
```

**API parameters:**
- `temperature: 0.1`
- `max_tokens: 256` (1024 for reasoning models)
- No `response_format` — relies on system prompt to produce JSON

**Confidence cap:** Tier 3 results are capped at `0.70` regardless of what the model returns. This limits position sizing for fallback classifications.

---

## 5. What Makes a Model Win

Based on Round 2 results, the performance hierarchy is:

### Must-have: Correct `none` vs `non-none` boundary
Conservative models (Haiku, DeepSeek, gpt-4.1-mini) classify too many pairs as `none`, producing few opportunities. The model needs to recognize real dependencies without being told explicitly.

### Key differentiator: Conditional detection
Sonnet found 250 conditional pairs; others found 0-14. These are probabilistic dependencies (O/U vs BTTS, spread vs totals) that don't meet the strict logical threshold of Tier 2's "exclude only if LOGICALLY IMPOSSIBLE" rule.

**The paradox:** Tier 2 explicitly says "correlation does NOT make a combination invalid" — yet Sonnet somehow produces classifications that lead to more conditional pairs. This happens because:
1. Sonnet is more willing to exclude borderline combos in Tier 2 (e.g., excluding (Over, No-BTTS) for high O/U lines)
2. When it falls to Tier 3, it correctly identifies `conditional` instead of defaulting to `none`

### Must-have: Clean JSON output
Parse failures = wasted API calls. M2.7 had 13 parse failures + 73 empty vectors. Zero tolerance for production.

### Nice-to-have: Concise output
Token usage directly impacts cost. DeepSeek V3 used only 438K tokens vs Sonnet's 2.06M for the same 597 pairs. Verbose reasoning (M2.7: 4.06M tokens) wastes money.

---

## 6. API Compatibility Requirements

The classifier uses the **OpenAI Python SDK** (`openai.AsyncOpenAI`). Any model provider must be OpenAI-compatible:

```python
client = openai.AsyncOpenAI(api_key=KEY, base_url=BASE_URL)
response = await client.chat.completions.create(
    model=MODEL_ID,
    messages=[...],
    temperature=0.0,
    max_tokens=512,
    response_format={"type": "json_object"},  # Tier 2 only
)
```

**Required support:**
- `POST /chat/completions` — standard chat completions
- `messages` with `role: system` and `role: user`
- `temperature`, `max_tokens` parameters
- Response: `choices[0].message.content` as string

**Optional support:**
- `response_format: {"type": "json_object"}` — used in Tier 2. If unsupported, must add model to skip list in classifier.py line 769
- `<think>` tag handling — reasoning models that emit `<think>...</think>` blocks are automatically stripped

**Known compatibility issues:**
- DashScope (Qwen): may not support `response_format`. Needs code change to skip JSON mode.
- Reasoning models (M2.7, QwQ): need higher `max_tokens` (2048) to accommodate `<think>` blocks before the JSON answer

---

## 7. How to Run an Eval

### Reclassification (re-label all 597 pairs with a new model)
```bash
docker compose run --rm -e POSTGRES_DB=polyarb_bt_MODEL backtest \
  python -m scripts.reclassify_pairs \
    --model MODEL_ID \
    --base-url https://PROVIDER/v1 \
    --api-key sk-xxx \
    --batch-size 3
```

### Backtest (run the trading simulation)
```bash
docker compose run --rm -e POSTGRES_DB=polyarb_bt_MODEL backtest \
  python -m scripts.backtest \
    --capital 10000 \
    --start 2024-09-24 \
    --end 2026-01-25 \
    --authoritative
```

### Parallel eval (multiple models at once)
See `scripts/run_eval_parallel.sh` (Round 2, 6 models via OpenRouter) and `scripts/run_eval_qwen.sh` (Round 3, Qwen models via DashScope).

Process:
1. Clone `polyarb_backtest` template DB → per-model isolated databases
2. Reclassify pairs with each model (parallel)
3. Run backtest on each (parallel)
4. Collect results from logs
5. Clean up per-model databases

### Key metrics to extract from logs
- Classification profile: count of each dependency type
- Source breakdown: rule_based / llm_vector / llm_label
- Parse failures, empty responses
- Backtest: return %, Sharpe, max drawdown, trades, settled trades
- Token usage and wall-clock time

---

## 8. Provider Endpoints

| Provider | Base URL | Auth | Notes |
|----------|---------|------|-------|
| OpenAI | (default, no base_url) | `OPENAI_API_KEY` | Direct access |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | Multi-model routing, used for Round 2 |
| DashScope (Intl) | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | DashScope API key | Qwen models, Singapore region |

Model IDs are passed **verbatim** — no prefix stripping. Use exactly what the provider expects (e.g., `openai/gpt-4.1-mini` for OpenRouter, `qwen3-max` for DashScope).

---

## 9. Current Code Quirks

- **Minimax special-casing** (lines 766, 769, 572): Models containing "minimax" skip JSON mode and get higher max_tokens. Any new reasoning model needs the same treatment.
- **Confidence discount** (0.80x, cap 0.85): Applied to Tier 2 results. Tier 3 is hard-capped at 0.70.
- **No retries**: API errors fail silently → `none` classification with 0.0 confidence.
- **No token counting**: Unlike the embedder, the classifier has no token-aware batching. Token usage is only visible in provider billing dashboards.
- **No classification caching**: The live detector re-classifies every candidate pair every cycle (~3,900 calls/3hr). See report Section 8 for cost impact.
