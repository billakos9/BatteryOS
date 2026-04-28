from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from .battery import BatteryProfile
from .schedule import Schedule, build_schedule_frame


def optimize_rule_based(
    timestamps: Sequence,
    forecast_prices: Sequence[float],
    battery: BatteryProfile,
    duration_hours: float = 0.25,
) -> Schedule:
    """Greedy rank-based heuristic.

    Picks the cheapest periods to fully charge and the most expensive periods
    to fully discharge, subject to power, SoC, and cycle limits. Used as a
    fast MVP and as a sanity floor for the MILP solvers.
    """
    prices = np.asarray(forecast_prices, dtype=float)
    n = len(prices)
    if n != len(timestamps):
        raise ValueError("timestamps and forecast_prices must have the same length")

    energy_per_step = battery.power_mw * duration_hours
    days = n * duration_hours / 24.0
    max_throughput = 2.0 * battery.max_cycles_per_day * days * battery.usable_energy_mwh

    breakeven = battery.degradation_cost_eur_per_mwh * 2.0 / max(battery.round_trip_efficiency, 1e-6)

    sorted_low = np.argsort(prices)
    sorted_high = np.argsort(-prices)

    charge = np.zeros(n)
    discharge = np.zeros(n)
    soc = np.full(n, battery.initial_soc_mwh)

    used_throughput = 0.0
    soc_state = battery.initial_soc_mwh

    plan: list[tuple[int, str]] = []
    i_low = i_high = 0
    while i_low < n and i_high < n and used_throughput + energy_per_step <= max_throughput:
        t_low = sorted_low[i_low]
        t_high = sorted_high[i_high]
        spread = prices[t_high] - prices[t_low]
        if spread <= breakeven:
            break
        if t_low == t_high:
            i_low += 1
            continue
        plan.append((t_low, "C"))
        plan.append((t_high, "D"))
        used_throughput += 2 * energy_per_step
        i_low += 1
        i_high += 1

    plan_by_t: dict[int, str] = {}
    for t, kind in plan:
        if t in plan_by_t:
            continue
        plan_by_t[t] = kind

    for t in range(n):
        kind = plan_by_t.get(t)
        if kind == "C":
            available = battery.soc_max_mwh - soc_state
            inflow_capacity = available / max(battery.charge_efficiency * duration_hours, 1e-9)
            p_ch = min(battery.power_mw, inflow_capacity)
            if p_ch > 0:
                charge[t] = p_ch
                soc_state = soc_state + battery.charge_efficiency * p_ch * duration_hours
        elif kind == "D":
            available = soc_state - battery.soc_min_mwh
            outflow_capacity = available * battery.discharge_efficiency / max(duration_hours, 1e-9)
            p_dis = min(battery.power_mw, outflow_capacity)
            if p_dis > 0:
                discharge[t] = p_dis
                soc_state = soc_state - p_dis * duration_hours / battery.discharge_efficiency

        soc_state = (1.0 - battery.self_discharge_per_hour * duration_hours) * soc_state
        soc_state = max(battery.soc_min_mwh, min(battery.soc_max_mwh, soc_state))
        soc[t] = soc_state

    df = build_schedule_frame(
        timestamps,
        prices,
        charge,
        discharge,
        soc,
        duration_hours,
        battery.degradation_cost_eur_per_mwh,
    )
    objective = float(df["period_profit_eur"].sum())
    return Schedule(
        df=df,
        duration_hours=duration_hours,
        objective_value=objective,
        solver_status="heuristic",
        metadata={"breakeven_eur_per_mwh": breakeven},
    )
