"""Tests for Bregman divergence and simplex projection."""

import numpy as np
import pytest

from services.optimizer.bregman import (
    duality_gap,
    kl_divergence,
    kl_gradient,
    project_to_simplex,
)


class TestKLDivergence:
    def test_identical_distributions(self):
        p = np.array([0.5, 0.5])
        assert kl_divergence(p, p) == pytest.approx(0.0, abs=1e-10)

    def test_known_value(self):
        q = np.array([0.75, 0.25])
        p = np.array([0.5, 0.5])
        expected = 0.75 * np.log(0.75 / 0.5) + 0.25 * np.log(0.25 / 0.5)
        assert kl_divergence(q, p) == pytest.approx(expected, abs=1e-10)

    def test_non_negative(self):
        rng = np.random.default_rng(42)
        for _ in range(50):
            q = rng.dirichlet([1, 1, 1])
            p = rng.dirichlet([1, 1, 1])
            assert kl_divergence(q, p) >= -1e-12

    def test_asymmetric(self):
        q = np.array([0.8, 0.2])
        p = np.array([0.3, 0.7])
        assert kl_divergence(q, p) != pytest.approx(kl_divergence(p, q), abs=0.01)

    def test_handles_near_zero(self):
        q = np.array([1e-15, 1.0 - 1e-15])
        p = np.array([0.5, 0.5])
        result = kl_divergence(q, p)
        assert np.isfinite(result)


class TestKLGradient:
    def test_gradient_shape(self):
        q = np.array([0.3, 0.7])
        p = np.array([0.5, 0.5])
        grad = kl_gradient(q, p)
        assert grad.shape == q.shape

    def test_numerical_gradient(self):
        """Verify analytical gradient against numerical finite differences."""
        q = np.array([0.4, 0.6])
        p = np.array([0.5, 0.5])
        analytical = kl_gradient(q, p)

        eps = 1e-6
        numerical = np.zeros_like(q)
        for i in range(len(q)):
            q_plus = q.copy()
            q_plus[i] += eps
            q_minus = q.copy()
            q_minus[i] -= eps
            numerical[i] = (kl_divergence(q_plus, p) - kl_divergence(q_minus, p)) / (2 * eps)

        np.testing.assert_allclose(analytical, numerical, atol=1e-5)


class TestDualityGap:
    def test_zero_gap_same_point(self):
        q = np.array([0.5, 0.5])
        grad = np.array([1.0, -1.0])
        assert duality_gap(grad, q, q) == pytest.approx(0.0, abs=1e-12)

    def test_positive_gap(self):
        grad = np.array([2.0, 1.0])
        q = np.array([0.6, 0.4])
        s = np.array([0.0, 1.0])
        gap = duality_gap(grad, q, s)
        expected = np.dot(grad, q - s)
        assert gap == pytest.approx(expected)


class TestProjectToSimplex:
    def test_already_on_simplex(self):
        v = np.array([0.3, 0.3, 0.4])
        result = project_to_simplex(v)
        np.testing.assert_allclose(result, v, atol=1e-10)
        assert result.sum() == pytest.approx(1.0, abs=1e-10)

    def test_negative_values(self):
        v = np.array([-0.5, 0.8, 1.2])
        result = project_to_simplex(v)
        assert all(r >= -1e-12 for r in result)
        assert result.sum() == pytest.approx(1.0, abs=1e-10)

    def test_all_equal(self):
        v = np.array([3.0, 3.0, 3.0])
        result = project_to_simplex(v)
        np.testing.assert_allclose(result, [1 / 3, 1 / 3, 1 / 3], atol=1e-10)

    def test_one_hot(self):
        v = np.array([10.0, -5.0, -5.0])
        result = project_to_simplex(v)
        assert result[0] == pytest.approx(1.0, abs=1e-10)
        assert result[1] == pytest.approx(0.0, abs=1e-10)
        assert result[2] == pytest.approx(0.0, abs=1e-10)

    def test_two_dimensional(self):
        v = np.array([0.7, 0.8])
        result = project_to_simplex(v)
        assert result.sum() == pytest.approx(1.0, abs=1e-10)
        assert all(r >= -1e-12 for r in result)
