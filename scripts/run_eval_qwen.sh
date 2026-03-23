#!/bin/bash
set -uo pipefail

# Round 3: Qwen model evaluation via DashScope API
# Uses same template DB and backtest params as Round 2 for comparability
# Results saved to separate eval directory — does NOT touch Round 2 data

cd /volume1/docker/polyarb

START_DATE="2024-09-24"
END_DATE="2026-01-25"
CAPITAL=10000
COMMIT_SHA="696b935"  # same pinned commit as Round 2

# DashScope API (OpenAI-compatible endpoint, Singapore region)
DASHSCOPE_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:?Set DASHSCOPE_API_KEY env var before running}"

EVAL_DIR="/volume1/docker/polyarb/eval_results/r3_qwen_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVAL_DIR"
cat > "$EVAL_DIR/metadata.txt" << EOF
round: 3 (Qwen)
commit: $COMMIT_SHA
start: $START_DATE
end: $END_DATE
capital: $CAPITAL
mode: parallel
base_url: $DASHSCOPE_BASE_URL
models: qwen3-max, qwen3.5-122b-a10b
EOF

# DashScope model IDs
MODELS=("qwen3-max" "qwen3.5-122b-a10b")
NAMES=("qwen3max" "qwen35_122b")

# Step 1: Kill stale connections and clone per-model DBs from template
echo "=== Creating per-model databases ==="
docker compose exec -T postgres psql -U polyarb -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'polyarb_backtest' AND pid <> pg_backend_pid();" || true
sleep 2
for NAME in "${NAMES[@]}"; do
  DB="polyarb_bt_${NAME}"
  echo "Creating $DB..."
  docker compose exec -T postgres psql -U polyarb -d postgres -c "DROP DATABASE IF EXISTS ${DB};" 2>/dev/null || true
  docker compose exec -T postgres psql -U polyarb -d postgres -c "CREATE DATABASE ${DB} WITH TEMPLATE polyarb_backtest OWNER polyarb;"
  echo "  $DB created"
done
echo "=== All databases created ==="

# Step 2: Run each model in parallel (reclassify then backtest)
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
for i in ${!MODELS[@]}; do
  run_model "${MODELS[$i]}" "${NAMES[$i]}" "$EVAL_DIR" "$START_DATE" "$END_DATE" "$CAPITAL" "$DASHSCOPE_BASE_URL" "$DASHSCOPE_API_KEY" &
  PIDS+=($!)
  echo "Launched ${NAMES[$i]} (PID $!)"
  sleep 2  # stagger container starts
done

echo "=== Both Qwen models launched, waiting... ==="

# Wait for all and track failures
FAILED=0
for i in ${!PIDS[@]}; do
  if wait ${PIDS[$i]}; then
    echo "=== ${NAMES[$i]} completed OK ==="
  else
    echo "=== ${NAMES[$i]} FAILED ==="
    FAILED=$((FAILED + 1))
  fi
done

# Step 3: Cleanup per-model databases
echo "=== Cleaning up databases ==="
for NAME in "${NAMES[@]}"; do
  DB="polyarb_bt_${NAME}"
  docker compose exec -T postgres psql -U polyarb -d postgres -c "DROP DATABASE IF EXISTS ${DB};" 2>/dev/null || true
done

echo "=== ALL DONE ($FAILED failures) ==="
echo "Finished: $(date)" >> "$EVAL_DIR/metadata.txt"
echo "Results saved to: $EVAL_DIR"
