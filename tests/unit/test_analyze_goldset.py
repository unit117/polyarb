"""Tests for V4 gold set analyzer — pure functions, no DB needed."""

import json
import tempfile
from pathlib import Path

from scripts.analyze_goldset import analyze, check_gate, load_dataset


def _make_records(n, dep_type="implication", family="crypto_threshold", labeled=False):
    """Create test gold set records."""
    return [
        {
            "pair_id": i,
            "market_a_id": i * 10,
            "market_b_id": i * 10 + 1,
            "current_dependency_type": dep_type,
            "pair_family": family,
            "selection_bucket": "resolved_verified",
            "shared_keywords": ["bitcoin", "price"],
            "semantic_similarity": 0.92 if i % 2 == 0 else None,
            "family_key_a": f"btc_december_{i}",
            "family_key_b": f"btc_january_{i}",
            "ground_truth_type": dep_type if labeled else "",
            "correct": None,
        }
        for i in range(n)
    ]


class TestAnalyze:
    def test_basic_stats(self):
        records = _make_records(20)
        stats = analyze(records)
        assert stats["total_pairs"] == 20
        assert stats["dep_type_counts"]["implication"] == 20
        assert stats["family_counts"]["crypto_threshold"] == 20
        assert stats["labeled"] == 0
        assert stats["unlabeled"] == 20

    def test_labeled_records(self):
        records = _make_records(10, labeled=True)
        stats = analyze(records)
        assert stats["labeled"] == 10
        assert stats["label_rate"] == 1.0
        assert stats["ground_truth_counts"]["implication"] == 10
        assert stats["correctness"]["correct"] == 10

    def test_mixed_dep_types(self):
        records = (
            _make_records(10, dep_type="implication")
            + _make_records(5, dep_type="mutual_exclusion")
            + _make_records(3, dep_type="partition")
        )
        stats = analyze(records)
        assert stats["total_pairs"] == 18
        assert stats["dep_type_counts"]["implication"] == 10
        assert stats["dep_type_counts"]["mutual_exclusion"] == 5
        assert stats["dep_type_counts"]["partition"] == 3

    def test_keyword_overlap(self):
        records = _make_records(5)
        stats = analyze(records)
        assert stats["keyword_overlap_mean"] == 2.0  # all have 2 keywords
        assert stats["keyword_overlap_max"] == 2
        assert stats["keyword_overlap_zero"] == 0

    def test_similarity_stats(self):
        records = _make_records(4)
        # Even-indexed have sim=0.92, odd have None
        stats = analyze(records)
        assert stats["similarity_count"] == 2
        assert stats["similarity_mean"] == 0.92

    def test_unique_markets(self):
        records = _make_records(3)
        # i=0 has market_a_id=0 (falsy, skipped), so 5 unique markets
        stats = analyze(records)
        assert stats["unique_markets"] == 5

    def test_empty_records(self):
        stats = analyze([])
        assert stats["total_pairs"] == 0
        assert stats["label_rate"] == 0.0


class TestCheckGate:
    def test_passes_good_dataset(self, capsys):
        records = (
            _make_records(50, dep_type="implication")
            + _make_records(40, dep_type="mutual_exclusion")
            + _make_records(30, dep_type="partition")
            + _make_records(30, dep_type="conditional")
            + _make_records(40, dep_type="none")
        )
        stats = analyze(records)
        assert check_gate(stats) is True

    def test_fails_too_few_total(self, capsys):
        records = _make_records(10)
        stats = analyze(records)
        assert check_gate(stats) is False
        captured = capsys.readouterr()
        assert "GATE FAIL" in captured.out

    def test_fails_missing_dep_type(self, capsys):
        records = (
            _make_records(100, dep_type="implication")
            + _make_records(60, dep_type="none")
        )
        stats = analyze(records)
        assert check_gate(stats) is False

    def test_fails_too_few_none(self, capsys):
        records = (
            _make_records(50, dep_type="implication")
            + _make_records(40, dep_type="mutual_exclusion")
            + _make_records(30, dep_type="partition")
            + _make_records(30, dep_type="conditional")
            + _make_records(10, dep_type="none")  # Only 10 < 30
        )
        stats = analyze(records)
        assert check_gate(stats) is False


class TestLoadDataset:
    def test_load_valid_json(self, tmp_path):
        path = tmp_path / "test.json"
        records = _make_records(3)
        path.write_text(json.dumps(records))
        loaded = load_dataset(path)
        assert len(loaded) == 3

    def test_load_not_list_exits(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"not": "a list"}))
        import pytest
        with pytest.raises(SystemExit):
            load_dataset(path)
