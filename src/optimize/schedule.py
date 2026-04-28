from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

SCHEDULE_COLUMNS: list[str] = [
    "timestamp",
    "forecast_price_eur_per_mwh",
    "charge_mw",
    "discharge_mw",
    "state_of_charge_mwh",
    "action",
    "period_profit_eur",
]

ACTION_CHARGE = "CHARGE"
ACTION_DISCHARGE = "DISCHARGE"
ACTION_IDLE = "IDLE"

EPSILON_MW = 1e-3


def label_action(charge_mw: float, discharge_mw: float) -> str:
    if charge_mw > EPSILON_MW:
        return ACTION_CHARGE
    if discharge_mw > EPSILON_MW:
        return ACTION_DISCHARGE
    return ACTION_IDLE


@dataclass
class Schedule:
    df: pd.DataFrame
    duration_hours: float
    objective_value: float
    solver_status: str
    metadata: dict

    def total_profit(self) -> float:
        return float(self.df["period_profit_eur"].sum())

    def revenue(self) -> float:
        prices = self.df["forecast_price_eur_per_mwh"].to_numpy()
        net_export = self.df["discharge_mw"].to_numpy() - self.df["charge_mw"].to_numpy()
        return float(np.sum(prices * net_export) * self.duration_hours)

    def throughput_mwh(self) -> float:
        gross = self.df["charge_mw"].to_numpy() + self.df["discharge_mw"].to_numpy()
        return float(np.sum(gross) * self.duration_hours)


def build_schedule_frame(
    timestamps: Sequence,
    prices: Sequence[float],
    charge_mw: Sequence[float],
    discharge_mw: Sequence[float],
    soc_mwh: Sequence[float],
    duration_hours: float,
    degradation_cost_eur_per_mwh: float,
) -> pd.DataFrame:
    timestamps = list(timestamps)
    prices = np.asarray(prices, dtype=float)
    charge = np.asarray(charge_mw, dtype=float)
    discharge = np.asarray(discharge_mw, dtype=float)
    soc = np.asarray(soc_mwh, dtype=float)

    market_profit = prices * (discharge - charge) * duration_hours
    deg_cost = degradation_cost_eur_per_mwh * (charge + discharge) * duration_hours
    period_profit = market_profit - deg_cost

    actions = [label_action(c, d) for c, d in zip(charge, discharge)]

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "forecast_price_eur_per_mwh": prices,
            "charge_mw": charge,
            "discharge_mw": discharge,
            "state_of_charge_mwh": soc,
            "action": actions,
            "period_profit_eur": period_profit,
        },
        columns=SCHEDULE_COLUMNS,
    )
