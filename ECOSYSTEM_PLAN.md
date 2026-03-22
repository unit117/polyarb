# PolyArb Ecosystem Integration Plan

*Generated 2026-03-21 — Based on survey of 15+ open-source Polymarket/prediction-market repos*

**Status as of 2026-03-22:**
- E1: Not started | E2: ⚠️ Partially superseded (custom Kalshi client built instead of pmxt) | E3-E6: Not started
- All IMPROVEMENT_PLAN phases (1-6) are now complete, so E2/E5/E6 prerequisites are met.

---

## Relationship to IMPROVEMENT_PLAN.md

The existing improvement plan covers **internal fixes and features** (Phases 1–6: deploy bug fixes, model switch, circuit breakers, WebSocket, Kalshi, monitoring). This plan covers **external ecosystem integrations** — open-source tools, datasets, and libraries that can accelerate those phases or unlock new capabilities. Where an item here feeds directly into an existing phase, a cross-reference is noted.

---

## Current Gaps This Plan Addresses

| Gap | Impact | Source Repo |
|-----|--------|-------------|
| Backtest uses daily candles only — no order book replay | Overstates fill quality, understates slippage | evan-kolberg/prediction-market-backtesting |
| No historical dataset for embedding validation | Can't measure if pgvector pairs actually predict arb | Jon-Becker/prediction-market-analysis |
| Kalshi integration planned but no reference impl | Building from scratch is slow | pmxt-dev/pmxt |
| No walk-forward parameter tuning | FW iterations/gap/timeout are hand-tuned | 0xrsydn/polymarket-crypto-toolkit |
| No cross-venue price feeds | Missing Polymarket↔Kalshi spread data | pmxt-dev/pmxt |
| Settlement backtest unvalidated | No ground-truth resolved outcomes to test against | Jon-Becker/prediction-market-analysis |

---

## Phase E1 — Historical Dataset Integration (highest ROI)

**Goal:** Use Jon-Becker's 36GB Polymarket+Kalshi dataset to validate embeddings and backtest against real resolutions.

**Source:** [Jon-Becker/prediction-market-analysis](https://github.com/Jon-Becker/prediction-market-analysis) (2.3K stars, updated 17 days ago)

**What it gives us:**
- Complete trade histories (maker/taker, prices, sizes, timestamps) for thousands of Polymarket markets
- Resolution outcomes — which market won, at what block number
- Kalshi equivalent data (tickers, bid/ask, volume, resolution status)
- Parquet format, queryable with DuckDB

**Integration steps:**

### E1a. Download and stage the dataset
```bash
# ~36GB compressed via Cloudflare R2
make setup  # from their repo — downloads to data/
```
Store on NAS at `/volume1/data/prediction-market-analysis/`. No need to load into Postgres — query with DuckDB or Pandas directly from Parquet.

### E1b. Embedding validation script
New script: `scripts/validate_embeddings.py`

**Logic:**
1. Load all resolved Polymarket markets from Jon-Becker Parquet files
2. For each market pair in our `market_pairs` table, look up both markets' resolution outcomes
3. Compute: did ME pairs actually resolve to mutual exclusion? (exactly 1 winner)
4. Compute: did conditional pairs show empirical price correlation before resolution?
5. Output: precision/recall by dependency type, cosine similarity bucket, and pair age

**Why this matters:** The embedding audit showed 76.5% verification rate, but that's based on LLM re-classification. This validates against *ground truth outcomes* — the only metric that matters for PnL.

### E1c. Backtest with real resolutions
Extend `scripts/backtest.py` to:
1. Import resolved outcomes from Jon-Becker data instead of inferring from prices
2. Run settlement logic against known winners/losers
3. Compute actual realized PnL (not just unrealized from price snapshots)

**Cross-ref:** Feeds into IMPROVEMENT_PLAN Phase 1 (re-baseline) and SETTLEMENT_PLAN (validates settlement logic).

**Effort:** ~1 day. **Risk:** Low — read-only data import, no changes to live system.

---

## Phase E2 — PMXT for Multi-Venue Data ⚠️ SUPERSEDED

**Original goal:** Replace manual Kalshi API integration with pmxt unified SDK.

**What happened:** Kalshi integration was built with a custom RSA-SHA256 REST client (`services/ingestor/kalshi_client.py`, 248 lines) instead of pmxt. The custom client is already deployed and working. pmxt could still be adopted later for WebSocket streaming or additional venues, but is no longer blocking.

**Source:** [pmxt-dev/pmxt](https://github.com/pmxt-dev/pmxt) (1.1K stars, updated 30 minutes ago, very active)

**What it gives us:**
- Unified Python SDK: `pmxt.Polymarket()`, `pmxt.Kalshi()`, plus 5 other venues
- Consistent market/order/trade schemas across all venues
- WebSocket streaming: `watch_order_book()`, `watch_trades()`
- Order placement: `create_order()` with venue-specific auth handled internally
- Historical OHLCV: `fetch_ohlcv()` at 1m–1d resolution

**Integration steps:**

### E2a. Add pmxt as ingestor dependency
```dockerfile
# services/ingestor/Dockerfile
RUN pip install pmxt
```

### E2b. New KalshiIngestor using pmxt
New file: `services/ingestor/kalshi_client.py`

```python
import pmxt

class KalshiIngestor:
    def __init__(self):
        self.exchange = pmxt.Kalshi(api_key=settings.kalshi_api_key)

    async def fetch_markets(self, query: str = None):
        return await self.exchange.fetch_markets(query=query)

    async def watch_prices(self, market_ids: list[str]):
        async for book in self.exchange.watch_order_book(market_ids):
            yield self._to_price_snapshot(book)
```

This replaces the from-scratch RSA-SHA256 auth + REST client that IMPROVEMENT_PLAN Phase 5 describes. The pmxt library handles auth, rate limiting, and schema normalization.

### E2c. Cross-venue market matching
New script: `scripts/match_cross_venue.py`

Use pgvector embeddings to match Polymarket markets with Kalshi equivalents:
1. Fetch all active Kalshi markets via pmxt
2. Generate embeddings (same OpenAI model as Polymarket markets)
3. For each Kalshi market, find nearest Polymarket neighbor in pgvector
4. Verify matches via LLM classifier (new type: `cross_platform_equivalent`)
5. Store as `MarketPair` with `dependency_type = 'cross_platform'`

**Cross-ref:** Directly enables IMPROVEMENT_PLAN Phase 5 (Kalshi integration). Reduces that phase from ~1 week to ~2-3 days by eliminating custom API client work.

**Effort:** ~2 days (including cross-venue matching). **Risk:** Medium — pmxt is v0.1.0, API may change. Pin version.

---

## Phase E3 — L2 Order Book Backtest (realistic fill simulation)

**Goal:** Replace daily-candle backtest with hourly order book replay for realistic slippage.

**Source:** [evan-kolberg/prediction-market-backtesting](https://github.com/evan-kolberg/prediction-market-backtesting) (25 stars)

**What it gives us:**
- Event-driven backtester built on NautilusTrader (Rust hot loop via PyO3)
- Hourly L2 order book snapshots via pmxt
- Realistic fill simulation: limit order matching against historical book depth
- Multi-market support

**Why this matters:** Our current backtest uses daily OHLCV candles and assumes fills at the daily price. Real arbitrage opportunities last seconds-to-minutes. Daily granularity:
- Overstates fill quality (can't see intra-day spread widening)
- Misses opportunities that opened and closed within a single day
- Can't model slippage against actual book depth

**Integration approach:**

### E3a. Backfill hourly order books
Extend `scripts/backfill_history.py` to fetch hourly OHLCV via pmxt instead of daily from CLOB API:
```python
exchange = pmxt.Polymarket()
ohlcv = await exchange.fetch_ohlcv(market_id, timeframe='1h', since=start_ts)
```

This also sidesteps the CLOB API's 14-day interval limit (noted in CLAUDE.md gotchas) since pmxt handles chunking internally.

### E3b. Add book-depth fill model
New file: `services/simulator/fill_model.py`

Replace the current VWAP fill model with a book-aware model:
```python
class BookDepthFillModel:
    """Simulate fills against historical order book depth."""

    def estimate_fill(self, side: str, size: Decimal, book_snapshot: dict) -> dict:
        """Walk the book to estimate VWAP and slippage for a given order size."""
        levels = book_snapshot["asks"] if side == "BUY" else book_snapshot["bids"]
        filled = Decimal("0")
        cost = Decimal("0")
        for price, qty in levels:
            take = min(size - filled, Decimal(str(qty)))
            cost += take * Decimal(str(price))
            filled += take
            if filled >= size:
                break
        vwap = cost / filled if filled > 0 else Decimal("0")
        mid = Decimal(str(book_snapshot["mid_price"]))
        slippage = abs(vwap - mid) / mid if mid > 0 else Decimal("0")
        return {"filled_size": filled, "vwap_price": vwap, "slippage": slippage}
```

### E3c. Reference implementation study
Before building our own, extract patterns from evan-kolberg's NautilusTrader integration:
```bash
gh repo clone evan-kolberg/prediction-market-backtesting /tmp/pmbt
# Study: src/backtester/fill_model.py, src/data/book_loader.py
```

**Cross-ref:** Improves BACKTEST_PLAN accuracy. Also informs IMPROVEMENT_PLAN Phase 2B (fee model) by providing real book-depth data for fee estimation.

**Effort:** ~2 days. **Risk:** Medium — hourly backfill is 24x more data than daily, storage/runtime increases.

---

## Phase E4 — Walk-Forward Parameter Optimization

**Goal:** Replace hand-tuned Frank-Wolfe parameters with data-driven optimization.

**Source:** [0xrsydn/polymarket-crypto-toolkit](https://github.com/0xrsydn/polymarket-crypto-toolkit) (51 stars)

**What it gives us:**
- Parameter sweep framework with walk-forward validation
- Plugin-based strategy interface
- Backtest-driven optimization loop

**Parameters to optimize:**

| Parameter | Current Value | Range to Sweep |
|-----------|--------------|----------------|
| `FW_MAX_ITERATIONS` | 200 | 50–500 |
| `FW_CONVERGENCE_GAP` | 0.001 | 0.0001–0.01 |
| `FW_TIMEOUT_SECONDS` | 5.0 | 1.0–15.0 |
| `MIN_PROFIT_BOUND` | 0.02 | 0.01–0.05 |
| `COSINE_SIMILARITY_THRESHOLD` | 0.82 | 0.75–0.90 |
| `POSITION_MAX_SIZE` | (from Kelly) | 0.5x–2x Kelly |

**Integration steps:**

### E4a. Parameter sweep script
New script: `scripts/param_sweep.py`

```python
import itertools

PARAM_GRID = {
    "fw_max_iterations": [100, 200, 400],
    "fw_convergence_gap": [0.0005, 0.001, 0.005],
    "min_profit_bound": [0.01, 0.02, 0.03, 0.05],
    "cosine_threshold": [0.78, 0.82, 0.86, 0.90],
}

async def run_sweep():
    results = []
    for params in itertools.product(*PARAM_GRID.values()):
        config = dict(zip(PARAM_GRID.keys(), params))
        pnl = await run_backtest_with_params(config)
        results.append({**config, **pnl})
    return sorted(results, key=lambda r: r["sharpe"], reverse=True)
```

### E4b. Walk-forward validation
Split historical data into train/test windows:
- Train: 21 days, Test: 7 days
- Slide forward by 7 days, repeat
- Only accept parameters that are stable across all windows

**Why walk-forward:** A single backtest over 30 days will overfit to that specific period. Walk-forward tests that the parameters generalize to unseen data.

### E4c. Sensitivity report
Output: which parameters matter most for PnL, and which are robust (flat sensitivity curve = safe to leave at default). Save as `reports/param_sensitivity.json` for dashboard display.

**Cross-ref:** Uses the improved backtest from E3. Should run after E1 (needs resolved outcomes for accurate PnL).

**Effort:** ~1 day for sweep script, ~half day for walk-forward wrapper. **Risk:** Low — runs offline against backtest DB.

---

## Phase E5 — Informed Trader Flow Analysis

**Goal:** Use maker/taker address data to detect informed order flow and improve timing.

**Source:** [Jon-Becker/prediction-market-analysis](https://github.com/Jon-Becker/prediction-market-analysis) — blockchain trade indexer

**What it gives us:**
- Every `OrderFilled` event on Polygon: maker address, taker address, asset ID, amount, block number
- Ability to identify repeat addresses (market makers, informed traders, arbitrageurs)
- Temporal patterns: when do informed traders act relative to resolution?

**Integration steps:**

### E5a. Address clustering
From the Jon-Becker Parquet trade data:
1. Group all trades by maker/taker address
2. Compute per-address: total volume, win rate at resolution, average trade size, number of distinct markets
3. Cluster into: market makers (high volume, balanced sides), informed traders (high win rate), retail (small size, low win rate)

### E5b. Informed flow signal
New feature for the detector: when an address previously classified as "informed" starts trading heavily in one direction on a market, it's a signal that the market is about to move. If we hold a position in a correlated market, this is an early warning.

### E5c. Address watchlist
Store top-100 informed addresses in Redis. When the WebSocket ingestor (IMPROVEMENT_PLAN Phase 4) sees a trade from a watched address, publish a `polyarb:informed_flow` event. The optimizer can use this as a tie-breaker when multiple opportunities compete for capital.

**Cross-ref:** Requires Phase 4 (WebSocket) from IMPROVEMENT_PLAN. Enhances Phase 6 (monitoring).

**Effort:** ~2 days for address analysis, ~1 day for real-time signal. **Risk:** Medium — address behavior may not be stable over time. Needs periodic re-clustering.

---

## Phase E6 — Oracle Price Anchoring

**Goal:** Use external price feeds (Chainlink, Binance) to identify stale Polymarket prices.

**Inspiration:** [txbabaxyz/polyrec](https://github.com/txbabaxyz/polyrec) — aggregates Chainlink + Binance + Polymarket

**What it gives us:**
- Detection of markets where the Polymarket price hasn't caught up to external data
- Crypto markets (BTC/ETH price targets) are the clearest case: if Binance BTC = $68,000 and a Polymarket "BTC above $67,500" question is priced at $0.85, that's a stale price

**Integration steps:**

### E6a. Binance price feed
New file: `services/ingestor/binance_feed.py`

Subscribe to Binance WebSocket for BTC, ETH, SOL spot prices. Publish to `polyarb:external_prices` on Redis.

### E6b. Staleness detector
In the detector service, for crypto-tagged markets:
1. Parse the price target from the market question (regex: already partially built for hourly crypto in today's fixes)
2. Compare current Polymarket price against external oracle
3. If external price clearly resolves the question (e.g., BTC > target by 2%+) but Polymarket price < 0.95, flag as stale/mispriced

### E6c. Priority routing
Stale-price opportunities get a priority boost in the optimizer queue. These are the lowest-risk arbitrage opportunities because the outcome is already known — only execution speed matters.

**Cross-ref:** Enhances IMPROVEMENT_PLAN Phase 4 (WebSocket) by adding a second data source. Only applicable to crypto markets (~15-20% of Polymarket volume).

**Effort:** ~1 day. **Risk:** Low — read-only external feed, no trading logic changes.

---

## Deferred / Evaluated but Not Pursuing

| Item | Source Repo | Reason |
|------|-------------|--------|
| **Polymarket/agents RAG integration** | Polymarket/agents (2.6K stars) | AI-driven market research is interesting but orthogonal to structural arb. Our edge is mathematical (Frank-Wolfe), not informational. Revisit if adding directional trading. |
| **NautilusTrader full integration** | evan-kolberg/prediction-market-backtesting | Full migration to NautilusTrader is overkill. Borrow their fill model (E3b) but keep our backtest framework. |
| **Copy trading / signal following** | CryptoVictormt/polymarket-copy-trading-bot | Different strategy entirely. Not compatible with structural arbitrage. |
| **Market making module** | warproxxx/poly-maker (948 stars) | Author says it loses money. Market making requires different infrastructure (inventory management, adverse selection modeling). Separate project if ever pursued. |
| **QuantDinger multi-agent architecture** | brokermr810/QuantDinger (1K stars) | Interesting architecture but our pipeline is already well-structured. Adding an LLM orchestration layer over the existing detector→optimizer→simulator pipeline adds latency and unpredictability. |
| **solanabull trading bot** | solanabull/Polymarket-Trading-Bot (956 stars) | Spam repo — description is keyword-stuffed. No useful code. |

---

## Schedule Summary

| Phase | What | Depends On | Effort | Priority | Status |
|-------|------|------------|--------|----------|--------|
| E1 | Historical dataset + embedding validation | — | 1 day | **Highest** — validates everything else | Not started |
| E2 | PMXT for Kalshi integration | ~~IMPROVEMENT Phase 3~~ ✅ | 2 days | ~~High~~ Low — custom client already built | ⚠️ Superseded |
| E3 | L2 order book backtest | E1 (needs resolved outcomes) | 2 days | High — accuracy of all future decisions | Not started |
| E4 | Walk-forward parameter tuning | E1 + E3 | 1.5 days | Medium — optimization after validation | Not started |
| E5 | Informed trader flow analysis | ~~IMPROVEMENT Phase 4~~ ✅ | 3 days | Medium — nice alpha signal | Not started |
| E6 | Oracle price anchoring | ~~IMPROVEMENT Phase 4~~ ✅ | 1 day | Medium — low-hanging fruit for crypto | Not started |

**Recommended execution order:** E1 → E3 → E4 → E6 → E5

E1 first because it validates whether our embeddings and backtest are trustworthy — everything downstream depends on that answer. E2 is superseded (custom Kalshi client already built). E5 and E6 both require WebSocket streaming (now complete via IMPROVEMENT Phase 4).

**Total effort:** ~8-9 days of focused work (E2 reduced since Kalshi client exists). All IMPROVEMENT_PLAN prerequisites are now met.

---

## Key Repos Referenced

| Repo | Stars | Used In |
|------|-------|---------|
| [Jon-Becker/prediction-market-analysis](https://github.com/Jon-Becker/prediction-market-analysis) | 2.3K | E1, E5 |
| [pmxt-dev/pmxt](https://github.com/pmxt-dev/pmxt) | 1.1K | E2, E3 |
| [evan-kolberg/prediction-market-backtesting](https://github.com/evan-kolberg/prediction-market-backtesting) | 25 | E3 |
| [0xrsydn/polymarket-crypto-toolkit](https://github.com/0xrsydn/polymarket-crypto-toolkit) | 51 | E4 |
| [txbabaxyz/polyrec](https://github.com/txbabaxyz/polyrec) | — | E6 |
| [0xalberto/polymarket-arbitrage-bot](https://github.com/0xalberto/polymarket-arbitrage-bot) | 68 | Competitive ref |
| [realfishsam/prediction-market-arbitrage-bot](https://github.com/realfishsam/prediction-market-arbitrage-bot) | — | E2 reference impl |
