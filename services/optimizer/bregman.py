"""Bregman divergence (KL) and gradient for probability simplex.

The FWMM algorithm (Dudik et al. 2016) uses KL divergence as the Bregman
divergence for the probability simplex. This gives LMSR-like pricing.
"""

import numpy as np

# Small epsilon to avoid log(0)
_EPS = 1e-12


def kl_divergence(q: np.ndarray, p: np.ndarray) -> float:
    """Compute D_KL(q || p) = sum(q_i * log(q_i / p_i)).

    Args:
        q: Target distribution (what we're projecting to).
        p: Reference distribution (current market prices).

    Returns:
        KL divergence value.
    """
    q_safe = np.clip(q, _EPS, None)
    p_safe = np.clip(p, _EPS, None)
    return float(np.sum(q_safe * np.log(q_safe / p_safe)))


def kl_gradient(q: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Gradient of D_KL(q || p) with respect to q.

    ∇_q D_KL(q || p) = log(q) - log(p) + 1

    Args:
        q: Current iterate.
        p: Reference distribution (market prices).

    Returns:
        Gradient vector.
    """
    q_safe = np.clip(q, _EPS, None)
    p_safe = np.clip(p, _EPS, None)
    return np.log(q_safe) - np.log(p_safe) + 1.0


def duality_gap(gradient: np.ndarray, q: np.ndarray, s: np.ndarray) -> float:
    """Frank-Wolfe duality gap: <∇f(q), q - s>.

    This is an upper bound on f(q) - f(q*) and serves as the
    convergence criterion.
    """
    return float(np.dot(gradient, q - s))


def project_to_simplex(v: np.ndarray) -> np.ndarray:
    """Project a vector onto the probability simplex.

    Uses the algorithm from Duchi et al. (2008) for efficient projection.
    """
    n = len(v)
    u = np.sort(v)[::-1]
    cssv = np.cumsum(u) - 1.0
    rho = np.nonzero(u * np.arange(1, n + 1) > cssv)[0][-1]
    theta = cssv[rho] / (rho + 1.0)
    return np.maximum(v - theta, 0.0)
