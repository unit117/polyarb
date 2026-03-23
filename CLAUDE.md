# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What This Is

PolyArb — combinatorial arbitrage detection and paper-trading system for Polymarket prediction markets. Detects mathematically provable arbitrage across correlated markets using Frank-Wolfe optimization (Dudik, Lahaie & Pennock 2016, arXiv:1606.02825).

## Current Status (as of 2026-03-23)

IMPROVEMENT_PLAN phases 1–6 are all complete (deploy fixes, GPT-4.1-mini model switch, circuit breakers, WebSocket streaming, Kalshi cross-platform integration, monitoring/observability). ECOSYSTEM_PLAN phase E1 (historical dataset validation) is in progress; E2–E6 not started.

E1 backtest ran over 489 days (2024-09-24 → 2026-01-25) with $10k capital. Original run: -86.6% loss from invalid mutual_exclusion pairs. After 27 bug fixes across 5 buckets: +0.19% return. See `E1_Backtest_Findings_Summary.md` for details.

Live paper trading running since ~Mar 20, 2026 on NAS.

## Architecture

```
Ingestor → Detector → Optimizer → Simulator → Dashboard
   ↓          ↓          ↓           ↓          ↓
Markets    Pairs    Opportunities  Portfolio   Web UI
         (pgvector)  (Frank-Wolfe)  (VWAP)   (React+WS)
                         ↕
              Redis Event Bus (8 channels)
                         ↕
                    PostgreSQL (pgvector)
```

Seven Docker containers: postgres (pgvector), redis, ingestor, detector, optimizer, simulator, dashboard. All Python services are async (asyncio + SQLAlchemy async + asyncpg). Services communicate via Redis pub/sub, not direct imports. Only `shared/` is imported across services.

Kalshi integration uses a custom RSA-SHA256 client (not pmxt SDK), with cross-platform pair matching via pgvector.

## Key Data & Datasets

**Jon Becker's dataset** (51GB) is downloaded on NAS at `/volume1/docker/data/prediction-market-analysis/`. Mounted into backtest containers at `/data/prediction-market-analysis/data`. Two scripts use it:
- `scripts/backtest_from_dataset.py` — bootstraps backtest DB from Parquet (default `--max-markets 5000`)
- `scripts/import_resolved_outcomes.py` — imports authoritative resolution outcomes

**Historical data source tiers** (for Polymarket):
1. Official APIs: CLOB `/prices-history` (max ~14-day chunks), Data API `/trades`
2. Becker dataset (what we use): pre-collected trade history + metadata, Parquet/DuckDB
3. Execution realism: pmxt archive (free hourly order book snapshots), PredictionData.dev (paid tick-level)

**Live data collection gaps** — the ingestor currently does NOT preserve enough for self-sufficient future backtesting:
- `FETCH_ORDER_BOOKS=false` by default — no L2 order book depth stored
- `MAX_SNAPSHOT_MARKETS=100` — only top 100 by liquidity get price snapshots (53k+ markets exist)
- No individual trade records — WebSocket `last_trade_price` events are folded into snapshots and discarded
- To fix: enable order books, increase snapshot market count, add a `trades` table for raw trade records

## Commands

### Running Services (on NAS at 192.168.5.100)
```bash
# Deploy from local Mac to NAS
tar czf /tmp/polyarb.tar.gz --exclude='node_modules' --exclude='.git' --exclude='__pycache__' --exclude='.env' . && \
cat /tmp/polyarb.tar.gz | ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && cat > x.tar.gz && tar xzf x.tar.gz && rm x.tar.gz && find . -name '._*' -delete"

# Rebuild and restart a single service
ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && docker compose build SERVICE && docker compose up -d SERVICE"

# Rebuild all and restart
ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && docker compose build && docker compose up -d"

# View logs
ssh applecat@192.168.5.100 "cd /volume1/docker/polyarb && docker compose logs -f SERVICE"
```

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

### Database Migrations
```bash
# Create new migration (run inside any service container)
alembic revision --autogenerate -m "description"

# Apply migrations (done automatically on service start via entrypoint.sh)
alembic upgrade head

# Check current revision
alembic current
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

**Portfolio state** — restored from DB on restart. `cost_basis` rebuilt from full trade history. When computing derived values around a mutation (e.g., exit PnL), always capture inputs before calling `execute_trade()`.

## Database Schema (12 migrations)

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

## Configuration

All settings via pydantic-settings from `.env` (see `.env.example` for 69 settings). Key groups: database, redis, APIs (OpenAI, Gamma, CLOB), detector thresholds (similarity 0.82, GPT-4.1-mini classifier), optimizer params (FW 200 iterations, 0.001 gap, 5s timeout), simulator (VWAP slippage, $10k capital, circuit breakers), Kalshi (disabled by default), live trading (disabled by default).

## Ports

- PostgreSQL: 5434 (host) → 5432 (container)
- Redis: 6380 (host) → 6379 (container)
- Dashboard (live): 8081 (host) → 8080 (container)
- Dashboard (backtest): 8082

Ports 5432, 5433, 6379, 8080 are already in use on NAS — do not reassign.

## Planning Documents

- `ECOSYSTEM_PLAN.md` — E1–E6 external integrations (datasets, Kalshi, order book replay, parameter tuning)
- `IMPROVEMENT_PLAN.md` — Phases 1–6 internal fixes (all complete)
- `E1_Backtest_Findings_Summary.md` — 27 bugs found/fixed, before/after results
- `BACKTEST_PLAN.md` — Backtest pipeline design
- `KALSHI_PLAN.md` — Cross-platform integration (complete)
- `SETTLEMENT_PLAN.md` — Authoritative settlement from dataset outcomes

## Gotchas

- CLOB API `/prices-history` rejects intervals > ~14 days — must chunk requests
- Polymarket API returns prices as strings in JSONB — always `float()` cast
- `scp` doesn't work on the NAS Synology — use tar-over-SSH pipe
- Backtest DB created via dblink has no `alembic_version` — stamp before upgrading
- If `npm install` fails with native module errors on macOS: `rm -rf node_modules package-lock.json && npm i`
- Becker dataset default `--max-markets 5000` only yields ~597 pairs — increase for broader coverage
- Pair verification was tightened after E1 catastrophe: mutual_exclusion requires same event_id + no identical question text
- Only first outcome's order book is fetched even when `FETCH_ORDER_BOOKS=true`
- Live kill switch (`polyarb:live_kill_switch`) is stored in Redis — it does not survive a Redis restart unless RDB/AOF persistence is enabled. Must be manually re-set after infrastructure restarts if it was active.
