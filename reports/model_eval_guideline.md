# Classifier Model Evaluation Guideline

**Created:** 2026-03-23
**Purpose:** Standardized protocol for comparing LLM classifier backends in the 3-tier classification pipeline.

**Scope:** This is a **classifier-only** comparison. It reclassifies existing `MarketPair` rows and backtests on the same pair universe. It does **not** re-run pair discovery, verification, or historical data import. If recent bug fixes touched those upstream stages, a separate full-pipeline rerun is needed first (re-import dataset, re-discover pairs), and then this protocol can be applied to compare classifiers on the refreshed pair universe.

---

## 1. Models Under Test

| # | Model ID (OpenRouter) | Type | Notes |
|---|----------------------|------|-------|
| 1 | `openai/gpt-4.1-mini` | Standard | Current production baseline |
| 2 | `minimax/minimax-m2.7` | Reasoning | Mandatory `<think>`, needs higher max_tokens |
| 3 | `anthropic/claude-3.5-haiku` | Standard | Budget Anthropic |
| 4 | `anthropic/claude-sonnet-4` | Standard | Mid-tier Anthropic |
| 5 | `google/gemini-2.5-flash` | Reasoning | Cheap reasoning model |
| 6 | `deepseek/deepseek-chat` | Standard | DeepSeek V3, cheapest option |

All models run via OpenRouter (`https://openrouter.ai/api/v1`) to avoid per-provider rate limits.

**API key:** `reclassify_pairs.py` reads `settings.openrouter_api_key` (env var `OPENROUTER_API_KEY`) and passes it as the bearer token when `--base-url` is set to OpenRouter. Ensure this is set in the `.env` file on the NAS before running.

---

## 2. Pre-Requisites

Before running any model evaluation:

### 2.1 Code Must Be Current
```bash
# Record the deployed commit SHA for reproducibility
COMMIT_SHA=$(git rev-parse HEAD)
echo "Deploying commit: $COMMIT_SHA"

# On local machine — ensure latest fixes are deployed
git pull origin main
# Deploy to NAS
tar czf /tmp/polyarb.tar.gz --exclude='node_modules' --exclude='.git' --exclude='__pycache__' --exclude='.env' . && \
cat /tmp/polyarb.tar.gz | ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && cat > x.tar.gz && tar xzf x.tar.gz && rm x.tar.gz && find . -name '._*' -delete"
# Rebuild backtest image
ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && docker compose build backtest"
```

### 2.2 Migrations Applied
```bash
# Ensure backtest DB has all migrations
# NOTE: If you recreated polyarb_backtest from scratch (e.g. via dblink),
# stamp it first: alembic stamp head — then upgrade is a no-op but safe.
ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && \
  docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest alembic current && \
  docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest alembic upgrade head"
```

### 2.3 Verify Critical Fixes Present
These bugs directly affect backtest accuracy. Confirm they are fixed before trusting results:

| Fix | File | What to check |
|-----|------|---------------|
| Implication direction from pair column | `scripts/backtest.py` | `pair.implication_direction or constraint.get(...)` in both detect and optimize |
| Missing direction → unconstrained | `services/detector/constraints.py` | `implication_direction_missing` warning + `_unconstrained_matrix` fallback |
| Profit bound handles unconstrained | `services/detector/constraints.py` | `_compute_profit_bound` returns 0 for all-ones matrix |
| Kelly sizing in backtest | `scripts/backtest.py` | `kelly_fraction = min(net_profit * 0.5, 1.0)` in `simulate_opportunity` |

> **Note:** The restore replay fee fix (`services/simulator/main.py`) is relevant for live simulator restarts but not for this evaluation. `scripts/backtest.py` creates a fresh `Portfolio` each run, so that fix has no effect here.

---

## 3. Evaluation Protocol

### 3.0 Pinned Parameters

All runs in a single evaluation batch **must** use identical parameters:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `--start` | `2024-09-24` | First date in Becker dataset |
| `--end` | `2026-01-25` | Last date in Becker dataset |
| `--capital` | `10000` | Standard starting capital |
| `--authoritative` | (flag) | Use dataset-based settlement, not live API |
| Commit SHA | Record at deploy time | Reproducibility |

### 3.1 Reclassification

Run each model against the backtest DB. Do **not** pass `--force` — the safety guard in `reclassify_pairs.py` already allows writes when `POSTGRES_DB=polyarb_backtest`. Omitting `--force` means a missing or wrong `-e POSTGRES_DB=polyarb_backtest` will fail safe instead of silently mutating live classifications.

```bash
ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && \
  nohup docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest \
  python -m scripts.reclassify_pairs \
    --model MODEL_ID \
    --base-url https://openrouter.ai/api/v1 \
    --batch-size 3 \
  > /tmp/MODEL_reclassify.log 2>&1 &"
```

**Important:**
- Each reclassification overwrites the previous model's classifications in the DB
- Run models sequentially (reclassify → backtest → next model)
- Use `nohup` to survive SSH disconnects
- Monitor via: `ssh ... "tail -5 /tmp/MODEL_reclassify.log"`
- Completion check: `ssh ... "grep reclassify_complete /tmp/MODEL_reclassify.log"`

### 3.2 Backtest

After each reclassification completes:

```bash
ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && \
  nohup docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest \
  python -m scripts.backtest \
    --capital 10000 \
    --start 2024-09-24 \
    --end 2026-01-25 \
    --authoritative \
    --output /tmp/MODEL_backtest_report.json \
  > /tmp/MODEL_backtest.log 2>&1 &"
```

**Completion check:**
```bash
ssh ... "grep backtest_complete /tmp/MODEL_backtest.log"
```

### 3.3 Automated Pipeline (All Models)

To run all models sequentially without manual intervention:

```bash
ssh applecat@192.168.5.100 "cat > /tmp/run_eval.sh << 'SCRIPT'
#!/bin/bash
set -euo pipefail

cd /volume1/docker/polyarb

# Pinned parameters
START_DATE=\"2024-09-24\"
END_DATE=\"2026-01-25\"
CAPITAL=10000
COMMIT_SHA=\$(git rev-parse HEAD 2>/dev/null || echo \"unknown\")

# Durable output directory
EVAL_DIR=\"/volume1/docker/polyarb/eval_results/\$(date +%Y%m%d_%H%M%S)\"
mkdir -p \"\$EVAL_DIR\"
echo \"commit: \$COMMIT_SHA\" > \"\$EVAL_DIR/metadata.txt\"
echo \"start: \$START_DATE\" >> \"\$EVAL_DIR/metadata.txt\"
echo \"end: \$END_DATE\" >> \"\$EVAL_DIR/metadata.txt\"
echo \"capital: \$CAPITAL\" >> \"\$EVAL_DIR/metadata.txt\"

MODELS=(\"openai/gpt-4.1-mini\" \"minimax/minimax-m2.7\" \"anthropic/claude-3.5-haiku\" \"anthropic/claude-sonnet-4\" \"google/gemini-2.5-flash\" \"deepseek/deepseek-chat\")
NAMES=(\"gpt41mini\" \"m27\" \"haiku\" \"sonnet\" \"gemini\" \"deepseek\")

for i in \${!MODELS[@]}; do
  MODEL=\${MODELS[\$i]}
  NAME=\${NAMES[\$i]}
  echo \"=== \$NAME: \$MODEL ===\"

  docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest \
    python -m scripts.reclassify_pairs \
      --model \"\$MODEL\" \
      --base-url https://openrouter.ai/api/v1 \
      --batch-size 3 \
    2>&1 | tee \"\$EVAL_DIR/\${NAME}_reclassify.log\"

  docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest \
    python -m scripts.backtest \
      --capital \$CAPITAL \
      --start \$START_DATE \
      --end \$END_DATE \
      --authoritative \
      --output \"\$EVAL_DIR/\${NAME}_backtest_report.json\" \
    2>&1 | tee \"\$EVAL_DIR/\${NAME}_backtest.log\"
done
echo \"=== ALL DONE ===\"
echo \"Results saved to: \$EVAL_DIR\"
SCRIPT
chmod +x /tmp/run_eval.sh && nohup bash /tmp/run_eval.sh > /tmp/eval_pipeline.log 2>&1 &"
```

**Monitor progress:**
```bash
ssh ... "grep -E 'reclassify_complete|backtest_complete|=== ' /tmp/eval_pipeline.log"
```

**Retrieve results after completion:**
```bash
# Find the eval directory
ssh ... "ls -d /volume1/docker/polyarb/eval_results/*"
# Copy results locally
scp -r applecat@192.168.5.100:/volume1/docker/polyarb/eval_results/YYYYMMDD_HHMMSS ./eval_results/
```

---

## 4. Metrics to Collect

### 4.1 Classification Quality

From `reclassify_complete` log line:

| Metric | How to extract |
|--------|---------------|
| Type distribution | `type_breakdown` — count per dependency type |
| Non-none count | Sum of all types except `none` |
| Source breakdown | `source_breakdown` — llm_vector vs llm_label vs rule_based |
| Vector success rate | `llm_vector / (total - rule_based)` |
| Transitions from baseline | `transitions` dict |
| Errors | `errors` count (should be 0) |

### 4.2 Backtest Performance

From `backtest_complete` log line (and `--output` JSON):

| Metric | Field | Good Range |
|--------|-------|------------|
| Total return % | `total_return_pct` | > 0% |
| Realized PnL $ | `realized_pnl` | > 0 |
| Sharpe ratio | `sharpe_ratio` | > 1.0 |
| Max drawdown % | `max_drawdown_pct` | < 5% |
| Total trades | `total_trades` | 100-1000 |
| Total settled | `total_settled` | > 50 |
| Win rate | Count positive vs negative `settlement_pnl` in day logs |
| Open positions EOD | `open_positions` | 0 (clean exit) |

### 4.3 Model Operational Metrics

From reclassification logs:

| Metric | How to count |
|--------|-------------|
| JSON parse failures | `grep -c resolution_vector_parse_failed` |
| Degenerate vectors | `grep -c resolution_vector_degenerate` |
| Empty content responses | `grep -c llm_empty_content_debug` |
| Empty vector responses | `grep -c resolution_vector_empty_debug` |
| Wall-clock time | Timestamps of first and last `batch_complete` |
| Cost estimate | Not currently logged — requires manual calculation from OpenRouter billing dashboard |

---

## 5. Results Template

After all models complete, compile into this table:

| Model | Return | PnL | Sharpe | Max DD | Trades | Non-none | Vec Rate | Parse Fails | Time |
|-------|--------|-----|--------|--------|--------|----------|----------|-------------|------|
| gpt-4.1-mini | | | | | | | | | |
| M2.7 | | | | | | | | | |
| Haiku 3.5 | | | | | | | | | |
| Sonnet 4 | | | | | | | | | |
| Gemini 2.5 Flash | | | | | | | | | |
| DeepSeek V3 | | | | | | | | | |

---

## 6. Known Issues / Caveats

- **Reclassify overwrites DB state.** Each model replaces the previous model's classifications. There is no versioning — run one model at a time, backtest, then move to the next.
- **Classifier-only evaluation.** This protocol does not re-run pair discovery or verification. If upstream bugs affected which pairs exist, re-import the dataset and re-discover pairs first.
- **Reasoning models** (M2.7, Gemini 2.5 Flash) may produce `<think>` blocks. Our classifier strips these via `_strip_think_tags()`. If `content` is null with reasoning in `model_extra`, we fail closed (return none/None).
- **Degenerate vectors** (all 4 combos valid → independent) are common for sports matchups between different games. This is correct behavior, not an error.
- **Confidence calibration**: Raw LLM confidence is discounted by 0.8x and capped at 0.85. A raw confidence of >= 0.875 is needed to pass the 0.70 verification threshold.
- **Backtest period**: 2024-09-24 to 2026-01-25 (489 days). Earlier period has fewer pairs and less price history. Results are dominated by the later, denser period.
- **Previous results (pre-696b935) are invalid** due to: wrong implication direction defaulting, missing Kelly sizing, inflated profit bounds from unconstrained matrices.
- **Token usage not logged.** Cost comparison requires checking the OpenRouter billing dashboard after each run. Consider adding token logging to `classifier.py` in a future iteration.
- **`set -euo pipefail` in the automated pipeline** means a failed reclassification will abort the entire run. This is intentional — running a backtest on a partially-classified DB produces meaningless results. If a model fails, fix the issue and re-run from that model onward.

---

## 7. Decision Criteria

Choose the production model based on:

1. **Sharpe ratio > 1.0** — risk-adjusted return must be acceptable
2. **Max drawdown < 5%** — hard limit for paper trading
3. **Realized PnL > $0** — must be profitable
4. **Vector success rate > 40%** — model must produce usable structured output
5. **Zero parse errors on critical paths** — no crashes in production
6. **Wall-clock time < 2 hours** for full reclassification — operational feasibility
7. **Cost < $5 per full run** — budget constraint

If multiple models pass all criteria, prefer the one with highest Sharpe ratio (risk-adjusted return), not highest raw return.

---

## 8. Artifact Checklist

After each evaluation run, the `eval_results/<timestamp>/` directory should contain:

| File | Purpose |
|------|---------|
| `metadata.txt` | Commit SHA, date range, capital |
| `<model>_reclassify.log` | Full reclassification output |
| `<model>_backtest.log` | Full backtest output |
| `<model>_backtest_report.json` | Structured backtest results (from `--output`) |

Keep this directory intact for future comparison. Do not rely on `/tmp/` logs — they are lost on container restart.
