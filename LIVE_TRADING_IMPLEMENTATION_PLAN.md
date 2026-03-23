# Live Trading Implementation Plan

**Status:** Draft (reviewed 2026-03-23)
**Created:** 2026-03-23

## Goal

Make "live trading" a real, auditable execution path without changing the arbitrage strategy itself.

This plan is intentionally operational, not research-driven:

- keep the existing detect -> optimize -> simulate flow
- preserve paper trading as the default execution path
- only write `source="live"` rows when there are venue-confirmed live fills
- make the dashboard's Paper/Live toggle reflect real data instead of aspirational state

## Why This Plan Exists

The repo already contains partial live-trading scaffolding, but it is not wired end-to-end:

- `LiveExecutor` exists in `services/simulator/live_executor.py`
- live config exists in `shared/config.py`
- `paper_trades.source` and `portfolio_snapshots.source` exist
- the dashboard exposes `/api/live/*` endpoints

What is missing is the actual persistence and control plane.

As of 2026-03-23, the operational DB on the NAS contains only `paper` rows:

- `paper_trades`: `paper = 9464`, `live = 0`
- `portfolio_snapshots`: `paper = 37495`, `live = 0`

## Current Gaps

### 1. Runtime gap

`services/simulator/main.py` constructs only the paper `SimulatorPipeline`. There is no `LiveExecutor` instantiation and no live coordinator loop.

### 2. Persistence gap

The simulator writes `PaperTrade(...)` and `PortfolioSnapshot(...)` without explicitly setting `source`, so all rows fall back to the model default of `"paper"`.

### 3. Audit gap

There are no `live_orders` or `live_fills` tables, so submitted orders, partial fills, cancels, rejects, and dry-run activity are not durably reconstructable.

### 4. Dashboard/control-plane gap

The dashboard keeps an in-process `_live_executor` reference, but the dashboard and simulator are separate services. The current `/api/live/kill` and `/api/live/enable` endpoints cannot be the real control path for the simulator process.

### 5. Portfolio separation gap

Paper and live need independent restore, snapshot, risk, and PnL state. Reusing the current paper portfolio for live would corrupt both accounting and controls.

## Design Principles

### 1. Fill-driven live ledger

Use `paper_trades(source="live")` and `portfolio_snapshots(source="live")` as the dashboard-facing live ledger, but only for actual fills and actual live portfolio state.

Dry-run or merely submitted orders must not create fake live trades.

### 2. Separate paper and live state

Paper and live must have separate:

- portfolio restore paths
- portfolio snapshots
- circuit-breaker state
- kill switches
- trade counts and PnL

### 3. Shared validation, separate execution

Paper and live should reuse the same leg validation and sizing logic, but execution and persistence should diverge after a validated execution plan is built.

### 4. Dashboard must read durable state

The dashboard should derive live status from Redis and the database, not from a Python object reference inside the dashboard container.

## Scope

**v1 is Polymarket-only.** Kalshi live execution is a known extension point (the venue adapter pattern in Phase 3 supports it) but is not part of this rollout.

## Non-Goals

This plan does **not** include:

- strategy changes
- maker-order support
- conditional-pair enablement
- archival/raw market data capture work
- new research experiments
- Kalshi live execution (v2 — venue adapter pattern supports it)

Those can happen later. The immediate problem is that "live mode" is not real yet.

## Implementation Plan

## Phase 1 - Add Durable Live Audit Tables

### Objective

Persist live order intent and live fill outcomes independently of the paper ledger.

### Schema additions

Add two new tables via Alembic. Start minimal — expand columns in later migrations once real fills exist and debugging needs are concrete.

#### `live_orders` (v1 minimal)

- `id`
- `opportunity_id`
- `market_id`
- `outcome`
- `token_id`
- `side`
- `requested_size`
- `requested_price`
- `status` — `dry_run`, `submitted`, `filled`, `partially_filled`, `cancelled`, `rejected`, `expired`
- `dry_run` — boolean
- `venue_order_id` — nullable, set on submission
- `submitted_at`
- `error` — nullable

**Deferred to v2:** `venue`, `scaled_size`, `last_update_at`, `raw_request`, `raw_response`

#### `live_fills` (v1 minimal)

- `id`
- `live_order_id`
- `market_id`
- `outcome`
- `side`
- `fill_size`
- `fill_price`
- `fees`
- `filled_at`

**Deferred to v2:** `opportunity_id`, `venue`, `token_id`, `venue_fill_id`, `raw_response` (derivable from `live_order_id` join)

### Indexes

- `live_orders(status)` — reconciler queries nonterminal orders
- `live_orders(submitted_at desc)` — dashboard display
- `live_fills(live_order_id)` — join back to order
- `live_fills(filled_at desc)` — dashboard display

### Acceptance criteria

- dry-run and real submissions can be persisted without touching `paper_trades`
- order/fill history is queryable without reading logs

## Phase 2 - Introduce Separate Live Portfolio State

### Objective

Make live accounting independent from paper accounting while reusing the same portfolio math.

### Changes

- Generalize restore in `services/simulator/main.py` to support `source="paper"` and `source="live"`.
- Restore `PortfolioSnapshot` and replay `PaperTrade` rows filtered by `source`.
- Create a separate in-memory live `Portfolio`.
- Create a separate live `CircuitBreaker`.
- Explicitly set `source` on every `PaperTrade` and `PortfolioSnapshot` write path.

### Important rules

- `PaperTrade(source="paper")` remains the output of simulated execution.
- `PaperTrade(source="live")` is written only from confirmed live fills.
- `PortfolioSnapshot(source="live")` is written from the live portfolio state only.

### Periodic mark-to-market snapshots for live

The paper path has two snapshot triggers: event-driven (after every trade and settlement) and periodic (`_snapshot_loop` in `main.py`, every 300 seconds). The periodic loop re-fetches current prices and writes a `PortfolioSnapshot` so that `unrealized_pnl`, `total_value`, and drawdown stay fresh even when no trades are executing.

Live needs the same periodic loop. Without it, a quiet period with open live positions will show stale unrealized PnL and total value on the dashboard — the last snapshot would reflect prices at the time of the most recent fill, which could be hours or days old.

Add a `_live_snapshot_loop` in `main.py` that:

- Runs every 300 seconds (same cadence as paper, configurable via `LIVE_SNAPSHOT_INTERVAL_SECONDS`)
- Calls `live_coordinator.snapshot_portfolio()`, which fetches current prices, computes mark-to-market values on the live `Portfolio`, and writes `PortfolioSnapshot(source="live")`
- Is only started when `LIVE_TRADING_ENABLED=true`
- No-ops cleanly when the live portfolio has no positions (still writes a snapshot so the dashboard always has a recent timestamp)

This is in addition to the event-driven snapshots in Phase 4 (after fills) and Phase 4b (after settlement). The periodic loop is the backstop that keeps the dashboard current between events.

### Cutover rule

The live portfolio starts with its own configured bankroll (`LIVE_TRADING_BANKROLL`), **not** a migration of paper positions. Paper and live portfolios are independent from day one. There is no position transfer or balance reconciliation between them.

### Acceptance criteria

- restoring paper state ignores live rows
- restoring live state ignores paper rows
- dashboard queries using `source=paper` vs `source=live` return different results when test data is seeded
- `PortfolioSnapshot(source="live")` is written periodically even when no fills or settlements occur, keeping unrealized PnL current

## Phase 3 - Wire Live Execution Into the Simulator Runtime

### Objective

Extract a validated leg bundle from the current pipeline, then wire live execution behind `LIVE_TRADING_ENABLED`.

### Execution boundary refactor (formerly Phase 0)

Before wiring live, extract the reusable validation/sizing boundary from `pipeline.py`:

- Split `simulate_opportunity()` into internal steps that produce a **validated leg bundle** (dataclass/dict) containing: opportunity context, sized legs, validated prices, expected edge.
- Paper execution consumes this bundle via `_execute_paper_legs(bundle)`.
- Live execution consumes the same bundle via `LiveTradingCoordinator`.
- This separation is required so live execution does not fork a second copy of paper validation logic.

### LiveExecutor becomes a thin venue adapter

The existing `LiveExecutor` in `live_executor.py` has internal `daily_pnl`, `disabled`, and `scale_factor` state that duplicates the Redis-backed circuit breaker and live portfolio. Strip it to a thin venue adapter:

- **Keep:** CLOB client initialization, order submission (`create_and_post_order`)
- **Remove:** internal `daily_pnl`, `disabled` flag, `scale_factor`, `min_edge`, `bankroll` — these are now owned by the live `Portfolio`, `CircuitBreaker`, and coordinator respectively
- **Live sizing** comes from the live portfolio's Kelly fraction, not from scaling paper sizes

### Changes

- Extract validated leg bundle from `pipeline.py` as described above.
- Instantiate the venue adapter in `services/simulator/main.py` when live trading is enabled.
- Add a `LiveTradingCoordinator` responsible for:
  - consuming validated leg bundles
  - mapping `Market.outcomes` -> `Market.token_ids`
  - creating `live_orders` rows
  - submitting orders through the venue adapter
  - handling dry-run vs submitted paths
- Keep paper execution and live execution logically separate after validation.

### Dry-run behavior

When `LIVE_TRADING_DRY_RUN=true`:

- write `live_orders` with `status="dry_run"`
- do **not** write `paper_trades(source="live")`
- do **not** mutate the live portfolio

### Real submission behavior

When `LIVE_TRADING_DRY_RUN=false`:

- create `live_orders` rows on submission
- do not write live ledger rows yet
- wait for reconciliation before mutating live portfolio

### Acceptance criteria

- simulator starts cleanly with live disabled
- simulator starts cleanly with live enabled + dry-run
- dry-run produces durable `live_orders` rows only

## Phase 4 - Add Live Order Reconciliation

### Objective

Move the live ledger from intent-based to fill-based.

### Changes

- Add a reconciler inside the simulator service.
- **Preferred:** Use the venue's private WebSocket for order/fill status updates, if the venue client supports it cleanly. Note: the repo's existing WS infra is public market-data WS, not authenticated private order WS — do not assume it can be reused as-is.
- **Required fallback:** Poll nonterminal `live_orders` every 5 seconds via REST API. This is the v1 default until private WS is proven reliable.
- Update order status until terminal:
  - `submitted`
  - `partially_filled`
  - `filled`
  - `cancelled`
  - `rejected`
  - `expired`
- On each actual fill:
  - write `live_fills`
  - apply the fill to the live `Portfolio`
  - write `PaperTrade(source="live")`
- After any portfolio change:
  - write `PortfolioSnapshot(source="live")`

Note: these are *event-driven* snapshots — they fire on each fill. The *periodic* mark-to-market snapshot loop (defined in Phase 2) runs independently on a timer to keep unrealized PnL fresh between fills.

### Important rule

The live portfolio must be mutated from reconciled fills, not from optimistic submit responses.

### Acceptance criteria

- partial fills are represented correctly
- cancelled/rejected orders do not create fake live trades
- live snapshots reflect real fill state only
- unrealized PnL stays current between fills via the periodic snapshot loop from Phase 2

## Phase 4b - Settle Live Positions on Market Resolution

### Objective

Close open live positions when their underlying markets resolve, crediting the live portfolio and writing audit records. This is distinct from the Phase 4 reconciler, which tracks *order* fills — settlement happens without any order being placed.

### Why this is separate from Phase 4

On Polymarket, market resolution is automatic and on-chain. Winning shares become redeemable for $1; losing shares go to $0. No exit order is submitted, so the Phase 4 reconciler (which polls for order status) will never see a settlement event. The system needs a parallel path that detects resolution and updates the live ledger accordingly.

### How paper settlement already works

The paper path solves this with `settle_resolved_markets()` in `pipeline.py`, which:

1. Collects market IDs from open positions
2. Queries for resolved markets (`Market.resolved_outcome IS NOT NULL`)
3. Calls `Portfolio.close_position(key, 1.0 or 0.0)` for each position
4. Writes `PaperTrade(side="SETTLE")` rows
5. Feeds losses into the circuit breaker
6. Snapshots the portfolio

The live path needs the same logic, but writes to the live portfolio and live ledger instead.

### Changes

#### 1. Add `settle_resolved_markets()` on the live coordinator

`LiveTradingCoordinator` (introduced in Phase 3) gets a `settle_resolved_markets()` method that mirrors `SimulatorPipeline._settle_resolved_markets_inner()` but operates on the live `Portfolio` instance from Phase 2. For each resolved market with open live positions:

- Call `live_portfolio.close_position(key, settlement_price)` where `settlement_price` is `1.0` for the winning outcome, `0.0` for losers
- Write a `live_fills` row with `fill_price` of 1.0 or 0.0 and `fees` of 0 (redemption is feeless on Polymarket)
- Write a corresponding `live_orders` row with `status="settled"` and `dry_run=false` (no venue order ID, since no order was placed)
- Write `PaperTrade(source="live", side="SETTLE")` for the dashboard ledger
- Feed losses into the live circuit breaker
- Write `PortfolioSnapshot(source="live")`

No new resolution detection logic is needed — the ingestor already publishes `CHANNEL_MARKET_RESOLVED` events (price inference + Gamma API confirmation).

#### 2. Add `"settled"` to the `live_orders.status` enum

This distinguishes venue-driven settlement from order-driven fills. Settlement rows have no `venue_order_id`.

#### 3. Wire live settlement into `main.py`

The existing paper settlement runs in two loops in `services/simulator/main.py`:

- `_settlement_loop` (line 227): calls `pipeline.settle_resolved_markets()` every 120 seconds
- `_resolution_event_loop` (line 237): calls `pipeline.settle_resolved_markets()` immediately on each `CHANNEL_MARKET_RESOLVED` event

Both loops must be extended to also call `live_coordinator.settle_resolved_markets()` when `LIVE_TRADING_ENABLED` is true. The concrete change:

```python
async def _settlement_loop(pipeline, live_coordinator, interval):
    while True:
        try:
            await pipeline.settle_resolved_markets()
            if live_coordinator:
                await live_coordinator.settle_resolved_markets()
        except Exception:
            logger.exception("settlement_loop_error")
        await asyncio.sleep(interval)

async def _resolution_event_loop(pipeline, live_coordinator, redis):
    async for event in subscribe(redis, CHANNEL_MARKET_RESOLVED):
        market_id = event.get("market_id")
        if market_id:
            logger.info("triggered_by_resolution", market_id=market_id)
            try:
                await pipeline.settle_resolved_markets()
                if live_coordinator:
                    await live_coordinator.settle_resolved_markets()
            except Exception:
                logger.exception("resolution_settlement_error", market_id=market_id)
```

`live_coordinator` is `None` when `LIVE_TRADING_ENABLED=false`, so the guard is just a null check — no separate feature flag test needed in the loop body.

This is **not** guarded by `LIVE_TRADING_DRY_RUN`. Dry-run orders never create live portfolio positions (Phase 3 is explicit about this), so `live_coordinator.settle_resolved_markets()` will no-op naturally if the live portfolio is empty.

#### 4. Confirm redemption via venue balance check (v2 extension)

In v1, trust the Gamma API resolution signal. In v2, after settling, poll the CLOB API balance endpoint to verify that the on-chain redemption actually credited the expected USDC. Log a warning if the expected payout doesn't match within a tolerance. This is a verification step, not a gating step — the ledger updates from the resolution signal regardless.

### What about positions entered during dry-run that resolve later?

Dry-run orders do not create live portfolio positions (Phase 3 is explicit about this). So there are never "dry-run live positions" that need settlement. If live trading transitions from dry-run to real while paper-only positions exist, those remain in the paper portfolio — the cutover rule from Phase 2 says there is no position transfer between paper and live.

### Edge cases

- **Partial resolution:** Some Polymarket markets resolve individual outcomes at different times (e.g., multi-outcome markets). The settlement logic must handle per-outcome resolution, not assume all outcomes resolve simultaneously. The existing `Market.resolved_outcome` field stores a single winning outcome — for multi-outcome markets, each outcome's market row resolves independently, so this works.

- **Resolution reversal:** Extremely rare, but Polymarket has reversed resolutions before. The system should log a warning if a market that was previously settled has `resolved_outcome` cleared, but should not automatically re-open closed positions. Manual intervention is appropriate for this case.

- **Concurrent settlement and new orders:** The execution lock from the paper pipeline (which serializes `settle_resolved_markets` with `simulate_opportunity`) must also cover the live portfolio. The live coordinator should hold a separate lock, but if both portfolios can hold positions in the same market, both settlement methods should be called under the same resolution event.

### Acceptance criteria

- When a market resolves with open live positions, the live portfolio reflects the correct payout (1.0 for winners, 0.0 for losers)
- `live_orders` contains a `status="settled"` row with no `venue_order_id`
- `live_fills` contains the settlement fill at the correct price
- `PaperTrade(source="live", side="SETTLE")` is written for dashboard visibility
- `PortfolioSnapshot(source="live")` is updated after settlement
- Live circuit breaker records settlement losses
- Paper settlement continues to work independently and is not affected
- Empty live portfolio (dry-run mode, or no live positions in the resolved market) produces no writes and no errors

## Phase 5 - Replace the Current Live Control Plane

### Objective

Make dashboard controls work across service boundaries.

### Changes

- Remove the assumption that the dashboard can directly hold a simulator-side executor object.
- Replace dashboard live control with Redis-backed state.

### Recommended control keys

- `polyarb:live_kill_switch`
- `polyarb:live_status`

### Dashboard API behavior

`/api/live/status` should read:

- configuration from `shared.config`
- runtime activity from Redis or DB-backed heartbeat
- durable execution stats from `live_orders`, `live_fills`, and `portfolio_snapshots(source="live")`

`/api/live/kill` and `/api/live/enable` should:

- set/clear the live-specific Redis key
- not depend on a local Python object reference

### Note on existing kill switch

The current `polyarb:kill_switch` is a global breaker used by paper trading too. Keep it as the global emergency brake. Add a live-specific kill switch rather than overloading the current one.

### Acceptance criteria

- dashboard and simulator work correctly as separate containers
- live status remains correct after either service restarts
- live kill/enable works without dashboard-local state

## Phase 6 - Dashboard and Docs Alignment

### Objective

Make the UI and docs match reality.

### Changes

- Update dashboard stats and trade views to surface live audit data when `source=live`.
- Ensure empty live views show "no live fills yet" rather than implying broken data.
- Update `services/dashboard/docs/src/articles/trading/paper-vs-live.tsx` to distinguish:
  - dry-run orders
  - submitted live orders
  - reconciled live fills
- Document that live ledger rows are fill-driven, not intent-driven.

### Acceptance criteria

- Paper/Live toggle is meaningful
- docs no longer claim functionality that does not exist

## Files Expected To Change

### New files

- `alembic/versions/NNN_live_audit_tables.py`
- `services/simulator/live_coordinator.py`
- `services/simulator/live_reconciler.py`

### Existing files

- `shared/models.py`
- `shared/config.py`
- `shared/events.py`
- `services/simulator/main.py`
- `services/simulator/pipeline.py`
- `services/simulator/live_executor.py`
- `services/dashboard/api/routes.py`
- `services/dashboard/api/main.py`
- `services/dashboard/docs/src/articles/trading/paper-vs-live.tsx`

## Test Plan

### Unit tests

- outcome -> token ID mapping
- dry-run order persistence
- restore filtered by `source`
- live portfolio snapshot writes (event-driven and periodic)
- periodic live snapshot loop writes `PortfolioSnapshot(source="live")` with current mark-to-market even when no fills occur
- reconciler transitions for:
  - submitted -> filled
  - submitted -> partially_filled -> filled
  - submitted -> rejected
  - submitted -> cancelled
- live settlement:
  - winning position pays out at 1.0, losing at 0.0
  - settlement writes `live_orders(status="settled")` with no venue_order_id
  - settlement writes `live_fills` at correct price with zero fees
  - settlement writes `PaperTrade(source="live", side="SETTLE")`
  - empty live portfolio no-ops on resolution event
  - circuit breaker records settlement losses

### Integration tests

- simulator with live disabled
- simulator with live enabled + dry-run
- simulator with mocked live fills
- live settlement triggered by `CHANNEL_MARKET_RESOLVED` event updates live portfolio and writes audit records
- paper and live settlement run independently on the same resolution event without interfering
- dashboard `/api/live/status` reading durable state
- dashboard kill/enable working via Redis keys

### Acceptance test on NAS

1. Deploy schema and runtime changes with `LIVE_TRADING_ENABLED=true` and `LIVE_TRADING_DRY_RUN=true`
2. Run for 24-48 hours
3. Verify:
   - `live_orders` populated
   - `live_fills` empty in dry-run
   - `paper_trades(source="live") = 0`
   - `portfolio_snapshots(source="live") = 0`
4. Turn off dry-run with a tiny bankroll
5. Verify:
   - live fills create `live_fills`
   - live fills create `paper_trades(source="live")`
   - live snapshots update independently from paper snapshots
   - `portfolio_snapshots(source="live")` timestamps advance every ~5 minutes even during quiet periods (periodic mark-to-market)
   - when a market resolves with open live positions, `PaperTrade(source="live", side="SETTLE")` rows appear and the live portfolio's `realized_pnl` updates

## Rollout Order

1. Phase 1 schema (includes `"settled"` in `live_orders.status` enum)
2. Phase 2 source-aware restore/snapshot
3. Phase 3 execution boundary refactor + live runtime wiring in dry-run mode
4. Phase 5 control-plane fix
5. Phase 4 reconciler and fill-driven ledger
6. Phase 4b live settlement wiring (shares resolution detection with paper path)
7. Phase 6 dashboard/docs cleanup
8. NAS dry-run burn-in (24-48h)
9. **Sizing viability gate** (see below)
10. Tiny-capital live pilot

## Pre-Live Sizing Gate

Before any non-dry-run pilot, validate that position sizes are viable for real execution:

- Compute the Kelly-sized positions the system would produce at the live bankroll level
- Compare against venue minimums (Polymarket: ~$1 notional, but fee floors make anything under ~$50 uneconomical)
- If positions are consistently below viable thresholds, the pilot cannot proceed — sizing parameters or bankroll must be adjusted first

This is a **deployment gate**, not an architectural blocker. It does not affect phases 1-6, dry-run burn-in, or the audit/control-plane work. But it must be passed before real money flows.

## Explicit Recommendation

Do **not** change the trading method before this plan is complete.

The highest-value work is not a new strategy. It is making live mode:

- real
- separated from paper state
- durable
- reconciled
- auditable

Only after this is in place should the project spend time on maker orders, strategy variants, or further research-driven trading changes.
