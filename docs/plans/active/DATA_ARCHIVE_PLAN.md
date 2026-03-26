# PolyArb Data Archive And Live Audit Plan

## Summary
Build a new archival subsystem inside the existing PolyArb repo, with the NAS as the primary storage target, and keep the current app Postgres focused on operational state. The archive will capture raw market data needed for future self-hosted backtests, while a parallel live-audit path will make real orders/fills durable and reconstructable.

This plan does **not** create a separate project and does **not** add cloud replication in v1. It does make future backtests independent of third-party historical vendors for all data collected after deployment.

## Implementation Changes
### 1. Add an in-repo `archive` service
- Create a new service that writes append-only raw files to `/volume1/docker/polyarb-archive` mounted into the container.
- Archive Polymarket raw websocket messages for **all active synced tokens**, not just the current top-100 snapshot set.
- Archive market metadata changes and resolution events from the existing Redis/event flow.
- Add periodic order-book polling for a tracked subset:
  - all markets in detected pairs
  - all markets with open paper/live positions
  - all markets with open live orders
  - top 500 active markets by liquidity
- Store raw files as hourly rotated `jsonl.zst`, partitioned by `venue/dataset/date/hour`.
- Add an archive-state SQLite DB under the archive root for rotation checkpoints, compaction markers, and restart recovery. Raw payloads do not go into Postgres.

### 2. Add derived Parquet datasets for research/backtesting
- Add a compaction job in the same service that converts closed raw files into partitioned Parquet using DuckDB.
- Maintain separate datasets for:
  - `market_ws`
  - `book_snapshots`
  - `market_metadata`
  - `market_resolutions`
  - `live_orders`
  - `live_fills`
  - `live_portfolio`
- Keep raw files immutable after rotation; Parquet is the query layer for research and future backtest bootstrap.
- Add a new bootstrap script that loads a selected time range from Parquet into `polyarb_backtest`, populating `markets`, `price_snapshots`, and `order_book` fields on demand.

### 3. Close the live-trading persistence gap
- Wire `LiveExecutor` into the simulator runtime when `LIVE_TRADING_ENABLED=true`.
- Add durable normalized audit tables:
  - `live_orders` for order intent, submission, venue IDs, status transitions, raw venue responses
  - `live_fills` for fill-level executions and fees
- Continue using `paper_trades` and `portfolio_snapshots` as the dashboard-facing execution ledger, but make `source="live"` real:
  - write `paper_trades(source="live")` only for actual fills
  - write `portfolio_snapshots(source="live")` from the live portfolio state
- Persist dry-run activity to `live_orders` with explicit `dry_run` status, but do not materialize fake live fills into `paper_trades`.
- Add an order reconciler loop that polls nonterminal live orders every 5 seconds and records fills/cancels/rejections until terminal.

### 4. Tighten current operational data capture
- Keep the existing operational `price_snapshots` path unchanged for app behavior.
- Do not rely on `FETCH_ORDER_BOOKS` or `MAX_SNAPSHOT_MARKETS` for archival completeness; the archive service has its own coverage policy.
- Preserve Gamma-based Polymarket resolutions as the authoritative operational resolution source, while also archiving the raw resolution event stream.

## Public Interfaces And Types
- New env/config:
  - `ARCHIVE_ROOT=/archive`
  - `ARCHIVE_BOOK_TOP_MARKETS=500`
  - `ARCHIVE_BOOK_POLL_SECONDS=15`
  - `ARCHIVE_TOKEN_REFRESH_SECONDS=300`
  - `ARCHIVE_ROTATE_MINUTES=60`
  - `ARCHIVE_ENABLE_PARQUET_COMPACTION=true`
- New DB tables: `live_orders`, `live_fills`.
- Existing tables gain behavioral changes, not schema shape changes:
  - `paper_trades.source="live"` becomes a real persisted path
  - `portfolio_snapshots.source="live"` becomes a real persisted path

## Test Plan
- Unit tests for raw event envelopes, file rotation, partition naming, restart recovery, and Parquet compaction idempotence.
- Integration tests with mocked CLOB websocket and book endpoints verifying:
  - all active token subscriptions are archived
  - tracked-market book snapshots are written
  - compaction produces queryable Parquet without duplication
- Integration tests for live audit verifying:
  - dry-run orders persist to `live_orders`
  - real fills produce `live_fills` and `paper_trades(source="live")`
  - reconciler updates order states to terminal and writes portfolio snapshots with `source="live"`
- Acceptance scenario: restart the archive service mid-stream and confirm no corrupted files, no duplicate Parquet rows, and no loss beyond the in-memory flush buffer.

## Assumptions And Defaults
- Primary storage is NAS only in v1; no cloud mirror, no offsite backup, and no automatic pruning in v1.
- Archive root is `/volume1/docker/polyarb-archive` on the NAS.
- v1 targets a strong raw archive, not full market-microstructure completeness; it captures all active token WS traffic plus scoped book snapshots, not universal full-depth books for every market.
- Future self-hosted backtests will use Parquet as the historical source of truth and hydrate `polyarb_backtest` for selected windows rather than querying raw files directly.
