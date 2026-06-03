from __future__ import annotations
import asyncio
from collections.abc import AsyncIterator
import json
import random
import time

import httpx
import structlog

log = structlog.get_logger()


def parse_stringified_json(value: str | list) -> list:
    """Parse fields that Polymarket returns as stringified JSON arrays."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


class GammaClient:
    def __init__(self, base_url: str, rate_limit_rps: float = 2.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self._lock = asyncio.Lock()
        self._min_interval = 1.0 / rate_limit_rps
        self._last_request_time = 0.0
        self._max_retries = 5
        # True if the most recent pagination stopped early at Gamma's offset
        # cap (~10000) rather than exhausting the result set. Callers use this
        # to avoid concluding that unfetched markets no longer exist.
        # Sequential use only (poll loop awaits each pagination fully).
        self.last_pagination_capped = False

    async def _rate_limit(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_time = self._min_interval - (now - self._last_request_time)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()

    async def _request(self, method: str, url: str, **kwargs) -> dict | list:
        for attempt in range(self._max_retries):
            await self._rate_limit()
            try:
                response = await self._client.request(method, url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    backoff = min(2 ** (attempt + 1), 60) + random.uniform(0, 1)
                    log.warning(
                        "gamma_api_retry",
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
                    "gamma_api_error",
                    error=str(e),
                    attempt=attempt + 1,
                    backoff=round(backoff, 1),
                )
                await asyncio.sleep(backoff)
        return []

    def _market_params(
        self,
        limit: int,
        offset: int,
        active: bool,
        closed: bool,
        order: str | None,
        ascending: bool,
    ) -> dict:
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
        }
        if order:
            # Order by liquidity desc by default so the most tradeable markets
            # fall within Gamma's offset cap (it 422s past offset 10000).
            params["order"] = order
            params["ascending"] = str(ascending).lower()
        return params

    async def list_markets(
        self,
        limit: int = 100,
        active: bool = True,
        closed: bool = False,
        order: str | None = "liquidityNum",
        ascending: bool = False,
    ) -> list[dict]:
        all_markets = []
        offset = 0
        self.last_pagination_capped = False
        while True:
            params = self._market_params(limit, offset, active, closed, order, ascending)
            try:
                batch = await self._request("GET", "/markets", params=params)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 422:
                    self.last_pagination_capped = True
                    log.warning("gamma_pagination_cap", offset=offset, total_so_far=len(all_markets))
                    break
                raise
            if not isinstance(batch, list):
                break
            all_markets.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
            log.info("gamma_paginating", offset=offset, total_so_far=len(all_markets))
        return all_markets

    async def iter_market_pages(
        self,
        limit: int = 100,
        active: bool = True,
        closed: bool = False,
        order: str | None = "liquidityNum",
        ascending: bool = False,
    ) -> AsyncIterator[list[dict]]:
        """Yield pages of markets without accumulating all in memory."""
        offset = 0
        self.last_pagination_capped = False
        while True:
            params = self._market_params(limit, offset, active, closed, order, ascending)
            try:
                batch = await self._request("GET", "/markets", params=params)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 422:
                    # Gamma caps pagination near offset 10000; treat the 422 as
                    # end-of-data instead of letting it abort the poll cycle
                    # (which previously stalled all price-snapshot writes).
                    self.last_pagination_capped = True
                    log.warning("gamma_pagination_cap", offset=offset)
                    break
                raise
            if not isinstance(batch, list) or not batch:
                break
            yield batch
            if len(batch) < limit:
                break
            offset += limit
            log.info("gamma_paginating", offset=offset)

    async def close(self) -> None:
        await self._client.aclose()
