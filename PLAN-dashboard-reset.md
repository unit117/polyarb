# Dashboard Reset & Chart Overhaul Plan

**Status as of 2026-03-22: Steps 1-2 COMPLETE.** Steps 3-8 pending (lower priority, partially covered by MetricsPanel).

**Context changes since plan was written (2026-03-21):**
- Phase 6 metrics endpoints are now live + `MetricsPanel.tsx` exists with funnel, dep-type table, duration histogram, hourly timeseries — some of the analytics originally envisioned for Chart View 3 are partially covered here
- Kalshi venue badges and cross-platform UI are implemented
- StatsBar already shows Unrealized/Realized/Total PnL split (not just flat counters)
- `source` filter (paper/live) exists on `/stats`, `/trades`, `/portfolio/history` endpoints
- Portfolio purge happened 2026-03-21 ~15:02 UTC — 1,799 PURGE trades recorded, counters reset

## 1. Timestamp Filter — Post-Reset Stats

### Problem
After purging contaminated positions, `paper_trades` still contains pre-fix trades. The StatsBar's "Trades" count includes all historical trades (including PURGE). The portfolio snapshot counters were reset by the purge, so win rate and PnL values from snapshots are correct — but trade counts from `/stats` are inflated.

### Approach
Add a `reset_timestamp` marker and filter all dashboard queries to only show post-reset data. Old data stays in DB for auditing.

### Implementation

**A. Mark the reset point**
- Add `SIMULATOR_RESET_EPOCH` to `.env` / `shared/config.py` (ISO timestamp, e.g. `2026-03-21T15:02:00Z`)
- Default: `None` (no filter, backwards compatible)

**B. Backend query filters (`services/dashboard/api/routes.py`)**

| Endpoint | Current Query | Add Filter |
|---|---|---|
| `GET /stats` → total_trades | `COUNT(*) FROM paper_trades` (with `source` filter) | `AND executed_at > reset_epoch` |
| `GET /stats` → portfolio | Latest `portfolio_snapshots` | Already OK (snapshots were cleared by purge) |
| `GET /trades` | `ORDER BY executed_at DESC` (with `source` filter) | `AND executed_at > reset_epoch` |
| `GET /portfolio/history` | `WHERE timestamp >= (now - hours)` (with `source` filter) | `AND timestamp > reset_epoch` |
| `GET /opportunities` | No change needed | Opportunities are reference data — keep all |
| `GET /pairs` | No change needed | Pairs are reference data — keep all |

**C. StatsBar — already improved**
- StatsBar now shows Unrealized/Realized/Total PnL split with trend arrows
- Win rate computed from `winning_trades / settled_trades` in portfolio snapshot (correctly reset by purge)
- Only the raw "Trades" count from `/stats` is inflated — this is fixed by the query filter above

**D. Files to change**
- `shared/config.py` — add `simulator_reset_epoch: datetime | None = None`
- `.env` / `.env.example` — add `SIMULATOR_RESET_EPOCH=2026-03-21T15:02:00Z`
- `services/dashboard/api/routes.py` — filter trades + stats queries
- No frontend changes needed

---

## 2. Chart Area Overhaul

### Current State
- `PnlChart.tsx`: single Recharts `AreaChart` with 2 series (portfolio value green area, unrealized PnL blue dashed area)
- Has `initialCapital` ReferenceLine at $10,000 with dashed gray line
- Custom tooltip shows Value + Unrealized PnL with percentage
- Shows "No portfolio data yet. Waiting for first trades..." when `history.length === 0`
- Backend `/portfolio/history` returns: `timestamp, cash, total_value, realized_pnl, unrealized_pnl, total_trades`
- Frontend ignores `cash` and `realized_pnl` from history (only uses `total_value` and `unrealized_pnl`)
- **Note:** `MetricsPanel.tsx` already exists as a separate tab with funnel, dep-type table, duration histogram, and hourly timeseries — some overlap with planned Views 2 & 3

### Design: 3-View Tabbed Chart Panel

Replace the single PnlChart with a tabbed panel: **Equity** (default) | **Execution** | **Opportunities**

Small pill-style tab selector in the top-right of the chart panel (like the Paper/Live toggle in the header).

---

### View 1: Equity (default)

**Type:** Recharts `ComposedChart` — stacked areas + lines

**Series (all from existing `/portfolio/history` data):**

| Series | Type | Color | Data Field |
|---|---|---|---|
| Portfolio Value | Area (primary) | Green fill (#22c55e, 20% opacity) | `total_value` |
| Cash | Line (dashed) | Gray (#6b7280) | `cash` (already returned by API, unused by frontend) |
| Realized PnL | Step line | Cyan (#06b6d4) | `realized_pnl` (already returned by API, unused by frontend) |
| Unrealized PnL | Area (subtle) | Blue fill (#3b82f6, 10% opacity) | `unrealized_pnl` |
| Initial Capital | ReferenceLine | Dim white dashed | `$10,000` constant |

**Tooltip:** Show all 4 values + total PnL % at hover point.

**Event markers (new — requires backend work):**
- Small dots/ticks on the x-axis at trade execution times
- Data source: overlay trade timestamps from `/trades` onto the chart timeline
- Implementation: frontend fetches trades list (already has it via `useDashboardData`), plots `executed_at` timestamps as `ReferenceDot` markers on the equity line
- Color-code: green dot for profitable opportunity, red for loss (requires knowing opportunity-level PnL — can derive from grouped trades)

**Backend changes:** None — all data already available. Frontend just needs to use `cash` and `realized_pnl` from history response.

---

### View 2: Execution

**Purpose:** Visualize trade execution quality — are we getting good fills?

**Charts (2 side-by-side or stacked):**

**A. Slippage Over Time**
- Type: `ScatterChart` or `BarChart`
- X: trade `executed_at`
- Y: `slippage` (decimal, e.g. 0.02 = 2%)
- Color: size-proportional (larger trades = darker dots)
- Data source: `/trades` endpoint (already fetched)
- Reference line at 0 (no slippage)

**B. Cumulative Fees**
- Type: `AreaChart`
- X: trade `executed_at`
- Y: running sum of `fees`
- Data source: `/trades` — compute cumulative sum client-side
- Shows total fee drag on the portfolio over time

**Backend changes:** None — slippage and fees already in trade response.

---

### View 3: Opportunities

**Purpose:** Visualize detection quality — is the optimizer finding real edges?

**Note:** `MetricsPanel.tsx` already covers some of this territory (funnel, dep-type hit rates, duration histogram, hourly activity table). Consider whether these scatter charts add enough value beyond what MetricsPanel already shows, or if this view should be deprioritized.

**Charts (2 side-by-side or stacked):**

**A. Estimated vs Theoretical Profit**
- Type: `ScatterChart`
- X: `theoretical_profit`
- Y: `estimated_profit`
- Each dot = one opportunity
- 45° reference line (estimated = theoretical means no fee/slippage drag)
- Color by `status` (simulated = green, detected = gray, unconverged = red)
- Data source: `/opportunities` (already fetched)

**B. Optimizer Convergence**
- Type: `ScatterChart`
- X: `fw_iterations`
- Y: `bregman_gap`
- Smaller gap + fewer iterations = better convergence
- Color by `dependency_type`
- Data source: `/opportunities`

**Backend changes:** None — all fields already in opportunity response.

---

### Empty State (history.length === 0 AND no trades)

When there's truly no data yet (fresh deploy, not post-reset), show a **System Pulse** view instead of "Waiting for first trades":

**Layout:** 3 compact cards in a row

| Card | Data Source | Shows |
|---|---|---|
| Pipeline Activity | WebSocket events (already received) | Live count of events per channel in last 5 min. "Ingestor: 142 markets polled, Detector: 38 pairs analyzed, Optimizer: 12 opportunities evaluated" |
| Pair Quality | `/pairs` (confidence field) | Mini histogram — 5 buckets of pair confidence (0.7-0.8, 0.8-0.85, 0.85-0.9, 0.9-0.95, 0.95+). Shows detection quality at a glance |
| Top Opportunities | `/opportunities` (top 3 by estimated_profit) | 3 small cards with pair names + estimated profit. Clickable → opens detail drawer |

**Implementation:** New `SystemPulse.tsx` component rendered by the chart panel when `history.length === 0`.

**WebSocket event counting:** `useDashboardData` already receives all `polyarb:*` events. Add a simple counter map (`{ [channel]: count }`) with a 5-minute sliding window. No backend changes.

---

## 3. Implementation Order

| Step | Scope | Files | Backend Change? | Status |
|---|---|---|---|---|
| 1 | Reset timestamp filter | `config.py`, `routes.py`, `.env` | Yes (query filters) | ✅ Done |
| 2 | Equity chart upgrade | `PnlChart.tsx` (5 series + tooltip) | No | ✅ Done |
| 3 | Tab container | New `ChartPanel.tsx` wrapping 3 views | No | Pending |
| 4 | Execution view | New `ExecutionChart.tsx` | No | Pending |
| 5 | Opportunities view | New `OpportunitiesChart.tsx` | No | Pending (low — MetricsPanel overlap) |
| 6 | System pulse empty state | New `SystemPulse.tsx` | No | Pending |
| 7 | Event counter in hook | `useDashboardData.ts` | No | Pending |
| 8 | Trade markers on equity | `PnlChart.tsx` overlay | No | Pending |

Steps 1-2 complete. Steps 3-8 are incremental improvements (some overlap with MetricsPanel).

---

## 4. No New Backend Endpoints Needed

Everything above uses data already returned by existing endpoints:
- `cash` from `/portfolio/history` — returned but ignored by frontend
- `realized_pnl` from `/portfolio/history` — returned but ignored by frontend
- `slippage`, `fees` from `/trades` — already displayed in table, just need charting
- `theoretical_profit`, `estimated_profit`, `fw_iterations`, `bregman_gap` from `/opportunities` — already in table
- `confidence` from `/pairs` — already in table
- WebSocket events — already forwarded to frontend
- `/metrics/*` endpoints (timeseries, funnel, by-dependency-type, duration) — **already exist and are consumed by MetricsPanel.tsx**

The only backend change is the reset timestamp filter on queries (Step 1).

---

## 5. Revised Priority Assessment

Given that MetricsPanel already covers the analytics use cases (funnel, dep-type breakdown, duration, hourly timeseries), the remaining high-value items are:

1. **Step 1 — Reset timestamp filter** (HIGH) — fixes inflated trade count, only backend change needed
2. **Step 2 — Equity chart upgrade** (HIGH) — use `cash` and `realized_pnl` already in API response
3. **Step 3 — Tab container** (MEDIUM) — organizes chart area, but MetricsPanel is already a separate tab
4. **Step 4 — Execution view** (MEDIUM) — slippage/fees charts are genuinely new visualizations
5. **Steps 5-8** (LOW) — overlap with MetricsPanel or are nice-to-have polish
