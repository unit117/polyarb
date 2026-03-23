"""Reclassify all market pairs using the new 3-tier classifier pipeline.

Runs each pair through: rule-based → resolution vectors → label-based fallback.
Updates dependency_type, confidence, constraint_matrix, resolution_vectors,
implication_direction, classification_source, and verified fields.

Use this before running a backtest to measure classifier improvements.

Usage:
    # Dry run — show what would change without writing to DB
    python -m scripts.reclassify_pairs --dry-run

    # Reclassify all pairs in the current DB
    python -m scripts.reclassify_pairs

    # Reclassify only pairs currently classified by LLM (skip rule-based)
    python -m scripts.reclassify_pairs --only-llm

    # Point at backtest DB
    POSTGRES_DB=polyarb_backtest python -m scripts.reclassify_pairs
"""

import argparse
import asyncio
import sys
from collections import Counter

import openai
import structlog

from sqlalchemy import select

sys.path.insert(0, ".")

from shared.config import settings
from shared.db import SessionFactory, init_db
from shared.models import Market, MarketPair
from services.detector.classifier import classify_pair

log = structlog.get_logger()


async def reclassify_all(
    dry_run: bool = False,
    only_llm: bool = False,
    batch_size: int = 3,
    model_override: str | None = None,
    base_url_override: str | None = None,
    api_key_override: str | None = None,
    prompt_adapter_override: str | None = None,
) -> dict:
    """Reclassify all market pairs using the 3-tier pipeline.

    Returns summary stats dict.
    """
    await init_db()

    # Resolve client config: CLI overrides > env settings > defaults
    base_url = base_url_override or settings.classifier_base_url or None
    model = model_override or settings.classifier_model
    prompt_adapter = prompt_adapter_override or settings.classifier_prompt_adapter

    if base_url:
        api_key = api_key_override or settings.openrouter_api_key or settings.openai_api_key
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    else:
        api_key = api_key_override or settings.openai_api_key
        client = openai.AsyncOpenAI(api_key=api_key)

    log.info(
        "classifier_client",
        model=model,
        base_url=base_url or "openai_direct",
        prompt_adapter=prompt_adapter,
    )

    stats = {
        "total": 0,
        "skipped": 0,
        "reclassified": 0,
        "unchanged": 0,
        "errors": 0,
        "changes": [],  # list of {pair_id, old_type, new_type, old_source, new_source}
    }
    source_counts = Counter()
    type_counts = Counter()
    change_counts = Counter()  # "old_type → new_type"

    async with SessionFactory() as session:
        result = await session.execute(select(MarketPair))
        pairs = list(result.scalars().all())

    log.info("reclassify_start", total_pairs=len(pairs), dry_run=dry_run, only_llm=only_llm)

    # Process sequentially within batches, with delay between batches
    # to avoid hitting OpenAI's daily RPD limit. Each pair may make
    # up to 2 API calls (resolution vector + label fallback).
    sem = asyncio.Semaphore(batch_size)

    async def process_pair(pair: MarketPair) -> None:
        stats["total"] += 1

        if only_llm and pair.classification_source == "rule_based":
            stats["skipped"] += 1
            return

        async with SessionFactory() as session:
            market_a = await session.get(Market, pair.market_a_id)
            market_b = await session.get(Market, pair.market_b_id)

            if not market_a or not market_b:
                stats["errors"] += 1
                log.warning("missing_market", pair_id=pair.id)
                return

            market_a_dict = {
                "question": market_a.question,
                "description": market_a.description or "",
                "outcomes": market_a.outcomes if isinstance(market_a.outcomes, list) else [],
                "event_id": market_a.event_id,
            }
            market_b_dict = {
                "question": market_b.question,
                "description": market_b.description or "",
                "outcomes": market_b.outcomes if isinstance(market_b.outcomes, list) else [],
                "event_id": market_b.event_id,
            }

            # Classify using 3-tier pipeline
            async with sem:
                try:
                    classification = await classify_pair(
                        client,
                        model,
                        market_a_dict,
                        market_b_dict,
                        prompt_adapter=prompt_adapter,
                    )
                except Exception as e:
                    stats["errors"] += 1
                    log.error("classify_error", pair_id=pair.id, error=str(e))
                    return

            new_type = classification["dependency_type"]
            new_confidence = classification["confidence"]
            new_source = classification.get("classification_source", "unknown")
            new_direction = classification.get("implication_direction")
            new_correlation = classification.get("correlation")
            valid_outcomes = classification.get("valid_outcomes")

            source_counts[new_source] += 1
            type_counts[new_type] += 1

            old_type = pair.dependency_type
            old_source = pair.classification_source or "unknown"

            changed = (new_type != old_type)

            if changed:
                transition = f"{old_type} → {new_type}"
                change_counts[transition] += 1
                stats["reclassified"] += 1
                stats["changes"].append({
                    "pair_id": pair.id,
                    "old_type": old_type,
                    "new_type": new_type,
                    "old_source": old_source,
                    "new_source": new_source,
                    "question_a": market_a.question[:80],
                    "question_b": market_b.question[:80],
                })
                log.info(
                    "reclassified",
                    pair_id=pair.id,
                    transition=transition,
                    new_source=new_source,
                    confidence=new_confidence,
                )
            else:
                stats["unchanged"] += 1

            if dry_run:
                return

            # Build a metadata-only constraint matrix shell.
            # The backtest rebuilds the full feasibility matrix + profit_bound
            # with real prices each day (backtest.py L140-153), so we only need
            # the metadata fields it reads: outcomes_a, outcomes_b, type,
            # correlation, implication_direction.
            outcomes_a = market_a_dict["outcomes"]
            outcomes_b = market_b_dict["outcomes"]

            if new_type == "none":
                constraint_matrix = None
                verified = False
            else:
                constraint_matrix = {
                    "type": new_type,
                    "outcomes_a": outcomes_a,
                    "outcomes_b": outcomes_b,
                    "correlation": new_correlation,
                    "implication_direction": new_direction,
                    "matrix": [[1] * len(outcomes_b) for _ in range(len(outcomes_a))],
                    "profit_bound": 0.0,  # placeholder — backtest recomputes
                }
                # Keep verified=True so the backtest can load these pairs.
                # The backtest re-verifies with real prices each day
                # (backtest.py L126-137) — that's the real gate.
                verified = True

            # Update pair in DB
            async with SessionFactory() as update_session:
                db_pair = await update_session.get(MarketPair, pair.id)
                if db_pair:
                    db_pair.dependency_type = new_type
                    db_pair.confidence = new_confidence
                    db_pair.constraint_matrix = constraint_matrix
                    db_pair.resolution_vectors = valid_outcomes
                    db_pair.implication_direction = new_direction
                    db_pair.classification_source = new_source
                    db_pair.verified = verified
                    await update_session.commit()

    # Run all pairs — process sequentially to respect rate limits.
    # Each pair makes up to 2 API calls; with batch_size=3 and 1s delay,
    # we stay well under 500 RPM.
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i + batch_size]
        await asyncio.gather(*[process_pair(p) for p in batch])
        processed = min(i + batch_size, len(pairs))
        log.info("batch_complete", processed=processed, total=len(pairs))
        # Rate limit: wait between batches to avoid 429s
        if processed < len(pairs):
            await asyncio.sleep(2.0)

    # Summary
    log.info(
        "reclassify_complete",
        **{k: v for k, v in stats.items() if k != "changes"},
        source_breakdown=dict(source_counts),
        type_breakdown=dict(type_counts),
        transitions=dict(change_counts),
    )

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Reclassify market pairs using new 3-tier pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing to DB")
    parser.add_argument("--only-llm", action="store_true", help="Only reclassify LLM-classified pairs (skip rule-based)")
    parser.add_argument("--batch-size", type=int, default=3, help="Concurrent LLM requests (default: 3)")
    parser.add_argument("--model", type=str, default=None, help="Model override (e.g. openai/gpt-4.1-mini, minimax/minimax-m2.7)")
    parser.add_argument("--base-url", type=str, default=None, help="API base URL (e.g. https://openrouter.ai/api/v1)")
    parser.add_argument("--api-key", type=str, default=None, help="API key override (for OpenRouter etc)")
    parser.add_argument(
        "--prompt-adapter",
        type=str,
        choices=["auto", "openai_generic", "claude_xml"],
        default=None,
        help="Prompt adapter override (default: use settings)",
    )
    parser.add_argument("--force", action="store_true", help="Required to run against the live DB (safety guard)")
    args = parser.parse_args()

    # Safety: refuse to mutate the live DB without --force
    if not args.dry_run and not settings.postgres_db.startswith("polyarb_bt") and not args.force:
        print("ERROR: Refusing to write to live DB without --force flag.")
        print(f"  Current DB: {settings.postgres_db}")
        print("  Use --dry-run to preview changes, or --force to proceed.")
        sys.exit(1)

    stats = await reclassify_all(
        dry_run=args.dry_run,
        only_llm=args.only_llm,
        batch_size=args.batch_size,
        model_override=args.model,
        base_url_override=args.base_url,
        api_key_override=args.api_key,
        prompt_adapter_override=args.prompt_adapter,
    )

    # Print readable summary
    print("\n" + "=" * 60)
    print("RECLASSIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total pairs:    {stats['total']}")
    print(f"Reclassified:   {stats['reclassified']}")
    print(f"Unchanged:      {stats['unchanged']}")
    print(f"Skipped:        {stats['skipped']}")
    print(f"Errors:         {stats['errors']}")

    if stats["changes"]:
        print(f"\n{'─' * 60}")
        print("TYPE CHANGES:")
        for change in stats["changes"]:
            print(f"  [{change['pair_id']}] {change['old_type']} → {change['new_type']}"
                  f"  (source: {change['new_source']})")
            print(f"         A: {change['question_a']}")
            print(f"         B: {change['question_b']}")


if __name__ == "__main__":
    asyncio.run(main())
