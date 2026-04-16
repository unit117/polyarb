# PolyArb

Combinatorial arbitrage detection and paper-trading system for [Polymarket](https://polymarket.com) prediction markets. Detects mathematically provable arbitrage across correlated markets using Frank-Wolfe optimization ([Dudik, Lahaie & Pennock 2016](https://arxiv.org/abs/1606.02825)).

## Architecture

```
Ingestor → Detector → Optimizer → Simulator → Dashboard
   ↓          ↓          ↓           ↓          ↓
Markets    Pairs    Opportunities  Portfolio   Web UI
         (pgvector)  (Frank-Wolfe)  (VWAP)   (React+WS)
```

Seven Docker containers orchestrated via `docker-compose.yml`. All Python services are fully async (asyncio + SQLAlchemy async + asyncpg). Services communicate through Redis pub/sub — no direct imports between services. Only `shared/` is imported across service boundaries.

| Service | Description |
|---------|-------------|
| **Ingestor** | Polls Polymarket (Gamma + CLOB) and Kalshi APIs, stores markets and price snapshots, generates embeddings via OpenAI |
| **Detector** | Finds correlated market pairs using pgvector cosine similarity, classifies relationship types (implication, mutual exclusion, partition), builds constraint matrices |
| **Optimizer** | Runs Frank-Wolfe constrained optimization to find provable arbitrage opportunities with positive expected edge |
| **Simulator** | Paper-trades opportunities with VWAP slippage modeling, Kelly sizing, circuit breakers, and portfolio tracking |
| **Dashboard** | FastAPI backend + React frontend with real-time WebSocket streaming of portfolio, trades, and opportunities |
| **PostgreSQL** | pgvector-enabled Postgres 16 for markets, pairs, opportunities, trades, and embeddings |
| **Redis** | Event bus (8 pub/sub channels) for inter-service communication |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- An OpenAI API key (for embeddings)

### Setup

```bash
# Clone and configure
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY

# Start all services
docker compose up -d

# View logs
docker compose logs -f
```

The dashboard will be available at `http://localhost:8081`.

### Configuration

All settings are managed via environment variables in `.env` (see `.env.example` for all settings). Key groups:

| Group | Examples |
|-------|----------|
| Database | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| Redis | `REDIS_URL` |
| APIs | `OPENAI_API_KEY`, `GAMMA_API_BASE`, `CLOB_API_BASE` |
| Detector | `SIMILARITY_THRESHOLD`, `CLASSIFIER_MODEL`, `DETECTION_INTERVAL_SECONDS` |
| Optimizer | `FW_MAX_ITERATIONS`, `FW_GAP_TOLERANCE`, `OPTIMIZER_MIN_EDGE` |
| Simulator | `INITIAL_CAPITAL`, `MAX_POSITION_SIZE`, `SLIPPAGE_MODEL` |
| Circuit Breakers | `CB_MAX_DAILY_LOSS`, `CB_MAX_DRAWDOWN_PCT`, `CB_COOLDOWN_SECONDS` |
| Kalshi | `KALSHI_ENABLED`, `KALSHI_API_KEY` (off by default) |
| Live Trading | `LIVE_TRADING_ENABLED` (off by default, requires manual enable) |

## Database

PostgreSQL 16 with pgvector. Schema managed by Alembic (18 migrations, run automatically on service start via `entrypoint.sh`). Extensions: `vector` (pgvector), `dblink` (backtest setup only).

### Schema

```
markets                    price_snapshots           market_pairs
───────────────────        ─────────────────         ──────────────────
id              PK         id (BigInt)     PK        id              PK
polymarket_id   UQ(+venue) market_id       FK→markets market_a_id    FK→markets
venue           "polymarket" timestamp                market_b_id    FK→markets
question        Text       prices          JSONB     dependency_type
description     Text       order_book      JSONB     confidence      Float
outcomes        JSONB      midpoints       JSONB     constraint_matrix JSONB
token_ids       JSONB                                resolution_vectors JSONB
active          Bool                                 verified        Bool
embedding       Vector(384)                          detected_at
fee_rate_bps    Int                                  implication_direction
resolved_outcome                                     classification_cache JSONB
resolved_at
end_date, volume, liquidity
created_at, updated_at

arbitrage_opportunities    paper_trades              portfolio_snapshots
───────────────────────    ─────────────             ───────────────────
id              PK         id              PK        id              PK
pair_id         FK→pairs   opportunity_id  FK→opps   timestamp
timestamp                  market_id       FK→markets cash            Numeric
type                       outcome                   positions       JSONB
theoretical_profit         side (buy|sell)            total_value     Numeric
estimated_profit           size                      realized_pnl
optimal_trades  JSONB      entry_price               unrealized_pnl
fw_iterations              vwap_price                total_trades    Int
bregman_gap     Float      slippage                  settled_trades  Int
status          *          fees                      winning_trades  Int
pending_at                 executed_at               cost_basis      JSONB
                                                     source (paper|live)
expired_at                 status
dependency_type            source (paper|live)
                           venue

live_orders                live_fills
──────────────             ──────────────
id              PK         id              PK
opportunity_id  FK→opps    live_order_id   FK→live_orders
market_id       FK→markets market_id       FK→markets
outcome                    outcome
token_id                   side
side                       venue_fill_id   UQ
requested_size             fill_size       Numeric
requested_price            fill_price      Numeric
status          **         fees            Numeric
dry_run         Bool       filled_at
venue_order_id
submitted_at
error           Text

* opp status: detected → pending → optimized → filled | expired | skipped | unconverged
** order status: dry_run | submitted | filled | partially_filled | cancelled | rejected | expired | settled
```

### Key Constraints

- `(venue, polymarket_id)` — unique on markets
- `(market_a_id, market_b_id)` — unique on market_pairs
- `(pair_id)` — unique partial index on opportunities WHERE status IN (detected, pending, optimized, unconverged) — prevents duplicate in-flight opps
- All timestamps are `TIMESTAMPTZ`; all monetary values are `Numeric` for decimal precision

### Initialization

Each service runs `alembic upgrade head` on container start (via `entrypoint.sh`), then calls `init_db()` which ensures the pgvector extension exists. Sessions use `AsyncSession` with pool_size=5, max_overflow=10.

### Backtest DB

`scripts/backtest_setup.py` creates a separate `polyarb_backtest` database on the same Postgres instance, copies markets and pairs via dblink (avoids OOM on 39k+ markets with embeddings), then the backfill step populates historical price_snapshots from the CLOB API.

```bash
# Create a new migration
docker compose exec ingestor alembic revision --autogenerate -m "description"

# Check current revision
docker compose exec ingestor alembic current
```

### Migration History

| # | Description |
|---|-------------|
| 001 | Initial schema: markets (with pgvector), price_snapshots |
| 002 | market_pairs, arbitrage_opportunities |
| 003 | paper_trades, portfolio_snapshots |
| 004 | resolved_outcome/resolved_at on markets; nullable opportunity_id |
| 005 | source column (paper/live) on trades + snapshots |
| 006 | settled_trades counter on portfolio_snapshots |
| 007 | Partial unique index for in-flight opportunity dedup |
| 008 | pending_at timestamp on opportunities |
| 009 | expired_at timestamp on opportunities |
| 010 | dependency_type snapshot on opportunities (backfilled) |
| 011 | venue column on markets + trades; composite unique index |
| 012 | resolution_vectors on market_pairs |
| 013 | Backfill pending_at timestamps |
| 014 | live_orders and live_fills tables for live trading audit trail |
| 015 | live fill IDs and order status check constraint |
| 016 | Pair classification cache for detector LLM reuse |
| 017 | cost_basis JSONB column on portfolio_snapshots |
| 018 | fee_rate_bps column on markets |

## Backtesting

A full backtest pipeline replays historical data through the detector → optimizer → simulator stack. Uses Jon Becker's 51GB Polymarket dataset for authoritative market outcomes.

```bash
# 1. Bootstrap backtest DB from Becker dataset (Parquet)
docker compose run --rm backtest python -m scripts.backtest_from_dataset \
  --dataset-path /data/prediction-market-analysis/data --max-markets 5000

# 2. Import resolved outcomes for authoritative settlement
docker compose run --rm backtest python -m scripts.import_resolved_outcomes

# 3. Run backtest with authoritative settlement
docker compose run --rm -e POSTGRES_DB=polyarb_backtest backtest \
  python -m scripts.backtest --capital 10000 --authoritative

# 4. (Optional) View results in a dedicated dashboard
docker compose --profile backtest up -d dashboard-backtest
# → http://localhost:8082
```

E1 backtest ran over 489 days (2024-09-24 → 2026-01-25) with $10k capital. After 27 bug fixes: +1.72% return with Sonnet 4 classifier. See `E1_Backtest_Findings_Summary.md` for details.

Live paper trading has been running since March 20, 2026. Post-purge clean window (Apr 8–16) showed +4.4% over 8 days on a $9,031 base.

## Ports

| Service | Host | Container |
|---------|------|-----------|
| PostgreSQL | 5434 | 5432 |
| Redis | 6380 | 6379 |
| Dashboard | 8081 | 8080 |
| Dashboard (backtest) | 8082 | 8080 |

## Project Structure

```
├── services/
│   ├── ingestor/      # Market data ingestion + embedding
│   ├── detector/      # Pair detection + classification + constraints
│   ├── optimizer/     # Frank-Wolfe arbitrage optimization
│   ├── simulator/     # Paper trading + live trading engine
│   └── dashboard/     # FastAPI backend + React frontend
├── shared/            # Cross-service models, DB, events, config, circuit breaker
├── alembic/           # Database migrations (18 revisions)
├── scripts/           # Backtest, backfill, eval, and maintenance scripts
├── reports/           # Classifier evals, audit reports, performance analysis
├── tests/             # Unit + integration tests
└── docker-compose.yml
```

## Live Trading

Live trading is implemented but disabled by default (`LIVE_TRADING_ENABLED=false`). When enabled, the system executes real trades on Polymarket via the CLOB API.

- **Dry-run mode** — orders are recorded in `live_orders` with `dry_run=true` for audit without execution
- **Kill switch** — `polyarb:live_kill_switch` in Redis halts all live trading instantly
- **Audit trail** — all orders and fills are persisted in `live_orders`/`live_fills` tables
- **Order status tracking** — `dry_run → submitted → filled | partially_filled | cancelled | rejected | expired | settled`

## Classifier Evaluation

The detector's market-pair classifier has been evaluated across 6 models. Results on the E1 backtest (489 days, $10k capital):

| Model | Return | Sharpe | Cost/run |
|-------|--------|--------|----------|
| Sonnet 4 | +0.84% | 1.51 | $11.60 |
| GPT-4.1-mini | +0.19% | 0.35 | $0.08 |

See `reports/classifier_model_comparison_*.md` for full comparison.

## Key Concepts

**Market pairs** — Two Polymarket (or Kalshi) markets whose outcomes are logically related. Detected via embedding similarity, then classified by an LLM into relationship types: `implication`, `mutual_exclusion`, or `partition`.

**Constraint matrices** — Encode which outcome combinations are feasible. The optimizer uses these to find portfolios where expected value exceeds cost regardless of which outcomes occur.

**Frank-Wolfe optimization** — Finds the optimal allocation across market outcomes subject to the constraint matrix, computing a guaranteed minimum edge (worst-case profit).

**VWAP slippage** — The simulator models realistic execution using volume-weighted average pricing from order book data rather than naive mid-price fills.

**Circuit breakers** — Automatic safety limits: max daily loss, max drawdown percentage, max position per market, and cooldown periods after consecutive errors.

**Total-spread gating** — The optimizer applies its minimum edge threshold to the combined spread across all legs of an opportunity, not per-leg. This allows implication pairs where each leg has a small edge but the total spread is profitable after fees and slippage.

**Resolved-market filtering** — The detector automatically excludes pairs where either market has already resolved, preventing phantom arbitrage signals from fixed post-resolution prices.

## AI Readability

The codebase is **generally AI-friendly** — clean service boundaries, no circular imports, consistent patterns. Each service follows the same entry point pattern (`main.py` → `init_db()` → `asyncio.gather(loops)`). Communication via Redis pub/sub means an AI can reason about each service in isolation.

Strengths:
- Clear separation: services only share code through `shared/`
- Consistent async patterns throughout (SQLAlchemy async sessions, Redis pub/sub)
- Alembic migrations are linear (no branches) and self-documenting
- Config is centralized in one pydantic-settings class

Areas that slow AI comprehension:
- **JSONB columns** — `optimal_trades`, `constraint_matrix`, `outcomes`, `token_ids` have implicit schemas that only become clear by reading the code that writes them
- **Status state machines** — opportunity status flow (detected → pending → optimized → filled/expired/skipped) is implicit, not declared anywhere
- **Magic numbers** — scattered constants like Half-Kelly `0.5` multiplier, `0.005` fallback slippage, `MAX_EDGE = 0.20` cap lack inline explanation

## Code Complexity & Refactoring Opportunities

### File size overview

| File | Lines | Verdict |
|------|-------|---------|
| `services/detector/pipeline.py` | 965 | Deduplicate detection logic |
| `services/detector/classifier.py` | 868 | Fine — mostly rule-based classifiers |
| `services/dashboard/api/routes.py` | 840 | Split into route modules |
| `services/simulator/pipeline.py` | 776 | Extract validation from execution |
| `services/ingestor/polling.py` | 540 | Borderline — could extract snapshot logic |
| `services/detector/constraints.py` | 407 | Borderline |
| Everything else | <270 | Clean |

### Top refactoring targets

**1. `simulator/pipeline.py` — `_execute_pending()` is 268 lines**

Does validation (cash checks, edge re-check, circuit breaker) and execution (trade, portfolio update, event publish) in a single two-pass method with 4 levels of nesting. Split into `_validate_legs()` and `_execute_trades()`.

**2. `detector/pipeline.py` — duplicated detection logic**

`_run_once_inner()` (144 lines) and `_detect_cross_venue()` (137 lines) share nearly identical classify → constrain → verify → persist → publish flows. Extract a shared `_classify_and_persist_pair()` to eliminate ~100 lines of duplication.

**3. `dashboard/api/routes.py` — 12 endpoints in one file**

Mixes portfolio stats, opportunity/trade/pair queries, time-series metrics, correlation validation, and live trading controls. Split into `routes/portfolio.py`, `routes/metrics.py`, `routes/trading.py`.

**4. Duplicate utility function**

`_get_latest_prices()` is defined in both `detector/pipeline.py` and `optimizer/pipeline.py` — should live in `shared/`.

**5. Magic numbers to extract as config**

| Current | Location | Suggested config key |
|---------|----------|---------------------|
| `0.5` (Half-Kelly) | simulator/pipeline.py | `KELLY_FRACTION` |
| `0.005` (fallback slippage) | simulator/vwap.py | `FALLBACK_SLIPPAGE` |
| `0.20` (max edge cap) | optimizer/trades.py | `MAX_EDGE_CAP` |
| `0.15` (divergence threshold) | detector/constraints.py | `DIVERGENCE_THRESHOLD` |

### What's already clean

- **Optimizer module** — `frank_wolfe.py` (171 lines), `bregman.py` (64 lines), `ip_oracle.py` (100 lines), `trades.py` (~250 lines) — well-decomposed, single-responsibility
- **Shared module** — `models.py`, `db.py`, `events.py`, `config.py`, `circuit_breaker.py` — all under 310 lines, clear contracts
- **No circular imports** — services communicate via Redis, not cross-imports
- **Type hints** — mostly present on public functions, a few missing return types on internal helpers

## License

All rights reserved. Not open source.
