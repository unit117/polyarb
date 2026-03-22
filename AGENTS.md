# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What This Is

PolyArb — combinatorial arbitrage detection and paper-trading system for Polymarket prediction markets. Detects mathematically provable arbitrage across correlated markets using Frank-Wolfe optimization (Dudik, Lahaie & Pennock 2016, arXiv:1606.02825).

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

### Database Migrations
```bash
# Create new migration (run inside any service container)
alembic revision --autogenerate -m "description"

# Apply migrations (done automatically on service start via entrypoint.sh)
alembic upgrade head

# Check current revision
alembic current
```

### Backtest (runs on NAS via docker compose profile)
```bash
# Setup backtest DB (copies markets/pairs from live via dblink)
docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest python -m scripts.backtest_setup

# Backfill historical prices from CLOB API
docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest python -m scripts.backfill_history --max-markets 3000

# Run backtest
docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest python -m scripts.backtest --capital 10000
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

## Database Schema (5 migrations)

- **001**: `markets` (with pgvector `embedding` Vector(384)), `price_snapshots`
- **002**: `market_pairs`, `arbitrage_opportunities`
- **003**: `paper_trades`, `portfolio_snapshots`
- **004**: `resolved_outcome`/`resolved_at` on markets; nullable `opportunity_id` on paper_trades
- **005**: `source` column (paper/live) on paper_trades + portfolio_snapshots

## Configuration

All settings via pydantic-settings from `.env` (see `.env.example` for 52 settings). Key groups: database, redis, APIs (OpenAI, Gamma, CLOB), detector thresholds, optimizer params (FW iterations/gap/timeout), simulator (capital, fees, slippage), live trading (disabled by default).

## Ports

- PostgreSQL: 5434 (host) → 5432 (container)
- Redis: 6380 (host) → 6379 (container)
- Dashboard: 8081 (host) → 8080 (container)

Ports 5432, 5433, 6379, 8080 are already in use on NAS — do not reassign.

## Gotchas

- CLOB API `/prices-history` rejects intervals > ~14 days — must chunk requests
- Polymarket API returns prices as strings in JSONB — always `float()` cast
- `scp` doesn't work on the NAS Synology — use tar-over-SSH pipe
- Backtest DB created via dblink has no `alembic_version` — stamp before upgrading
- If `npm install` fails with native module errors on macOS: `rm -rf node_modules package-lock.json && npm i`
