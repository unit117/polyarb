# Classifier Eval V4 Plan

**Date:** 2026-03-24  
**Purpose:** Replace noisy Round 3 leaderboard-chasing with an accuracy-first evaluation plan that separates classifier quality from backtest artifacts and market-luck effects.

---

## 1. Why V4

Round 3 exposed three problems:

1. **Backtest integrity is not clean enough yet.** The deep inspection found a resolved-market reopening path in the backtest, which can inflate PnL for models that keep classifying stale markets as tradable.
2. **Pnl is a bad primary ranking metric for classifiers.** A model can "win" because it overweights one lucky cluster, not because it classifies dependencies better.
3. **The current dataset slice is too blunt.** The `--max-markets 5000` import path in [`backtest_from_dataset.py`](/Users/unit117/Dev/polyarb/scripts/backtest_from_dataset.py#L107) and [`backtest_from_dataset.py`](/Users/unit117/Dev/polyarb/scripts/backtest_from_dataset.py#L429) ranks by raw volume, not by evaluation usefulness. That is popularity sampling, not classifier benchmarking.

V4 fixes this by splitting evaluation into two tracks:

- **Gold track:** hand-labeled ground truth, measures classification accuracy directly
- **Silver track:** curated backtest dataset, measures downstream tradability after the measurement pipeline is trustworthy

Backtest PnL becomes a secondary metric, not the primary truth source.

### Verified constraints from the current Becker import

These are now confirmed from the live `polyarb_backtest` DB and a sampled Becker Parquet file:

- all 5000 imported markets currently have `event_id = NULL`
- all 5000 imported markets currently have `liquidity = NULL`
- all 5000 imported markets are binary
- the sampled Becker `markets_*.parquet` schema has no `event_id`, `event_slug`, `group_slug`, or equivalent grouping column

So V4 cannot depend on `event_id` or liquidity filters unless those fields are derived or imported from another source.

---

## 2. V4 Goals

### Primary goals

- Measure classifier quality directly with precision/recall/F1 on a labeled pair set
- Eliminate resolved-market contamination from backtest results
- Create a curated market universe that tests the pair types we actually care about

### Secondary goals

- Re-run the best candidate models on a corrected backtest
- Isolate the Sonnet adapter issue only after the backtest path is clean
- Produce eval artifacts that are reusable for future rounds

### Non-goals

- Do not optimize live trading yet
- Do not spend money on more Sonnet reruns before the measurement path is fixed
- Do not use full-universe PnL as the only model-selection criterion

---

## 3. V4 Structure

V4 has four phases:

1. **Measurement hygiene**
2. **Gold set creation**
3. **Silver dataset curation**
4. **Corrected model evaluation**

Each phase has an explicit gate. Do not move to the next phase until the previous gate is satisfied.

---

## 4. Phase 1: Measurement Hygiene

### Objective

Make the backtest safe enough that repeated runs mean the same thing.

### Required fixes

#### 1. Block trading on resolved markets

In [`scripts/backtest.py`](/Users/unit117/Dev/polyarb/scripts/backtest.py):

- [`get_prices_at`](/Users/unit117/Dev/polyarb/scripts/backtest.py#L57) uses the latest snapshot at or before `as_of`
- [`detect_opportunities`](/Users/unit117/Dev/polyarb/scripts/backtest.py#L86) does not exclude already-resolved markets
- [`simulate_opportunity`](/Users/unit117/Dev/polyarb/scripts/backtest.py#L264) runs before settlement
- [`settle_resolved_positions`](/Users/unit117/Dev/polyarb/scripts/backtest.py#L412) only closes positions after that day's simulation

Fix options:

- Best: exclude any pair where either market has `resolved_at <= as_of` during detection
- Also safe: refuse to simulate opportunities if either leg is already resolved
- Optional extra guard: settle resolved positions before simulation each day

#### 2. Add explicit invariant logging

Add a warning or hard fail if:

- a trade is executed on a market with `resolved_at <= as_of`
- a pair is re-opened after all involved markets are resolved

#### 3. Add regression coverage

Add a unit or integration test proving:

- a resolved market cannot generate new trades on later dates
- a previously resolved pair cannot repeatedly settle across multiple days

### Gate for Phase 1

Before moving on:

- rerun a short backtest around the suspicious Jan 15-Jan 24 window
- confirm the repeated `871/2383` settlement loop is gone
- confirm no trades are executed on resolved markets

---

## 5. Phase 2: Gold Set

### Objective

Build a small, trusted, hand-labeled dataset that measures classification quality directly.

### Target size

- **150-200 labeled pairs**

That is large enough to compare models, small enough to label in a few hours.

### Why this matters

Gold-set metrics are the closest thing to "guaranteed results" here. They do not depend on price-path luck, stale snapshots, or optimizer sizing. If a model misclassifies the pair, it loses. If it classifies correctly, it wins.

### Pair composition

The gold set should be stratified, not random.

Include roughly:

- **40-50 implication** pairs
- **30-40 mutual exclusion** pairs
- **20-30 partition** pairs
- **20-30 conditional** pairs
- **30-40 none** hard negatives

### Family coverage

Prioritize these families:

- BTC threshold ladders on the same month
- Fed rate-cut count ladders
- Date-window nesting markets
- Same-event duplicate winner markets
- Sports winner vs game/map winner
- Sports O/U vs BTTS
- Same-team, nearby-match negatives

Because the current Becker market parquet has no event-group field, grouping must initially use:

- regex family extraction from `question`
- `slug` pattern matching
- manual family tagging for gold-set review

### Explicit exclusions

Do not waste gold-set space on junk examples:

- missing-question or malformed markets
- markets without enough text to reason about
- obviously duplicate rows with no classifier challenge

### Artifacts

Use the existing evaluation path in [`eval_classifier.py`](/Users/unit117/Dev/polyarb/scripts/eval_classifier.py) instead of inventing a new format.

Deliverables:

- `scripts/eval_data/labeled_pairs_v4.json`
- short labeling guide for dependency semantics
- model score table with macro F1 and per-class F1

### Gold metrics

Primary:

- macro F1
- per-class precision/recall/F1
- false-positive rate on `none`

Secondary:

- confusion matrix
- pair-family breakdown

### Gate for Phase 2

Do not proceed until:

- at least 150 pairs are labeled
- each dependency type has meaningful coverage
- at least 30 `none` pairs are included as hard negatives

---

## 6. Phase 3: Silver Dataset

### Objective

Create a cleaner backtest universe that is broad enough to matter, but curated enough to reflect classifier quality instead of random market mix.

### Core change

Stop using pure top-volume market selection as the main sampling method.

The current importer in [`backtest_from_dataset.py`](/Users/unit117/Dev/polyarb/scripts/backtest_from_dataset.py#L107) does:

- `ORDER BY volume DESC NULLS LAST`
- `LIMIT max_markets`

That should become a **stratified market universe builder**.

### Silver selection rules

Keep markets that are:

- resolved within the backtest window
- have enough volume
- have usable text
- belong to families likely to produce informative pairs

Prefer markets from:

- politics
- crypto thresholds
- economics / macro ladders
- sports winner / game winner / totals families

### Pair-level curation rules

Keep pairs that are:

- `verified = true`
- mostly `implication`, `mutual_exclusion`, `partition`
- selected `conditional` pairs only after correlation validation

Use [`validate_correlations.py`](/Users/unit117/Dev/polyarb/scripts/validate_correlations.py#L27) to downgrade weak or contradicted conditional pairs before backtesting.

### Important correction to the earlier pair filters

Do **not** use these as primary SQL filters in the current Becker-backed DB:

- `event_id IS NOT NULL`
- `liquidity >= X`
- `jsonb_array_length(outcomes) = 2`

Why:

- `event_id` is null for the imported Becker markets
- `liquidity` is null for the imported Becker markets
- all 5000 imported markets are already binary

The useful initial pair-level filters are instead:

- `verified = true`
- `dependency_type IN ('implication', 'mutual_exclusion', 'partition')`
- both markets resolved in-window
- question-pattern exclusions for noisy sports correlation structures
- optional regex inclusion for known deterministic families

### Recommended universes

Maintain three DB universes:

- **Gold DB**: only labeled gold pairs, for direct classification scoring
- **Silver DB**: curated tradable pairs, for corrected backtests
- **Full DB**: broad market slice, for later stress testing only

### Manual curation shortcut

If we want a fast path before script changes, create a curated pair whitelist in a cloned DB:

- deterministic ladders
- same-event winner duplicates
- clean date-window implications
- validated conditional sports pairs only

This can be done with SQL first, then automated later.

Recommended first-pass SQL:

```sql
SELECT mp.id, mp.dependency_type,
       ma.question AS q_a, mb.question AS q_b
FROM market_pairs mp
JOIN markets ma ON ma.id = mp.market_a_id
JOIN markets mb ON mb.id = mp.market_b_id
WHERE mp.verified = true
  AND mp.dependency_type IN ('implication', 'mutual_exclusion', 'partition')
  AND ma.resolved_outcome IS NOT NULL
  AND mb.resolved_outcome IS NOT NULL
  AND lower(ma.question) !~ 'over|under|both teams to score|spread|handicap'
  AND lower(mb.question) !~ 'over|under|both teams to score|spread|handicap';
```

Then manually tag the output into:

- true gold
- maybe gold
- noisy / exclude

### Gate for Phase 3

Before evaluation:

- silver dataset has diverse families, not one dominant cluster
- there are enough conditional candidates to test that class seriously
- pair count is large enough to backtest, but small enough to inspect manually if needed

Target:

- **1000-2500 markets**
- **500-1500 useful pairs**

---

## 7. Phase 4: Corrected Evaluation

### Objective

Rerun model comparison only after the measurement path and dataset are clean.

### Pair-subset execution note

The current [`backtest.py`](/Users/unit117/Dev/polyarb/scripts/backtest.py) loads all verified pairs from the DB. There is no `--pair-ids` or `--pair-table` selector yet.

So the practical V4 execution options are:

- clone the backtest DB and mark non-target pairs unverified, or
- add a backtest flag to restrict pair IDs or a pair source table

The clone-and-unverify approach is the fastest path. A proper selector flag is still worth adding.

### Run order

#### Step 1: Gold-set scoring

Run all candidate models on the labeled gold set.

Decision:

- eliminate models with poor macro F1 or high false-positive rate on `none`

#### Step 2: Silver backtest

Run only the surviving models on the curated silver dataset.

Decision:

- compare corrected PnL, Sharpe, drawdown, and opportunity quality

#### Step 3: Sonnet adapter isolation

Only after Steps 1 and 2:

- rerun Sonnet on `openai_generic`
- compare against Sonnet `claude_xml`
- use the fixed backtest and the same curated silver dataset

This avoids paying for a rerun on a measurement stack we already know is compromised.

### Initial model shortlist for V4

Run these first:

- Sonnet 4
- Qwen3 Max
- Qwen3.5-122B
- Gemini 2.5 Flash
- M2.7

Use gpt-4.1-mini as the baseline comparator.

---

## 8. Success Criteria

V4 is successful if it produces:

1. a gold-set ranking that is stable and defensible
2. a silver backtest ranking that does not depend on obvious artifacts
3. enough pair-family detail to explain why a model wins

Concrete signs of success:

- no resolved-market reopening in logs
- no single stale cluster dominating realized PnL
- conditional performance can be measured directly on labeled pairs
- Sonnet adapter decision can be made on clean evidence

---

## 9. Deliverables

### Reports

- `reports/classifier_v4_plan_2026-03-24.md`
- `reports/classifier_goldset_results_YYYY-MM-DD.md`
- `reports/classifier_silver_backtest_YYYY-MM-DD.md`

### Data

- `scripts/eval_data/labeled_pairs_v4.json`
- curated silver market/pair selection manifest

### Code

- backtest resolved-market fix in [`backtest.py`](/Users/unit117/Dev/polyarb/scripts/backtest.py)
- dataset-curation changes in [`backtest_from_dataset.py`](/Users/unit117/Dev/polyarb/scripts/backtest_from_dataset.py)
- optional question-family extraction helper for grouping markets without `event_id`
- optional helper script for whitelisting or exporting gold/silver universes
- optional `--pair-ids` or `--pair-table` support in [`backtest.py`](/Users/unit117/Dev/polyarb/scripts/backtest.py)

---

## 10. Recommended Execution Order

1. Fix resolved-market backtest bug
2. Add regression test for resolved-market trading
3. Export and label the gold set
4. Score all candidate models on the gold set
5. Build silver dataset selection logic
6. Run corrected silver backtests for shortlisted models
7. Run paid Sonnet `openai_generic` isolation only after the above

---

## 11. Practical Decision

If the goal is to get a trustworthy answer quickly:

- **fastest trustworthy path:** Phase 1 + Phase 2
- **best full benchmark path:** all four phases

If we have to choose one thing to do next, it should be:

**fix the backtest and build the gold set.**

That gives us one trustworthy downstream metric and one trustworthy direct metric, which is enough to stop optimizing against noise.
