# Phase 4 Code Inspection Report

**Date:** 2026-03-21 (updated with post-fix review and GPT cross-check)
**Scope:** WebSocket streaming (Phase 4) and all downstream bug fixes — 783 lines across 5 files
**Files inspected:**

- `services/ingestor/ws_client.py` (481 lines)
- `services/ingestor/polling.py` (380 lines)
- `services/detector/pipeline.py` (418 lines)
- `services/detector/main.py` (113 lines)
- `services/simulator/pipeline.py` (500 lines)
- `alembic/versions/007_opportunity_uniqueness.py`

**Post-inspection fixes applied:**
- `_seed_last_known_prices()` now handles markets with no prior DB snapshot by seeding `_reconnect_pending` from `_get_market_outcomes()` (token map lookup), preventing partial WS-only snapshots.
- Commit `a9a0a1b` fixed stale reconnect markets being inserted into Postgres.
- `_seed_last_known_prices` DB-seeded path now uses token map as source of truth for expected outcomes (commit `25eed15`).
- Cold-start guard added in `_flush_snapshots`: skips markets whose merged snapshot doesn't cover all expected outcomes (commit `25eed15`).
- Trade events deferred until after `session.commit()` in simulator (commit `25eed15`).
- IntegrityError on opportunity INSERT now caught per-pair instead of aborting the batch (commit `25eed15`).
- Stale pending sweeper (`_revert_stale_pending`) with 5min cutoff + `pending_at` column (commit `6c9debf`, migration `008`).
- Reconnect-pending lifecycle logging: DEBUG on clear, WARN after 60s stuck (commit `01e951f`).
- Flush loop exponential backoff on persistent DB errors (commit `01e951f`).
- Channel payload schemas documented in `shared/events.py` (commit `01e951f`).
- **Polling `CHANNEL_SNAPSHOT_CREATED` now includes `source` and `market_ids`** — fixes GPT P1 finding where graceful-degradation rescan path was dead when WS was down.

**Cross-checked by:** GPT review rounds 1 & 2 (confirmed `a9a0a1b` fix, identified cold-start gap + polling fallback gap)

---

## 1. WS Client Data Integrity (`ws_client.py`)

### 1.1 Reconnect Lifecycle

**Current behavior:** On reconnect (line 420–422), the client clears `_last_known_prices`, `_pending_snapshots`, and `_reconnect_pending` before calling `_connect()`. The `_reconnect_pending` dict is then populated lazily during `_seed_last_known_prices()` when the first flush needs a DB seed for a market.

**Finding — RISK: Race between reconnect clear and in-progress flush.**
When `run()` reaches line 420 and clears `_reconnect_pending`, there may be a `_flush_snapshots` coroutine still running from the previous connection's `asyncio.create_task()` (line 428). The `finally` block (lines 433–444) cancels the flush task, but cancellation is cooperative — if the flush is mid-`await session.execute()`, the cancellation won't take effect until the next yield point. During that window, the flush could write stale data using the now-cleared `_last_known_prices`. In practice this is low risk because the finally block awaits the cancellation, but there's a theoretical TOCTOU gap if the DB write completes before cancellation propagates.

**Recommendation:** Add a generation counter or epoch that the flush loop checks before writing. If the epoch has advanced (reconnect happened), discard the batch.

### 1.2 Per-Outcome Reconnect Tracking

**Current behavior:** `_mark_outcome_refreshed()` (line 370) removes outcomes from `_reconnect_pending[market_id]` as WS events arrive. Once all outcomes are refreshed, the market is removed from the dict and its snapshots flow to DB.

**Finding — BUG RISK: Markets with >2 outcomes (DB-seeded path).**
When a market HAS a prior DB snapshot, `_seed_last_known_prices()` (line 244) still populates `_reconnect_pending[market_id]` with `set(prices.keys())` — the keys from the last snapshot, not the canonical outcome list. If the DB snapshot has 2 outcomes (e.g., "Yes"/"No") but the market actually has 3 (multi-option question), the tracker will clear after seeing only 2 WS updates, allowing the 3rd outcome through with a stale price. Conversely, if the DB has an old outcome name that's been renamed, the set will never clear — that market stays suppressed forever.

**Partially addressed:** The no-prior-snapshot path (line 249) now correctly uses `_get_market_outcomes()` from the token map. But the DB-seeded path still trusts snapshot keys.

**Recommendation:** Use `_get_market_outcomes()` (or `Market.outcomes`) as the source of truth for BOTH paths — DB-seeded and unseeded. The DB snapshot provides the initial price values for `_last_known_prices`, but the set of outcome names to track should come from the token map.

### 1.3 Snapshot Merging / Flush Logic

**Current behavior:** `_flush_snapshots()` (line 253) runs every `buffer_seconds` (default 2s). It copies `_pending_snapshots`, clears it, seeds any unseen markets from DB, merges WS updates over `_last_known_prices`, and writes to DB.

**Original finding — CORRECTNESS: First-ever snapshot for a brand new market.**
If a market had no prior `PriceSnapshot` in the DB, `_seed_last_known_prices` would leave `_last_known_prices[market_id]` empty, causing partial snapshots to hit the DB.

**Status: FIXED.** `_seed_last_known_prices()` (line 245–251) now handles the no-prior-snapshot case by populating `_reconnect_pending` from `_get_market_outcomes()` (which derives outcomes from the token map). This blocks the market from being flushed to DB until all outcomes have been seen via WS.

**Residual finding — COLD-START GAP (GPT cross-check, P2).**
The fix relies on `_token_map` being populated before the first flush. On startup, WS and polling launch concurrently (`services/ingestor/main.py:57`). If a market becomes WS-eligible before its first polling snapshot lands AND `_get_market_outcomes()` returns an empty set (e.g., `_token_map` not yet built), the market won't be added to `_reconnect_pending` at all — the `if expected:` guard on line 250 skips it. The partial WS data then flows to DB unchecked. This is a narrow window (only affects markets with no DB history where the token map build hasn't completed), but there's no automated test coverage for it.

**Recommendation:** Either ensure `_build_token_map()` completes before the flush loop starts (it currently does — called at line 406 in `run()` before `_connect()`), or add a defensive check in `_flush_snapshots`: if a market has no entry in `_last_known_prices` AND no entry in `_reconnect_pending` after seeding, skip it. Also add an integration test for the cold-start/unseeded-market case.

### 1.4 Subscription Drift

**Current behavior:** `update_subscriptions()` (line 136) diffs against `_subscribed_tokens` and sends subscribe/unsubscribe messages. The `_token_map` is rebuilt separately in `_build_token_map()`, called on reconnect (line 464) and during `poll_once()` (line 346 of polling.py).

**Finding — RISK: Token map and subscription set can diverge.**
`update_subscriptions()` modifies `_subscribed_tokens` but does NOT update `_token_map`. If a new market is added and its tokens get subscribed, but `_build_token_map` hasn't run yet, WS events for those tokens will be silently dropped by `_handle_price_change()` (line 333: `mapping = self._token_map.get(asset_id)` returns None). The events are lost — there's no retry or buffering.

**Recommendation:** Either call `_build_token_map()` inside `update_subscriptions()`, or buffer unknown token IDs in a small queue that gets processed when the token map next refreshes.

### 1.5 Graceful Degradation

**Current behavior:** `polling.py` line 375 checks `self._ws_client.connected` and falls back to 30s polling when WS is down.

**Finding — GAP: No price coverage during reconnect backoff.**
After a WS disconnect, exponential backoff (line 449–452) can delay reconnection up to 60 seconds. Meanwhile, `connected` is already `False` (line 447), so polling runs at 30s. But there's a window during the backoff where neither WS nor polling is feeding prices — the first fast poll hasn't happened yet because `poll_once()` sleeps *after* completing work (line 380). The actual gap depends on where the poller is in its sleep cycle. Worst case: up to 30s with no fresh prices.

**Status:** Low severity — the system was already running on 300s polling before Phase 4, so a 30s gap is an improvement. Noted for awareness.

---

## 2. Detector Concurrency (`pipeline.py` + `main.py`)

### 2.1 Detection Lock

**Current behavior:** `_detection_lock` (line 41) is an `asyncio.Lock` that serializes `run_once()`. Both the periodic loop and the market-sync event loop call `run_once()`, which acquires the lock.

**Finding — PERFORMANCE: LLM classification holds the lock.**
Inside `_run_once_inner()`, the LLM call at line 93–98 (`classify_pair()`) is awaited while `_detection_lock` is held. If classification takes 5–10 seconds per pair (typical for GPT-4.1-mini), and there are 20 candidates, the lock is held for minutes. During this time, all snapshot-triggered rescans queue behind it — but they use `_rescan_lock` (line 40), which is separate. **The snapshot rescan path (`rescan_by_market_ids`) is NOT blocked by `_detection_lock`**, which is correct. However, a market-sync event arriving during a long classification run will block until the run completes, potentially causing a backlog.

**Status:** Working as designed. The lock prevents duplicate classification work, which is more important than latency.

### 2.2 Reactive Rescan Logic (`rescan_by_market_ids`)

**Current behavior:** Line 268–394. Fetches verified pairs involving the given market IDs, loads in-flight opportunities, then either creates new opps, refreshes existing ones, or skips pending ones.

**Finding — CORRECTNESS: The in-flight opp query may miss duplicates.**
Line 303–314 builds `in_flight_opps` as a dict keyed by `pair_id`. If two in-flight opportunities exist for the same pair (which the unique index in migration 007 should prevent), only the last one wins. The unique index is partial — it covers `('detected', 'pending', 'optimized', 'unconverged')` — so this is correctly prevented at the DB level.

**Finding — EDGE CASE: Detected opp gets its profit refreshed but not re-emitted.**
Line 344–367: When `existing_opp.status == "detected"`, the profit is refreshed (line 349–351) but no event is published. This is intentional (the optimizer hasn't run yet), but if the optimizer already *tried* and the opp was `detected` because of a concurrent reset, the optimizer won't know to retry until its next sweep. This is a minor latency issue, not a correctness bug.

### 2.3 DB-Before-Redis Ordering

**Current behavior:** All three methods (`_run_once_inner`, `_rescan_existing_pairs`, `rescan_by_market_ids`) collect events in `deferred_events` lists and publish them after `session.commit()`.

**Finding — VERIFIED CORRECT.** Every code path follows the pattern: accumulate events → `await session.commit()` → publish loop. There are no early returns between a `session.add()` and the commit that skip the publish. The `_rescan_lock` ensures `_rescan_existing_pairs` and `rescan_by_market_ids` don't interleave, so there's no risk of one committing while the other is mid-publish.

**Finding — MINOR: Trade execution publishes before commit.**
In `simulator/pipeline.py` line 232–244, `CHANNEL_TRADE_EXECUTED` is published *inside* the `for trade in opp.optimal_trades["trades"]` loop, before the final `session.commit()` at line 253. If a later trade fails and the session rolls back, the earlier trade events are already published but the rows don't exist. Subscribers reading these trade IDs will get nothing.

**Recommendation:** Defer trade execution events the same way the detector does — collect them in a list and publish after commit.

### 2.4 Migration 007 Unique Index

**Current behavior:** Partial unique index on `(pair_id)` where status in `('detected', 'pending', 'optimized', 'unconverged')`.

**Finding — CORRECT but no conflict handling in code.** The detector creates opportunities with `session.add()` + `session.flush()` (line 375–376 in `rescan_by_market_ids`). If a race condition causes a duplicate, this will raise `IntegrityError`. The error propagates up to `_snapshot_rescan_loop` in `main.py` (line 106) which catches `Exception` and logs it. The entire batch of pairs for that rescan interval is lost. The system recovers on the next interval, but legitimate non-duplicate opportunities in the same batch are also dropped.

**Recommendation:** Wrap the opportunity insert in a `try/except IntegrityError` and skip just that pair instead of failing the whole batch. Alternatively, use `INSERT ... ON CONFLICT DO UPDATE` for opportunity creation.

---

## 3. Simulator Race Guards (`simulator/pipeline.py`)

### 3.1 Pending Status Try/Finally

**Current behavior:** `_simulate_opportunity_inner()` (line 57) sets `opp.status = "pending"` in one transaction (line 71–72), then calls `_execute_pending()` in a try/except (line 74–95). On exception, it reverts `pending → optimized`.

**Finding — RISK: Revert uses a new session that can fail independently.**
The revert at line 83–89 opens a new session and checks `opp.status == "pending"` before reverting. If the DB is down (the reason `_execute_pending` failed), this revert also fails, and the exception at line 90–94 logs it but re-raises the original. The opportunity stays `pending` forever. The only recovery path is a manual DB update or a cleanup sweep.

**Finding — MISSING: No cleanup sweep for stranded pending opps.**
There's no background task that periodically checks for opportunities stuck in `pending` for more than N minutes and reverts them. If the simulator restarts, `process_pending()` (line 456) only queries `optimized`/`unconverged` — pending ones are invisible.

**Recommendation:** Add a periodic cleanup: any opportunity that's been `pending` for >5 minutes should be reverted to `optimized`.

### 3.2 Cross-Service Status Reads (No Row Locking)

**Current behavior:** In `_execute_pending()` (line 99), the simulator reads the opportunity with `session.get()`, which does a simple SELECT. Meanwhile, `rescan_by_market_ids` in the detector can be reading and modifying the same opportunity.

**Finding — RACE CONDITION: No row-level locking.**
The detector's `rescan_by_market_ids` (line 346) checks `existing_opp.status == "pending"` to decide whether to skip. But without `SELECT ... FOR UPDATE`, the detector could read the status as `optimized` (before the simulator's commit at line 72), start modifying it, and then the simulator's commit goes through — now both services think they own the opportunity.

In practice, the `_in_flight` set (line 45–55) prevents the simulator from processing the same opportunity concurrently within one instance, and the `_rescan_lock` serializes detector rescans. But the cross-service race between detector and simulator is still theoretically possible if the timing is tight.

**Recommendation:** Use `SELECT ... FOR UPDATE SKIP LOCKED` in the simulator when reading opportunities to execute, ensuring the detector can't modify them concurrently.

### 3.3 Trade Event Publishing Before Commit

(Covered in section 2.3 above.) `CHANNEL_TRADE_EXECUTED` events are published inside the trade loop before the final `session.commit()`. This is inconsistent with the detector's deferred-publish pattern.

---

## 4. Integration-Level Concerns

### 4.1 Redis Channel Contracts

**Channels used by Phase 4:**

| Channel | Publisher | Subscriber | Payload |
|---------|-----------|------------|---------|
| `CHANNEL_SNAPSHOT_CREATED` | ws_client, polling | detector `_snapshot_rescan_loop` | `{count, source?, market_ids?}` |
| `CHANNEL_MARKET_RESOLVED` | ws_client, polling | simulator | `{market_id, resolved_outcome, source, price?}` |
| `CHANNEL_ARBITRAGE_FOUND` | detector | optimizer, simulator | `{opportunity_id, pair_id, type, theoretical_profit}` |
| `CHANNEL_TRADE_EXECUTED` | simulator | dashboard | `{trade_id, opportunity_id, market_id, ...}` |

**Original finding — INCONSISTENT: `CHANNEL_SNAPSHOT_CREATED` payload differs by source.**
The polling path published `{"count": N}` with no `source` or `market_ids`, while the WS path included both. The detector's `_snapshot_rescan_loop` reads `market_ids` from the event, so polling-originated snapshots never triggered reactive rescans — making graceful degradation ineffective for already-known pairs.

**Status: FIXED.**
- Polling now publishes `{count, source: "polling", market_ids: [...]}` matching the WS schema.
- `shared/events.py` schema doc updated to reflect the uniform payload.
- This was flagged as P1 by GPT cross-check: when WS is down, the detector's rescan path was dead because `event.get("market_ids", [])` always returned `[]` for polling events.

### 4.2 Error Propagation

**Finding — WS flush errors are swallowed.**
`_flush_snapshots()` line 326 catches all exceptions and logs them, but continues the loop. If the DB is persistently unavailable, the flush loop will log errors every 2 seconds indefinitely while silently dropping all price data. There's no circuit breaker, no backoff, and no alert escalation.

**Finding — WS listen errors cause reconnect.**
`_listen()` (line 378) is called from `run()` inside a try block. Any exception in the listen loop (including `websockets.ConnectionClosed`) triggers the reconnect path with exponential backoff. This is correct.

**Finding — Detector errors are isolated per trigger.**
Each of the three detector triggers (periodic, event, snapshot) has its own try/except (lines 65, 77, 106 in main.py). An error in one doesn't affect the others. This is correct.

### 4.3 Logging and Observability

**Finding — GOOD: Key state transitions are logged.**
Reconnect events (`ws_disconnected`), subscription updates (`ws_subscribed`/`ws_unsubscribed`), snapshot flushes (`ws_snapshots_flushed` with `stale_suppressed` count), and detection cycles are all logged at INFO level.

**Finding — MISSING: No logging for reconnect-pending state.**
When a market enters `_reconnect_pending` (during seeding) and when it exits (all outcomes refreshed), there's no log entry. If markets get stuck in pending forever (due to the outcome-name mismatch bug in 1.2), there's no way to detect it from logs alone.

**Recommendation:** Add DEBUG-level logging in `_mark_outcome_refreshed()` when a market is fully cleared from `_reconnect_pending`, and a periodic WARN if any market has been pending for >60 seconds.

**Finding — MISSING: No metric for flush-to-DB latency.**
The time between a WS event arriving and the snapshot being committed to DB is invisible. For arb detection latency, this is a key metric.

---

## 5. Summary of Issues by Severity

### Fixed

- ~~**Partial snapshots for brand-new markets** (§1.3)~~ — `_seed_last_known_prices` now blocks unseeded markets via `_reconnect_pending` using token-map outcomes (commit `769d7df`).
- ~~**Stale reconnect DB inserts** (commit `a9a0a1b`)~~ — Confirmed fixed by GPT review.
- ~~**Stranded pending opportunities** (§3.1)~~ — Added `_revert_stale_pending` sweeper with 5min cutoff (commit `6c9debf`).
- ~~**IntegrityError drops entire rescan batch** (§2.4)~~ — Wrapped opportunity INSERT in per-pair `try/except IntegrityError` (commit `25eed15`).
- ~~**Reconnect-pending DB-seeded path uses snapshot keys** (§1.2)~~ — Now uses token map as source of truth for expected outcomes, falls back to snapshot keys only if token map has no entry (commit `25eed15`).
- ~~**Cold-start gap for unseeded markets** (§1.3 residual)~~ — Added defensive check in `_flush_snapshots`: skip markets whose merged snapshot doesn't cover all expected outcomes from token map (commit `25eed15`).
- ~~**Trade events published before commit** (§2.3 / §3.3)~~ — Deferred `CHANNEL_TRADE_EXECUTED` events until after `session.commit()` (commit `25eed15`).
- ~~**Polling fallback rescan dead when WS down** (GPT P1)~~ — Polling `CHANNEL_SNAPSHOT_CREATED` now includes `source: "polling"` and `market_ids: [...]`, so the detector's `_snapshot_rescan_loop` can rescan affected pairs during graceful degradation. Schema doc in `shared/events.py` updated to match.
- ~~**Inconsistent CHANNEL_SNAPSHOT_CREATED payload schema** (§4.1)~~ — Both WS and polling now publish uniform `{count, source, market_ids}`. Documented in `shared/events.py`.

### Medium (accepted risk)

5. **Token map / subscription set divergence** (§1.4) — WS events for newly subscribed markets are silently dropped until next token map rebuild. Accepted: `poll_once()` already calls `_build_token_map()` before `update_subscriptions()`, so the window is bounded by poll interval.
7. **No row-level locking on opportunity status** (§3.2) — Detector and simulator can theoretically race on the same row. Accepted: the two-phase pending approach handles all observed interference patterns correctly without `FOR UPDATE`.

### Low (observability / maintainability)

- ~~**No logging for reconnect-pending lifecycle** (§4.3)~~ — Added DEBUG log on market fully refreshed, WARN after 60s stuck (commit `01e951f`).
- ~~**Flush loop has no backoff on persistent DB errors** (§4.2)~~ — Added exponential backoff up to 30s with consecutive error counter (commit `01e951f`).
10. **No flush-to-DB latency metric** (§4.3) — Deferred: requires metrics infrastructure.
12. **No integration test for cold-start/unseeded-market path** (§1.3 residual) — Deferred: requires test harness.
