"""Forecaster contract and a reference baseline implementation.

The backtester does NOT know about your forecaster's internals. It only
calls a single function: `forecaster(asof, target_day, n_scenarios)`,
which must return a `PriceScenarios` covering exactly the delivery day.

This file provides:

  Forecaster              The Protocol (typing.Protocol) you can target.
  naive_seasonal_forecaster
                          A drop-in reference implementation that uses a
                          last-7-days same-hour mean + Gaussian noise.
                          Use it to smoke-test the backtester before the
                          real ML forecaster is ready.
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from src.optimize import PriceScenarios


@runtime_checkable
class Forecaster(Protocol):
    """The contract the forecaster module must satisfy.

    The backtester will call `forecaster(asof, target_day, n_scenarios)`
    once per delivery day. The forecaster must return a `PriceScenarios`
    bundle whose `timestamps` match the delivery-day MTU axis exactly.

    Strict point-in-time rule: the forecaster MUST NOT consume any data
    whose release timestamp is greater than `asof`. The backtester does
    not enforce this — the forecaster is trusted to be PIT-correct.
    """

    def __call__(
        self,
        asof: pd.Timestamp,
        target_day: pd.Timestamp,
        n_scenarios: int = 30,
        timestamps: Optional[pd.DatetimeIndex] = None,
    ) -> PriceScenarios: ...


def naive_seasonal_forecaster(
    history: pd.Series,
    *,
    lookback_days: int = 7,
    noise_std_eur_per_mwh: float = 20.0,
    seed: int = 0,
) -> Callable[..., PriceScenarios]:
    """Build a naive forecaster from a historical price series.

    The returned callable conforms to the Forecaster protocol. For each
    target day, it averages the same MTU-of-day across the previous
    `lookback_days` days that ended before `asof`, then samples
    n_scenarios trajectories by adding i.i.d. Gaussian noise around the
    mean curve. This is the canonical naive baseline; your real
    forecaster should beat it.

    Args:
        history:
            DateTime-indexed Series of historical clearing prices, sampled
            at the same MTU as the test horizon (e.g. 15-min for SDAC).
        lookback_days:
            Number of trailing days to average for the seasonal mean.
        noise_std_eur_per_mwh:
            Standard deviation of the additive noise used to materialize
            ensemble scenarios.
        seed:
            RNG seed for reproducibility.
    """
    if not isinstance(history.index, pd.DatetimeIndex):
        raise ValueError("history must be DateTime-indexed")
    rng = np.random.default_rng(seed)

    def _forecaster(
        asof: pd.Timestamp,
        target_day: pd.Timestamp,
        n_scenarios: int = 30,
        timestamps: Optional[pd.DatetimeIndex] = None,
    ) -> PriceScenarios:
        if timestamps is None:
            day_start = pd.Timestamp(target_day).normalize()
            inferred_freq = pd.infer_freq(history.index[-50:]) or "15min"
            timestamps = pd.date_range(
                day_start, day_start + pd.Timedelta(days=1), freq=inferred_freq, inclusive="left"
            )
        T = len(timestamps)
        same_mtu_means = np.zeros(T)
        n_used = 0
        for i in range(1, lookback_days + 1):
            shift = pd.Timedelta(days=i)
            shifted = pd.DatetimeIndex(timestamps) - shift
            past = shifted[shifted < asof]
            if len(past) != T:
                continue
            try:
                vals = history.reindex(past)
            except Exception:
                continue
            if vals.isna().any():
                continue
            same_mtu_means += vals.to_numpy()
            n_used += 1
        if n_used == 0:
            raise ValueError(
                f"naive_seasonal_forecaster: no valid lookback days before asof={asof}"
            )
        mean_curve = same_mtu_means / n_used

        samples = mean_curve[None, :] + rng.normal(
            0.0, noise_std_eur_per_mwh, size=(n_scenarios, T)
        )
        weights = np.full(n_scenarios, 1.0 / n_scenarios)
        return PriceScenarios(
            timestamps=list(timestamps),
            prices=samples,
            weights=weights,
            labels=[f"naive_{i}" for i in range(n_scenarios)],
        )

    return _forecaster
