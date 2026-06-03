"""Tests for shared/events.py publish/subscribe helpers."""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import shared.circuit_breaker as circuit_breaker_contracts
import shared.events as event_contracts
from shared.events import (
    get_redis,
    publish,
    subscribe,
    CHANNEL_ARBITRAGE_FOUND,
)


class TestGetRedis:
    @pytest.mark.asyncio
    async def test_creates_redis_from_settings_url(self):
        mock_redis = MagicMock()
        with patch("shared.events.aioredis.from_url", return_value=mock_redis) as mock_from_url:
            result = await get_redis()
        mock_from_url.assert_called_once()
        call_kwargs = mock_from_url.call_args
        assert call_kwargs.kwargs.get("decode_responses") is True
        assert result is mock_redis


class TestPublish:
    @pytest.mark.asyncio
    async def test_publishes_json_encoded_payload(self):
        r = AsyncMock()
        payload = {"opportunity_id": 1, "status": "detected"}
        await publish(r, CHANNEL_ARBITRAGE_FOUND, payload)
        r.publish.assert_awaited_once_with(
            CHANNEL_ARBITRAGE_FOUND,
            json.dumps(payload),
        )

    @pytest.mark.asyncio
    async def test_publishes_to_correct_channel(self):
        r = AsyncMock()
        await publish(r, "my:channel", {"key": "val"})
        args = r.publish.call_args[0]
        assert args[0] == "my:channel"
        assert json.loads(args[1]) == {"key": "val"}


class TestDashboardChannelContract:
    def test_dashboard_channel_constants_match_backend_events(self):
        """The dashboard WS handler must match raw Redis channel names."""
        repo_root = Path(__file__).resolve().parents[3]
        ts_channels = (
            repo_root / "services/dashboard/web/src/redisChannels.ts"
        ).read_text()

        frontend_values = set(re.findall(r'"(polyarb:[^"]+)"', ts_channels))
        backend_values = set()
        for module in (event_contracts, circuit_breaker_contracts):
            backend_values.update(
                value
                for name, value in vars(module).items()
                if name.startswith("CHANNEL_") and isinstance(value, str)
            )

        assert frontend_values == backend_values


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_yields_decoded_messages(self):
        """subscribe() should yield dicts from JSON messages."""
        payload = {"opportunity_id": 7, "type": "implication"}
        encoded = json.dumps(payload)

        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        # get_message returns None on idle polls (exercises the loop-continue
        # path), then a real message.
        mock_pubsub.get_message = AsyncMock(
            side_effect=[None, {"type": "message", "data": encoded}]
        )

        r = AsyncMock()
        r.pubsub = MagicMock(return_value=mock_pubsub)

        results = []
        async for msg in subscribe(r, "test:channel"):
            results.append(msg)
            break  # only consume one message

        assert results == [payload]
        mock_pubsub.subscribe.assert_awaited_once_with("test:channel")

    @pytest.mark.asyncio
    async def test_tolerates_read_timeout(self):
        """A redis read timeout on an idle channel must not crash the loop."""
        from redis.exceptions import TimeoutError as RedisTimeoutError

        payload = {"x": 1}
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()
        # First poll raises a read timeout (must be swallowed), then a message.
        mock_pubsub.get_message = AsyncMock(
            side_effect=[RedisTimeoutError("Timeout reading from redis:6379"),
                         {"type": "message", "data": json.dumps(payload)}]
        )

        r = AsyncMock()
        r.pubsub = MagicMock(return_value=mock_pubsub)

        results = []
        async for msg in subscribe(r, "chan"):
            results.append(msg)
            break

        assert results == [payload]

    @pytest.mark.asyncio
    async def test_unsubscribes_on_exit(self):
        """subscribe() must unsubscribe and close pubsub when generator is closed."""
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()
        mock_pubsub.get_message = AsyncMock(
            return_value={"type": "message", "data": json.dumps({"x": 1})}
        )

        r = AsyncMock()
        r.pubsub = MagicMock(return_value=mock_pubsub)

        # Consume one message, then close the generator so the finally runs.
        gen = subscribe(r, "chan")
        await gen.__anext__()
        await gen.aclose()

        mock_pubsub.unsubscribe.assert_awaited_once_with("chan")
        mock_pubsub.aclose.assert_awaited_once()
