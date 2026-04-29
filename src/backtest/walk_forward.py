"""Walk-forward backtest of the (forecaster + optimize_dispatch) pipeline."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Optional, Sequence

import numpy as np
import pandas as pd

from src.optimize import (
    BatteryProfile,
    PriceScenarios,
    optimize_dispatch,
)

from .metrics import (
    crps_ensemble,
    naive_seasonal_forecast,
    perfect_foresight_pnl,
    point_metrics,
    quantile_pinball_score,
)
from .result import BacktestDay, BacktestResult


def run_walk_forward_backtest(
    realized_prices: pd.Series,
    forecaster: Callable[..., PriceScenarios],
    battery: BatteryProfile,
    test_days: Sequence,
    *,
    duration_hours: float = 0.25,
    gate_close_offset: pd.Timedelta = pd.Timedelta(hours=12),
    carry_soc: bool = True,
    n_scenarios: int = 30,
    alpha: float = 0.10,
    risk_aversion: float = 0.5,
    build_bid_curves: bool = False,
    run_robustness_sweep: bool = False,
    naive_lookback_days: int = 7,
    quantile_levels: Sequence[float] = (0.1, 0.5, 0.9),
) -> BacktestResult:
    """Run the walk-forward harness.

    Args:
        realized_prices:
            DateTime-indexed Series of historical clearing prices, sampled
            at the same MTU as `duration_hours`. Must cover all
            `test_days` plus the lookback window for naive baseline and
            for the forecaster's PIT inputs.
        forecaster:
            Callable conforming to `Forecaster` protocol:
            `forecaster(asof, target_day, n_scenarios, timestamps) -> PriceScenarios`.
        battery:
            BatteryProfile. SoC is carried day-to-day if `carry_soc=True`.
        test_days:
            Sequence of date-like values (one per delivery day to backtest).
        duration_hours:
            MTU length, e.g. 0.25 for 15-min SDAC, 1.0 for legacy hourly.
        gate_close_offset:
            asof = target_day_midnight - gate_close_offset. Default
            12:00 the day before delivery (SDAC convention).
        carry_soc:
            When True, the day-end SoC is rolled into the next day's
            initial SoC. Realistic. When False, every day starts at the
            battery profile's initial_soc_mwh — useful for daily-isolated
            ablations.
        n_scenarios:
            Hint passed to the forecaster.
        alpha, risk_aversion:
            Mean-CVaR knobs for the optimizer.
        build_bid_curves, run_robustness_sweep:
            Off by default (each adds many extra solves). Turn on for
            spot-checks or for the dashboard's deep-dive view.
        naive_lookback_days:
            Window for the naive seasonal baseline.
        quantile_levels:
            Quantiles to score with pinball loss.

    Returns:
        BacktestResult.
    """
    if not isinstance(realized_prices.index, pd.DatetimeIndex):
        raise ValueError("realized_prices must be DateTime-indexed")
    if realized_prices.index.tz is not None:
        realized_prices = realized_prices.copy()
        realized_prices.index = realized_prices.index.tz_localize(None)

    days_results: list[BacktestDay] = []
    initial_soc = battery.initial_soc_mwh

    for raw_day in test_days:
        target_day = pd.Timestamp(raw_day).normalize()
        asof = target_day - gate_close_offset

        day_end = target_day + pd.Timedelta(days=1)
        day_mask = (realized_prices.index >= target_day) & (realized_prices.index < day_end)
        day_prices = realized_prices.loc[day_mask]
        if day_prices.empty:
            raise ValueError(f"no realized prices found for {target_day.date()}")
        day_timestamps = day_prices.index

        scenarios = forecaster(
            asof=asof,
            target_day=target_day,
            n_scenarios=n_scenarios,
            timestamps=day_timestamps,
        )
        if len(scenarios.timestamps) != len(day_timestamps):
            raise ValueError(
                f"forecaster returned {len(scenarios.timestamps)} timestamps "
                f"for {target_day.date()}, expected {len(day_timestamps)}"
            )

        battery_today = (
            replace(battery, initial_soc_mwh=float(initial_soc)) if carry_soc else battery
        )

        result = optimize_dispatch(
            scenarios,
            battery_today,
            duration_hours=duration_hours,
            alpha=alpha,
            risk_aversion=risk_aversion,
            n_reduced_scenarios=None,
            build_bid_curves=build_bid_curves,
            run_robustness_sweep=run_robustness_sweep,
            realized_prices=day_prices.to_numpy(),
        )

        realized_pnl = float(result.realized_evaluation["realized_profit_eur"])

        pf = perfect_foresight_pnl(
            day_prices.to_numpy(),
            battery_today,
            duration_hours=duration_hours,
            timestamps=day_timestamps,
        )

        naive_curve = naive_seasonal_forecast(
            realized_prices, day_timestamps, asof=asof, lookback_days=naive_lookback_days
        )
        naive_sc = PriceScenarios(
            timestamps=list(day_timestamps),
            prices=naive_curve.reshape(1, -1),
            weights=np.array([1.0]),
            labels=["naive"],
        )
        naive_dispatch = optimize_dispatch(
            naive_sc,
            battery_today,
            duration_hours=duration_hours,
            alpha=1.0,
            risk_aversion=0.0,
            n_reduced_scenarios=None,
            build_bid_curves=False,
            run_robustness_sweep=False,
            realized_prices=day_prices.to_numpy(),
        )
        naive_pnl = float(naive_dispatch.realized_evaluation["realized_profit_eur"])

        realized_arr = day_prices.to_numpy()
        fmetrics = point_metrics(scenarios.expected_prices(), realized_arr)
        fmetrics.update(
            quantile_pinball_score(scenarios, realized_arr, quantiles=quantile_levels)
        )
        fmetrics["crps_mean"] = float(np.mean(crps_ensemble(scenarios, realized_arr)))

        final_soc = (
            float(result.schedule.df["state_of_charge_mwh"].iloc[-1])
            if not result.schedule.df.empty
            else float(initial_soc)
        )
        if carry_soc:
            initial_soc = max(
                battery.soc_min_mwh, min(battery.soc_max_mwh, final_soc)
            )

        days_results.append(
            BacktestDay(
                target_day=target_day,
                asof=asof,
                forecast_scenarios=scenarios,
                dispatch=result,
                realized_prices=realized_arr,
                realized_pnl_eur=realized_pnl,
                perfect_foresight_pnl_eur=float(pf["perfect_foresight_profit_eur"]),
                naive_pnl_eur=naive_pnl,
                initial_soc_mwh=float(battery_today.initial_soc_mwh),
                final_soc_mwh=final_soc,
                forecast_metrics=fmetrics,
            )
        )

    return BacktestResult(
        days=days_results,
        battery=battery,
        metadata={
            "duration_hours": duration_hours,
            "gate_close_offset_hours": gate_close_offset.total_seconds() / 3600.0,
            "carry_soc": carry_soc,
            "alpha": alpha,
            "risk_aversion": risk_aversion,
            "n_scenarios_hint": n_scenarios,
            "naive_lookback_days": naive_lookback_days,
        },
    )
