# Paper Trading — Final Findings (2026-08-21)

**Decision:** live paper trading was **stopped on 2026-08-21 15:28 UTC** (`docker compose stop simulator` on the NAS; `restart: unless-stopped` keeps it down). The ingestor, detector, optimizer, dashboard, postgres and redis were left running for data capture.

**Why:** the book finished **+19.1%** over the 131-day clean window, but a fill-realism audit against the recorded Polymarket trade tape showed that PnL is mostly **not executable**. Paper trading had told us everything it could; continuing would only have added more of the same number.

---

## 1. Final book

| Metric | Value |
|---|---|
| Final snapshot | 2026-08-21 15:28:01 UTC |
| Total value | **$10,866.99** (clean-window peak $10,888.94 the same day, drawdown 0.2%) |
| Cash / realized / unrealized | $11,104.92 / $1,669.52 / $9.74 |
| Trades / settled / winning | 12,320 / 1,341 / 777 (57.9%) |
| Clean window (Apr 12 purge, $9,130 base → now) | +$1,737 / **+19.1%** over 131 days |
| Since Jul 23 remediation deploy | +$349 / +3.3% |
| Since Aug 6 eval | +$115 / +1.07% (≈ $7–8/day) |
| Open positions | 50, $2,398.72 cost basis (~22% of book deployed) |
| Trade cadence | ~385 legs/day pre-remediation → 83/day → **54/day** (Aug 7–21) |

Daily EOD value rose on 17 of 21 August days; worst day −$10. Breaker and kill switch never tripped; no crash loops. The July 2026 forensic replay (ledger reproduces cash to $0.00, settlements match Gamma outcomes) still holds — the **accounting** is right. What is wrong is the **fill model** underneath it.

## 2. Finding — ~99% of fills never touched an order book

`services/simulator/vwap.py::compute_vwap()` returns `_midpoint_fill(midpoint ± base_slippage_rate)` (0.5%) whenever `select_outcome_book(snapshot.order_book, outcome)` is missing or empty. The midpoint it is handed is `trade.market_price` — the **optimizer's detection-time price**, not the fill-time snapshot (`services/simulator/validation.py`, `midpoint = trade.market_price or 0.5`).

Evidence (legs since 2026-07-23, n = 2,096):

- **2,068 legs (98.7%) have `slippage` exactly 0.005** — the fallback signature.
- A LATERAL join to the latest `price_snapshots` row at `executed_at` shows only **27 legs (1.3%)** had a non-null `order_book`. WS-written snapshots (every ~2 s) store JSON `null` books; REST books (`POST /books`) are sparse.

So the paper simulator has effectively never been walking a book. "VWAP slippage modeling" in the docs described a code path that was almost never taken.

## 3. Finding — the market did not trade at our prices

Method: for every paper leg since Jul 23, look at the `market_trades` WS tape (real Polymarket prints, captured since Jul 22) for the same `market_id` + `outcome`. 93% of legs had tape activity within ±1 h, so coverage is not the issue.

| | BUY legs (1,043) | SELL legs (1,053) |
|---|---|---|
| *Any* real print at-or-better than our price within 5 min | 188 (18%) | 89 (8.5%) |
| …with enough volume to cover our size | 177 | 87 |
| **Strict** — a real taker on our side at our price (ask/bid really existed) | 125 (12%) | **10 (1%)** |
| Next real print vs. our paper price (median) | −1.0¢ (we overpaid slightly) | **11.6¢ below our sell price** |

The SELL leg is where the cross-market arb edge lives, and paper was selling into bids that did not exist. Histogram of (our SELL price − next real print): 297 of 546 legs were ≥10¢ above the next trade; 54 were ≥30¢ above.

Worst cases are in-play sports O/U markets with wide, jumping spreads. Example — market 466672071 *"Texas Rangers vs. Los Angeles Angels: O/U 9.5"*, 2026-08-14 04:34:48 UTC: paper sold Over at **0.435** (snapshot midpoint 0.435, book `null`); the tape printed **0.30** seven minutes earlier and **0.09** eight minutes later; WS midpoints in that window oscillated 0.15 ↔ 0.45 within seconds. Sell at a fictional 0.43, Under wins, book 0.43/share.

## 4. Finding — sizes are dust, and the "edge" only exists at dust size

`validation.py`: `base_size = min(estimated_profit × kelly_multiplier(0.5), kelly_fraction_cap(0.25)) × max_position_size($100)`. A 2% edge sizes the bundle at **~$1**.

Since the Apr 12 reset: 13,168 legs; **97% are < 5 shares** (median ≈ 2, p90 ≈ 4.5); zero legs ≥ 20 shares. Total gross notional traded ≈ **$10.4k** — so $1.64k realized is a ~16% return on notional, which no real cross-market arb pays. Polymarket CLOB `minimum_order_size` is **5 shares** (verified 2026-08-21 via `/sampling-markets`); `services/simulator/live_executor.py` has no minimum-size handling. Positions of 100–200 shares in the book were accumulated from hundreds of ~2-share repeats on the same pair.

## 5. Finding — where the "profit" came from

Per-market reconstruction since Apr 12 (Σ settle_cash − buy_cost + sell_proceeds − fees over 1,334 settled markets = $1,996, vs. $1,635 realized delta from snapshots — close enough for attribution):

| Category | Markets | Reconstructed PnL | Gains / losses |
|---|---|---|---|
| Sports (O/U, "vs.") | 1,255 | **$1,318 (66%)** | +$3,457 / −$2,139 |
| Other (mostly FDV-launch: Tabi $176, Fuse $78, Hurupay $67) | 77 | $429 | +$740 / −$311 |
| Crypto / price thresholds | 2 | $12 | +$33 / −$21 |

Gross swings of ±$3k to net $1.3k is not what locked arbitrage looks like.

## 6. Finding — zombie positions

32 of 50 open positions ($1,648, 68.7% of cost basis, ~15% of total value) had had **no price since 2026-07-07** (one since Jul 22): FDV-launch, IPO-cap and past sports markets that went `active=false` without `resolved_outcome`. The simulator's `valuation_marked_at_cost` guard carried them at cost (correct fail-safe) but nothing could exit or settle them. Likely cause: the ingestor's Gamma pagination 422s at offset 2100 for `closed=true`, so resolution sync never reaches them.

## 7. What real execution would have looked like

Only ~12% of BUY legs and ~1% of SELL legs were demonstrably fillable, a bundle needs both, and bundles were ~$1 each. Realistically **tens of dollars over five months at best, plausibly negative** after half-filled bundles (legging risk). The +19% is not a number real money would have seen. **Do not put the live adapter on this engine as-is.**

## 8. Other findings from the same window (hygiene, not blocking)

- Ingestor: 49 tracebacks + 34 WS `1013 slow consumer: send buffer full` kicks in 48 h (host load ~4–5), auto-reconnect; Gamma offset-2100 422 recurring.
- Classifier (kimi-k2.6): 110–220 JSON-parse errors/day, retried, never cached.
- `markets` table bloat 19 GB → 30 GB, never vacuumed; DB 249 GB (`price_snapshots` 217 GiB); `/volume1` 82% used, 1.7 TB free.
- 5 app-container restarts on 2026-08-15 (postgres boot race), none since; 05:00 UTC host reboot confirmed dead.

## 9. If paper trading is ever resumed — fix first, then re-measure from a clean cutover

1. **No midpoint fallback.** Require a fresh real per-outcome book at fill time or reject the bundle (`no_book_skipped` + a metrics counter). Use the fill-time snapshot, never `trade.market_price`.
2. **Spread guard.** Reject legs whose best bid/ask spread exceeds a few cents — kills the in-play sports phantom fills.
3. **Venue minimum size.** Floor legs at 5 shares / $1 (or skip); size from book depth, not half-Kelly × $100.
4. **Resolve zombie markets** — fix closed-market discovery past the Gamma offset cap so inactive positions settle.
5. Then run paper for several weeks and compare against the tape again (the queries above are the acceptance test).

## Method notes

All numbers came from the live NAS DB on 2026-08-21: `portfolio_snapshots`, `paper_trades`, `price_snapshots` (always bounded by `market_id` — no pure-timestamp index), `market_trades` (`ix_market_trades_market_ts`), plus `GET /api/metrics/observability`. Tape check = per leg, real prints for the same `market_id`+`outcome` in `[executed_at, +5 min]` at-or-better than `vwap_price` (strict variant also requires the tape `side` to match ours). Book-presence check = latest snapshot `≤ executed_at` with `order_book::text NOT IN ('null','{}')`.
