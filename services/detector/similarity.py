"""pgvector cosine similarity search for candidate market pairs."""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def find_similar_pairs(
    session: AsyncSession,
    threshold: float,
    top_k: int,
    batch_size: int,
) -> list[dict]:
    """Find candidate market pairs using pgvector KNN search.

    Instead of an O(n^2) self-join, iterates through a batch of markets
    and uses pgvector's HNSW index to find each market's nearest neighbors.
    Only returns pairs above the similarity threshold that don't already
    exist in market_pairs.
    """
    # Pick a batch of active markets to search from
    anchor_query = text("""
        SELECT id, embedding
        FROM markets
        WHERE active = true AND embedding IS NOT NULL
        ORDER BY RANDOM()
        LIMIT :batch_size
    """)
    anchors = await session.execute(anchor_query, {"batch_size": batch_size})
    anchor_rows = anchors.fetchall()

    if not anchor_rows:
        logger.info("no_anchors_found")
        return []

    results = []
    seen = set()

    for anchor in anchor_rows:
        # Use pgvector KNN operator to find nearest neighbors via HNSW index
        knn_query = text("""
            SELECT m.id AS neighbor_id,
                   1 - (m.embedding <=> (SELECT embedding FROM markets WHERE id = :anchor_id)) AS similarity
            FROM markets m
            WHERE m.active = true
              AND m.embedding IS NOT NULL
              AND m.id != :anchor_id
            ORDER BY m.embedding <=> (SELECT embedding FROM markets WHERE id = :anchor_id)
            LIMIT :k
        """)
        neighbors = await session.execute(
            knn_query, {"anchor_id": anchor.id, "k": 5}
        )

        for row in neighbors.fetchall():
            if row.similarity < threshold:
                continue

            # Canonical ordering: smaller id first
            a_id = min(anchor.id, row.neighbor_id)
            b_id = max(anchor.id, row.neighbor_id)
            pair_key = (a_id, b_id)

            if pair_key in seen:
                continue
            seen.add(pair_key)

            # Check if pair already exists
            exists = await session.execute(
                text("SELECT 1 FROM market_pairs WHERE market_a_id = :a AND market_b_id = :b"),
                {"a": a_id, "b": b_id},
            )
            if exists.fetchone():
                continue

            results.append({
                "market_a_id": a_id,
                "market_b_id": b_id,
                "similarity": float(row.similarity),
            })

            if len(results) >= top_k:
                break

        if len(results) >= top_k:
            break

    # Sort by similarity descending
    results.sort(key=lambda x: x["similarity"], reverse=True)

    logger.info("similarity_search_complete", candidates=len(results), threshold=threshold)
    return results


async def find_cross_venue_pairs(
    session: AsyncSession,
    threshold: float,
    top_k: int,
) -> list[dict]:
    """Find cross-venue pairs by matching Kalshi markets to Polymarket markets.

    Uses pgvector KNN: for each Kalshi market with an embedding, find the
    nearest Polymarket neighbor. Only returns pairs above threshold that
    don't already exist in market_pairs.
    """
    # Get all active Kalshi markets with embeddings as anchors
    anchor_query = text("""
        SELECT id, embedding
        FROM markets
        WHERE active = true
          AND embedding IS NOT NULL
          AND venue = 'kalshi'
    """)
    anchors = await session.execute(anchor_query)
    anchor_rows = anchors.fetchall()

    if not anchor_rows:
        logger.info("no_kalshi_anchors")
        return []

    results = []
    seen = set()

    for anchor in anchor_rows:
        # Find nearest Polymarket neighbor via pgvector KNN
        knn_query = text("""
            SELECT m.id AS neighbor_id,
                   1 - (m.embedding <=> (SELECT embedding FROM markets WHERE id = :anchor_id)) AS similarity
            FROM markets m
            WHERE m.active = true
              AND m.embedding IS NOT NULL
              AND m.venue = 'polymarket'
            ORDER BY m.embedding <=> (SELECT embedding FROM markets WHERE id = :anchor_id)
            LIMIT 1
        """)
        neighbors = await session.execute(knn_query, {"anchor_id": anchor.id})
        row = neighbors.fetchone()

        if not row or row.similarity < threshold:
            continue

        a_id = min(anchor.id, row.neighbor_id)
        b_id = max(anchor.id, row.neighbor_id)
        pair_key = (a_id, b_id)

        if pair_key in seen:
            continue
        seen.add(pair_key)

        # Skip if pair already exists
        exists = await session.execute(
            text("SELECT 1 FROM market_pairs WHERE market_a_id = :a AND market_b_id = :b"),
            {"a": a_id, "b": b_id},
        )
        if exists.fetchone():
            continue

        results.append({
            "market_a_id": a_id,
            "market_b_id": b_id,
            "similarity": float(row.similarity),
        })

        if len(results) >= top_k:
            break

    results.sort(key=lambda x: x["similarity"], reverse=True)
    logger.info("cross_venue_search_complete", candidates=len(results), threshold=threshold)
    return results
