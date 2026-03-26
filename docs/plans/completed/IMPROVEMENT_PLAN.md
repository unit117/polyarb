# PolyArb Improvement Plan

*Generated 2026-03-21 — Competitive analysis of 5 public repos + embedding audit + 30-day backtest review*

---

## Current State

**30-day backtest** (Feb 19–Mar 19): +5.36% with settlement on $10K simulated capital. Realized PnL is -$245 with 57% loss rate at settlement (16L / 12W). Profitable only from unrealized gains in 388 open positions.

**Embedding audit** (post bug-fix rebuild): 76.5% verification rate (1,568 / 2,050 pairs). Mutual exclusion pairs verify at 99.7%. Conditional pairs at 0% (now addressed — downgraded to `none` when missing correlation). The 0.82 cosine threshold is well-calibrated: low-similarity pairs like "Bengals win AFC North" vs "Browns win AFC North" are legitimate catches. However, the highest-similarity bucket (0.95+) actually underperforms 0.85-0.90 because near-identical crypto time-window questions are semantically close but logically independent.

**Bug fixes deployed today:** Conditional-without-correlation downgrade, hourly crypto regex, O/U implication classifier, outcome order guard in constraints, tighter ME price check (1.50 → 1.20).

---

## Already Done (no further action needed)

These items from the original plan are resolved by today's code changes:

- ~~Embedding audit~~ — Completed. Embeddings are effective for ME pairs (99.7%). Threshold is sound.
- ~~Conditional pair 0% verification~~ — Fixed. LLM conditionals without correlation now downgraded to `none`.
- ~~Crypto time-window misclassification~~ — Fixed. Hourly regex now catches `"10PM ET"` format alongside `"3:15AM-3:30AM"`.
- ~~Over/Under implication chains~~ — Fixed. New `_check_over_under_markets` rule-based classifier.
- ~~Outcome order guard~~ — Fixed. Warning logged when `outcomes[0] != "Yes"` to catch inverted constraint matrices.
- ~~Mutual exclusion price check too loose~~ — Fixed. Tightened from 1.50 to 1.20.

---

## Phase 1 — Deploy & Re-baseline ✅ COMPLETE (2026-03-21)

**Goal:** Get today's fixes live, rebuild stale data, measure impact.

**Steps:**
1. ✅ Deploy code to NAS via tar-over-SSH
2. ✅ Run `rebuild_constraints` to reclassify all pairs with new rules
3. ✅ Run `purge_positions` to clean out trades from pre-fix pairs
4. ✅ Re-run `audit_embeddings` to get the new baseline numbers
5. ✅ Monitor logs for 24h — watch for new classification patterns the rules don't catch

---

## Phase 2 — Model Switch & Fee Fix ✅ COMPLETE

**Goal:** Improve classification accuracy and edge calculation without structural changes.

### 2A. Switch classifier to GPT-4.1-mini ✅

Already configured in `shared/config.py` line 36: `classifier_model: str = "gpt-4.1-mini"`.

### 2B. Replace flat 2% fee with realistic fee schedule ✅

Implemented in `shared/config.py` lines 106-130:
- `polymarket_fee(price, side)` → symmetric fee: `price * (1-price) * 0.015`
- `kalshi_fee(price)` → `ceil(0.07 * price * (1-price))` in cents
- `venue_fee(venue, price, side)` → routing function

Used by both `optimizer/trades.py` and `simulator/pipeline.py`.

---

## Phase 3 — Safety Prerequisites ✅ COMPLETE

**Goal:** These must be complete before `live_trading_enabled` is ever set to `true`.

### 3A. Circuit breakers ✅

Implemented in `shared/circuit_breaker.py` (196 lines):
- 5 trip conditions: max daily loss, max position per market, max drawdown, consecutive errors, Redis kill switch
- 5-minute cooldown with auto-reset
- Wired into `simulator/pipeline.py` as pre-trade gate
- All settings in `shared/config.py` lines 58-63

### 3B. Kelly criterion position sizing ✅

Implemented in `services/simulator/pipeline.py` lines 119-140:
- Half-Kelly: `kelly_fraction = min(net_profit * 0.5, 1.0)`
- Drawdown scale-down: 100% at 5% drawdown, 50% at 10%+
- Uses optimizer's `estimated_profit` directly

### 3C. In-flight trade deduplication ✅

Implemented in `services/simulator/pipeline.py` lines 46-56:
- In-memory `_in_flight: set[int]` of opportunity IDs
- Checks membership before adding, clears after completion

---

## Phase 4 — WebSocket Streaming ✅ COMPLETE

**Goal:** Replace 30-second polling with real-time price updates.

Implemented in `services/ingestor/ws_client.py` (536 lines):
- `ClobWebSocket` class connecting to `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- Reconnection with exponential backoff
- Token ID subscription management
- Message parsing for `price_change` and `last_trade_price` events
- 2-second buffering for batch DB flushes
- Market resolution detection (price >= 0.98)
- Polling remains as 5-minute reconciliation fallback
- Config in `shared/config.py` lines 24-30

---

## Phase 5 — Kalshi Cross-Platform Arb ✅ COMPLETE

**Goal:** Add Kalshi as a second venue for cross-platform arbitrage.

Implemented across multiple files (see KALSHI_PLAN.md for full details):
- `services/ingestor/kalshi_client.py` (248 lines) — custom RSA-SHA256 REST client (not pmxt)
- `services/ingestor/kalshi_polling.py` — market sync, price snapshots, settlement detection
- `shared/models.py` — `venue` column on Market and PaperTrade
- `services/detector/similarity.py` — `find_cross_venue_pairs()` via pgvector KNN
- `services/detector/classifier.py` — `cross_platform` dependency type
- `services/detector/constraints.py` — `_cross_platform_matrix()` with fee-aware profit bounds
- `services/detector/verification.py` — cross-platform verification rules
- `services/optimizer/trades.py` — per-leg venue fee routing
- Dashboard: venue badges on pairs, trades, and opportunities tables
- Migration 011: venue column + composite unique constraint

---

## Phase 6 — Monitoring & Observability ✅ COMPLETE

**Goal:** Understand what the system is actually doing and which pair types make money.

### 6A. Opportunity duration tracking ✅

- `expired_at` column on `ArbitrageOpportunity` (migration 009)
- Set when opportunity reprices below threshold in `detector/pipeline.py`
- Duration returned in API response

### 6B. Dashboard metrics ✅

Four new endpoints in `services/dashboard/api/routes.py`:
- `/api/metrics/timeseries` — hourly aggregates
- `/api/metrics/funnel` — detected → optimized → simulated → profitable
- `/api/metrics/by-dependency-type` — hit rates by pair type
- `/api/metrics/duration` — duration histogram

### 6C. Conditional pair empirical validation ⚠️ PARTIAL

Infrastructure exists (PriceSnapshot table, dependency_type tracking via migration 010). Conditional pairs are already downgraded to `none` if correlation is missing (Phase 1 bug fix). Full rolling-correlation validator not yet built — deferred as conditional pairs are rare.

---

## Deferred / Not Pursuing

| Item | Reason |
|------|--------|
| **Local embeddings** | Audit shows OpenAI embeddings are effective (99.7% ME verification). Not worth the migration effort. Revisit only if costs become meaningful. |
| **Dump-and-hedge module** | Different strategy class (momentum vs. structural arb). Adds complexity without improving the core pipeline. Revisit after live trading is profitable. |
| **Warm-start IP oracle** | Marginal gain (30-50% fewer iterations on recurring pairs). Current 200-iteration budget with 36.6% convergence will improve once constraint matrices are cleaner from today's fixes. |
| **Maker order support** | Matters only for live trading. Build when live executor is ready, not before. |
| **Switch to Claude for classification** | Different API/SDK, not justified for a fallback classifier where rule-based checks handle the hard cases. |

---

## Schedule Summary

| Phase | What | Status | Completed |
|-------|------|--------|-----------|
| 1 | Deploy fixes, rebuild, re-audit | ✅ DONE | 2026-03-21 |
| 2 | GPT-4.1-mini + fee model | ✅ DONE | 2026-03-21 |
| 3 | Circuit breakers, Kelly, dedup | ✅ DONE | 2026-03-21 |
| 4 | WebSocket streaming | ✅ DONE | 2026-03-21 |
| 5 | Kalshi integration | ✅ DONE | 2026-03-22 |
| 6 | Monitoring & observability | ✅ DONE (6C partial) | 2026-03-22 |

**All phases complete.** Only remaining item: 6C rolling-correlation validator for conditional pairs (deferred — rare case).

---

## Competitive Landscape

| Repo | Language | Focus | Key Takeaway |
|------|----------|-------|--------------|
| [taetaehoho/poly-kalshi-arb](https://github.com/taetaehoho/poly-kalshi-arb) | Rust | Cross-platform sports arb | Lock-free atomics, in-flight dedup, concurrent leg execution |
| [ImMike/polymarket-arbitrage](https://github.com/ImMike/polymarket-arbitrage) | Python | Bundle mispricing + risk mgmt | Kill switch, drawdown tracking, opportunity duration buckets |
| [dev-protocol/polymarket-arbitrage-bot](https://github.com/dev-protocol/polymarket-arbitrage-bot) | TypeScript | 15-min crypto dump-and-hedge | Tactical strategy, rolling price buffer, forced hedge on timeout |
| [0xalberto/polymarket-arbitrage-bot](https://github.com/0xalberto/polymarket-arbitrage-bot) | — | BTC-focused live trading | Real P&L data: single-market focus outperforms multi-market |
| [jiliangzhu/MarketPulse-X](https://github.com/jiliangzhu/MarketPulse-X) | Rust | High-perf detection system | Lock-free orderbooks, SIMD-ready detection, comprehensive circuit breakers |

**PolyArb's edges vs competitors:** pgvector semantic market discovery (unique), Frank-Wolfe constrained optimization (unique), multi-type dependency classification with 7 rule-based classifiers + LLM fallback, VWAP execution simulation, full backtest infrastructure.

---

## Research References

See `research/README.md` for the full annotated paper library. Key references informing this plan:

- **Dudík, Lahaie, Pennock (2016)** — Frank-Wolfe algorithm foundation (our optimizer)
- **Polymarket Arbitrage (2025)** — Empirical analysis of cross-market arb on Polymarket
- **Manski (2006)** — Prices ≠ probabilities due to risk premia. Some detected "arbitrage" may be rational pricing. Implications: min_edge must exceed both fees AND potential risk premium explanations.
- **Wolfers & Zitzewitz (2006)** — Counterargument: prices are close enough to probabilities in practice
- **Biais, Glosten, Spatt (2005)** — Market microstructure theory informing slippage/VWAP modeling
