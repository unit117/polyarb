from __future__ import annotations
import asyncio
import random
import time

import httpx
import structlog

log = structlog.get_logger()


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

    async def _request(self, method: str, url: str, **kwargs) -> dict | None:
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

    async def get_snapshot_for_market(
        self,
        token_ids: list[str],
        outcomes: list[str],
        fetch_order_books: bool = False,
    ) -> dict:
        midpoints = {}
        prices = {}
        for i, token_id in enumerate(token_ids):
            outcome = outcomes[i] if i < len(outcomes) else f"outcome_{i}"
            mid = await self.get_midpoint(token_id)
            if mid is not None:
                midpoints[outcome] = mid
                prices[outcome] = mid

        order_books: dict[str, dict] = {}
        if fetch_order_books:
            for i, token_id in enumerate(token_ids):
                outcome = outcomes[i] if i < len(outcomes) else f"outcome_{i}"
                book = await self.get_order_book(token_id)
                if book:
                    order_books[outcome] = book

        return {
            "prices": prices,
            "midpoints": midpoints,
            # Keep backwards-compatible "order_book" key (first outcome's book)
            # for existing consumers, plus new per-outcome "order_books" dict.
            "order_book": order_books.get(outcomes[0]) if outcomes and order_books else None,
            "order_books": order_books,
        }

    async def close(self) -> None:
        await self._client.aclose()
