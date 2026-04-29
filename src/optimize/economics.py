from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from .battery import BatteryProfile


@dataclass
class FeasibilityReport:
    feasible: bool
    soc_min_violation_mwh: float
    soc_max_violation_mwh: float
    power_violation_mw: float
    simultaneity_violation_mw: float
    cycles_used: float
    cycle_violation: float
    dynamics_residual_mwh: float
    terminal_soc_violation_mwh: float


def period_profit(
    price_eur_per_mwh: float,
    charge_mw: float,
    discharge_mw: float,
    duration_hours: float,
    degradation_cost_eur_per_mwh: float,
) -> float:
    market = price_eur_per_mwh * (discharge_mw - charge_mw) * duration_hours
    deg = degradation_cost_eur_per_mwh * (charge_mw + discharge_mw) * duration_hours
    return market - deg


def equivalent_full_cycles(
    charge_mw: Sequence[float],
    discharge_mw: Sequence[float],
    duration_hours: float,
    usable_energy_mwh: float,
) -> float:
    throughput = (np.asarray(charge_mw).sum() + np.asarray(discharge_mw).sum()) * duration_hours
    return float(throughput / (2.0 * usable_energy_mwh))


def evaluate_schedule(
    schedule_df: pd.DataFrame,
    realized_prices: Sequence[float],
    battery: BatteryProfile,
    duration_hours: float,
) -> dict:
    realized = np.asarray(realized_prices, dtype=float)
    charge = schedule_df["charge_mw"].to_numpy()
    discharge = schedule_df["discharge_mw"].to_numpy()

    if len(realized) != len(charge):
        raise ValueError("realized_prices length must match schedule length")

    market_profit = float(np.sum(realized * (discharge - charge)) * duration_hours)
    throughput = float(np.sum(charge + discharge) * duration_hours)
    deg_cost = float(battery.degradation_cost_eur_per_mwh * throughput)
    tx_cost = float(battery.transaction_cost_eur_per_mwh * throughput)
    realized_profit = market_profit - deg_cost - tx_cost

    cycles = equivalent_full_cycles(charge, discharge, duration_hours, battery.usable_energy_mwh)

    days = len(charge) * duration_hours / 24.0
    cycle_violation = max(0.0, cycles - battery.max_cycles_per_day * days)

    return {
        "realized_profit_eur": realized_profit,
        "market_profit_eur": market_profit,
        "degradation_cost_eur": deg_cost,
        "transaction_cost_eur": tx_cost,
        "cycles_used": cycles,
        "cycle_violation": cycle_violation,
        "throughput_mwh": throughput,
    }


def feasibility_report(
    schedule_df: pd.DataFrame,
    battery: BatteryProfile,
    duration_hours: float,
    tol_mw: float = 1e-4,
) -> FeasibilityReport:
    charge = schedule_df["charge_mw"].to_numpy()
    discharge = schedule_df["discharge_mw"].to_numpy()
    soc = schedule_df["state_of_charge_mwh"].to_numpy()
    n = len(charge)

    soc_min_v = float(np.maximum(0.0, battery.soc_min_mwh - soc).max())
    soc_max_v = float(np.maximum(0.0, soc - battery.soc_max_mwh).max())
    power_v = float(
        max(
            np.maximum(0.0, charge - battery.power_mw).max(),
            np.maximum(0.0, discharge - battery.power_mw).max(),
        )
    )
    sim_v = float(np.minimum(charge, discharge).max())

    cycles = equivalent_full_cycles(charge, discharge, duration_hours, battery.usable_energy_mwh)
    days = n * duration_hours / 24.0
    cycle_v = max(0.0, cycles - battery.max_cycles_per_day * days)

    decay = 1.0 - battery.self_discharge_per_hour * duration_hours
    sim_soc = np.zeros(n)
    state = battery.initial_soc_mwh
    for t in range(n):
        state = (
            decay * state
            + battery.charge_efficiency * charge[t] * duration_hours
            - discharge[t] * duration_hours / battery.discharge_efficiency
        )
        sim_soc[t] = state
    dynamics_residual = float(np.max(np.abs(sim_soc - soc))) if n > 0 else 0.0

    if battery.terminal_soc_mwh is not None and n > 0:
        terminal_v = float(max(0.0, battery.terminal_soc_mwh - soc[-1]))
    else:
        terminal_v = 0.0

    feasible = (
        max(soc_min_v, soc_max_v, power_v, sim_v, cycle_v, terminal_v) <= tol_mw
        and dynamics_residual <= max(tol_mw, 1e-3)
    )

    return FeasibilityReport(
        feasible=feasible,
        soc_min_violation_mwh=soc_min_v,
        soc_max_violation_mwh=soc_max_v,
        power_violation_mw=power_v,
        simultaneity_violation_mw=sim_v,
        cycles_used=cycles,
        cycle_violation=cycle_v,
        dynamics_residual_mwh=dynamics_residual,
        terminal_soc_violation_mwh=terminal_v,
    )
