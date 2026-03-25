#!/bin/bash
set -uo pipefail

# V4 Classifier Evaluation Orchestrator
#
# Runs the complete V4 eval pipeline:
#   Phase 1: Validate gold set & silver dataset
#   Phase 2: Per-model reclassify + accuracy scoring against gold set
#   Phase 3: Per-model backtest on silver dataset
#   Phase 4: Aggregate results into comparison report
#
# Usage:
#   ./scripts/run_v4_eval.sh                        # All 8 models
#   ./scripts/run_v4_eval.sh --models gpt41mini,sonnet  # Specific models
#   ./scripts/run_v4_eval.sh --skip-reclassify      # Backtest only (reuse existing DBs)
#   ./scripts/run_v4_eval.sh --dry-run              # Print plan, don't execute

cd /volume1/docker/polyarb

# Source .env for API keys
if [ -f .env ]; then
  set -a; source .env; set +a
fi

# ── Config ──────────────────────────────────────────────────────────

START_DATE="2024-09-24"
END_DATE="2026-01-25"
CAPITAL=10000

GOLD_SET="scripts/eval_data/labeled_pairs_v4.json"
SILVER_SET="scripts/eval_data/silver_pairs_v4.json"

OPENROUTER_API_KEY="${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY env var}"
DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:?Set DASHSCOPE_API_KEY env var}"

# Model registry: name|model_id|base_url|api_key_var
declare -A MODEL_MAP
MODEL_MAP[gpt41mini]="openai/gpt-4.1-mini|https://openrouter.ai/api/v1|OPENROUTER_API_KEY"
MODEL_MAP[m27]="minimax/minimax-m2.7|https://openrouter.ai/api/v1|OPENROUTER_API_KEY"
MODEL_MAP[haiku]="anthropic/claude-3.5-haiku|https://openrouter.ai/api/v1|OPENROUTER_API_KEY"
MODEL_MAP[sonnet]="anthropic/claude-sonnet-4|https://openrouter.ai/api/v1|OPENROUTER_API_KEY"
MODEL_MAP[gemini]="google/gemini-2.5-flash|https://openrouter.ai/api/v1|OPENROUTER_API_KEY"
MODEL_MAP[deepseek]="deepseek/deepseek-chat|https://openrouter.ai/api/v1|OPENROUTER_API_KEY"
MODEL_MAP[qwen3max]="qwen3-max|https://dashscope-intl.aliyuncs.com/compatible-mode/v1|DASHSCOPE_API_KEY"
MODEL_MAP[qwen35]="qwen3.5-122b-a10b|https://dashscope-intl.aliyuncs.com/compatible-mode/v1|DASHSCOPE_API_KEY"

ALL_NAMES=(gpt41mini m27 haiku sonnet gemini deepseek qwen3max qwen35)

# ── Parse args ──────────────────────────────────────────────────────

SELECTED_NAMES=()
SKIP_RECLASSIFY=false
SKIP_BACKTEST=false
DRY_RUN=false
MAX_PARALLEL=4  # Limit concurrent reclassify runs to avoid API rate limits

while [[ $# -gt 0 ]]; do
  case "$1" in
    --models) IFS=',' read -ra SELECTED_NAMES <<< "$2"; shift 2 ;;
    --skip-reclassify) SKIP_RECLASSIFY=true; shift ;;
    --skip-backtest) SKIP_BACKTEST=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --max-parallel) MAX_PARALLEL="$2"; shift 2 ;;
    --gold-set) GOLD_SET="$2"; shift 2 ;;
    --silver-set) SILVER_SET="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ ${#SELECTED_NAMES[@]} -eq 0 ]; then
  SELECTED_NAMES=("${ALL_NAMES[@]}")
fi

EVAL_DIR="eval_results/v4_eval_$(date +%Y%m%d_%H%M%S)"

# ── Helpers ─────────────────────────────────────────────────────────

log() { echo "[$(date +%H:%M:%S)] $*"; }

get_model_field() {
  local name="$1" field="$2"
  local entry="${MODEL_MAP[$name]}"
  case "$field" in
    model) echo "$entry" | cut -d'|' -f1 ;;
    url)   echo "$entry" | cut -d'|' -f2 ;;
    key)   local var; var=$(echo "$entry" | cut -d'|' -f3); echo "${!var}" ;;
  esac
}

# ── Phase 0: Pre-flight ────────────────────────────────────────────

log "V4 Eval Pipeline"
log "Models: ${SELECTED_NAMES[*]}"
log "Gold set: $GOLD_SET"
log "Silver set: $SILVER_SET"
log "Output: $EVAL_DIR"

if $DRY_RUN; then
  echo ""
  echo "=== DRY RUN ==="
  echo "Would create ${#SELECTED_NAMES[@]} databases"
  for name in "${SELECTED_NAMES[@]}"; do
    echo "  polyarb_bt_${name}: reclassify $(get_model_field "$name" model) + backtest"
  done
  echo "Would score against $GOLD_SET"
  if $SKIP_BACKTEST; then
    echo "Backtest: SKIPPED (--skip-backtest)"
  else
    echo "Would backtest against $SILVER_SET"
  fi
  exit 0
fi

mkdir -p "$EVAL_DIR"
cat > "$EVAL_DIR/metadata.txt" << EOF
round: v4
start: $START_DATE
end: $END_DATE
capital: $CAPITAL
gold_set: $GOLD_SET
silver_set: $SILVER_SET
models: ${SELECTED_NAMES[*]}
started: $(date)
EOF

# ── Phase 1: Validate datasets ─────────────────────────────────────

log "Phase 1: Validating datasets..."

if [ -f "$GOLD_SET" ]; then
  docker compose run --rm backtest python -m scripts.analyze_goldset "$GOLD_SET" --check-gate -v \
    2>&1 | tee "$EVAL_DIR/goldset_analysis.log"
  GATE_EXIT=${PIPESTATUS[0]}
  if [ "$GATE_EXIT" -ne 0 ]; then
    log "WARNING: Gold set gate check failed — accuracy scoring may be unreliable"
  fi
else
  log "WARNING: Gold set $GOLD_SET not found — skipping accuracy scoring"
fi

if [ ! -f "$SILVER_SET" ]; then
  log "Silver set not found, curating..."
  docker compose run --rm backtest python -m scripts.curate_silver_dataset \
    --output "$SILVER_SET" 2>&1 | tee "$EVAL_DIR/silver_curation.log"
fi

# ── Phase 2: Clone DBs + Reclassify ────────────────────────────────

log "Phase 2: Database setup + reclassification..."

# Kill stale connections
docker compose exec -T postgres psql -U polyarb -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'polyarb_backtest' AND pid <> pg_backend_pid();" \
  >/dev/null 2>&1 || true
sleep 2

# Create per-model DBs
for name in "${SELECTED_NAMES[@]}"; do
  DB="polyarb_bt_${name}"
  log "Creating $DB..."
  docker compose exec -T postgres psql -U polyarb -d postgres -c "DROP DATABASE IF EXISTS ${DB};" 2>/dev/null || true
  docker compose exec -T postgres psql -U polyarb -d postgres -c "CREATE DATABASE ${DB} WITH TEMPLATE polyarb_backtest OWNER polyarb;"
done

# Wait for postgres to recover from WAL replay after heavy DB cloning
_wait_pg_ready() {
  local max_wait=${1:-120}
  local elapsed=0
  log "Waiting for postgres readiness (timeout ${max_wait}s)..."
  while [ $elapsed -lt $max_wait ]; do
    if docker compose exec -T postgres pg_isready -U polyarb -q 2>/dev/null; then
      log "Postgres ready after ${elapsed}s"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  log "ERROR: Postgres not ready after ${max_wait}s — aborting"
  exit 1
}
_wait_pg_ready 120

if ! $SKIP_RECLASSIFY; then
  log "Reclassifying with ${#SELECTED_NAMES[@]} models (max $MAX_PARALLEL parallel)..."

  PIDS=()
  RUNNING=0

  for name in "${SELECTED_NAMES[@]}"; do
    MODEL=$(get_model_field "$name" model)
    URL=$(get_model_field "$name" url)
    KEY=$(get_model_field "$name" key)
    DB="polyarb_bt_${name}"

    log "  Launching reclassify: $name ($MODEL)"
    docker compose run --rm -e POSTGRES_DB="$DB" backtest \
      python -m scripts.reclassify_pairs \
        --model "$MODEL" --base-url "$URL" --api-key "$KEY" --batch-size 3 \
      2>&1 | tee "$EVAL_DIR/${name}_reclassify.log" &
    PIDS+=($!)
    RUNNING=$((RUNNING + 1))

    # Throttle parallel jobs
    if [ "$RUNNING" -ge "$MAX_PARALLEL" ]; then
      wait "${PIDS[0]}"
      PIDS=("${PIDS[@]:1}")
      RUNNING=$((RUNNING - 1))
    fi
    sleep 2
  done

  # Wait for remaining
  for pid in "${PIDS[@]}"; do
    wait "$pid"
  done
  log "All reclassifications complete"
fi

# ── Phase 2b: Score accuracy against gold set ───────────────────────

_wait_pg_ready 120

if [ -f "$GOLD_SET" ]; then
  log "Scoring accuracy against gold set..."
  EVAL_ABS="$(pwd)/$EVAL_DIR"
  for name in "${SELECTED_NAMES[@]}"; do
    MODEL=$(get_model_field "$name" model)
    URL=$(get_model_field "$name" url)
    KEY=$(get_model_field "$name" key)
    DB="polyarb_bt_${name}"
    log "  Scoring $name ($MODEL)..."
    docker compose run --rm \
      -e POSTGRES_DB="$DB" \
      -v "$EVAL_ABS:/app/eval_output" \
      backtest \
      python -m scripts.eval_classifier eval \
        --data-file "$GOLD_SET" \
        --model "$MODEL" --base-url "$URL" --api-key "$KEY" \
        --summary-json "/app/eval_output/${name}_accuracy.json" \
      2>&1 | tee "$EVAL_DIR/${name}_accuracy.log"
  done
fi

# ── Phase 3: Backtest on silver dataset ─────────────────────────────

FAILED=0
if $SKIP_BACKTEST; then
  log "Phase 3: Skipped (--skip-backtest)"
else
  log "Phase 3: Backtesting on silver dataset..."

  EVAL_ABS="$(pwd)/$EVAL_DIR"
  PIDS=()
  for name in "${SELECTED_NAMES[@]}"; do
    DB="polyarb_bt_${name}"
    log "  Launching backtest: $name"

    PAIR_FILE_ARG=""
    if [ -f "$SILVER_SET" ]; then
      PAIR_FILE_ARG="--pair-file $SILVER_SET"
    fi

    docker compose run --rm \
      -e POSTGRES_DB="$DB" \
      -v "$EVAL_ABS:/app/eval_output" \
      backtest \
      python -m scripts.backtest \
        --capital "$CAPITAL" --start "$START_DATE" --end "$END_DATE" \
        --authoritative $PAIR_FILE_ARG \
        --output "/app/eval_output/${name}_backtest_report.json" \
      2>&1 | tee "$EVAL_DIR/${name}_backtest.log" &
    PIDS+=($!)
    sleep 2
  done

  # Wait for all backtests
  for i in "${!PIDS[@]}"; do
    if wait "${PIDS[$i]}"; then
      log "${SELECTED_NAMES[$i]} backtest OK"
    else
      log "${SELECTED_NAMES[$i]} backtest FAILED"
      FAILED=$((FAILED + 1))
    fi
  done
fi

# ── Phase 4: Aggregate results ──────────────────────────────────────

log "Phase 4: Aggregating results..."

_json_field() {
  # Usage: _json_field file.json field_name default
  python3 -c "
import json, sys
try:
    d = json.load(open('$1'))
    # support nested summary.field for backtest reports
    v = d.get('summary', d).get('$2', d.get('$2'))
    print(v if v is not None else '$3')
except Exception:
    print('$3')
" 2>/dev/null
}

{
  echo "# V4 Eval Results — $(date +%Y-%m-%d)"
  echo ""
  if $SKIP_BACKTEST; then
    echo "| Model | Accuracy | Macro F1 | FPR |"
    echo "|-------|----------|----------|-----|"
  else
    echo "| Model | Accuracy | Macro F1 | FPR | Return% | Sharpe | Trades |"
    echo "|-------|----------|----------|-----|---------|--------|--------|"
  fi

  for name in "${SELECTED_NAMES[@]}"; do
    ACC_JSON="$EVAL_DIR/${name}_accuracy.json"

    # Extract from accuracy JSON
    ACCURACY=$(_json_field "$ACC_JSON" accuracy_pct "N/A")
    MACRO_F1=$(_json_field "$ACC_JSON" macro_f1 "N/A")
    FPR=$(_json_field "$ACC_JSON" fpr_pct "N/A")

    if $SKIP_BACKTEST; then
      echo "| $name | ${ACCURACY}% | $MACRO_F1 | ${FPR}% |"
    else
      BT_JSON="$EVAL_DIR/${name}_backtest_report.json"
      RETURN=$(_json_field "$BT_JSON" total_return_pct "N/A")
      SHARPE=$(_json_field "$BT_JSON" sharpe_ratio "N/A")
      TRADES=$(_json_field "$BT_JSON" total_trades "0")
      echo "| $name | ${ACCURACY}% | $MACRO_F1 | ${FPR}% | ${RETURN}% | $SHARPE | $TRADES |"
    fi
  done
} > "$EVAL_DIR/summary.md"

cat "$EVAL_DIR/summary.md"

# ── Cleanup ─────────────────────────────────────────────────────────

log "Cleaning up per-model databases..."
for name in "${SELECTED_NAMES[@]}"; do
  DB="polyarb_bt_${name}"
  docker compose exec -T postgres psql -U polyarb -d postgres -c "DROP DATABASE IF EXISTS ${DB};" 2>/dev/null || true
done

echo "Finished: $(date)" >> "$EVAL_DIR/metadata.txt"
log "Done ($FAILED failures). Results: $EVAL_DIR"
log "Summary: $EVAL_DIR/summary.md"
