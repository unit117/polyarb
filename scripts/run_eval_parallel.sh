#!/bin/bash
set -uo pipefail

cd /volume1/docker/polyarb

START_DATE="2024-09-24"
END_DATE="2026-01-25"
CAPITAL=10000
COMMIT_SHA="696b935"  # pinned — no .git on NAS

EVAL_DIR="/volume1/docker/polyarb/eval_results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVAL_DIR"
cat > "$EVAL_DIR/metadata.txt" << EOF
commit: $COMMIT_SHA
start: $START_DATE
end: $END_DATE
capital: $CAPITAL
mode: parallel
EOF

MODELS=("openai/gpt-4.1-mini" "minimax/minimax-m2.7" "anthropic/claude-3.5-haiku" "anthropic/claude-sonnet-4" "google/gemini-2.5-flash" "deepseek/deepseek-chat")
NAMES=("gpt41mini" "m27" "haiku" "sonnet" "gemini" "deepseek")

# Step 1: Kill any stale connections to template DB, then clone per-model
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

  echo "=== START $NAME: $MODEL ==="

  docker compose run --rm -e POSTGRES_DB="$DB" backtest \
    python -m scripts.reclassify_pairs \
      --model "$MODEL" \
      --base-url https://openrouter.ai/api/v1 \
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
  run_model "${MODELS[$i]}" "${NAMES[$i]}" "$EVAL_DIR" "$START_DATE" "$END_DATE" "$CAPITAL" &
  PIDS+=($!)
  echo "Launched ${NAMES[$i]} (PID $!)"
  sleep 2  # stagger container starts slightly
done

echo "=== All 6 models launched, waiting... ==="

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
