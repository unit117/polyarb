# Position Settlement & PNL Realization — Implementation Plan

**Status: ✅ ALL 8 STEPS COMPLETE** (implemented 2026-03-21)

## Problem

The simulator enters positions but never closes them. `realized_pnl` is always $0, `winning_trades` is always 0, and positions accumulate indefinitely. This plan adds settlement logic directly into the simulator pipeline.

---

## Architecture Decision

All settlement logic lives inside the **existing simulator service** — no new microservice. We add:

1. A `settle_resolved_markets()` method on `SimulatorPipeline`
2. A `close_position()` method on `Portfolio`
3. A resolution detection loop in `main.py`
4. Rebalancing-exit logic in the existing trade execution flow

---

## Step 1: Add `resolved_outcome` Column to `Market` Model ✅

**File:** `shared/models.py` (lines 46-47)

Add a field to track which outcome won when a market resolves:

```python
resolved_outcome: Mapped[str | None] = mapped_column(String, nullable=True)
resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
```

Then generate an Alembic migration (or raw SQL `ALTER TABLE`).

**Why:** We need to know *which* outcome won so we can pay out $1 per winning share and $0 per losing share.

---

## Step 2: Add `close_position()` to `Portfolio` ✅

**File:** `services/simulator/portfolio.py` (lines 96-143)

Add a new method that settles a position at a known payout price (1.0 for winners, 0.0 for losers):

```python
def close_position(self, key: str, settlement_price: float) -> dict:
    """Close a position at a known settlement price.

    For market resolution: settlement_price = 1.0 (winning outcome) or 0.0 (losing).
    For rebalancing exits: settlement_price = current market price.
    """
    if key not in self.positions:
        return {"closed": False, "reason": "no_position"}

    shares = self.positions[key]
    cost = self.cost_basis.get(key, Decimal("0"))
    payout = shares * Decimal(str(settlement_price))
    pnl = payout - cost

    self.cash += payout
    self.realized_pnl += pnl

    if pnl > 0:
        self.winning_trades += 1

    del self.positions[key]
    self.cost_basis.pop(key, None)

    return {
        "closed": True,
        "key": key,
        "shares": float(shares),
        "settlement_price": settlement_price,
        "pnl": float(pnl),
        "is_winner": pnl > 0,
    }
```

**Key behavior:**
- Winning outcome shares pay $1.00 each (prediction market convention)
- Losing outcome shares pay $0.00
- PNL = payout minus cost basis
- Positive PNL increments `winning_trades`
- Position and cost basis are deleted after close

---

## Step 3: Add Resolution Detection to Ingestor ✅

**File:** `services/ingestor/polling.py` (lines 263-345) + `services/ingestor/ws_client.py` (lines 330-351)

### 3a: Price-based inference (fast, early detection)

In the existing `snapshot_prices()` loop, after storing a price snapshot, check if any price is near-terminal:

```python
RESOLUTION_THRESHOLD = 0.98  # price >= 0.98 suggests market resolved

for outcome, price in snapshot.prices.items():
    if float(price) >= RESOLUTION_THRESHOLD:
        # Publish early resolution signal
        await publish(redis, CHANNEL_MARKET_RESOLVED, {
            "market_id": market.id,
            "resolved_outcome": outcome,
            "source": "price_inference",
            "price": float(price),
        })
```

### 3b: API-based confirmation (authoritative)

Add a periodic task that re-fetches markets from the Gamma API with `closed=True` to find resolved markets:

```python
async def check_resolved_markets(gamma: GammaClient, session_factory, redis):
    """Fetch closed markets from Gamma API and mark resolved ones."""
    closed_markets = await gamma.list_markets(active=False, closed=True)

    async with session_factory() as session:
        for raw in closed_markets:
            market = await session.execute(
                select(Market).where(Market.polymarket_id == raw["condition_id"])
            )
            market = market.scalar_one_or_none()
            if not market or market.resolved_outcome:
                continue  # already resolved or not tracked

            # Determine winning outcome from API data
            # Polymarket returns tokens with price=1 for winner
            winning_outcome = _extract_winner(raw)
            if winning_outcome:
                market.resolved_outcome = winning_outcome
                market.resolved_at = func.now()
                market.active = False
                await session.commit()

                await publish(redis, CHANNEL_MARKET_RESOLVED, {
                    "market_id": market.id,
                    "resolved_outcome": winning_outcome,
                    "source": "gamma_api",
                })
```

### 3c: Add new event channel

**File:** `shared/events.py`

```python
CHANNEL_MARKET_RESOLVED = "polyarb:market_resolved"
```

---

## Step 4: Add `settle_resolved_markets()` to `SimulatorPipeline` ✅

**File:** `services/simulator/pipeline.py` (lines 351-416)

This is the core settlement logic. It scans for resolved markets that have open positions and closes them:

```python
async def settle_resolved_markets(self) -> dict:
    """Close all positions in markets that have resolved."""
    stats = {"settled": 0, "pnl_realized": 0.0}

    async with self.session_factory() as session:
        # Find all resolved markets where we hold positions
        resolved = await session.execute(
            select(Market).where(
                Market.resolved_outcome.isnot(None),
                Market.id.in_(
                    [int(k.split(":")[0]) for k in self.portfolio.positions]
                )
            )
        )

        for market in resolved.scalars().all():
            # Close each position in this market
            for outcome in list(self.portfolio.positions.keys()):
                if not outcome.startswith(f"{market.id}:"):
                    continue

                position_outcome = outcome.split(":")[1]
                is_winner = (position_outcome == market.resolved_outcome)
                settlement_price = 1.0 if is_winner else 0.0

                result = self.portfolio.close_position(outcome, settlement_price)
                if result["closed"]:
                    stats["settled"] += 1
                    stats["pnl_realized"] += result["pnl"]

                    # Record closing trade in DB
                    paper_trade = PaperTrade(
                        opportunity_id=None,  # settlement, not from an opportunity
                        market_id=market.id,
                        outcome=position_outcome,
                        side="SETTLE",
                        size=Decimal(str(result["shares"])),
                        entry_price=Decimal(str(settlement_price)),
                        vwap_price=Decimal(str(settlement_price)),
                        slippage=Decimal("0"),
                        fees=Decimal("0"),
                        status="settled",
                    )
                    session.add(paper_trade)

        await session.commit()

    if stats["settled"] > 0:
        await self.snapshot_portfolio()
        logger.info("settlement_complete", **stats)

    return stats
```

**Note:** `PaperTrade.opportunity_id` is currently a non-nullable FK. We need to either make it nullable (for settlement trades) or create a sentinel "settlement" opportunity. Making it nullable is cleaner — see Step 6.

---

## Step 5: Add Rebalancing Exit Logic ✅

**File:** `services/simulator/pipeline.py` (lines 418-483, `purge_contaminated_positions()`)

When a new rebalancing opportunity generates a trade that *reverses* an existing position, treat it as a partial or full exit and realize PNL:

```python
# Inside simulate_opportunity(), after computing fill, before execute_trade():

key = f"{market.id}:{trade['outcome']}"
existing_position = self.portfolio.positions.get(key, Decimal("0"))

# Detect reversal: selling when long, or buying when short
is_exit = (
    (trade["side"] == "SELL" and existing_position > 0) or
    (trade["side"] == "BUY" and existing_position < 0)
)

if is_exit and existing_position != 0:
    # Calculate realized PNL for the portion being closed
    close_size = min(abs(existing_position), Decimal(str(fill["filled_size"])))
    avg_entry = self.portfolio.cost_basis.get(key, Decimal("0")) / abs(existing_position)
    exit_price = Decimal(str(fill["vwap_price"]))

    if existing_position > 0:  # closing a long
        realized = (exit_price - avg_entry) * close_size
    else:  # closing a short
        realized = (avg_entry - exit_price) * close_size

    self.portfolio.realized_pnl += realized
    if realized > 0:
        self.portfolio.mark_winner()
```

This piggybacks on the existing `execute_trade()` flow — positions still update normally via `execute_trade()`, but we additionally track the realized PNL component when a trade is reducing/reversing a position.

---

## Step 6: Schema Migration ✅

**File:** `alembic/versions/004_settlement_schema.py`

Make `PaperTrade.opportunity_id` nullable to support settlement trades:

```sql
ALTER TABLE paper_trades ALTER COLUMN opportunity_id DROP NOT NULL;
```

Add the new columns to `markets`:

```sql
ALTER TABLE markets ADD COLUMN resolved_outcome VARCHAR;
ALTER TABLE markets ADD COLUMN resolved_at TIMESTAMPTZ;
CREATE INDEX ix_markets_resolved ON markets (resolved_outcome) WHERE resolved_outcome IS NOT NULL;
```

---

## Step 7: Wire Settlement into the Main Loop ✅

**File:** `services/simulator/main.py` (lines 140-203)

Add a settlement loop alongside the existing periodic/snapshot/event loops:

```python
async def _settlement_loop(pipeline: SimulatorPipeline) -> None:
    """Periodically check for resolved markets and settle positions."""
    while True:
        try:
            await pipeline.settle_resolved_markets()
        except Exception:
            logger.exception("settlement_loop_error")
        await asyncio.sleep(120)  # Check every 2 minutes
```

And subscribe to the new resolution event for immediate settlement:

```python
async def _resolution_event_loop(pipeline: SimulatorPipeline, redis) -> None:
    async for event in subscribe(redis, CHANNEL_MARKET_RESOLVED):
        market_id = event.get("market_id")
        if market_id:
            logger.info("triggered_by_resolution", market_id=market_id)
            try:
                await pipeline.settle_resolved_markets()
            except Exception:
                logger.exception("resolution_settlement_error", market_id=market_id)
```

Update `main()` to include both:

```python
await asyncio.gather(
    _periodic_loop(pipeline, settings.simulator_interval_seconds),
    _snapshot_loop(pipeline),
    _event_loop(pipeline, redis),
    _settlement_loop(pipeline),           # NEW
    _resolution_event_loop(pipeline, redis),  # NEW
)
```

---

## Step 8: Add Settlement Config ✅

**File:** `shared/config.py` (lines 55-56)

```python
# Settlement settings
resolution_price_threshold: float = 0.98    # price above this = inferred resolved
settlement_interval_seconds: int = 120      # how often to check for resolved markets
```

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| `shared/models.py` | Add `resolved_outcome`, `resolved_at` to `Market`; make `PaperTrade.opportunity_id` nullable |
| `shared/events.py` | Add `CHANNEL_MARKET_RESOLVED` |
| `shared/config.py` | Add settlement config params |
| `services/simulator/portfolio.py` | Add `close_position()` method |
| `services/simulator/pipeline.py` | Add `settle_resolved_markets()`; add rebalancing exit PNL tracking in `simulate_opportunity()` |
| `services/simulator/main.py` | Add `_settlement_loop()` and `_resolution_event_loop()` to `asyncio.gather()` |
| `services/ingestor/polling.py` | Add price-inference resolution detection |
| `services/ingestor/gamma_client.py` | No changes needed (already supports `closed=True`) |
| SQL migration | `ALTER TABLE` for new columns + nullable FK |

---

## Execution Order (all complete)

1. ✅ **Schema migration** (Step 6) — `alembic/versions/004_settlement_schema.py`
2. ✅ **Portfolio.close_position()** (Step 2) — `services/simulator/portfolio.py`
3. ✅ **Events + Config** (Steps 3c, 8) — `CHANNEL_MARKET_RESOLVED` + config settings
4. ✅ **Resolution detection in ingestor** (Step 3a, 3b) — price inference + Gamma API
5. ✅ **settle_resolved_markets()** (Step 4) — closes positions at 0/1 settlement prices
6. ✅ **Rebalancing exits** (Step 5) — `purge_contaminated_positions()` for audit trail
7. ✅ **Wire into main loop** (Step 7) — periodic + event-driven settlement loops
8. ✅ **Test** — realized PNL updates, win rate increments, positions clean up
