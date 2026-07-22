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

        async def fake_request(method, url, **kwargs):
            # Return a book for every requested token so no fallback fires
            return [
                {"token_id": p["token_id"], "bids": [], "asks": [["0.5", "1"]]}
                for p in kwargs["json"]
            ]

        client._request = AsyncMock(side_effect=fake_request)
        out = await client.get_books_batch([f"t{i}" for i in range(250)])
        assert client._request.await_count == 3  # 100 + 100 + 50
        assert len(out) == 250


class TestBatchFallbackSemantics:
    @pytest.mark.asyncio
    async def test_transport_error_skips_chunk_without_sequential_storm(self):
        import httpx

        client = _client()
        client._request.side_effect = httpx.ConnectError("down")
        client.get_midpoint = AsyncMock()
        out = await client.get_midpoints_batch(["t1", "t2"])
        assert out == {}
        client.get_midpoint.assert_not_awaited()  # no 100x doomed fallback

    @pytest.mark.asyncio
    async def test_accepted_but_empty_response_triggers_fallback(self):
        client = _client()
        client._request.return_value = {}
        client.get_midpoint = AsyncMock(side_effect=["0.4", "0.6"])
        out = await client.get_midpoints_batch(["t1", "t2"])
        assert out == {"t1": "0.4", "t2": "0.6"}
        assert client.get_midpoint.await_count == 2


class TestCoverageTrim:
    def _m(self, mid, liq):
        from types import SimpleNamespace

        return SimpleNamespace(id=mid, liquidity=liq)

    def test_discovery_set_survives_paired_flood(self):
        from services.ingestor.polling import trim_snapshot_coverage

        discovery = [self._m(i, 1000 - i) for i in range(10)]
        paired = [self._m(100 + i, 5) for i in range(100)]
        out = trim_snapshot_coverage(
            discovery + paired,
            liquidity_top_ids={m.id for m in discovery},
            paired_ids={m.id for m in paired},
            cap=50,
        )
        kept = {m.id for m in out}
        assert {m.id for m in discovery} <= kept  # reserved unconditionally
        assert len(out) == 50

    def test_paired_outrank_unpaired_in_remaining_budget(self):
        from services.ingestor.polling import trim_snapshot_coverage

        top = [self._m(1, 100)]
        paired = [self._m(2, 1)]
        unpaired_liquid = [self._m(3, 99)]
        out = trim_snapshot_coverage(
            top + paired + unpaired_liquid,
            liquidity_top_ids={1},
            paired_ids={2},
            cap=2,
        )
        assert {m.id for m in out} == {1, 2}

    def test_under_cap_untouched(self):
        from services.ingestor.polling import trim_snapshot_coverage

        markets = [self._m(i, i) for i in range(5)]
        assert trim_snapshot_coverage(markets, {0}, {1}, cap=10) is markets
