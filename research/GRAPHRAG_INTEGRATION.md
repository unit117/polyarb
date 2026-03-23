# Improving Detector Pair Recall

## Context

Investigated whether MiroFish-style GraphRAG could improve PolyArb's detector.
Conclusion: **no**. The original proposal targeted the wrong bottleneck and
proposed soft causal edges that don't produce the hard logical constraints
the optimizer needs.

This revised doc captures the actual issues found and a cheaper corrective path.

## Issue 1: Hardcoded k=5 in pgvector KNN search

Two-part mismatch in `services/detector/similarity.py`:

1. **Hardcoded neighbor fanout (line 54):** The KNN query passes `"k": 5`
   instead of using the `top_k` parameter. Each anchor sees at most 5
   nearest neighbors regardless of configuration.

2. **Global cap vs per-query semantics (line 84):** `top_k` *is* used — but
   as a global stop condition (`if len(results) >= top_k: break`), capping
   total output across all anchors. So `top_k=20` means "stop after 20
   total candidates from all anchors combined," not "20 neighbors per anchor."

```python
# Line 53-54 — neighbor fanout hardcoded to 5
neighbors = await session.execute(
    knn_query, {"anchor_id": anchor.id, "k": 5}  # should be "k": top_k
)

# Line 84 — top_k used as global output cap, not per-anchor
if len(results) >= top_k:
    break
```

**Impact:** With `batch_size=100` anchors and `k=5`, the search examines at
most 500 neighbor slots per cycle (minus duplicates and existing pairs). The
global cap of 20 means the first 4-20 anchors (depending on hit rate) exhaust
the budget and the remaining anchors are never searched.

Some of the "missed pairs" attributed to embedding limitations may simply be
pairs that rank 6th–20th in similarity per anchor and never get evaluated, or
pairs involving anchors that come late in the random ordering.

**Fix:** Two changes:

1. Replace `"k": 5` with `"k": neighbor_k` on line 54.
2. Split `top_k` into two separate settings in `shared/config.py`:
   - `similarity_neighbor_k: int = 20` — per-anchor KNN fanout (how many
     neighbors each anchor examines)
   - `similarity_candidate_cap: int = 50` — global output cap per cycle
     (max candidates emitted to classifier)

   The current code overloads one variable for both roles. Even after fixing
   the hardcoded 5, keeping a single knob means tuning neighbor depth forces
   a change to the cycle output budget and vice versa. These are independent
   concerns: neighbor_k controls recall depth, candidate_cap controls
   downstream load on the classifier.

**Validation before/after:**

`find_similar_pairs()` samples anchors with `ORDER BY RANDOM()` (line 24),
so a single k=5 run vs a single k=20 run is confounded by different anchor
sets. Two options to get a clean comparison:

1. **Pin the anchor set:** Temporarily replace `ORDER BY RANDOM()` with a
   deterministic ordering (e.g., `ORDER BY id`) for both runs, so the only
   variable is k. Restore randomness after measurement.
2. **Aggregate over many runs:** Run ≥20 cycles at each k setting and compare
   distributions (mean candidates, mean verified pairs, mean LLM calls).

For each run, log:
- Anchor IDs used (to detect overlap between runs)
- Candidate count and similarity scores
- Classification outcomes by source (rule_based / llm_vector / llm_label)
- Verification pass/fail and profit_bound

This should be done **before** any structural changes to the candidate pipeline.

## Issue 2: Existing rule-based coverage is already substantial

The classifier (`services/detector/classifier.py:524`) already handles these
structural patterns deterministically, with no LLM:

| Rule | Pattern | Confidence |
|------|---------|------------|
| `_check_same_event` | Shared event_id + overlapping outcomes → partition | 0.95 |
| `_check_outcome_subset` | One market's outcomes ⊆ another's → partition | 0.85 |
| `_check_crypto_time_intervals` | Same asset, different time windows → none | 0.95 |
| `_check_price_threshold_markets` | "PLTR above $128" vs "$134" → implication | 0.95 |
| `_check_milestone_threshold_markets` | "YouTube subs above 475M" vs "477M" → implication | 0.95 |
| `_check_ranking_markets` | "Top 10" vs "Top 20" → implication | 0.95 |
| `_check_over_under_markets` | O/U 1.5 vs O/U 2.5 → implication | 0.95 |

These are exactly the kind of hard logical constraints that produce valid
feasibility matrices. Adding a generic entity graph would not improve on
these — it would add a fuzzier version of what already exists.

## Issue 3: Why GraphRAG is wrong here

The original proposal included examples like:
- "Fed cuts rates" ↔ "Mortgage rates fall" — **causal correlation, not logical constraint**
- "AI regulation passes" ↔ "NVDA above $200" — **speculative impact, not provable**

These cannot produce binary feasibility matrices. There is no joint outcome
that is *logically impossible* — rates can be cut while mortgages stay flat
(banks don't pass through), regulation can pass while NVDA rises (already
priced in). The optimizer needs `constraint_matrix.profit_bound > 0` from
excluded joint outcomes. Soft edges produce no excluded outcomes.

Additionally:
- LLM entity extraction **adds** token spend instead of reducing it
- `CHANNEL_MARKET_UPDATED` is a batch sync event `{action:"sync", count:int}`,
  not a per-market stream — a KG builder would need new event plumbing
- Shared entities like "Trump", "BTC", "NBA" create high-degree fan-out nodes
  that expand candidate volume without improving precision
- NetworkX is not in `services/detector/requirements.txt` and an in-memory
  graph needs bootstrap/invalidation/restart recovery logic

## Recommended Path

### Step 1: Fix k=5 bug and measure impact

Changes in `similarity.py` and `shared/config.py`:
```python
# shared/config.py — split the overloaded knob
similarity_neighbor_k: int = 20          # per-anchor KNN fanout
similarity_candidate_cap: int = 50       # global output cap per cycle

# similarity.py line 54 — use neighbor_k for fanout
neighbors = await session.execute(
    knn_query, {"anchor_id": anchor.id, "k": neighbor_k}
)

# similarity.py line 84 — use candidate_cap for global stop
if len(results) >= candidate_cap:
    break
```

Add logging to measure before/after, broken down by `classification_source`
(`rule_based`, `llm_vector`, `llm_label`):
- Candidate count per cycle
- Candidates classified via each source (rule_based / llm_vector / llm_label)
- Candidates surviving verification, by classification source
- LLM calls per cycle (vector + label fallback separately)
- New verified pairs with profit_bound > 0

The source breakdown matters: if extra recall mostly lands in `llm_label`
(the lowest-confidence fallback path, capped at 0.70), the gain is fragile.
If it lands in `rule_based` or `llm_vector`, the gain is robust.

If k=20 materially increases verified opportunities, the embedding recall
was the bottleneck and no structural changes are needed yet.

### Step 2: Deterministic `market_features` extraction

If improved neighbor_k is not sufficient, add **regex/rule-based feature
extraction** (no LLM) as a complement to embedding similarity. Extract
structured predicates from market questions at ingest time.

**Phase this in two stages:**

#### Phase 2a: Threshold/ranking/O-U/time-window features (ship first)

These predicate families are natural extensions of existing classifier regexes
(`_check_price_threshold_markets`, `_check_milestone_threshold_markets`,
`_check_ranking_markets`, `_check_over_under_markets`, `_check_crypto_time_intervals`).
The extraction logic already exists — it just runs post-similarity instead of
at ingest time.

```python
@dataclass
class MarketFeatures:
    market_id: int
    subject: str | None       # "PLTR", "Bitcoin", "YouTube subscribers"
    predicate: str | None     # "above", "Top N", "O/U"
    threshold: float | None   # 128.0, 475_000_000, 10, 2.5
    date: str | None          # "2026-03-21"
    time_window: str | None   # "3:15AM-3:30AM"
    direction: str | None     # "above", "below", "over", "under"
```

**Storage:** Dedicated `market_features` table with indexed columns, not
JSONB on the markets row. The discovery queries below need relational joins
with indexed equality checks — opaque JSON would require functional indexes
or runtime extraction, which defeats the purpose.

```sql
CREATE TABLE market_features (
    id SERIAL PRIMARY KEY,
    market_id INTEGER NOT NULL REFERENCES markets(id) UNIQUE,
    subject VARCHAR(255),
    predicate VARCHAR(50),
    threshold DOUBLE PRECISION,
    date VARCHAR(20),
    time_window VARCHAR(30),
    direction VARCHAR(10)
);

CREATE INDEX idx_mf_subject ON market_features(subject);
CREATE INDEX idx_mf_predicate ON market_features(predicate);
CREATE INDEX idx_mf_subject_predicate ON market_features(subject, predicate);
```

**Candidate discovery via features:**

Matching requires the full predicate signature to prevent fan-out:

```sql
-- Markets with same predicate family, subject, direction, and date/window
-- but different thresholds → candidate implication chain
SELECT a.market_id, b.market_id
FROM market_features a
JOIN market_features b
  ON  a.subject = b.subject
  AND a.predicate = b.predicate         -- same family (above, Top N, O/U)
  AND a.direction = b.direction          -- both "above" or both "below"
  AND a.market_id < b.market_id
  AND COALESCE(a.date, '') = COALESCE(b.date, '')           -- same date or both null
  AND COALESCE(a.time_window, '') = COALESCE(b.time_window, '')  -- same window or both null
  AND a.threshold IS DISTINCT FROM b.threshold               -- different threshold
WHERE a.market_id = ANY(:anchor_ids)
  AND NOT EXISTS (
    SELECT 1 FROM market_pairs
    WHERE market_a_id = a.market_id AND market_b_id = b.market_id
  )
LIMIT :candidate_cap;
```

The tight guards (predicate family, direction, date, time window) prevent
the fan-out problem. "BTC above $90k on March 21 3:15AM" only matches other
"BTC above $X on March 21 3:15AM" markets, not all BTC markets.

#### Phase 2b: Event-slot exclusion (only if Phase 2a shows recall lift)

Event-slot extraction (e.g., "Lakers win NBA" → event_slot="NBA Championship")
is harder than threshold extraction. It requires venue-specific knowledge of
how Polymarket structures event groups, and the extraction is fuzzier — "win
the NBA" vs "win the championship" vs "take the title" all mean the same slot
but don't pattern-match trivially.

Only add this if Phase 2a demonstrates that feature-based candidates produce
verified opportunities that embeddings miss. If threshold/ranking/O-U features
don't show recall lift, event-slot features (which are harder to extract
correctly) are unlikely to either.

```sql
-- Phase 2b only: markets competing for same singular event slot
ALTER TABLE market_features ADD COLUMN event_slot VARCHAR(255);
CREATE INDEX idx_mf_event_slot ON market_features(event_slot);

SELECT a.market_id, b.market_id
FROM market_features a
JOIN market_features b
  ON  a.event_slot = b.event_slot
  AND a.predicate = b.predicate
  AND a.subject != b.subject             -- different subject, same slot
  AND a.market_id < b.market_id
  AND COALESCE(a.date, '') = COALESCE(b.date, '')
WHERE a.market_id = ANY(:anchor_ids)
  AND NOT EXISTS (
    SELECT 1 FROM market_pairs
    WHERE market_a_id = a.market_id AND market_b_id = b.market_id
  )
LIMIT :candidate_cap;
```

**Key difference from the GraphRAG proposal:** Features are *predicates about
markets* (subject + predicate + threshold + direction + date + window), not
*entities in a graph*. The relations are implicit in matching predicate
signatures, not stored as edges. This avoids the entity normalization problem
and the high-degree-node fan-out.

### Step 3: Shadow evaluation

Run feature-based candidates in shadow mode alongside pgvector:
- Log feature-only candidates separately
- Pass them through the existing classifier and verifier
- Measure:
  - **Recall improvement**: pairs found by features but not embeddings
  - **Precision**: what fraction survive classification + verification
  - **LLM volume**: no ingest-time LLM cost (feature extraction is
    deterministic), but classifier LLM cost will rise with candidate count
    since more candidates = more `llm_vector` / `llm_label` calls for pairs
    that don't match any rule-based pattern
  - **Opportunity yield**: new verified pairs with profit_bound > 0

Only promote feature-based candidates to the live pipeline if precision
holds and opportunity yield is positive.

### What about GraphRAG in the future?

Revisit only if:
1. Steps 1-3 are implemented and measured
2. There's a documented corpus of missed pairs that are neither embedding-
   recoverable (k=20) nor feature-recoverable (structured predicates)
3. Those missed pairs have hard logical constraints (not just correlation)
4. The volume of such pairs justifies the added LLM spend and infrastructure

Until then, the simpler path is better.
