from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import pulp

from .battery import BatteryProfile
from .economics import evaluate_schedule
from .schedule import Schedule, build_schedule_frame
from .scenarios import PriceScenarios
from ._milp_core import (
    build_battery_model,
    extract_values,
    get_solver,
    scenario_profit_expression,
)


def optimize_cvar(
    scenarios: PriceScenarios,
    battery: BatteryProfile,
    duration_hours: float = 0.25,
    alpha: float = 0.10,
    risk_aversion: float = 1.0,
    time_limit_s: Optional[int] = 180,
    enforce_disjunction: bool = False,
    degradation_costs_eur_per_mwh: Optional[Iterable[float]] = None,
) -> Schedule:
    """Mean-CVaR objective via Rockafellar-Uryasev LP reformulation.

    Maximizes:  (1 - lambda) * E[profit] + lambda * CVaR_alpha[profit]
    where CVaR_alpha is the conditional expectation of profit in the worst
    alpha fraction of scenarios. alpha=0.10 means "average over the worst 10%
    of outcomes". This is the formulation used by Habitat Energy, Statkraft,
    and most production trading optimizers.

    LP epigraph form for CVaR (maximization, lower-tail risk):
        CVaR_alpha = max_{eta, u_s >= 0}  eta - (1/alpha) * sum_s w_s * u_s
        s.t.  u_s >= eta - profit_s
    """
    if not 0 < alpha <= 1:
        raise ValueError("alpha must lie in (0, 1]")
    if not 0 <= risk_aversion <= 1:
        raise ValueError("risk_aversion (lambda) must lie in [0, 1]")

    horizon = scenarios.horizon
    degradation_cost = (
        battery.degradation_cost_eur_per_mwh
        if degradation_costs_eur_per_mwh is None
        else np.asarray(list(degradation_costs_eur_per_mwh), dtype=float)
    )
    if not np.isscalar(degradation_cost) and len(degradation_cost) != horizon:
        raise ValueError("degradation_costs_eur_per_mwh length must match scenario horizon")
    model = build_battery_model(
        battery,
        horizon,
        duration_hours,
        name="battery_cvar",
        enforce_disjunction=enforce_disjunction,
    )
    S = scenarios.n_scenarios

    profits = [
        scenario_profit_expression(model, scenarios.prices[s], degradation_cost)
        for s in range(S)
    ]
    expected_profit = pulp.lpSum(scenarios.weights[s] * profits[s] for s in range(S))

    eta = pulp.LpVariable("var_eta")
    u = [pulp.LpVariable(f"u_{s}", lowBound=0) for s in range(S)]
    for s in range(S):
        model.prob += u[s] >= eta - profits[s]

    cvar = eta - (1.0 / alpha) * pulp.lpSum(scenarios.weights[s] * u[s] for s in range(S))
    model.prob += (1.0 - risk_aversion) * expected_profit + risk_aversion * cvar

    solver = get_solver(time_limit_s=time_limit_s)
    status = model.prob.solve(solver)

    charge = extract_values(model.p_ch)
    discharge = extract_values(model.p_dis)
    soc = extract_values(model.soc)

    scenario_profits = []
    for s in range(S):
        prices_s = scenarios.prices[s]
        market = float(
            np.sum(prices_s * (np.array(discharge) - np.array(charge))) * duration_hours
        )
        if np.isscalar(degradation_cost):
            degradation_cost_array = np.full(horizon, float(degradation_cost))
        else:
            degradation_cost_array = np.asarray(degradation_cost, dtype=float)
        deg = float(
            np.sum(
                degradation_cost_array
                * (np.array(charge) + np.array(discharge))
            )
            * duration_hours
        )
        scenario_profits.append(market - deg)
    scenario_profits = np.array(scenario_profits)

    sort_idx = np.argsort(scenario_profits)
    sorted_profits = scenario_profits[sort_idx]
    sorted_weights = scenarios.weights[sort_idx]
    tail_value = 0.0
    mass_remaining = float(alpha)
    for p_s, w_s in zip(sorted_profits, sorted_weights):
        take = min(float(w_s), mass_remaining)
        tail_value += float(p_s) * take
        mass_remaining -= take
        if mass_remaining <= 1e-12:
            break
    cvar_realized = float(tail_value / alpha) if alpha > 0 else float("nan")

    df = build_schedule_frame(
        scenarios.timestamps,
        scenarios.expected_prices(),
        charge,
        discharge,
        soc,
        duration_hours,
        degradation_cost,
    )

    return Schedule(
        df=df,
        duration_hours=duration_hours,
        objective_value=float(pulp.value(model.prob.objective) or 0.0),
        solver_status=pulp.LpStatus[status],
        metadata={
            "solver": solver.name,
            "objective": "mean_cvar",
            "alpha": alpha,
            "risk_aversion": risk_aversion,
            "n_scenarios": S,
            "expected_profit_eur": float(scenarios.weights @ scenario_profits),
            "cvar_eur": cvar_realized,
            "worst_profit_eur": float(scenario_profits.min()),
            "best_profit_eur": float(scenario_profits.max()),
            "scenario_profits_eur": scenario_profits.tolist(),
            "degradation_model": (
                "constant"
                if degradation_costs_eur_per_mwh is None
                else "soc_banded_fixed_point"
            ),
        },
    )


@dataclass
class ParameterSweepResult:
    table: pd.DataFrame
    nominal_profit: float
    worst_case_profit: float
    p10_profit: float
    median_profit: float

    def summary(self) -> dict:
        return {
            "nominal_profit_eur": self.nominal_profit,
            "worst_case_profit_eur": self.worst_case_profit,
            "p10_profit_eur": self.p10_profit,
            "median_profit_eur": self.median_profit,
            "n_perturbations": len(self.table),
        }


def sweep_battery_parameters(
    schedule: Schedule,
    realized_prices: Iterable[float],
    nominal_battery: BatteryProfile,
    perturbations: Optional[dict[str, list[float]]] = None,
) -> ParameterSweepResult:
    """Replay one schedule against perturbed battery parameters.

    The schedule is fixed (already optimized under nominal assumptions).
    For each perturbation, evaluate realized profit using the perturbed
    battery's degradation/efficiency. This is the standard robustness check
    when battery telemetry is unavailable: how badly does our PnL degrade
    if the asset doesn't match the spec sheet?
    """
    if perturbations is None:
        perturbations = {
            "round_trip_efficiency": [0.85, 0.90, 0.95, 1.0],
            "degradation_cost_eur_per_mwh": [1.0, 2.0, 3.0, 5.0],
        }

    realized = np.asarray(list(realized_prices), dtype=float)
    rows: list[dict] = []

    eta_options = perturbations.get("round_trip_efficiency", [nominal_battery.round_trip_efficiency])
    deg_options = perturbations.get(
        "degradation_cost_eur_per_mwh", [nominal_battery.degradation_cost_eur_per_mwh]
    )

    for eta_rt in eta_options:
        eta_one_way = float(np.sqrt(max(eta_rt, 1e-6)))
        for deg in deg_options:
            perturbed = replace(
                nominal_battery,
                charge_efficiency=min(1.0, eta_one_way),
                discharge_efficiency=min(1.0, eta_one_way),
                degradation_cost_eur_per_mwh=float(deg),
            )
            metrics = evaluate_schedule(
                schedule.df, realized, perturbed, schedule.duration_hours
            )
            rows.append(
                {
                    "round_trip_efficiency": eta_rt,
                    "degradation_cost_eur_per_mwh": deg,
                    **metrics,
                }
            )

    table = pd.DataFrame(rows)
    nominal_metrics = evaluate_schedule(
        schedule.df, realized, nominal_battery, schedule.duration_hours
    )
    profits = table["realized_profit_eur"].to_numpy()
    return ParameterSweepResult(
        table=table,
        nominal_profit=float(nominal_metrics["realized_profit_eur"]),
        worst_case_profit=float(profits.min()),
        p10_profit=float(np.percentile(profits, 10)),
        median_profit=float(np.percentile(profits, 50)),
    )
