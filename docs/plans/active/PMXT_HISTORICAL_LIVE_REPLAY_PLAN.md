# PMXT Historical Live Replay Follow-Up Plan

**Status:** Draft v5 — Phase 0 complete
**Date:** 2026-03-26
**Supersedes:** replay-first Draft v3 ordering in this file, plus detector-first `polyarb_detector_improvement_plan_v2.docx`

## 1. Executive Summary

The right follow-up is **not** a four-week replay rewrite starting with simulator refactors.

The current V4 work already answered one question:

- `anthropic/claude-sonnet-4` is the current production pick
- `qwen3-max` is the best fallback / shadow candidate
- the silver backtest is still non-informative (`0` trades)

So the next unknown is no longer "which LLM is best." The real unknown is:

- what live-only market context is missing from current detection / verification
- whether PMXT historical data materially improves decision quality
- whether a live-style replay is worth the implementation cost

That changes the order of work.

### Recommended sequence

1. Audit PMXT archive coverage and schema
2. Capture a real live shadow dataset from current Polymarket traffic
3. Build one thin-slice PMXT replay spike on a recent window
4. Decide whether a full replay refactor is justified
5. Only then consider the broader execution-sink rewrite

This keeps the PMXT direction, but it avoids committing the repo to a large simulator change before we have proof that PMXT data is the missing lever.

## 2. Why The Earlier Replay-First Ordering Needs Correction

The earlier replay-first framing was directionally right about one thing:

- the current historical backtest is not execution-realistic

That remains true. `scripts/backtest.py` still executes synthetic paper trades directly from historical snapshots, while `services/simulator/pipeline.py` and `services/simulator/live_coordinator.py` represent the live-style order / fill ledger path.

But the earlier ordering still jumped too early to the architecture-heavy work.

### Correction 1: we still have an evidence problem, not only an execution-path problem

The current classifier result is usable for model selection, but not strong enough to trust as a standalone trading gate.

The missing information may come from:

- live order book depth
- spread / liquidity
- trade recency
- event metadata only visible or easier to join via live APIs / PMXT
- verification rules informed by current market microstructure

Before a large replay rewrite, we should prove which of those fields actually changes decisions.

### Correction 2: the current silver backtest cannot rank models

The V4 silver path produced `0` trades. That means backtest PnL is not currently a reliable model-ranking signal. So a full replay project should not be justified as "needed immediately for model choice." That decision is already made.

### Correction 3: PMXT archive value must be proven before simulator surgery

PMXT may still be the right historical source for better replay realism. But the costliest part of the earlier plan was:

- extracting execution sinks from the simulator
- introducing replay execution infrastructure
- building a generalized oldest-to-latest runner

That should happen only after a smaller proof shows the replay is likely to produce materially better answers than today's daily backtest plus live review queue.

## 3. Primary Questions This Follow-Up Must Answer

The plan succeeds only if it answers these questions in order:

1. What PMXT historical data actually exists?
2. Which live-only fields are missing from today's verification and ranking decisions?
3. Does PMXT data materially improve our ability to evaluate those decisions?
4. Can we prove one live-style historical order path end-to-end without rewriting the whole simulator?
5. Is a full replay refactor actually the highest-leverage next investment after that?

## 4. Principles

- Prefer evidence before architecture
- Freeze the current model choice while data work proceeds
- Separate decision-quality work from fill-realism work
- Use isolated replay state, never the operational live database
- Keep the daily backtest as the coarse regression harness until a replay path clearly beats it
- Minimize core simulator churn until the thin slice proves out

## 5. Current Code Reality

### Historical path today

- `scripts/backtest.py` replays day-by-day over `price_snapshots`
- it computes fills directly and writes `PaperTrade` rows itself
- it does not model live order submission, pending orders, or reconciliation

### Live path today

- `services/simulator/pipeline.py` builds `ValidatedExecutionBundle`
- `services/simulator/live_coordinator.py` persists live order intent and confirmed fills
- `services/simulator/live_reconciler.py` turns venue state into fill events
- dashboard and portfolio snapshots already distinguish `source="paper"` vs `source="live"`

### Architectural implication

The repo is already partway to a realistic live ledger. The question is not whether replay is imaginable. The question is whether a full replay is worth paying for now.

## 6. Recommended Order Of Work

1. PMXT archive audit
2. Live shadow logger + review queue
3. Thin-slice PMXT replay spike
4. Decision gate
5. Only if justified: execution-sink extraction and broader replay runner

Do **not** start with the simulator refactor.

## 7. Phase 0 - PMXT Archive Audit — COMPLETE

**Completed:** 2026-03-26

### Artifacts

- `scripts/pmxt_archive_audit.py`
- `scripts/pmxt_filter.py`
- `docs/research/pmxt_archive_audit_2026-03-25.md`
- `docs/research/pmxt_archive_audit_2026-03-25_local_sample.md`
- Mar 21 2026 data: `/volume1/docker/polyarb/pmxt_db/polymarket/2026-03-21/` (24 files, 11GB)

### Key findings

**Archive scope:**
- PMXT publishes **orderbook only** — no trades dataset exists. Confirmed by inspecting the archive listing at `archive.pmxt.dev`.
- Files are hourly snapshots: `polymarket_orderbook_YYYY-MM-DDTHH.parquet`
- Schema columns: `data` (JSON), `market_id`, `timestamp_created_at`, `timestamp_received`, `update_type`
- ~30k distinct markets per hourly file, ~18-31M rows per file, 350-600MB compressed

**ID space mismatch (critical for replay):**
- PMXT `market_id` = CTF condition_id hex (`0x00000977...`)
- DB `polymarket_id` = Gamma numeric ID (`1003190`)
- These do **not** match. Join key is `data.token_id` (large decimal) matching DB `markets.token_ids`.
- `pmxt_filter.py` primary market_id filter is a no-op; all matching works through token_id secondary path.

**Coverage against live DB (from T12 midday snapshot):**

| Metric | Value |
|---|---|
| PMXT distinct condition_ids | 16,604 |
| PMXT distinct token_ids | 33,208 |
| Token_ids matched to DB | 33,208 / 33,208 (100%) |
| DB markets with PMXT data | 16,604 / 53,357 |
| Pairs with both sides in PMXT | 10,527 / 26,155 (40.2%) |
| Pairs with one side only | 810 (3.1%) |
| Pairs with neither side | 14,818 (56.7%) |

**Filter assessment:** Running `pmxt_filter.py` against live DB kept 521M / 521M rows (99.9%). Filtering is unnecessary — use raw files directly.

**Implications for Phase 1:**
- 10.5k pairs with full coverage is ample for thin-slice replay
- No fill realism possible (no trades data) — replay limited to orderbook best bid/ask
- Replay script must join on `token_id`, not `market_id`
- R2 direct download works: `https://r2.pmxt.dev/polymarket_orderbook_YYYY-MM-DDTHH.parquet`
- Mar 22-23 data (48 more files, ~22GB) available if Mar 21 proves the pipeline

## 8. Phase 0.5 - Live Shadow Logger And Review Queue — IN PROGRESS

**Started:** 2026-03-27
**Implementation:** Codex built migration, model, pipeline hooks, export script. Claude aligned model to migration schema and enabled in live .env.

### Objective

Capture real candidate pairs from live Polymarket traffic before changing the simulator.

### Why this comes before replay

This is the cheapest way to answer what is actually missing from the current system:

- market microstructure fields
- event grouping metadata
- stale pair invalidation behavior
- classifier false positives / false negatives on real traffic
- verification failures caused by live prices or depth

### Work

Add a lightweight shadow logging path that records candidate-pair review rows for `3-7` days of normal live operation.

Use a concrete storage choice:

- persist shadow rows in a dedicated Postgres table, for example `shadow_candidate_logs`
- keep JSONL as an export format for manual review, not the primary write path

Why this is the default:

- the repo already relies on Postgres for operational state
- query/filtering by timestamp, pair, verification reason, and market metadata will be much easier from SQL
- a single export script can materialize review-ready JSONL from the table later

Each row should capture:

- timestamp
- pair ID, market IDs, event IDs / slugs
- market questions / normalized titles
- dependency type predicted by current classifier
- classifier confidence and model metadata
- verification result and rejection reason
- current prices, spread, visible depth, liquidity proxies
- last trade recency if available
- whether the pair would have been passed to optimization
- whether the pair would have traded under current gates
- whether the pair failed for the same verification reasons currently causing the silver set to produce `0` trades

Then:

- export the highest-signal `100-200` rows
- manually review them
- classify the main failure modes

### Artifacts (implemented 2026-03-27)

- `alembic/versions/016_shadow_candidate_logs.py` — 51-column table with order book, classifier, verification, optimizer preview fields
- `shared/models.py` — `ShadowCandidateLog` model aligned to migration
- `services/detector/shadow_logging.py` — order book summary, silver failure signatures, optimizer preview gate
- `services/detector/pipeline.py` — `_log_shadow_candidate()` called at every decision point (classified_none, uncertainty_filtered, verification_failed, profit_non_positive, detected)
- `scripts/export_live_shadow_queue.py` — exports top-N rows by review priority to JSONL with summary stats
- `shared/config.py` — `shadow_logging_enabled` (default false), `shadow_logging_optimizer_preview` (default true)
- `.env` — enabled on live (`SHADOW_LOGGING_ENABLED=true`)

### Remaining artifacts

- `docs/research/live_shadow_review_2026-03-xx.md` — after 3-7 days of collection
- JSONL exports under a dedicated review output directory as needed

### Acceptance criteria

- we have `3-7` days of real candidate-pair logs
- we have `100-200` manually reviewed live examples
- we can answer which missing fields most often explain bad decisions
- we have an evidence-backed view of whether PMXT archive data would help those cases
- we can quantify how often the shadow queue hits the same verification rejection patterns that currently zero out the silver backtest

## 9. Phase 1 - Thin-Slice PMXT Replay Spike

### Objective

Prove one end-to-end historical live-style execution path on a small recent window before any generalized replay rewrite.

### Scope limits

The spike should stay intentionally narrow:

- one recent PMXT-covered window, ideally `24-72` hours
- a small market set or one resolved event cluster
- one model configuration
- one conservative fill policy
- one isolated replay database, for example `polyarb_replay_spike`

### Explicit non-goals for the spike

- no full simulator execution-sink refactor yet
- no generalized replay framework
- no claim that this replaces the daily backtest
- no dashboard polish beyond basic inspectability

### Work

- load PMXT archive data chronologically for the chosen window (Mar 21 2026, 24 hours)
- join on `data.token_id` → DB `markets.token_ids` (not `market_id`)
- maintain visible state per outcome (best bid/ask from orderbook)
- drive a minimal replay loop oldest-to-latest
- submit one live-style order intent path
- persist pending order state, fills or expirations, and portfolio snapshots
- compare one slice of replay behavior against the current daily backtest on the same window
- note: no trades data exists — fills must be simulated from orderbook state only

### Suggested artifacts

- `scripts/replay_pmxt_spike.py`
- a dedicated replay DB or isolated schema for the spike
- one short comparison write-up

### Acceptance criteria

- we can demonstrate:
  - order intent before fills
  - partial fill or expiration behavior
  - settlement behavior
  - ledger rows inspectable after the run
- we can quantify at least one meaningful difference from the current daily backtest
- we know what extra complexity a generalized replay would require

## 10. Decision Gate After The Thin Slice

Do **not** automatically proceed from the spike to a full replay refactor.

### Go criteria

Proceed to a broader replay implementation only if all of the following are true:

- PMXT archive coverage is good enough for windows we care about
- live shadow review shows that PMXT / live-only fields materially change decisions
- the thin-slice replay runs end-to-end without contorting the codebase
- the resulting differences vs daily backtest are meaningful enough to justify the added complexity

### No-go criteria

Do **not** proceed to a full replay rewrite if any of these are true:

- PMXT coverage is too sparse or too recent
- live shadow review shows the bigger problem is metadata normalization, event clustering, or stale pair handling
- the spike suggests a large simulator rewrite for little expected decision-quality gain
- the daily backtest plus live shadow queue appears sufficient for near-term detector and verification improvements

## 11. Phase 2 - Conditional Full Replay Refactor

Only start this if the decision gate passes.

### Objective

Extract paper, live, and replay into independent consumers of the same validated bundle.

### Rough effort

Assume `1-3 weeks` depending on what the thin slice proves and how much simulator extraction is actually required.

### Likely work

- refactor `services/simulator/pipeline.py` so opportunity preparation is separate from execution sinks
- introduce sink interfaces for:
  - paper execution
  - live execution
  - replay execution
- introduce a generalized replay state store and replay execution adapter
- build a broader oldest-to-latest replay runner
- run at least one `7-day` replay before attempting longer windows

### Acceptance criteria

- replay no longer depends on paper execution happening first
- replay writes live-style ledger outputs in an isolated replay DB
- we can run one recent `7-day` window deterministically

## 12. Timeline

### Week 1 — DONE (2026-03-25 to 2026-03-26)

- Phase 0 archive audit — complete
- Mar 21 data downloaded and verified (24 files, 11GB)
- Filter run confirmed 10.5k pairs with both-side coverage, token_id join path validated
- No trades data exists (confirmed blocker for fill realism)
- Phase 0.5 implementation — complete (2026-03-27), deploy pending

### Week 2 (starting 2026-03-28)

- deploy shadow logging to NAS, run migration 016
- collect shadow data for 3-7 days
- manually review high-signal rows via export script
- decide which PMXT fields matter most

### Week 3

- build the thin-slice PMXT replay spike
- run one recent `24-72` hour window

### Week 4

- write the go / no-go decision
- only if clearly justified, scope the full replay refactor

This is intentionally smaller and more evidence-driven than the earlier four-week replay-first version.

## 13. Risks And Decisions

### Risk 1: PMXT archive does not cover the windows we actually need

Decision:

- support the actual covered window first
- keep the Becker-based daily backtest for older periods

### Risk 1b: PMXT has no trades data (CONFIRMED)

PMXT only publishes hourly orderbook snapshots. No trade records exist. This means:

- fills cannot be simulated from actual trade flow
- replay fill model will be orderbook-derived (best bid/ask crossing)
- execution realism is limited to "would this order have been fillable at the observed book state"
- for tick-level trade data, PredictionData.dev is the only known source (paid)

### Risk 2: PMXT data does not materially change decisions

Decision:

- let the live shadow review answer that before building more architecture

### Risk 3: the thin slice shows replay is valuable but much more expensive than expected

Decision:

- gate the full refactor behind explicit evidence from the spike

### Risk 4: replay data pollutes operational live metrics

Decision:

- isolate replay in a dedicated database from day one

### Risk 5: we lose momentum on detector / verifier improvements while waiting on replay

Decision:

- use the live shadow queue as the parallel improvement input
- do not block small verifier / ranking fixes on the full replay project

### Risk 6: the conditional full replay refactor gets underestimated

Decision:

- treat Phase 2 as a separate effort after the decision gate
- assume a rough implementation range of `1-3 weeks` depending on what the thin slice proves and how much simulator extraction is actually required

## 14. Success Criteria

This follow-up plan succeeds when all of the following are true:

- we know what PMXT historical data actually exists
- we have a reviewed live shadow dataset from real traffic
- we can name the live-only fields that matter most
- we have proven one PMXT-based historical live-style execution slice end-to-end
- we have a decision-ready answer on whether a full replay refactor is worth the cost

If those conditions are met, the next replay step will be justified by evidence instead of architecture preference.

## 15. Bottom Line

The right immediate plan is:

- **not** "rewrite the simulator first"
- **not** "ignore PMXT and keep only the daily backtest"
- **yes** "audit PMXT, capture live shadow evidence, prove a thin replay slice, then decide"

That is the highest-leverage follow-up from the current V4 state.
