# Bugs To Fix

## 1. ~~HIGH — `NOT IN` parameter ceiling in `sync_markets()`~~ FIXED

**Fixed in:** `services/ingestor/polling.py:175-188` — chunking with `STALE_CHUNK = 10_000`. Same fix applied to `kalshi_polling.py` and `ws_client.py`.

## 2. ~~HIGH — No backfill of `pending_at` in migration 008~~ FIXED

**Fixed in:** `alembic/versions/013_backfill_pending_at.py` — backfills `pending_at = timestamp` for all pre-existing pending rows.

## 3. MEDIUM — Trailing debounce can starve dashboard refresh

**File:** `services/dashboard/web/src/hooks/useDashboardData.ts:295-308`

Every WS event resets the 150ms timer. Sustained bursts postpone all refetches until traffic stops. Unlikely at current event rates but trivially avoidable.

**Fix:** Switch to leading+trailing debounce — fire immediately on first event, then coalesce for 150ms.
