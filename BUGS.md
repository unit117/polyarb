# Bugs To Fix

## 1. HIGH — `NOT IN` parameter ceiling in `sync_markets()`

**File:** `services/ingestor/polling.py:162-170`

`~Market.polymarket_id.in_(seen_ids)` with ~37k IDs generates a `NOT IN ($1, ..., $37000)` clause. asyncpg's parameter limit is 32767 (`INT16_MAX`). Will crash once market count exceeds that.

**Fix:** Revert to the old pattern (blanket `SET active=False`, then re-activate in batches), or use a temp table / `ANY(array)` cast.

## 2. HIGH — No backfill of `pending_at` in migration 008

**File:** `alembic/versions/008_pending_at_timestamp.py`

The stale-pending sweeper (`services/simulator/pipeline.py:588`) requires `pending_at IS NOT NULL`. Pre-existing `pending` rows from before migration 008 have `pending_at = NULL` and are permanently invisible to the sweeper, blocking their pair.

**Fix:** Add to the migration: `UPDATE arbitrage_opportunities SET pending_at = timestamp WHERE status = 'pending' AND pending_at IS NULL`.

## 3. MEDIUM — Trailing debounce can starve dashboard refresh

**File:** `services/dashboard/web/src/hooks/useDashboardData.ts:295-308`

Every WS event resets the 150ms timer. Sustained bursts postpone all refetches until traffic stops. Unlikely at current event rates but trivially avoidable.

**Fix:** Switch to leading+trailing debounce — fire immediately on first event, then coalesce for 150ms.
