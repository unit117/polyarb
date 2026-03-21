"""Kalshi REST API client with RSA-SHA256 authentication.

Uses direct HTTP calls (httpx) rather than the kalshi-python-async SDK
to stay consistent with the GammaClient/ClobClient pattern and avoid
the SDK's aiohttp dependency. Authentication follows Kalshi's
RSA-SHA256 signing scheme.
"""

import asyncio
import base64
import random
import time
from datetime import datetime, timezone

import httpx
import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, utils

log = structlog.get_logger()

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiClient:
    """Async Kalshi API client with rate limiting and RSA-SHA256 auth."""

    def __init__(
        self,
        api_key: str,
        private_key_pem: str,
        base_url: str = KALSHI_API_BASE,
        rate_limit_rps: float = 1.5,
    ):
        self._api_key = api_key
        key_data = private_key_pem
        # If it looks like a file path rather than inline PEM, read the file
        if not key_data.lstrip().startswith("-----"):
            import os
            path = os.path.expanduser(key_data.strip())
            with open(path, "rb") as f:
                key_data = f.read().decode()
        self._private_key = serialization.load_pem_private_key(
            key_data.encode() if isinstance(key_data, str) else key_data,
            password=None,
        )
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self._lock = asyncio.Lock()
        self._min_interval = 1.0 / rate_limit_rps
        self._last_request_time = 0.0
        self._max_retries = 5

    def _sign_request(self, method: str, path: str, timestamp_ms: int) -> str:
        """Create RSA-SHA256 signature for Kalshi API auth."""
        message = f"{timestamp_ms}{method}{path}"
        digest = hashes.Hash(hashes.SHA256())
        digest.update(message.encode())
        hash_bytes = digest.finalize()
        signature = self._private_key.sign(
            hash_bytes,
            padding.PKCS1v15(),
            utils.Prehashed(hashes.SHA256()),
        )
        return base64.b64encode(signature).decode()

    def _auth_headers(self, method: str, path: str) -> dict:
        """Generate authentication headers for a request."""
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        signature = self._sign_request(method.upper(), path, timestamp_ms)
        return {
            "KALSHI-ACCESS-KEY": self._api_key,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "Content-Type": "application/json",
        }

    async def _rate_limit(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_time = self._min_interval - (now - self._last_request_time)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()

    async def _request(self, method: str, path: str, **kwargs) -> dict | list | None:
        for attempt in range(self._max_retries):
            await self._rate_limit()
            try:
                headers = self._auth_headers(method, path)
                response = await self._client.request(
                    method, path, headers=headers, **kwargs
                )
                if response.status_code == 429 or response.status_code >= 500:
                    backoff = min(2 ** (attempt + 1), 60) + random.uniform(0, 1)
                    log.warning(
                        "kalshi_api_retry",
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
                    log.error("kalshi_api_failed", error=str(e), path=path)
                    return None
                backoff = min(2 ** (attempt + 1), 60) + random.uniform(0, 1)
                log.warning(
                    "kalshi_api_error",
                    error=str(e),
                    attempt=attempt + 1,
                    backoff=round(backoff, 1),
                )
                await asyncio.sleep(backoff)
        return None

    async def list_markets(
        self, limit: int = 200, status: str = "open", max_markets: int = 500
    ) -> list[dict]:
        """Fetch active markets with cursor-based pagination.

        Returns normalized market dicts compatible with PolyArb's Market model.
        """
        all_markets: list[dict] = []
        cursor: str | None = None

        while len(all_markets) < max_markets:
            params: dict = {"limit": min(limit, max_markets - len(all_markets)), "status": status}
            if cursor:
                params["cursor"] = cursor

            data = await self._request("GET", "/markets", params=params)
            if not data or not isinstance(data, dict):
                break

            markets = data.get("markets", [])
            cursor = data.get("cursor")

            for m in markets:
                normalized = self._normalize_market(m)
                if normalized:
                    all_markets.append(normalized)

            if not cursor or len(markets) < limit:
                break

            log.info(
                "kalshi_paginating",
                fetched=len(all_markets),
                cursor=cursor[:20] if cursor else None,
            )

        log.info("kalshi_markets_fetched", count=len(all_markets))
        return all_markets

    def _normalize_market(self, raw: dict) -> dict | None:
        """Convert Kalshi market JSON to PolyArb-compatible dict."""
        ticker = raw.get("ticker")
        title = raw.get("title")
        if not ticker or not title:
            return None

        # Kalshi markets are binary (Yes/No)
        outcomes = ["Yes", "No"]

        # Extract prices — Kalshi uses _dollars fields (0-100 cents → 0-1 range)
        yes_bid = raw.get("yes_bid_dollars") or 0
        yes_ask = raw.get("yes_ask_dollars") or 0
        midpoint = (yes_bid + yes_ask) / 2 if (yes_bid and yes_ask) else 0

        return {
            "venue": "kalshi",
            "polymarket_id": ticker,  # Reuse polymarket_id column
            "event_id": raw.get("event_ticker"),
            "question": title,
            "description": raw.get("subtitle") or "",
            "outcomes": outcomes,
            "token_ids": [ticker],  # Kalshi uses ticker as token identifier
            "active": raw.get("status") == "open",
            "volume": float(raw.get("volume_fp") or 0),
            "liquidity": float(raw.get("open_interest_fp") or 0),
            "end_date": raw.get("close_time"),
            "prices": {"Yes": midpoint, "No": round(1.0 - midpoint, 4) if midpoint else 0},
        }

    async def get_market(self, ticker: str) -> dict | None:
        """Fetch a single market by ticker."""
        data = await self._request("GET", f"/markets/{ticker}")
        if data and isinstance(data, dict):
            market = data.get("market", data)
            return self._normalize_market(market)
        return None

    async def list_settled_markets(self, limit: int = 200) -> list[dict]:
        """Fetch recently settled markets with raw status/result fields.

        Returns raw Kalshi dicts (not normalized) so callers can read
        the 'status', 'result', and 'ticker' fields for resolution.
        """
        all_markets: list[dict] = []
        cursor: str | None = None

        while True:
            params: dict = {"limit": limit, "status": "settled"}
            if cursor:
                params["cursor"] = cursor

            data = await self._request("GET", "/markets", params=params)
            if not data or not isinstance(data, dict):
                break

            markets = data.get("markets", [])
            all_markets.extend(markets)
            cursor = data.get("cursor")

            if not cursor or len(markets) < limit:
                break

        return all_markets

    async def get_orderbook(self, ticker: str, depth: int = 10) -> dict | None:
        """Fetch order book for a market ticker."""
        data = await self._request(
            "GET", f"/markets/{ticker}/orderbook", params={"depth": depth}
        )
        if not data or not isinstance(data, dict):
            return None

        orderbook = data.get("orderbook", data)
        return {
            "bids": orderbook.get("yes", []),
            "asks": orderbook.get("no", []),
        }

    async def get_prices(self, ticker: str) -> dict | None:
        """Fetch current prices for a market (uses get_market)."""
        market = await self.get_market(ticker)
        if market:
            return market.get("prices")
        return None

    async def close(self) -> None:
        await self._client.aclose()
