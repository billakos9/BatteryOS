"""Shared MILP building blocks for battery dispatch.

Uses PuLP because it ships with the CBC solver; swap to HiGHS via
`pulp.HiGHS_CMD()` for larger horizons. The same constraint structure is
reused by deterministic, stochastic, and CVaR objectives.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import pulp

from .battery import BatteryProfile


@dataclass
class BatteryMILP:
    prob: pulp.LpProblem
    p_ch: list[pulp.LpVariable]
    p_dis: list[pulp.LpVariable]
    soc: list[pulp.LpVariable]
    z: list[pulp.LpVariable]
    duration_hours: float


def build_battery_model(
    battery: BatteryProfile,
    horizon: int,
    duration_hours: float,
    name: str = "battery",
    enforce_disjunction: bool = False,
) -> BatteryMILP:
    """Construct the shared MILP/LP scaffolding.

    `enforce_disjunction=False` (default) drops the binary z(t) variables
    and solves the LP relaxation. With round-trip efficiency < 1 the LP
    optimum coincides with the MILP optimum because simultaneous charge
    and discharge is strictly dominated. For lossless storage
    (eta_rt >= 1) this is no longer guaranteed, so we require explicit
    binaries in that case.
    """
    if horizon <= 0:
        raise ValueError(f"horizon must be > 0, got {horizon}")
    if duration_hours <= 0:
        raise ValueError(f"duration_hours must be > 0, got {duration_hours}")
    if not enforce_disjunction and battery.round_trip_efficiency >= 1.0 - 1e-9:
        raise ValueError(
            "LP relaxation is not safe when round_trip_efficiency >= 1.0; "
            "the LP can return simultaneous charge+discharge. "
            "Pass enforce_disjunction=True for lossless storage."
        )
    prob = pulp.LpProblem(name, pulp.LpMaximize)

    p_ch = [
        pulp.LpVariable(f"p_ch_{t}", lowBound=0, upBound=battery.power_mw)
        for t in range(horizon)
    ]
    p_dis = [
        pulp.LpVariable(f"p_dis_{t}", lowBound=0, upBound=battery.power_mw)
        for t in range(horizon)
    ]
    soc = [
        pulp.LpVariable(
            f"soc_{t}",
            lowBound=battery.soc_min_mwh,
            upBound=battery.soc_max_mwh,
        )
        for t in range(horizon)
    ]
    if enforce_disjunction:
        z = [pulp.LpVariable(f"z_{t}", cat=pulp.LpBinary) for t in range(horizon)]
        for t in range(horizon):
            prob += p_ch[t] <= battery.power_mw * z[t]
            prob += p_dis[t] <= battery.power_mw * (1 - z[t])
    else:
        z = []

    decay = 1.0 - battery.self_discharge_per_hour * duration_hours

    prob += soc[0] == (
        decay * battery.initial_soc_mwh
        + battery.charge_efficiency * p_ch[0] * duration_hours
        - p_dis[0] * duration_hours / battery.discharge_efficiency
    )
    for t in range(1, horizon):
        prob += soc[t] == (
            decay * soc[t - 1]
            + battery.charge_efficiency * p_ch[t] * duration_hours
            - p_dis[t] * duration_hours / battery.discharge_efficiency
        )

    if battery.terminal_soc_mwh is not None:
        prob += soc[horizon - 1] >= battery.terminal_soc_mwh

    days = horizon * duration_hours / 24.0
    max_throughput = 2.0 * battery.max_cycles_per_day * days * battery.usable_energy_mwh
    prob += (
        pulp.lpSum((p_ch[t] + p_dis[t]) * duration_hours for t in range(horizon))
        <= max_throughput
    )

    return BatteryMILP(prob=prob, p_ch=p_ch, p_dis=p_dis, soc=soc, z=z, duration_hours=duration_hours)


def _period_costs(cost: float | Sequence[float], horizon: int) -> list[float]:
    if isinstance(cost, (int, float)):
        return [float(cost)] * horizon
    costs = [float(c) for c in cost]
    if len(costs) != horizon:
        raise ValueError("degradation cost vector length must match horizon")
    return costs


def scenario_profit_expression(
    model: BatteryMILP,
    prices: Sequence[float],
    degradation_cost_eur_per_mwh: float | Sequence[float],
) -> pulp.LpAffineExpression:
    horizon = len(model.p_ch)
    if len(prices) != horizon:
        raise ValueError("prices length must match horizon")
    degradation_costs = _period_costs(degradation_cost_eur_per_mwh, horizon)
    revenue = pulp.lpSum(
        prices[t] * (model.p_dis[t] - model.p_ch[t]) * model.duration_hours
        for t in range(horizon)
    )
    deg = pulp.lpSum(
        degradation_costs[t]
        * (model.p_ch[t] + model.p_dis[t])
        * model.duration_hours
        for t in range(horizon)
    )
    return revenue - deg


def get_solver(time_limit_s: Optional[int] = None, msg: bool = False) -> pulp.LpSolver:
    try:
        solver = pulp.HiGHS_CMD(msg=msg, timeLimit=time_limit_s)
        if solver.available():
            return solver
    except Exception:
        pass
    return pulp.PULP_CBC_CMD(msg=msg, timeLimit=time_limit_s)


def extract_values(vars_: Sequence[pulp.LpVariable]) -> list[float]:
    return [float(v.value() or 0.0) for v in vars_]
