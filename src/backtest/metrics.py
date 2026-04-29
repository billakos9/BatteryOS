"""Forecast-accuracy and dispatch-economic metrics.

  Forecast accuracy (vs realized clearing prices)
    point_metrics            MAE, RMSE, sMAPE on the scenario mean
    quantile_pinball_score   pinball loss at q in (0, 1)
    crps_ensemble            Continuous Ranked Probability Score per timestamp

  Dispatch economics (vs the ground truth)
    perfect_foresight_pnl    optimum if you had known realized prices
    naive_seasonal_forecast  last-N-days same-MTU mean baseline
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from src.optimize import (
    BatteryProfile,
    PriceScenarios,
    optimize_dispatch,
)


def point_metrics(forecast_mean: Sequence[float], realized: Sequence[float]) -> dict:
    fm = np.asarray(forecast_mean, dtype=float)
    rz = np.asarray(realized, dtype=float)
    err = fm - rz
    denom = np.abs(fm) + np.abs(rz) + 1e-9
    return {
        "mae_eur_per_mwh": float(np.mean(np.abs(err))),
        "rmse_eur_per_mwh": float(np.sqrt(np.mean(err ** 2))),
        "smape": float(2.0 * np.mean(np.abs(err) / denom)),
        "bias_eur_per_mwh": float(np.mean(err)),
    }


def pinball_loss(quantile: float, observed: float, predicted: float) -> float:
    e = observed - predicted
    return max(quantile * e, (quantile - 1.0) * e)


def quantile_pinball_score(
    scenarios: PriceScenarios,
    realized: Sequence[float],
    quantiles: Sequence[float] = (0.1, 0.5, 0.9),
) -> dict:
    """Pinball loss per quantile, averaged over the horizon.

    Quantiles are extracted from the weighted scenario empirical CDF.
    """
    rz = np.asarray(realized, dtype=float)
    if len(rz) != scenarios.horizon:
        raise ValueError("realized length must equal scenarios.horizon")

    sort_idx = np.argsort(scenarios.prices, axis=0)
    sorted_p = np.take_along_axis(scenarios.prices, sort_idx, axis=0)
    sorted_w = scenarios.weights[sort_idx]
    cum_w = np.cumsum(sorted_w, axis=0)

    out: dict = {}
    for q in quantiles:
        q_pred = np.zeros(scenarios.horizon)
        for t in range(scenarios.horizon):
            j = int(np.searchsorted(cum_w[:, t], q, side="left"))
            j = min(j, scenarios.n_scenarios - 1)
            q_pred[t] = sorted_p[j, t]
        losses = [pinball_loss(q, float(rz[t]), float(q_pred[t])) for t in range(scenarios.horizon)]
        out[f"pinball_q{int(round(q*100))}"] = float(np.mean(losses))
    return out


def crps_ensemble(scenarios: PriceScenarios, realized: Sequence[float]) -> np.ndarray:
    """Per-timestamp CRPS from the weighted ensemble.

    CRPS(F, y) = E_F |X - y| - 0.5 * E_F |X - X'|
    """
    rz = np.asarray(realized, dtype=float)
    T = scenarios.horizon
    if len(rz) != T:
        raise ValueError("realized length must equal scenarios.horizon")
    prices = scenarios.prices
    weights = scenarios.weights
    crps = np.zeros(T)
    for t in range(T):
        s = prices[:, t]
        term1 = float(np.sum(weights * np.abs(s - rz[t])))
        diff = np.abs(s[:, None] - s[None, :])
        term2 = 0.5 * float(weights @ diff @ weights)
        crps[t] = term1 - term2
    return crps


def perfect_foresight_pnl(
    realized_prices: Sequence[float],
    battery: BatteryProfile,
    duration_hours: float = 0.25,
    timestamps: Sequence | None = None,
) -> dict:
    """Profit obtainable if realized prices had been known in advance.

    Solves the optimizer with one scenario equal to the realized curve.
    This is the headline benchmark: % of perfect foresight is the most
    important number in the deck.
    """
    rp = np.asarray(realized_prices, dtype=float)
    if timestamps is None:
        timestamps = list(range(len(rp)))
    sc = PriceScenarios(
        timestamps=list(timestamps),
        prices=rp.reshape(1, -1),
        weights=np.array([1.0]),
        labels=["perfect"],
    )
    result = optimize_dispatch(
        sc,
        battery,
        duration_hours=duration_hours,
        n_reduced_scenarios=None,
        alpha=1.0,
        risk_aversion=0.0,
        build_bid_curves=False,
        run_robustness_sweep=False,
    )
    return {
        "perfect_foresight_profit_eur": float(result.schedule.total_profit()),
        "schedule": result.schedule,
    }


def naive_seasonal_forecast(
    history: pd.Series,
    target_timestamps: pd.DatetimeIndex,
    asof: pd.Timestamp,
    lookback_days: int = 7,
) -> np.ndarray:
    """Naive point forecast: average the same-MTU value over the last
    `lookback_days` days strictly before `asof`. Returns a 1-D array
    aligned with `target_timestamps`.
    """
    if not isinstance(history.index, pd.DatetimeIndex):
        raise ValueError("history must be DateTime-indexed")

    T = len(target_timestamps)
    accum = np.zeros(T)
    n_used = 0
    for i in range(1, lookback_days + 1):
        shift = pd.Timedelta(days=i)
        shifted = pd.DatetimeIndex(target_timestamps) - shift
        if (shifted >= asof).any():
            continue
        try:
            vals = history.reindex(shifted)
        except Exception:
            continue
        if vals.isna().any():
            continue
        accum += vals.to_numpy()
        n_used += 1
    if n_used == 0:
        raise ValueError("naive_seasonal_forecast: no valid lookback days before asof")
    return accum / n_used
