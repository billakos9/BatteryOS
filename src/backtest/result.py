"""BacktestDay and BacktestResult containers.

Each backtested day produces a BacktestDay record. The BacktestResult
holds them all plus the aggregated headline metrics that the dashboard
and the pitch deck consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from src.optimize import BatteryProfile, DispatchResult, PriceScenarios


@dataclass
class BacktestDay:
    target_day: pd.Timestamp
    asof: pd.Timestamp
    forecast_scenarios: PriceScenarios
    dispatch: DispatchResult
    realized_prices: np.ndarray
    realized_pnl_eur: float
    perfect_foresight_pnl_eur: float
    naive_pnl_eur: float
    initial_soc_mwh: float
    final_soc_mwh: float
    forecast_metrics: dict = field(default_factory=dict)

    def pct_of_perfect(self) -> float:
        if self.perfect_foresight_pnl_eur > 0:
            return float(self.realized_pnl_eur / self.perfect_foresight_pnl_eur)
        return float("nan")

    def lift_over_naive(self) -> float:
        if self.naive_pnl_eur != 0:
            return float((self.realized_pnl_eur - self.naive_pnl_eur) / abs(self.naive_pnl_eur))
        return float("nan")


@dataclass
class BacktestResult:
    days: list[BacktestDay]
    battery: BatteryProfile
    metadata: dict = field(default_factory=dict)

    def daily_table(self) -> pd.DataFrame:
        rows = []
        for d in self.days:
            row = {
                "target_day": d.target_day,
                "asof": d.asof,
                "initial_soc_mwh": d.initial_soc_mwh,
                "final_soc_mwh": d.final_soc_mwh,
                "realized_pnl_eur": d.realized_pnl_eur,
                "perfect_foresight_pnl_eur": d.perfect_foresight_pnl_eur,
                "naive_pnl_eur": d.naive_pnl_eur,
                "pct_of_perfect": d.pct_of_perfect(),
                "lift_over_naive": d.lift_over_naive(),
                "n_scenarios": d.forecast_scenarios.n_scenarios,
            }
            for k, v in d.forecast_metrics.items():
                row[f"forecast_{k}"] = v
            rows.append(row)
        return pd.DataFrame(rows)

    def headline_metrics(self) -> dict:
        df = self.daily_table()
        if df.empty:
            return {}
        total_pf = float(df["perfect_foresight_pnl_eur"].sum())
        total_realized = float(df["realized_pnl_eur"].sum())
        total_naive = float(df["naive_pnl_eur"].sum())
        return {
            "n_days": int(len(df)),
            "total_realized_pnl_eur": total_realized,
            "total_perfect_foresight_pnl_eur": total_pf,
            "total_naive_pnl_eur": total_naive,
            "overall_pct_of_perfect": float(total_realized / total_pf) if total_pf > 0 else float("nan"),
            "overall_lift_over_naive": (
                float((total_realized - total_naive) / abs(total_naive))
                if total_naive != 0
                else float("nan")
            ),
            "avg_pct_of_perfect": float(df["pct_of_perfect"].mean()),
            "avg_lift_over_naive": float(df["lift_over_naive"].mean()),
            "avg_forecast_mae_eur_per_mwh": (
                float(df["forecast_mae_eur_per_mwh"].mean())
                if "forecast_mae_eur_per_mwh" in df
                else float("nan")
            ),
            "avg_forecast_rmse_eur_per_mwh": (
                float(df["forecast_rmse_eur_per_mwh"].mean())
                if "forecast_rmse_eur_per_mwh" in df
                else float("nan")
            ),
            "avg_forecast_crps_eur_per_mwh": (
                float(df["forecast_crps_mean"].mean()) if "forecast_crps_mean" in df else float("nan")
            ),
        }

    def to_long_dispatch_frame(self) -> pd.DataFrame:
        """Concatenate every day's schedule into a long frame for plotting."""
        frames = []
        for d in self.days:
            df = d.dispatch.schedule.df.copy()
            df["target_day"] = d.target_day
            df["realized_price_eur_per_mwh"] = d.realized_prices
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
