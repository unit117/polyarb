# Kalshi Integration Plan (Phase 5 + E2)

*Generated 2026-03-21 — Combines IMPROVEMENT_PLAN Phase 5 and ECOSYSTEM_PLAN Phase E2*

**Status: ✅ ALL 10 STEPS COMPLETE** (implemented 2026-03-22)

**Note:** Built with a custom RSA-SHA256 REST client instead of pmxt SDK. All functionality from the original plan is implemented.

---

## Context

PolyArb is Polymarket-only. IMPROVEMENT_PLAN Phase 5 calls for Kalshi as a second venue for cross-platform arbitrage. ECOSYSTEM_PLAN Phase E2 proposes using the `pmxt` SDK instead of building a custom RSA-SHA256 Kalshi API client, reducing effort from ~1 week to ~2-3 days. This plan combines both.

Phase 3 (circuit breakers, Kelly, dedup) and Phase 4 (WebSocket) are already complete, so this is unblocked.

---

## Implementation Steps

### Step 1: Database Migration (`alembic/versions/011_venue_column.py`) ✅

- Add `venue VARCHAR(32) NOT NULL DEFAULT 'polymarket'` to `markets`
- Add index `ix_markets_venue` on `venue`
- Drop existing unique constraint on `polymarket_id`
- Add composite unique constraint on `(venue, polymarket_id)` — allows same external ID across venues
- Add `venue VARCHAR(32)` to `paper_trades` (nullable for existing rows)

**Why keep `polymarket_id` column name:** It's referenced in 5 files. Renaming is a larger migration for cosmetic benefit. Kalshi tickers go in `polymarket_id` with `venue='kalshi'`.

### Step 2: Model Updates (`shared/models.py`) ✅

- Add `venue` column to `Market` (default `'polymarket'`)
- Update `__table_args__` unique constraint from `polymarket_id` alone to `(venue, polymarket_id)`
- Add `venue` column to `PaperTrade` (nullable, default `'polymarket'`)

### Step 3: Config Changes (`shared/config.py`) ✅

New settings:
```
kalshi_enabled: bool = False
kalshi_api_key: str = ""
kalshi_api_secret: str = ""
kalshi_poll_interval_seconds: int = 120
kalshi_max_markets: int = 500
kalshi_rate_limit_rps: float = 1.5
```

New venue fee router:
```python
def venue_fee(venue: str, price: float, side: str = "BUY") -> float:
    if venue == "kalshi":
        return kalshi_fee(price)
    return polymarket_fee(price, side)
```

### Step 4: Kalshi Client (`services/ingestor/kalshi_client.py`) ✅ — NEW FILE

Custom RSA-SHA256 authenticated REST client (248 lines, not pmxt-based):
- `fetch_markets()` → returns normalized dicts (venue, external_id, question, outcomes, volume)
- `fetch_prices(ticker)` → returns PriceSnapshot-compatible dict
- Rate limiting via asyncio lock (same pattern as `GammaClient`)
- Pin `pmxt==0.1.0` in `services/ingestor/requirements.txt`

**Note:** If pmxt breaks or the API changes, fall back to building a custom Kalshi REST client with RSA-SHA256 auth. The `KalshiClient` abstraction layer means only this file would need to change.

### Step 5: Kalshi Polling (`services/ingestor/kalshi_polling.py`) ✅ — NEW FILE

`KalshiPoller` class following `MarketPoller` pattern:
- `sync_markets()` — fetch from pmxt, batch upsert with `venue='kalshi'`
- `snapshot_prices()` — fetch prices for top Kalshi markets by volume
- Reuse existing `embedder.py` for embedding computation (same model/dims)
- Publish same Redis events (`CHANNEL_MARKET_UPDATED`, `CHANNEL_SNAPSHOT_CREATED`)

### Step 6: Ingestor Entry Point (`services/ingestor/main.py`) ✅

Add conditional Kalshi startup:
```python
if settings.kalshi_enabled:
    kalshi_poller = KalshiPoller(...)
    tasks.append(kalshi_poller.run())
# Add to existing asyncio.gather
```

### Step 7: Cross-Platform Dependency Type ✅

**`services/detector/classifier.py`:**
- Add `"cross_platform"` to `DEPENDENCY_TYPES`
- Add `_check_cross_platform()` rule: fires when venues differ + similarity > 0.92 → auto-classify with confidence 0.95
- For moderate matches (0.82-0.92), use LLM to verify

**`services/detector/constraints.py`:**
- Add `_cross_platform_matrix()` — identity matrix: (Yes,Yes)=1, (No,No)=1, mixed=0
- Add fee-aware profit bound: `spread - polymarket_fee(cheaper) - kalshi_fee(dearer)`

**`services/detector/verification.py`:**
- Add `cross_platform` verification: both binary, different venues, reasonable price range (0.05-0.95)

### Step 8: Cross-Venue Similarity Search (`services/detector/similarity.py`) ✅

Add `find_cross_venue_pairs()`:
- Anchors = Kalshi markets, neighbors = Polymarket markets (or vice versa)
- Uses pgvector KNN with `CROSS JOIN LATERAL` for efficient 1-nearest search
- Returns matches above threshold, filtered against existing pairs

**`services/detector/pipeline.py`:**
- Add `_detect_cross_venue()` method called from `run_once()` when Kalshi is enabled
- Separate from intra-venue detection cycle

### Step 9: Fee Routing in Optimizer + Simulator ✅

**`services/optimizer/trades.py`:**
- Accept `venue_a`, `venue_b` params in `compute_trades()`
- Tag each trade dict with `"venue"` field
- Use `venue_fee()` for per-leg fee calculation

**`services/optimizer/pipeline.py`:**
- Load market venues when fetching pair data, pass to `compute_trades()`

**`services/simulator/pipeline.py`:**
- Replace `from shared.config import polymarket_fee` with `venue_fee`
- Read venue from trade dict or market model for fee calculation

### Step 10: Dashboard Updates (`services/dashboard/`) ✅

- Add venue badge to markets table
- Show "Cross-Venue" tag on cross-platform pairs
- Add venue filter to opportunities view

---

## Files Summary

| Action | File |
|--------|------|
| CREATE | `alembic/versions/011_venue_column.py` |
| CREATE | `services/ingestor/kalshi_client.py` |
| CREATE | `services/ingestor/kalshi_polling.py` |
| MODIFY | `shared/models.py` |
| MODIFY | `shared/config.py` |
| MODIFY | `services/ingestor/main.py` |
| MODIFY | `services/ingestor/requirements.txt` |
| MODIFY | `services/detector/classifier.py` |
| MODIFY | `services/detector/constraints.py` |
| MODIFY | `services/detector/verification.py` |
| MODIFY | `services/detector/similarity.py` |
| MODIFY | `services/detector/pipeline.py` |
| MODIFY | `services/optimizer/trades.py` |
| MODIFY | `services/optimizer/pipeline.py` |
| MODIFY | `services/simulator/pipeline.py` |
| MODIFY | `.env.example` |

---

## Verification

1. **Backward compat**: Deploy with `kalshi_enabled=false`, verify zero behavioral changes
2. **Kalshi ingestion**: Enable Kalshi, verify markets appear with `venue='kalshi'` and embeddings computed
3. **Cross-venue matching**: Run one-shot script to find top-10 cross-venue matches, manually verify
4. **Pair detection**: Verify `market_pairs` rows with `dependency_type='cross_platform'` and correct constraint matrices
5. **Fee routing**: Check opportunity logs — `estimated_profit` should reflect both venue fees
6. **End-to-end**: Trigger cross-platform opportunity through detect → optimize → simulate, verify PaperTrade with correct fees
7. **Deploy to NAS**: tar-over-SSH, rebuild containers, run migration, monitor logs

---

## Risks

| Risk | Mitigation |
|------|-----------|
| pmxt v0.1.0 breaking changes | Pin version, wrap in `KalshiClient` abstraction. If pmxt breaks, build custom REST client — only `kalshi_client.py` changes. |
| Kalshi rate limits (2 req/s) | Conservative 1.5 rps default, exponential backoff |
| False positive cross-venue matches | High threshold (0.92) for auto-classify, LLM for moderate |
| NAS resource constraints | No new container, runs in existing ingestor |
| Migration on running system | Additive column with default — non-breaking |

---

## Schedule

| Step | What | Effort |
|------|------|--------|
| 1-2 | DB migration + model updates | 30 min |
| 3 | Config changes | 20 min |
| 4-5 | Kalshi client + polling | 4 hours |
| 6 | Ingestor entry point | 20 min |
| 7 | Cross-platform dependency type | 2 hours |
| 8 | Cross-venue similarity search | 1.5 hours |
| 9 | Fee routing (optimizer + simulator) | 1.5 hours |
| 10 | Dashboard updates | 2 hours |
| **Total** | | **~12 hours** |
