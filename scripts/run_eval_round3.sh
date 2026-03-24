#!/bin/bash
set -uo pipefail

# Round 3: All 8 models with new prompt_specs layer
# 6 via OpenRouter (same as Round 2) + 2 Qwen via DashScope
# Compares new prompt_specs vs Round 2 baseline on identical data

cd /volume1/docker/polyarb

# Source .env for API keys if not already set
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

START_DATE="2024-09-24"
END_DATE="2026-01-25"
CAPITAL=10000
PROMPT_ADAPTER="auto"

# API keys
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY env var or add to .env}"
DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:?Set DASHSCOPE_API_KEY env var or add to .env}"

EVAL_DIR="/volume1/docker/polyarb/eval_results/r3_promptspec_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVAL_DIR"
cat > "$EVAL_DIR/metadata.txt" << EOF
round: 3 (prompt_specs layer)
start: $START_DATE
end: $END_DATE
capital: $CAPITAL
mode: parallel (8 models)
openrouter_models: gpt-4.1-mini, M2.7, Haiku 3.5, Sonnet 4, Gemini 2.5 Flash, DeepSeek V3
dashscope_models: qwen3-max, qwen3.5-122b-a10b
purpose: measure prompt_specs improvement vs Round 2 baseline
prompt_adapter: $PROMPT_ADAPTER
EOF

# OpenRouter models (same 6 as Round 2)
OR_MODELS=("openai/gpt-4.1-mini" "minimax/minimax-m2.7" "anthropic/claude-3.5-haiku" "anthropic/claude-sonnet-4" "google/gemini-2.5-flash" "deepseek/deepseek-chat")
OR_NAMES=("gpt41mini" "m27" "haiku" "sonnet" "gemini" "deepseek")

# DashScope models (2 Qwen)
DS_MODELS=("qwen3-max" "qwen3.5-122b-a10b")
DS_NAMES=("qwen3max" "qwen35_122b")

# Combine all
ALL_NAMES=("${OR_NAMES[@]}" "${DS_NAMES[@]}")

# Step 1: Kill stale connections and clone per-model DBs from template
echo "=== Creating 8 per-model databases ==="
docker compose exec -T postgres psql -U polyarb -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'polyarb_backtest' AND pid <> pg_backend_pid();" || true
sleep 2
for NAME in "${ALL_NAMES[@]}"; do
  DB="polyarb_bt_${NAME}"
  echo "Creating $DB..."
  docker compose exec -T postgres psql -U polyarb -d postgres -c "DROP DATABASE IF EXISTS ${DB};" 2>/dev/null || true
  docker compose exec -T postgres psql -U polyarb -d postgres -c "CREATE DATABASE ${DB} WITH TEMPLATE polyarb_backtest OWNER polyarb;"
  echo "  $DB created"
done
echo "=== All 8 databases created ==="

# Step 2: Run models in parallel
run_model() {
  local MODEL="$1"
  local NAME="$2"
  local DB="polyarb_bt_${NAME}"
  local EVAL_DIR="$3"
  local START_DATE="$4"
  local END_DATE="$5"
  local CAPITAL="$6"
  local BASE_URL="$7"
  local API_KEY="$8"

  echo "=== START $NAME: $MODEL ==="

  docker compose run --rm -e POSTGRES_DB="$DB" backtest \
    python -m scripts.reclassify_pairs \
      --model "$MODEL" \
      --base-url "$BASE_URL" \
      --api-key "$API_KEY" \
      --prompt-adapter "$PROMPT_ADAPTER" \
      --batch-size 3 \
    2>&1 | tee "$EVAL_DIR/${NAME}_reclassify.log"

  docker compose run --rm -e POSTGRES_DB="$DB" backtest \
    python -m scripts.backtest \
      --capital "$CAPITAL" \
      --start "$START_DATE" \
      --end "$END_DATE" \
      --authoritative \
    2>&1 | tee "$EVAL_DIR/${NAME}_backtest.log"

  echo "=== DONE $NAME ==="
}

export -f run_model

PIDS=()

# Launch 6 OpenRouter models
for i in ${!OR_MODELS[@]}; do
  run_model "${OR_MODELS[$i]}" "${OR_NAMES[$i]}" "$EVAL_DIR" "$START_DATE" "$END_DATE" "$CAPITAL" "https://openrouter.ai/api/v1" "$OPENROUTER_API_KEY" &
  PIDS+=($!)
  echo "Launched ${OR_NAMES[$i]} (PID $!)"
  sleep 2
done

# Launch 2 DashScope models
for i in ${!DS_MODELS[@]}; do
  run_model "${DS_MODELS[$i]}" "${DS_NAMES[$i]}" "$EVAL_DIR" "$START_DATE" "$END_DATE" "$CAPITAL" "https://dashscope-intl.aliyuncs.com/compatible-mode/v1" "$DASHSCOPE_API_KEY" &
  PIDS+=($!)
  echo "Launched ${DS_NAMES[$i]} (PID $!)"
  sleep 2
done

echo "=== All 8 models launched, waiting... ==="

# Wait for all and track failures
FAILED=0
for i in ${!PIDS[@]}; do
  if wait ${PIDS[$i]}; then
    echo "=== ${ALL_NAMES[$i]} completed OK ==="
  else
    echo "=== ${ALL_NAMES[$i]} FAILED ==="
    FAILED=$((FAILED + 1))
  fi
done

# Step 3: Cleanup per-model databases
echo "=== Cleaning up databases ==="
for NAME in "${ALL_NAMES[@]}"; do
  DB="polyarb_bt_${NAME}"
  docker compose exec -T postgres psql -U polyarb -d postgres -c "DROP DATABASE IF EXISTS ${DB};" 2>/dev/null || true
done

echo "=== ALL DONE ($FAILED failures) ==="
echo "Finished: $(date)" >> "$EVAL_DIR/metadata.txt"
echo "Results saved to: $EVAL_DIR"
