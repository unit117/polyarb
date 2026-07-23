# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What This Is

PolyArb — combinatorial arbitrage detection and paper-trading system for Polymarket prediction markets. Detects mathematically provable arbitrage across correlated markets using Frank-Wolfe optimization (Dudik, Lahaie & Pennock 2016, arXiv:1606.02825).

## Current Status (as of 2026-07-23)

Live paper trading since 2026-03-20 on the NAS; +16.1% over the 99-day clean window as of Jul 20 (see the end of README "Backtesting"). The classifier default is `gpt-4.1-mini` but production has run **kimi-k2.6** (Moonshot, via `CLASSIFIER_BASE_URL`) since 2026-06-01 — first gold-set score 70.8%, below the March leaderboard's production tier; 73.5% of live trades are rule-based, so the classifier is not the bottleneck.

The July 2026 six-flaw remediation is complete through Phase 5 (tracked in `REMEDIATION_PLAN.md`, which is **gitignored** by the `*_PLAN.md` rule — local file + memory only):
- Safety gates: post-restart startup grace, per-pair exposure-opening flow cap ($100/7d, flip-aware), zero-edge/flow-cap rejections feed the frozen-pair cooldown, Redis-durable circuit-breaker state scoped per book.
- Classifier: bounded transient-only retries, failures never cached (225k poisoned cache rows purged), declarative per-model capability registry (`CLASSIFIER_MODEL_CAPABILITIES` .env override).
- Data capture: CLOB batch endpoints, per-outcome order books for paired markets, `market_trades` raw WS tape (~200–300k rows/day).
- Observability: daily Redis counters for every safety mechanism, `GET /api/metrics/observability`, ObservabilityPanel on the dashboard metrics tab.

Historical context: IMPROVEMENT_PLAN phases 1–6 complete (Mar 2026); E1 backtest complete — 489 days, -86.6% before 27 bug fixes, **+0.19%** after (gpt-4.1-mini baseline; Sonnet 4 scored +0.84%); E2 superseded; PMXT order-book replay tooling shipped (`scripts/pmxt_*.py`).

## Architecture

```
Ingestor → Detector → Optimizer → Simulator → Dashboard
   ↓          ↓          ↓           ↓          ↓
Markets    Pairs    Opportunities  Portfolio   Web UI
         (pgvector)  (Frank-Wolfe)  (VWAP)   (React+WS)
                         ↕
              Redis Event Bus (9 channels)
                         ↕
                    PostgreSQL (pgvector)
```

Seven Docker containers: postgres (pgvector), redis (appendonly, named volume), ingestor, detector, optimizer, simulator, dashboard. All Python services are async (asyncio + SQLAlchemy async + asyncpg). Services communicate via Redis pub/sub, not direct imports. Only `shared/` is imported across services.

Kalshi integration uses a custom RSA-SHA256 client (not pmxt SDK), with cross-platform pair matching via pgvector.

## Key Data & Datasets

**Jon Becker's dataset** (51GB) is downloaded on NAS at `/volume1/docker/data/prediction-market-analysis/`. Mounted into backtest containers at `/data/prediction-market-analysis/data`. Two scripts use it:
- `scripts/backtest_from_dataset.py` — bootstraps backtest DB from Parquet (default `--max-markets 5000`)
- `scripts/import_resolved_outcomes.py` — imports authoritative resolution outcomes

**Historical data source tiers** (for Polymarket):
1. Official APIs: CLOB `/prices-history` (max ~14-day chunks), Data API `/trades`
2. Becker dataset (what we use): pre-collected trade history + metadata, Parquet/DuckDB
3. Execution realism: pmxt archive (free hourly order book snapshots), PredictionData.dev (paid tick-level)

**Live capture posture** (since 2026-07-22 the ingestor preserves enough to backtest the live period from our own data):
- Midpoints via CLOB batch endpoints (`POST /midpoints`) for all verified-pair markets + top-N liquidity (the liquidity top-N is the *discovery set* and is never evicted by the cap — see `trim_snapshot_coverage`)
- Per-outcome L2 books (`POST /books`, top 10 levels, best-first) for paired markets — `FETCH_ORDER_BOOKS=true`, `MAX_CLOB_SNAPSHOTS=4000` on the NAS
- Raw WS trade tape in `market_trades` (price/size/side/event_ts, best-effort dedup)
- Retention pruning exists but is OFF (`SNAPSHOT_RETENTION_DAYS=0`); `price_snapshots` is 179GB+ and growing ~1.5GB/day — watch the dashboard Storage chips
- Known non-goals: WS `book` events unconsumed (REST cadence only); no Kalshi book capture; trade tape covers only the ≤3000 WS-subscribed tokens

## Commands

### Running Services (on NAS at $NAS_HOST)
```bash
# Deploy from local Mac to NAS (source .env.nas for $NAS_USER/$NAS_HOST/$NAS_PASS; use sshpass)
tar czf /tmp/polyarb.tar.gz --exclude='node_modules' --exclude='.git' --exclude='__pycache__' \
  --exclude='.env' --exclude='.env.nas' --exclude='pmxt_db' --exclude='*.tar.gz' --exclude='.claude' . && \
cat /tmp/polyarb.tar.gz | ssh $NAS_USER@$NAS_HOST "cd /volume1/docker/polyarb && cat > x.tar.gz && tar xzf x.tar.gz && rm x.tar.gz && find . -name '._*' -delete"

# Rebuild and restart a single service
ssh $NAS_USER@$NAS_HOST "cd /volume1/docker/polyarb && docker compose build SERVICE && docker compose up -d SERVICE"

# Rebuild all and restart
ssh $NAS_USER@$NAS_HOST "cd /volume1/docker/polyarb && docker compose build && docker compose up -d"

# View logs
ssh $NAS_USER@$NAS_HOST "cd /volume1/docker/polyarb && docker compose logs -f SERVICE"
```

After any deploy, check ALL five services for errors, not just the one changed.

### Backtest (runs on NAS via docker compose profile)
```bash
# Bootstrap from Becker dataset (preferred — authoritative outcomes)
docker compose run --rm backtest python -m scripts.backtest_from_dataset \
  --dataset-path /data/prediction-market-analysis/data --max-markets 5000

# Import resolved outcomes into existing backtest DB
docker compose run --rm backtest python -m scripts.import_resolved_outcomes

# Legacy: setup from live DB via dblink (fewer pairs, no authoritative outcomes)
docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest python -m scripts.backtest_setup

# Run backtest (use --authoritative for dataset-based settlement)
docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest python -m scripts.backtest --capital 10000 --authoritative
```

Note: the backtest does NOT model the newer live gates (flow cap, startup grace, zero-edge cooldown) — account for that before backtest-based parameter tuning.

### Database Migrations
```bash
# Create new migration (run inside any service container)
alembic revision --autogenerate -m "description"

# Apply migrations (done automatically on service start via entrypoint.sh;
# concurrent entrypoints are serialized by a pg advisory lock in alembic/env.py)
alembic upgrade head

# Check current revision
alembic current
```

### Tests (local)
```bash
# Needs Python >= 3.10 (redis-py 7.4 won't install on 3.9; use e.g. /opt/homebrew/bin/python3.12)
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-test.txt \
  -r services/detector/requirements.txt -r services/simulator/requirements.txt \
  -r services/optimizer/requirements.txt -r services/ingestor/requirements.txt
.venv/bin/python -m pytest tests/unit tests/integration -q
```

### Dashboard Frontend
```bash
cd services/dashboard/web && npm install && npm run build  # Built during Docker image build
```

## Key Patterns

**Service entry point pattern** (`services/*/main.py`):
```python
setup_logging(settings.log_level)
await init_db()
# Initialize clients, create pipeline
await asyncio.gather(periodic_loop(), event_loop(), ...)
```

**Database access** — always async sessions:
```python
async with SessionFactory() as session:
    result = await session.execute(select(Model).where(...))
```

**Redis events** — publish dicts, subscribe in event loops:
```python
await publish(redis, CHANNEL_NAME, {"key": "value"})
```

**Portfolio state** — restored from DB on restart. `cost_basis` and the per-pair flow ledger are rebuilt from trade history. When computing derived values around a mutation (e.g., exit PnL), always capture inputs before calling `execute_trade()`.

**Fail-open safety plumbing** — Redis-backed mechanisms (frozen cooldown, breaker state, metrics) swallow Redis failures and fall back to in-memory/no-op: they must never block trading or break the pipeline they protect. Follow this pattern for new mechanisms.

**Execution gates** (`services/simulator/validation.py`) — a trade must pass, in order: resolved-market check, positive edge (zero-edge rejections feed the cooldown), then per leg: snapshot freshness, startup grace (snapshot newer than boot during the first `SIMULATOR_STARTUP_GRACE_SECONDS`), frozen-price guard, VWAP + fee edge check, circuit breaker; and finally, once per bundle after all legs: per-pair flow cap (`MAX_PAIR_WEEKLY_FLOW`, flip-aware, exits exempt). When debugging "why didn't it trade", check these in order — the dashboard Observability panel counts each gate's rejections.

## Database Schema (19 migrations)

- **001**: `markets` (with pgvector `embedding` Vector(384)), `price_snapshots` (prices, midpoints, order_book JSONB)
- **002**: `market_pairs`, `arbitrage_opportunities`
- **003**: `paper_trades`, `portfolio_snapshots`
- **004**: `resolved_outcome`/`resolved_at` on markets; nullable `opportunity_id` on paper_trades
- **005**: `source` column (paper/live) on paper_trades + portfolio_snapshots
- **006**: `settled_trades` counter on portfolio_snapshots
- **007**: Opportunity uniqueness constraints
- **008**: `pending_at` timestamp on opportunities
- **009**: `expired_at` timestamp on opportunities
- **010**: `dependency_type` snapshot on opportunities
- **011**: `venue` column on markets (composite unique on `venue, polymarket_id`)
- **012**: `resolution_vectors` on market_pairs
- **013**: backfill `pending_at`
- **014**: live-order audit tables (`live_orders`, `live_fills`)
- **015**: live fill ids + status check
- **016**: `pair_classification_cache`
- **017**: `portfolio_cost_basis`
- **018**: `fee_rate_bps` on markets
- **019**: `market_trades` raw WS trade tape

## Configuration

All settings via pydantic-settings from `.env` (see `.env.example`; do not hardcode a count — it rots). Key groups: database, redis, APIs (OpenAI for embeddings, Gamma, CLOB), detector thresholds (similarity 0.82; classifier default `gpt-4.1-mini`, live runs kimi-k2.6 via `CLASSIFIER_BASE_URL`, per-model quirks in `services/detector/model_capabilities.py` overridable via `CLASSIFIER_MODEL_CAPABILITIES`), optimizer params (FW 200 iterations, 0.001 gap, 5s timeout), simulator (VWAP slippage, $10k capital, circuit breakers, startup grace, per-pair flow cap), ingestor capture (order books, trade tape, retention), Kalshi (disabled by default), live trading (disabled by default).

## Ports

- PostgreSQL: 5434 (host) → 5432 (container)
- Redis: 6380 (host) → 6379 (container)
- Dashboard: repo default 8080; the NAS `.env` overrides to **8081** (8080 is taken there)
- Dashboard (backtest): 8082

Ports 5432, 5433, 6379, 8080 are already in use on NAS — do not reassign.

## Planning Documents

- `REMEDIATION_PLAN.md` — July 2026 six-flaw remediation (LOCAL ONLY: `*_PLAN.md` is gitignored)
- `ECOSYSTEM_PLAN.md` — E1–E6 external integrations (E1 done, E2 superseded)
- `IMPROVEMENT_PLAN.md` — Phases 1–6 internal fixes (all complete)
- `E1_Backtest_Findings_Summary.md` — 27 bugs found/fixed, before/after results
- `BACKTEST_PLAN.md` — Backtest pipeline design
- `KALSHI_PLAN.md` — Cross-platform integration (complete)
- `SETTLEMENT_PLAN.md` — Authoritative settlement from dataset outcomes

## Gotchas

- The NAS is a **UGREEN DXP4800 Pro running UGOS (Debian 12)** — not a Synology; no DSM tooling. Reachable via Tailscale (`dxp4800pro-00d9`) when off the home LAN. Credentials in `.env.nas` (never committed).
- `scp` doesn't work on the NAS — use the tar-over-SSH pipe (or base64 for single files; `cat | ssh` eats stdin in loops).
- `price_snapshots` is **179GB+ with NO pure-timestamp index** — never filter it by timestamp alone (instant seq-scan). Bound queries by `market_id` (indexed with timestamp) or PK id ranges, and check `pg_stat_activity` for zombie scans after killing a slow query.
- `order_book` JSONB has TWO shapes forever: legacy rows hold one top-level `{bids, asks}` (the first outcome's book); new rows are keyed per outcome. Always read via `shared.pricing.select_outcome_book`. WS-written rows store JSON `null`, not SQL NULL — filter with `order_book::text NOT IN ('null', '{}')`.
- CLOB API `/prices-history` rejects intervals > ~14 days — must chunk requests
- Polymarket API returns prices as strings in JSONB — always `float()` cast
- Backtest DB created via dblink has no `alembic_version` — stamp before upgrading
- `alembic/env.py` takes a pg advisory lock and must `commit()` after acquiring it — an implicit SQLAlchemy transaction there once caused migrations to **roll back silently** while logging success
- If `npm install` fails with native module errors on macOS: `rm -rf node_modules package-lock.json && npm i`
- Becker dataset default `--max-markets 5000` only yields ~597 pairs — increase for broader coverage
- Pair verification was tightened after the E1 catastrophe: mutual_exclusion requires same event_id + no identical question text
- Kill switch (`polyarb:kill_switch`, shared across books) and cooldown/breaker state now survive restarts AND `docker compose down` (redis runs appendonly on the named volume `polyarb_redisdata`)
- Kimi (Moonshot direct) rejects any custom temperature with HTTP 400 — handled by the capability registry; fix future provider quirks via `CLASSIFIER_MODEL_CAPABILITIES` in `.env`, not code hotfixes on the NAS
