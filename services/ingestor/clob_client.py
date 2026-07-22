from __future__ import annotations
import asyncio
import random
import time

import httpx
import structlog

log = structlog.get_logger()

# POST /midpoints and POST /books accept [{"token_id": ...}, ...]; no batch
# cap is documented, so stay conservative and fall back to single-token GETs
# if a batch request is rejected.
BATCH_SIZE = 100


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def normalize_book(book: dict | None, depth_levels: int) -> dict | None:
    """Sort levels best-first and truncate to bound JSONB growth.

    The CLOB does not guarantee level ordering; compute_vwap walks levels
    front-to-back assuming best-first, and truncation must keep the BEST
    levels — so sorting here is correctness, not cosmetics.
    """
    if not isinstance(book, dict):
        return None

    def _price(level) -> float:
        try:
            raw = level[0] if isinstance(level, (list, tuple)) else level.get("price", 0)
            return float(raw)
        except (TypeError, ValueError, IndexError):
            return 0.0

    bids = sorted(book.get("bids") or [], key=_price, reverse=True)
    asks = sorted(book.get("asks") or [], key=_price)
    if depth_levels > 0:
        bids = bids[:depth_levels]
        asks = asks[:depth_levels]
    return {"bids": bids, "asks": asks}


class ClobClient:
    def __init__(self, base_url: str, rate_limit_rps: float = 2.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self._lock = asyncio.Lock()
        self._min_interval = 1.0 / rate_limit_rps
        self._last_request_time = 0.0
        self._max_retries = 5

    async def _rate_limit(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_time = self._min_interval - (now - self._last_request_time)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()

    async def _request(self, method: str, url: str, **kwargs) -> dict | list | None:
        for attempt in range(self._max_retries):
            await self._rate_limit()
            try:
                response = await self._client.request(method, url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    backoff = min(2 ** (attempt + 1), 60) + random.uniform(0, 1)
                    log.warning(
                        "clob_api_retry",
                        status=response.status_code,
                        attempt=attempt + 1,
                        backoff=round(backoff, 1),
                    )
                    await asyncio.sleep(backoff)
                    continue
                if response.status_code == 404:
                    # CLOB returns 404 for closed/delisted markets that no longer
                    # have a live order book. This is common for resolved markets
                    # we have not flipped inactive yet (the Gamma resolution sync
                    # is offset-capped, so older closed markets linger active).
                    # Treat it as "no quote" rather than an error so it doesn't
                    # spam ERROR-level tracebacks on every poll cycle.
                    log.debug("clob_not_found", url=url, params=kwargs.get("params"))
                    return None
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as e:
                if attempt == self._max_retries - 1:
                    raise
                backoff = min(2 ** (attempt + 1), 60) + random.uniform(0, 1)
                log.warning(
                    "clob_api_error",
                    error=str(e),
                    attempt=attempt + 1,
                    backoff=round(backoff, 1),
                )
                await asyncio.sleep(backoff)
        return None

    async def get_midpoint(self, token_id: str) -> str | None:
        result = await self._request(
            "GET", "/midpoint", params={"token_id": token_id}
        )
        if result:
            return result.get("mid")
        return None

    async def get_order_book(self, token_id: str) -> dict | None:
        return await self._request(
            "GET", "/book", params={"token_id": token_id}
        )

    async def get_fee_rate(self, token_id: str) -> int | None:
        """Fetch taker fee rate in basis points from CLOB API.

        The CLOB returns {"base_fee": N} where N is already in basis points.
        """
        result = await self._request(
            "GET", "/fee-rate", params={"token_id": token_id}
        )
        if result and "base_fee" in result:
            return int(result["base_fee"])
        return None

    # ------------------------------------------------------------------
    # Batch endpoints — the coverage raise depends on these: sequential
    # single-token GETs at 2 RPS cost ~8.3 min for 500 binary markets,
    # saturating the 300s poll cycle. Batched: ~110 requests for ~11k
    # tokens ≈ 55s.
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_mid(value) -> str | None:
        if isinstance(value, dict):
            value = value.get("mid", value.get("midpoint"))
        if value is None:
            return None
        return str(value)

    async def get_midpoints_batch(self, token_ids: list[str]) -> dict[str, str]:
        """POST /midpoints for many tokens; returns {token_id: mid}.

        Falls back to single-token GETs for a chunk the batch endpoint
        rejects, so a contract change degrades to the old (slow) behavior
        instead of a blackout.
        """
        out: dict[str, str] = {}
        for chunk in _chunks(token_ids, BATCH_SIZE):
            body = [{"token_id": t} for t in chunk]
            try:
                result = await self._request("POST", "/midpoints", json=body)
            except httpx.HTTPStatusError as e:
                # Contract problem (4xx): worth the slow sequential fallback
                log.warning(
                    "clob_midpoints_batch_rejected",
                    status=e.response.status_code,
                    chunk=len(chunk),
                )
                result = None
            except httpx.HTTPError as e:
                # Transport problem: the sequential fallback would turn one
                # failed request into 100 doomed ones during an outage —
                # skip the chunk and keep what other chunks returned
                log.warning("clob_midpoints_batch_transport_error", error=str(e))
                continue
            covered = 0
            if isinstance(result, dict):
                for token_id, value in result.items():
                    mid = self._parse_mid(value)
                    if mid is not None:
                        out[token_id] = mid
                        covered += 1
            elif isinstance(result, list):
                for item in result:
                    if isinstance(item, dict) and item.get("token_id"):
                        mid = self._parse_mid(item.get("mid", item.get("midpoint")))
                        if mid is not None:
                            out[item["token_id"]] = mid
                            covered += 1
            if result is not None and covered > 0:
                continue
            if result is not None:
                # Accepted-but-empty response — contract drift; fall back
                log.warning("clob_midpoints_batch_empty", chunk=len(chunk))
            # Sequential fallback for this chunk only
            for token_id in chunk:
                try:
                    mid = await self.get_midpoint(token_id)
                except httpx.HTTPError:
                    continue
                if mid is not None:
                    out[token_id] = mid
        return out

    async def get_books_batch(
        self, token_ids: list[str], depth_levels: int = 10
    ) -> dict[str, dict]:
        """POST /books for many tokens; returns {token_id: {bids, asks}}.

        Books are normalized best-first and truncated to depth_levels per
        side (full books at 288 cycles/day would be ~GB-scale growth).
        """
        out: dict[str, dict] = {}
        for chunk in _chunks(token_ids, BATCH_SIZE):
            body = [{"token_id": t} for t in chunk]
            try:
                result = await self._request("POST", "/books", json=body)
            except httpx.HTTPStatusError as e:
                log.warning(
                    "clob_books_batch_rejected",
                    status=e.response.status_code,
                    chunk=len(chunk),
                )
                result = None
            except httpx.HTTPError as e:
                log.warning("clob_books_batch_transport_error", error=str(e))
                continue
            covered = 0
            if isinstance(result, list):
                for book in result:
                    if not isinstance(book, dict):
                        continue
                    token_id = book.get("asset_id") or book.get("token_id")
                    normalized = normalize_book(book, depth_levels)
                    if token_id and normalized:
                        out[token_id] = normalized
                        covered += 1
            if result is not None and covered > 0:
                continue
            if result is not None:
                log.warning("clob_books_batch_empty", chunk=len(chunk))
            # Sequential fallback for this chunk only
            for token_id in chunk:
                try:
                    book = await self.get_order_book(token_id)
                except httpx.HTTPError:
                    continue
                normalized = normalize_book(book, depth_levels)
                if normalized:
                    out[token_id] = normalized
        return out

    async def get_snapshot_for_market(
        self,
        token_ids: list[str],
        outcomes: list[str],
        fetch_order_books: bool = False,
        depth_levels: int = 10,
    ) -> dict:
        """Single-market snapshot (sequential; kept for callers off the batch
        path, e.g. scripts). Books are fetched for ALL outcomes and keyed by
        outcome — the old first-outcome-only book was applied to whichever
        outcome got traded."""
        midpoints = {}
        prices = {}
        for i, token_id in enumerate(token_ids):
            outcome = outcomes[i] if i < len(outcomes) else f"outcome_{i}"
            mid = await self.get_midpoint(token_id)
            if mid is not None:
                midpoints[outcome] = mid
                prices[outcome] = mid

        order_book = None
        if fetch_order_books and token_ids:
            books = {}
            for i, token_id in enumerate(token_ids):
                outcome = outcomes[i] if i < len(outcomes) else f"outcome_{i}"
                book = normalize_book(await self.get_order_book(token_id), depth_levels)
                if book:
                    books[outcome] = book
            order_book = books or None

        return {
            "prices": prices,
            "midpoints": midpoints,
            "order_book": order_book,
        }

    async def close(self) -> None:
        await self._client.aclose()
