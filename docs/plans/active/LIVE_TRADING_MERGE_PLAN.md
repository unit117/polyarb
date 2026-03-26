# Live Trading Merge Plan

**Created:** 2026-03-23
**Purpose:** Compare Claude and GPT implementations of LIVE_TRADING_IMPLEMENTATION_PLAN.md and produce a single merged version on main.

## Source Worktrees

| Label | Path |
|-------|------|
| Claude | `/Users/unit117/Dev/polyarb/.claude/worktrees/lucid-kilby/` |
| GPT | `/Users/unit117/.codex/worktrees/65f6/polyarb` |

Both branch from `106f51a` (main HEAD). All changes are uncommitted local modifications.

---

## Summary Verdict

**GPT wins on architecture (~70/30).** Claude's implementation is functional but bundles too much logic into the coordinator and interleaves paper+live execution in the pipeline. GPT has better separation of concerns, idempotent reconciliation via `venue_fill_id`, explicit configurable intervals, and a richer dashboard status module.

**One critical bug unique to Claude:** missing `venue_fill_id` on `live_fills` means fills can be double-applied on reconciliation retry.

**One gap in GPT not in Claude:** GPT's tests for the coordinator cover only settlement; submission and kill-switch paths are untested.

---

## File-by-File Decision

| File | Take From | Reason |
|------|-----------|--------|
| `alembic/versions/014_live_audit_tables.py` | GPT | Cleaner constraint syntax, proper downgrade |
| `alembic/versions/015_live_fill_ids_and_status_check.py` | GPT only | `venue_fill_id` unique index + CHECK constraint; Claude has neither |
| `shared/models.py` | GPT | `token_id NOT NULL`, CHECK constraint, unique `venue_fill_id` index |
| `shared/config.py` | GPT | Adds `live_snapshot_interval_seconds`, `live_status_heartbeat_seconds`, `live_reconcile_interval_seconds`, `signature_type`, `funder` |
| `shared/events.py` | GPT | Distinguishes pub/sub channel from Redis key |
| `shared/live_runtime.py` | GPT only | Status/kill-switch helpers; Claude has no equivalent module |
| `services/simulator/state.py` | GPT only | Extracted `restore_portfolio()` with source filtering; Claude does this inline |
| `services/simulator/live_executor.py` | GPT | FAK order type, comprehensive `fetch_order_state()` with trade association fallback |
| `services/simulator/live_coordinator.py` | GPT | Stateless bundle receiver, explicit `publish_status()`, `settle_resolved_markets()` |
| `services/simulator/live_reconciler.py` | GPT | `ReconciledFill` dataclass, `normalize_live_order_status()` pure function, `loop_forever()` pattern |
| `services/simulator/main.py` | GPT | Explicit task loops, all phases wired, heartbeat, settlement extended for live |
| `services/simulator/pipeline.py` | GPT | `ValidatedExecutionBundle` dataclass, clean split between validation and execution |
| `services/dashboard/api/routes.py` | GPT | Redis-backed, no local executor ref |
| `services/dashboard/api/live_status.py` | GPT only | Heartbeat freshness, order/fill counts, configured vs enabled distinction |
| `services/dashboard/docs/.../paper-vs-live.tsx` | GPT | Updated to describe dry-run / submitted / reconciled distinction |
| `tests/unit/shared/test_live_runtime.py` | GPT only | |
| `tests/unit/dashboard/test_live_status.py` | GPT only | |
| `tests/unit/simulator/test_state_restore.py` | GPT only | |
| `tests/unit/simulator/test_live_reconciler.py` | GPT | More complete (pure function tests) |
| `tests/unit/simulator/test_live_coordinator.py` | GPT | Start here, then add missing cases (see below) |

---

## Bugs to Fix During Merge

### From Claude (do not carry forward)
1. `live_fills` has no `venue_fill_id` — fills double-applied on reconciliation retry
2. `live_orders.token_id` is nullable — orders without token IDs fail silently at submission
3. Paper + live execution interleaved in pipeline — if live submission fails, paper trade already committed
4. No `live_snapshot_interval_seconds` / `live_status_heartbeat_seconds` config — intervals hardcoded

### From GPT (fix during merge)
5. `live_orders.status` has no default in migration 014 — coordinator must always set it explicitly on insert
6. Kill-switch does not survive Redis restart — acceptable for v1 but should be documented in CLAUDE.md

---

## Missing Tests (Add After Merge)

These are gaps in **both** implementations that should be written as part of the merge:

| Test | File |
|------|------|
| `submit_validated_bundle()` dry-run path writes `status="dry_run"`, no portfolio mutation | `test_live_coordinator.py` |
| `submit_validated_bundle()` real path writes `status="submitted"`, calls executor | `test_live_coordinator.py` |
| Kill-switch blocks submission | `test_live_coordinator.py` |
| `token_id_for_outcome()` returns correct token, raises on missing | `test_live_coordinator.py` |
| Circuit breaker blocks submission when tripped | `test_live_coordinator.py` |
| `apply_reconciliation()` writes `LiveFill` + `PaperTrade(source="live")`, updates portfolio | `test_live_coordinator.py` |
| Reconciler `submitted→filled` full transition updates order status | `test_live_reconciler.py` |
| Reconciler `submitted→partially_filled→filled` two-step | `test_live_reconciler.py` |
| Reconciler `submitted→rejected` does not write fills | `test_live_reconciler.py` |
| Reconciler `submitted→cancelled` does not write fills | `test_live_reconciler.py` |
| Duplicate `venue_fill_id` is skipped (idempotency) | `test_live_reconciler.py` |

---

## Merge Steps

### Step 1 — Schema
- [ ] Copy `alembic/versions/014_live_audit_tables.py` from GPT worktree to main
- [ ] Copy `alembic/versions/015_live_fill_ids_and_status_check.py` from GPT worktree to main
- [ ] Verify both migrate and downgrade cleanly against a local test DB

### Step 2 — Shared modules
- [ ] Apply `shared/models.py` from GPT (LiveOrder, LiveFill with constraints)
- [ ] Apply `shared/config.py` from GPT (all interval settings + signature_type/funder)
- [ ] Apply `shared/events.py` from GPT (channel vs key distinction)
- [ ] Copy `shared/live_runtime.py` from GPT (new file)

### Step 3 — Simulator
- [ ] Copy `services/simulator/state.py` from GPT (new file)
- [ ] Apply `services/simulator/live_executor.py` from GPT (FAK, fetch_order_state)
- [ ] Copy `services/simulator/live_coordinator.py` from GPT (new file)
- [ ] Copy `services/simulator/live_reconciler.py` from GPT (new file)
- [ ] Apply `services/simulator/pipeline.py` from GPT (ValidatedExecutionBundle)
- [ ] Apply `services/simulator/main.py` from GPT (all loops wired)

### Step 4 — Dashboard
- [ ] Apply `services/dashboard/api/routes.py` from GPT
- [ ] Copy `services/dashboard/api/live_status.py` from GPT (new file)
- [ ] Apply `services/dashboard/docs/.../paper-vs-live.tsx` from GPT

### Step 5 — Tests
- [x] Copy all new test files from GPT
- [x] Write missing coordinator and reconciler tests listed above
- [x] Run full test suite: `pytest tests/unit/` — 283 passed

### Step 6 — Fix known bugs
- [ ] Verify `live_orders.status` is always set explicitly on insert (no silent null)
- [ ] Add note to CLAUDE.md: kill-switch is a runtime Redis flag, does not survive Redis restart without persistence

### Step 7 — Integration smoke test
- [ ] Bring up DB locally, run `alembic upgrade head`, verify tables and constraints
- [ ] Start simulator with `LIVE_TRADING_ENABLED=true LIVE_TRADING_DRY_RUN=true`
- [ ] Confirm `live_orders` rows appear with `status="dry_run"`
- [ ] Confirm `live_fills` is empty
- [ ] Confirm `portfolio_snapshots(source="live")` rows appear
- [ ] Confirm dashboard `/api/live/status` returns correct configured/enabled/dry_run fields

### Step 8 — Commit and deploy
- [ ] Single commit with message referencing LIVE_TRADING_IMPLEMENTATION_PLAN.md phases 1–6
- [ ] Deploy to NAS per CLAUDE.md deploy procedure
- [ ] Run NAS burn-in per plan: 24–48h with dry-run enabled

---

## Pre-Live Gate (before disabling dry-run)

Per LIVE_TRADING_IMPLEMENTATION_PLAN.md §Pre-Live Sizing Gate:
- [ ] Compute Kelly-sized positions at `LIVE_TRADING_BANKROLL`
- [ ] Confirm sizes exceed ~$50 notional (Polymarket fee floor)
- [ ] Confirm `LIVE_TRADING_MAX_POSITION_SIZE` is set sensibly
- [ ] Sign off before setting `LIVE_TRADING_DRY_RUN=false`
