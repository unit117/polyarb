# GitHub Polymarket Projects — Research Notes

> Side file: interesting patterns and ideas extracted from open-source Polymarket arbitrage projects.
> These are not proven — treat as inspiration, not guidelines. The Saguillo paper is the authority.

---

## sonnyfully/polymarket-bot

**Repo:** https://github.com/sonnyfully/polymarket-bot
**Stack:** TypeScript monorepo, pnpm, Prisma + Postgres, OpenAI API
**Relevance:** Most architecturally similar to PolyArb.

**Interesting patterns:**
- Uses "semantic market mapping" with confidence thresholds and versioning to classify equivalences, inversions, and constraint sets
- Market mappings stored in `config/market-mappings.json` with **weight** parameters — suggests weighted constraint satisfaction rather than boolean matrix
- LLM-based "AI discovery agent" finds market equivalences automatically
- Source code for the LLM integration is not public (hidden in `packages/`)

**What we could borrow:**
- Mapping versioning pattern — track which classifier version produced each pair classification, useful for A/B testing models
- Weighted constraints as an extension of our binary feasibility matrix

---

## JWadeOn/polymarket-routing

**Repo:** https://github.com/JWadeOn/polymarket-routing
**Docs:** https://github.com/JWadeOn/polymarket-routing/blob/master/docs/equivalence_logic.md
**Stack:** Go, cross-venue router (Polymarket ↔ Kalshi)
**Relevance:** Best-documented equivalence matching logic found.

**Matching formula:**
```
Confidence = (TitleScore × 0.60) + (DateScore × 0.25) + (CategoryScore × 0.15)
Threshold: 0.65
```

**Title normalization pipeline (sequential):**
1. Lowercase
2. Dollar-sign stripping via regex `\$[\d,]+`
3. Alias expansion: btc→bitcoin, eth→ethereum, fed→federal reserve, cpi→inflation, q1→first quarter
4. Punctuation removal (retain alphanumeric + spaces)
5. Stop word elimination: will, the, a, an, by, in, to, of, be, is, on, at
6. Token deduplication
7. Alphabetical sort (order-independence)

**Polarity inversion detection (XOR negation tokens):**
```
inversionTokens = ["not", "no", "fail", "cut", "lower", "below", "miss"]
If exactly_one_title_contains_negation → inversion → flip price: 1.0 - P(Yes)
```
Rationale: both negated = aligned, neither = aligned, exactly one = inverted.

**Date matching:**
```
DateScore = max(0, 1 − delta / (72h × 2))  // linear decay, 0 at 144h
Missing dates default to 0.5 (neutral)
```

**What we could borrow:**
- Title normalization + alias expansion as a pre-filter before pgvector similarity
- Negation XOR for inversion detection in rule-based classifier — cheap, catches "Will X rise above Y" vs "Will X fail to reach Y"
- The 0.65 threshold is calibrated against real Polymarket/Kalshi API data

---

## chainstacklabs/polyclaw

**Repo:** https://github.com/chainstacklabs/polyclaw
**Stack:** Python, OpenRouter API
**Relevance:** Uses LLM for logical implication detection with tiered coverage scores.

**Key details:**
- Default model: `nvidia/nemotron-nano-9b-v2:free` via OpenRouter
- Uses "contrapositive logic" — only logically necessary implications accepted, correlations rejected
- Coverage tiers: T1 ≥95% (near-arbitrage), T2 90-95%, T3 85-90%, T4 <85% (filtered)
- **Important finding:** DeepSeek R1's `reasoning_content` field causes incompatible response formats — confirms reasoning-loop problems from Saguillo paper

**What we could borrow:**
- Tiered coverage scoring as an alternative to binary verified/not-verified
- The finding that even a 9B free model can do strict logical implication if the prompt is constrained enough — useful for cheap pre-filtering

---

## 0xalberto/polymarket-arbitrage-bot

**Repo:** https://github.com/0xalberto/polymarket-arbitrage-bot
**Relevance:** Single-market and multi-market event arbitrage scanner.

Not much novel here — straightforward price-based arb detection without LLM classification. Useful only as a reference for Polymarket CLOB API integration patterns.

---

## Key Takeaways

1. **No one else is doing resolution vectors** — the Saguillo paper is the only implementation of this approach. All GitHub projects use either simple price arb, Jaccard matching, or label-based LLM classification.
2. **Title normalization is universally useful** — polymarket-routing's alias expansion pipeline should be adopted regardless of classifier changes.
3. **DeepSeek R1 reasoning format is a known pain point** — both polyclaw and the paper hit issues with it. MiniMax M2.7 with mandatory `<think>` tags may have a cleaner separation.
4. **Coverage tiers > binary verification** — polyclaw's T1-T4 system is worth considering as a Step 3 enhancement.
