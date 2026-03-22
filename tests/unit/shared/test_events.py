"""Tests for shared/events.py publish/subscribe helpers."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_yields_decoded_messages(self):
        """subscribe() should yield dicts from JSON messages."""
        payload = {"opportunity_id": 7, "type": "implication"}
        encoded = json.dumps(payload)

        # Build a mock pubsub that yields one message then stops
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        async def _listen():
            yield {"type": "subscribe", "data": 1}  # ignored
            yield {"type": "message", "data": encoded}

        mock_pubsub.listen = _listen

        r = AsyncMock()
        r.pubsub = MagicMock(return_value=mock_pubsub)

        results = []
        async for msg in subscribe(r, "test:channel"):
            results.append(msg)
            break  # only consume one message

        assert results == [payload]
        mock_pubsub.subscribe.assert_awaited_once_with("test:channel")

    @pytest.mark.asyncio
    async def test_unsubscribes_on_exit(self):
        """subscribe() must unsubscribe and close pubsub when generator is closed."""
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        async def _listen():
            yield {"type": "message", "data": json.dumps({"x": 1})}

        mock_pubsub.listen = _listen

        r = AsyncMock()
        r.pubsub = MagicMock(return_value=mock_pubsub)

        # Exhaust the generator fully so the finally block always runs
        async for _ in subscribe(r, "chan"):
            pass

        mock_pubsub.unsubscribe.assert_awaited_once_with("chan")
        mock_pubsub.aclose.assert_awaited_once()
