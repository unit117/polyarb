"""Integration tests for the detector pipeline with mocked DB/Redis/OpenAI."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.detector.pipeline import DetectionPipeline, _market_to_dict


def _mock_session_factory():
    """Create a mock async session factory."""
    session = AsyncMock()
    session.add = MagicMock()  # add() is sync
    factory = AsyncMock()
    factory.__aenter__ = AsyncMock(return_value=session)
    factory.__aexit__ = AsyncMock(return_value=False)

    def create():
        return factory
    return create, session


def _make_market_model(
    market_id, question, outcomes=None, event_id=None, venue="polymarket",
    description="",
):
    m = MagicMock()
    m.id = market_id
    m.question = question
    m.outcomes = outcomes or ["Yes", "No"]
    m.event_id = event_id
    m.description = description
    m.venue = venue
    return m


class TestMarketToDict:
    def test_converts_model_to_dict(self):
        m = _make_market_model(1, "Will X happen?", ["Yes", "No"], "evt1")
        d = _market_to_dict(m)
        assert d["id"] == 1
        assert d["question"] == "Will X happen?"
        assert d["outcomes"] == ["Yes", "No"]
        assert d["event_id"] == "evt1"
        assert d["venue"] == "polymarket"


class TestDetectionPipelineRunOnce:
    @pytest.mark.asyncio
    async def test_no_candidates_returns_zero_stats(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        openai_client = AsyncMock()

        pipeline = DetectionPipeline(
            session_factory=factory_fn,
            openai_client=openai_client,
            redis=redis,
            similarity_threshold=0.82,
            similarity_top_k=20,
            batch_size=100,
            classifier_model="gpt-4.1-mini",
        )

        with patch("services.detector.pipeline.find_similar_pairs", new_callable=AsyncMock) as mock_sim:
            mock_sim.return_value = []

            with patch("services.detector.pipeline.settings") as mock_settings:
                mock_settings.kalshi_enabled = False
                mock_settings.uncertainty_price_floor = 0.05
                mock_settings.uncertainty_price_ceil = 0.95

                result = await pipeline.run_once()

        assert result["candidates"] == 0
        assert result["pairs_created"] == 0

    @pytest.mark.asyncio
    async def test_creates_pair_from_candidate(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        openai_client = AsyncMock()

        market_a = _make_market_model(1, "PLTR above $128?", event_id="evt1")
        market_b = _make_market_model(2, "PLTR above $134?", event_id="evt1")

        # Mock the market query
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[market_a, market_b])
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)

        # Mock price snapshot query
        snap = MagicMock()
        snap.prices = {"Yes": 0.7, "No": 0.3}
        mock_price_result = MagicMock()
        mock_price_result.scalar_one_or_none = MagicMock(return_value=snap)

        call_count = [0]
        async def mock_execute(stmt):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_result  # Market query
            return mock_price_result  # Price queries
        session.execute = AsyncMock(side_effect=mock_execute)

        # Mock pair flush (assign ID)
        flush_count = [0]
        async def mock_flush():
            flush_count[0] += 1
        session.flush = AsyncMock(side_effect=mock_flush)

        pipeline = DetectionPipeline(
            session_factory=factory_fn,
            openai_client=openai_client,
            redis=redis,
            similarity_threshold=0.82,
            similarity_top_k=20,
            batch_size=100,
            classifier_model="gpt-4.1-mini",
        )

        candidates = [{"market_a_id": 1, "market_b_id": 2, "similarity": 0.90}]

        with patch("services.detector.pipeline.find_similar_pairs", new_callable=AsyncMock) as mock_sim:
            mock_sim.return_value = candidates

            # Mock classify_pair to return a partition (same event_id triggers rule-based)
            with patch("services.detector.pipeline.classify_pair", new_callable=AsyncMock) as mock_classify:
                mock_classify.return_value = {
                    "dependency_type": "partition",
                    "confidence": 0.95,
                    "reasoning": "Same event",
                }

                with patch("services.detector.pipeline.settings") as mock_settings:
                    mock_settings.kalshi_enabled = False
                    mock_settings.max_snapshot_age_seconds = 0
                    mock_settings.uncertainty_price_floor = 0.05
                    mock_settings.uncertainty_price_ceil = 0.95

                    # Mock _rescan_existing_pairs to avoid complex queries
                    with patch.object(pipeline, "_rescan_existing_pairs", new_callable=AsyncMock) as mock_rescan:
                        mock_rescan.return_value = {"opportunities": 0}

                        result = await pipeline.run_once()

        assert result["candidates"] == 1
        assert result["pairs_created"] >= 1
        # session.add should have been called with a MarketPair
        assert session.add.called

    @pytest.mark.asyncio
    async def test_skips_none_dependency(self):
        factory_fn, session = _mock_session_factory()
        redis = AsyncMock()
        openai_client = AsyncMock()

        market_a = _make_market_model(1, "Question A")
        market_b = _make_market_model(2, "Question B")

        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[market_a, market_b])
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        session.execute = AsyncMock(return_value=mock_result)

        pipeline = DetectionPipeline(
            session_factory=factory_fn,
            openai_client=openai_client,
            redis=redis,
            similarity_threshold=0.82,
            similarity_top_k=20,
            batch_size=100,
            classifier_model="gpt-4.1-mini",
        )

        candidates = [{"market_a_id": 1, "market_b_id": 2, "similarity": 0.85}]

        with patch("services.detector.pipeline.find_similar_pairs", new_callable=AsyncMock) as mock_sim:
            mock_sim.return_value = candidates

            with patch("services.detector.pipeline.classify_pair", new_callable=AsyncMock) as mock_classify:
                mock_classify.return_value = {
                    "dependency_type": "none",
                    "confidence": 0.10,
                }

                with patch("services.detector.pipeline.settings") as mock_settings:
                    mock_settings.kalshi_enabled = False
                    mock_settings.uncertainty_price_floor = 0.05
                    mock_settings.uncertainty_price_ceil = 0.95

                    with patch.object(pipeline, "_rescan_existing_pairs", new_callable=AsyncMock) as mock_rescan:
                        mock_rescan.return_value = {"opportunities": 0}

                        result = await pipeline.run_once()

        assert result["candidates"] == 1
        assert result["pairs_created"] == 0  # Skipped because dep_type == "none"
