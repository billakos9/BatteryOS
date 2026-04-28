from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


@dataclass
class PriceScenarios:
    """Bundle of equal-length price curves with probability weights.

    Attributes:
        timestamps: shared time axis (length T).
        prices: matrix of shape (S, T), one row per scenario.
        weights: probability mass per scenario, sums to 1, length S.
        labels: human-readable scenario names, length S.
    """

    timestamps: list
    prices: np.ndarray
    weights: np.ndarray
    labels: list[str]

    def __post_init__(self) -> None:
        self.prices = np.asarray(self.prices, dtype=float)
        self.weights = np.asarray(self.weights, dtype=float)
        if self.prices.ndim != 2:
            raise ValueError("prices must be 2D (S, T)")
        if self.prices.shape[0] != len(self.weights):
            raise ValueError("weights must match number of scenarios")
        if self.prices.shape[1] != len(self.timestamps):
            raise ValueError("prices columns must match timestamps")
        if len(self.labels) != len(self.weights):
            raise ValueError("labels must match number of scenarios")
        total = float(self.weights.sum())
        if not np.isclose(total, 1.0):
            raise ValueError(f"weights must sum to 1, got {total}")

    @property
    def n_scenarios(self) -> int:
        return self.prices.shape[0]

    @property
    def horizon(self) -> int:
        return self.prices.shape[1]

    def expected_prices(self) -> np.ndarray:
        return self.weights @ self.prices


def scenarios_from_quantiles(
    timestamps: Sequence,
    p10: Sequence[float],
    p50: Sequence[float],
    p90: Sequence[float],
    weights: tuple[float, float, float] = (0.2, 0.6, 0.2),
) -> PriceScenarios:
    """Three-scenario representation from quantile forecasts.

    The (0.2, 0.6, 0.2) default approximates a normal distribution: it lines
    up the three points with the means of the lower 20%, middle 60%, and
    upper 20% of a Gaussian and gives a CRPS close to the underlying
    distribution. Tune the weights if your forecaster is heavy-tailed.
    """
    arr = np.vstack(
        [np.asarray(p10, dtype=float), np.asarray(p50, dtype=float), np.asarray(p90, dtype=float)]
    )
    return PriceScenarios(
        timestamps=list(timestamps),
        prices=arr,
        weights=np.array(weights, dtype=float),
        labels=["p10", "p50", "p90"],
    )


def scenarios_from_samples(
    timestamps: Sequence,
    samples: np.ndarray,
    n_reduced: int = 20,
    rng_seed: int = 0,
) -> PriceScenarios:
    """Reduce a Monte Carlo ensemble to `n_reduced` scenarios via k-means.

    `samples` has shape (N, T): N draws of the price curve from the
    forecaster (or bootstrap resamples). Returns the cluster centroids
    weighted by cluster membership probability. This is the standard
    scenario-reduction step used in industrial stochastic optimizers.
    """
    samples = np.asarray(samples, dtype=float)
    if samples.ndim != 2:
        raise ValueError("samples must be 2D (N, T)")
    n_samples, horizon = samples.shape
    if horizon != len(timestamps):
        raise ValueError("samples columns must match timestamps")
    if n_reduced >= n_samples:
        weights = np.full(n_samples, 1.0 / n_samples)
        labels = [f"s{i}" for i in range(n_samples)]
        return PriceScenarios(
            timestamps=list(timestamps), prices=samples, weights=weights, labels=labels
        )

    centroids, assignments = _kmeans(samples, n_reduced, rng_seed)
    counts = np.bincount(assignments, minlength=n_reduced).astype(float)
    nonzero = counts > 0
    centroids = centroids[nonzero]
    counts = counts[nonzero]
    weights = counts / counts.sum()
    labels = [f"c{i}" for i in range(centroids.shape[0])]
    return PriceScenarios(
        timestamps=list(timestamps), prices=centroids, weights=weights, labels=labels
    )


def _kmeans(
    data: np.ndarray, k: int, seed: int, max_iter: int = 50, tol: float = 1e-4
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = data.shape[0]
    init_idx = rng.choice(n, size=k, replace=False)
    centroids = data[init_idx].copy()

    for _ in range(max_iter):
        dists = np.linalg.norm(data[:, None, :] - centroids[None, :, :], axis=2)
        assignments = np.argmin(dists, axis=1)
        new_centroids = np.zeros_like(centroids)
        for j in range(k):
            mask = assignments == j
            if mask.any():
                new_centroids[j] = data[mask].mean(axis=0)
            else:
                new_centroids[j] = data[rng.integers(0, n)]
        shift = float(np.linalg.norm(new_centroids - centroids))
        centroids = new_centroids
        if shift < tol:
            break
    return centroids, assignments
