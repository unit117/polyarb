# Round 3 Classifier Eval - Deep Inspection

**Date:** 2026-03-24  
**Artifacts inspected:** `eval_results/r3_promptspec_20260324_005806/` and `eval_results/20260323_174343/` on NAS  
**Scope:** Read-only audit of the Round 3 logs plus targeted Postgres lookups on the NAS  
**Primary question:** Which Round 3 results are real signal, and which require rerun before they can be trusted?

---

## 1. Executive Summary

The raw leaderboard is not equally trustworthy across models.

**Most important finding:** M2.7's reported +0.87% result is likely inflated by a backtest artifact. A single stale-snapshot trading cluster involving markets `2383` ("Mavericks vs. Nuggets", resolved **2025-12-02**) and `871` ("Nuggets vs. Mavericks", resolved **2026-01-15**) contributed **+$64.60 net**, or **72% of M2.7's total realized PnL**. The backtest appears to keep reopening resolved markets because detection uses the most recent snapshot at or before `as_of`, and settlement happens after simulation.

**Second finding:** Sonnet 4's collapse is real at the pair-distribution level, not just summary noise. In Round 2, Sonnet's label-path output was dominated by `conditional @ 0.68`. In Round 3 under `claude_xml`, it is dominated by `none @ 0.76`. Of the **249** Sonnet R2 conditional pairs that changed in either round, **239 became `none` in R3**, only **9 stayed conditional**, and **1 became mutual_exclusion**.

**Third finding:** Qwen3 Max looks more credible than M2.7 on the current artifacts. Its PnL is concentrated in interpretable settlement clusters and it shows **no** equivalent post-resolution daily reopening pattern.

**Fourth finding:** Gemini's Sharpe improvement is genuine variance compression. Mean daily return is almost unchanged from R2 to R3, but daily return standard deviation falls by about **62%** (`0.0001406 -> 0.0000534`), which explains the Sharpe jump from `0.51 -> 1.37`.

**Bottom line:** Do **not** spend money on the Sonnet generic rerun yet. First fix the resolved-market backtest bug and rerun at least M2.7, Qwen3 Max, and Sonnet R3. Only after that is it worth paying to isolate `claude_xml` vs `openai_generic`.

---

## 2. Sonnet 4: The Regression Is Real

### Aggregate shift

| Metric | R2 | R3 |
|---|---:|---:|
| Return | +0.84% | +0.07% |
| Sharpe | 1.51 | 0.04 |
| Trades | 136 | 294 |
| Settled | 88 | 18 |
| Conditional pairs | 250 | 10 |

The important change is not trade count. It is classification mix.

### Pair-level transition audit

Reconstructing final Sonnet classifications from the `reclassified pair_id=... transition='old -> new'` lines gives:

| R2 final -> R3 final | Count |
|---|---:|
| `conditional -> none` | **239** |
| `conditional -> conditional` | 9 |
| `conditional -> mutual_exclusion` | 1 |

This is the core of the regression. The conditional inventory did not mainly migrate to implication or partition. It mostly disappeared.

### Confidence regime shift

**Round 2 Sonnet label-path distribution**

- `conditional @ 0.68`: 225
- `mutual_exclusion @ 0.8`: 63
- `none @ 0.76`: 42
- `partition @ 0.8`: 35
- `conditional @ 0.60`: 24

**Round 3 Sonnet label-path distribution**

- `none @ 0.76`: 256
- `mutual_exclusion @ 0.76`: 35
- `mutual_exclusion @ 0.784`: 31
- `mutual_exclusion @ 0.8`: 30
- `none @ 0.68`: 24
- `conditional @ 0.68`: 8

That is too structured to dismiss as normal randomness. The model moved into a different output regime.

### What this proves, and what it does not

This proves:

- Sonnet's Round 3 regression is real in the raw logs.
- The regression is specifically a collapse of conditional classifications.
- The collapse is associated with a strong output-shape change under `claude_xml`.

This does **not** yet prove:

- that `claude_xml` alone is the cause,
- because the content also changed from R2 inline prompts to R3 `prompt_specs`.

The `openai_generic` Sonnet rerun is still the right isolation test. It is just no longer the first test to run.

---

## 3. M2.7: Raw Win, Low Trust

### Headline stats

| Metric | Value |
|---|---:|
| Return | +0.87% |
| Realized PnL | +$89.38 |
| Sharpe | 0.30 |
| Trades | 346 |
| Settled | 45 |
| Positive settlements | 19 |
| Negative settlements | 26 |

The win/loss shape is real: more losing settlements than winning settlements, with a few outsized winners carrying the result.

### Settlement concentration by market

Top realized PnL contributors in the M2.7 backtest log:

| Market ID | Question | Count | PnL |
|---|---|---:|---:|
| 655 | Will 2 Fed rate cuts happen in 2025? | 1 | +144.37 |
| 2383 | Mavericks vs. Nuggets | 14 | +137.31 |
| 923 | Will 1 Fed rate cut happen in 2025? | 1 | -83.04 |
| 871 | Nuggets vs. Mavericks | 10 | -72.71 |
| 698 | Will 3 Fed rate cuts happen in 2025? | 1 | -30.03 |
| 2647 | Will Russia capture all of Pokrovsk by November 30? | 6 | -13.24 |
| 848 | Will 4 Fed rate cuts happen in 2025? | 1 | +12.93 |
| 464 | Will Wicked: For Good be the top grossing movie of 2025? | 1 | +8.26 |
| 1053 | Will 6 Fed rate cuts happen in 2025? | 1 | -7.41 |
| 1712 | Will Russia capture Pokrovsk by August 31? | 6 | -5.82 |

The Fed ladder on **2025-12-10** is legitimate and large:

- net settlement PnL that day: **+$36.82**
- contributing markets: `655`, `923`, `698`, `848`, `1053`

That cluster is real signal. The problem is that it is not the whole story.

### The stale resolved-market cluster

The suspicious cluster is:

- `2383` = "Mavericks vs. Nuggets", resolved at **2025-12-02 02:00:00+00**
- `871` = "Nuggets vs. Mavericks", resolved at **2026-01-15 02:30:00+00**

Postgres confirms the last available price snapshots are:

| Market ID | First snapshot | Last snapshot | Snapshots |
|---|---|---|---:|
| 2383 | 2025-11-28 23:59:59+00 | **2025-12-02 23:59:59+00** | 5 |
| 871 | 2026-01-10 23:59:59+00 | **2026-01-15 23:59:59+00** | 6 |

Yet M2.7 logs repeated settlements on these markets all the way through the simulated end of the backtest:

- `2383` settled **14 times** for **+$137.31**
- `871` settled **10 times** for **-$72.71**
- net contribution of this cluster: **+$64.60**

The daily backtest summaries show the same pattern:

| Sim date | Settled | Settlement PnL | Trades executed |
|---|---:|---:|---:|
| 2026-01-15 | 2 | -14.15 | 2 |
| 2026-01-16 | 2 | +5.29 | 2 |
| 2026-01-17 | 2 | +5.29 | 2 |
| 2026-01-18 | 2 | +5.29 | 2 |
| 2026-01-19 | 2 | +5.29 | 2 |
| 2026-01-20 | 2 | +5.29 | 2 |
| 2026-01-21 | 2 | +5.29 | 2 |
| 2026-01-22 | 2 | +5.29 | 2 |
| 2026-01-23 | 2 | +5.29 | 2 |
| 2026-01-24 | 2 | +5.29 | 2 |

This is not normal market behavior. It is consistent with the backtest reopening already-resolved markets using stale last snapshots.

### Why the code permits this

In [`scripts/backtest.py`](/Users/unit117/Dev/polyarb/scripts/backtest.py):

- [`get_prices_at`](/Users/unit117/Dev/polyarb/scripts/backtest.py#L57) returns the most recent snapshot with `timestamp <= as_of`
- [`detect_opportunities`](/Users/unit117/Dev/polyarb/scripts/backtest.py#L86) does **not** exclude markets whose `resolved_at <= as_of`
- [`simulate_opportunity`](/Users/unit117/Dev/polyarb/scripts/backtest.py#L264) runs **before** settlement
- [`settle_resolved_positions`](/Users/unit117/Dev/polyarb/scripts/backtest.py#L412) closes positions only after simulation for that day

That means a resolved market can still be traded at its stale last pre-resolution price on later days, then immediately settled the same day.

### Impact on trust

If the `2383`/`871` cluster is invalid and removed, M2.7's realized PnL falls from:

- **+$89.38 -> +$24.78**

That would move M2.7 from clear first place to below both Qwen models.

This is the single biggest reason not to trust the current raw leaderboard.

---

## 4. Qwen3 Max: More Plausible Than M2.7

### Headline stats

| Metric | Value |
|---|---:|
| Return | +0.48% |
| Realized PnL | +$49.67 |
| Sharpe | 0.16 |
| Trades | 404 |
| Settled | 30 |
| Positive settlements | 9 |
| Negative settlements | 21 |

### Settlement concentration by market

| Market ID | Question | Count | PnL |
|---|---|---:|---:|
| 655 | Will 2 Fed rate cuts happen in 2025? | 1 | +162.72 |
| 923 | Will 1 Fed rate cut happen in 2025? | 1 | -83.04 |
| 698 | Will 3 Fed rate cuts happen in 2025? | 1 | -30.03 |
| 1287 | Will 5 Fed rate cuts happen in 2025? | 1 | -17.62 |
| 65 | Maduro out in 2025? | 1 | +17.32 |
| 2647 | Will Russia capture all of Pokrovsk by November 30? | 6 | -13.24 |
| 848 | Will 4 Fed rate cuts happen in 2025? | 1 | +12.93 |
| 1712 | Will Russia capture Pokrovsk by August 31? | 6 | -5.82 |
| 375 | Will Bitcoin reach $130k in October? | 1 | +5.68 |
| 400 | Maduro out by November 30, 2025? | 1 | -5.30 |

### Why this looks cleaner

- No `871`/`2383` stale resolved-market cluster
- No repeated Jan 16-24 same-pattern reopening
- Largest gain still comes from the same 2025 Fed ladder family, but that cluster is interpretable and bounded
- The rest of the PnL comes from ordinary one-off settlements, not a daily loop

I would still rerun Qwen after the backtest fix, but its current result is much easier to believe than M2.7's.

---

## 5. Gemini 2.5 Flash: Sharpe Improvement Is Variance Compression

Gemini's headline change looked odd because return barely moved:

| Round | Return | Sharpe | Final Value |
|---|---:|---:|---:|
| R2 | +0.18% | 0.51 | 10018.12 |
| R3 | +0.19% | 1.37 | 10018.64 |

Daily-return stats explain it:

| Round | Mean daily return | Std dev | Non-zero days | Max abs daily move |
|---|---:|---:|---:|---:|
| R2 | 0.000003727 | 0.000140565 | 78 | 0.001638 |
| R3 | 0.000003825 | **0.000053422** | 134 | **0.000540** |

Interpretation:

- mean return is basically unchanged
- volatility falls by about **62%**
- return is distributed across more days with smaller moves

So the Sharpe jump is real, and it is coming from smoother equity behavior rather than higher absolute profitability.

---

## 6. Cross-Model Disagreement: Good Prompt-Tuning Targets

Using the Round 3 `reclassified` logs across all 8 models:

- **251** pairs changed in at least one model
- **52** of those pairs have **4 distinct final labels** across the model set

These are the highest-value prompt-tuning candidates.

### Representative high-disagreement pairs

**Duplicate same-match winner markets**

- Pair `102`: "Dodgers vs. Brewers" vs "Dodgers vs. Brewers"
- Pair `308`: "Celtics vs. Nets" vs "Celtics vs. Nets"
- Pair `1`: "Bulls vs. Hornets" vs "Bulls vs. Hornets"
- Pair `2`: "Spurs vs. Timberwolves" vs "Spurs vs. Timberwolves"

These pairs split across `partition`, `mutual_exclusion`, `none`, and `implication` depending on model. That is a strong sign the prompt needs explicit guidance for same-question duplicate winner markets.

**Timeline / threshold implications**

- Pair `8`: "Will the Government shutdown end by November 15?" vs "Will the Government shutdown end October 15+?"

Models split across `implication`, `conditional`, `cross_platform`, and `none`. This should become a canonical few-shot example for date-window nesting.

**Series winner vs game winner**

- Pair `77`: "LoL: Gen.G vs Hanwha Life Esports (BO5)" vs "Game 1 Winner"
- Pair `81`: same BO5 vs "Game 2 Winner"
- Pair `486`: "LoL: T1 vs Top Esports (BO5)" vs "Game 3 Winner"

These are exactly the kinds of pairs where strong prompts should distinguish deterministic implication from weaker conditional correlation.

### Practical takeaway

The disagreement set is not dominated by obscure politics or weird market wording. It is dominated by a few recurring structures:

- duplicate winner markets
- date-window nesting
- series winner vs map/game winner
- same-team overlap across nearby matches

Those are the best candidates for prompt-spec examples or hard-coded rule assists.

---

## 7. Revised Trust Ranking

### Current raw leaderboard

1. M2.7: +0.87%  
2. Qwen3 Max: +0.48%  
3. Qwen3.5-122B: +0.38%  
4. Gemini 2.5 Flash: +0.19%  
5. Sonnet 4: +0.07%

### Trust-adjusted view

1. **Qwen3 Max**: best current result without clear log-level contamination  
2. **Qwen3.5-122B**: slower, but also not obviously contaminated  
3. **Gemini 2.5 Flash**: small return, highest confidence in variance story  
4. **Sonnet 4**: underperformed, but regression mechanism is at least identifiable  
5. **M2.7**: raw top line, lowest trust due to stale resolved-market cluster

This is not a final model ranking. It is a ranking of how much trust to place in the current artifacts.

---

## 8. Recommended Next Steps

### Step 0: Fix the backtest before any paid rerun

Highest priority fix:

- In [`scripts/backtest.py`](/Users/unit117/Dev/polyarb/scripts/backtest.py), prevent `detect_opportunities` and `simulate_opportunity` from using markets with `resolved_at <= as_of`
- Alternatively, exclude any pair where either leg is resolved as of the simulated date

Without this fix, the next rerun can still overstate whichever model happens to classify stale resolved-market pairs most aggressively.

### Step 1: Rerun a minimal corrected leaderboard

After the fix, rerun only:

1. M2.7  
2. Qwen3 Max  
3. Sonnet 4 (still on `claude_xml`)

This answers the most urgent question: does M2.7 still beat Qwen after the resolved-market bug is removed?

### Step 2: Then run Sonnet adapter isolation

Only after Step 1:

1. Clone fresh DB  
2. Reclassify Sonnet 4 with `--prompt-adapter openai_generic`  
3. Backtest again with the fixed script

That isolates:

- prompt content effect
- adapter effect
- backtest contamination effect

in the right order.

### Step 3: Improve future eval artifact quality

For the next round, preserve more than logs:

- keep per-model DBs or dump `market_pairs` after each reclassify
- export pair-level CSV: `pair_id, old_type, new_type, source, confidence`
- export backtest JSON with settlement rows, not just summary

That removes most of the reconstruction work required here.

---

## 9. Final Assessment

Claude's original inspection plan was directionally right on Sonnet and Qwen, but it missed the most important issue in the current artifacts:

**the backtest itself is allowing resolved markets to be re-traded from stale snapshots.**

That means:

- Sonnet's regression is worth investigating, but it is **not** the first blocker
- M2.7's apparent first-place finish is **not trustworthy as-is**
- Qwen3 Max is the cleanest current positive result

If I had to decide what to do next from these artifacts alone:

1. fix the resolved-market backtest issue,
2. rerun M2.7, Qwen3 Max, Sonnet,
3. only then spend money on the Sonnet generic rerun.
