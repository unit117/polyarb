# Bugs To Fix

## 1. ~~HIGH — `NOT IN` parameter ceiling in `sync_markets()`~~ FIXED

**Fixed in:** `services/ingestor/polling.py:175-188` — chunking with `STALE_CHUNK = 10_000`. Same fix applied to `kalshi_polling.py` and `ws_client.py`.

## 2. ~~HIGH — No backfill of `pending_at` in migration 008~~ FIXED

**Fixed in:** `alembic/versions/013_backfill_pending_at.py` — backfills `pending_at = timestamp` for all pre-existing pending rows.

## 3. MEDIUM — Trailing debounce can starve dashboard refresh

**File:** `services/dashboard/web/src/hooks/useDashboardData.ts:295-308`

Every WS event resets the 150ms timer. Sustained bursts postpone all refetches until traffic stops. Unlikely at current event rates but trivially avoidable.

**Fix:** Switch to leading+trailing debounce — fire immediately on first event, then coalesce for 150ms.

## 4. HIGH — Simulator midpoint-fallback fills (`services/simulator/vwap.py`, `services/simulator/validation.py`) — OPEN

`compute_vwap()` returns `_midpoint_fill(midpoint ± 0.005)` whenever the per-outcome book is missing/empty, and `validation.py` hands it `trade.market_price` (the optimizer's detection-time price). WS-written `price_snapshots` carry `null` books, so 2,068 of 2,096 paper legs since 2026-07-23 took this path. Against the `market_trades` tape only 1% of SELL legs / 12% of BUY legs had a real print at our price within 5 min. Paper PnL is therefore mostly not executable (see `docs/paper-trading-findings-2026-08-21.md`).

**Fix:** reject the bundle when no fresh real book exists (counter + `no_book_skipped` log; midpoint fallback only behind an explicit opt-in default OFF); price from the fill-time snapshot; add a best-bid/ask spread guard (kills in-play sports phantom fills).

## 5. MEDIUM — Kelly sizing produces sub-minimum orders (`services/simulator/validation.py`, `services/simulator/live_executor.py`) — OPEN

`base_size = min(edge × 0.5, 0.25) × max_position_size($100)` → ~$1 bundles; 97% of legs since April are < 5 shares. Polymarket CLOB `minimum_order_size` is 5 shares and the live executor does not enforce it.

**Fix:** floor leg size at the venue minimum (or skip if the edge no longer clears `min_net_profit` at that size); size from book depth rather than half-Kelly × cap.
