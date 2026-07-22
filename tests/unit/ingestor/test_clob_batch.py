"""Tests for the CLOB batch endpoints and book normalization (Phase 4)."""

from unittest.mock import AsyncMock

import pytest

from services.ingestor.clob_client import ClobClient, normalize_book


def _client() -> ClobClient:
    client = ClobClient.__new__(ClobClient)  # skip httpx setup
    client._request = AsyncMock()
    return client


class TestNormalizeBook:
    def test_sorts_best_first_and_truncates(self):
        book = {
            "bids": [{"price": "0.40", "size": "10"}, {"price": "0.45", "size": "5"}],
            "asks": [{"price": "0.60", "size": "3"}, {"price": "0.55", "size": "7"}],
        }
        out = normalize_book(book, depth_levels=1)
        assert out["bids"] == [{"price": "0.45", "size": "5"}]  # best bid = highest
        assert out["asks"] == [{"price": "0.55", "size": "7"}]  # best ask = lowest

    def test_handles_pair_format_levels(self):
        book = {"bids": [["0.40", "10"], ["0.45", "5"]], "asks": []}
        out = normalize_book(book, depth_levels=10)
        assert out["bids"][0] == ["0.45", "5"]

    def test_none_and_garbage(self):
        assert normalize_book(None, 10) is None
        assert normalize_book("nope", 10) is None
        assert normalize_book({}, 10) == {"bids": [], "asks": []}


class TestMidpointsBatch:
    @pytest.mark.asyncio
    async def test_dict_response(self):
        client = _client()
        client._request.return_value = {"t1": "0.55", "t2": {"mid": "0.60"}}
        out = await client.get_midpoints_batch(["t1", "t2"])
        assert out == {"t1": "0.55", "t2": "0.60"}
        client._request.assert_awaited_once_with(
            "POST", "/midpoints", json=[{"token_id": "t1"}, {"token_id": "t2"}]
        )

    @pytest.mark.asyncio
    async def test_list_response(self):
        client = _client()
        client._request.return_value = [
            {"token_id": "t1", "mid": "0.51"},
            {"token_id": "t2", "midpoint": "0.49"},
        ]
        out = await client.get_midpoints_batch(["t1", "t2"])
        assert out == {"t1": "0.51", "t2": "0.49"}

    @pytest.mark.asyncio
    async def test_null_batch_falls_back_to_singles(self):
        client = _client()
        client._request.return_value = None
        client.get_midpoint = AsyncMock(side_effect=["0.30", None])
        out = await client.get_midpoints_batch(["t1", "t2"])
        assert out == {"t1": "0.30"}
        assert client.get_midpoint.await_count == 2


class TestBooksBatch:
    @pytest.mark.asyncio
    async def test_books_keyed_by_asset_id_and_normalized(self):
        client = _client()
        client._request.return_value = [
            {
                "asset_id": "t1",
                "bids": [{"price": "0.40", "size": "1"}, {"price": "0.45", "size": "2"}],
                "asks": [{"price": "0.60", "size": "1"}, {"price": "0.55", "size": "2"}],
            }
        ]
        out = await client.get_books_batch(["t1"], depth_levels=1)
        assert out["t1"]["bids"] == [{"price": "0.45", "size": "2"}]
        assert out["t1"]["asks"] == [{"price": "0.55", "size": "2"}]

    @pytest.mark.asyncio
    async def test_chunking(self):
        client = _client()
        client._request.return_value = []
        await client.get_books_batch([f"t{i}" for i in range(250)])
        assert client._request.await_count == 3  # 100 + 100 + 50
