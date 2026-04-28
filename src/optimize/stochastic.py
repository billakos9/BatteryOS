from __future__ import annotations

from typing import Optional

import numpy as np
import pulp

from .battery import BatteryProfile
from .schedule import Schedule, build_schedule_frame
from .scenarios import PriceScenarios
from ._milp_core import (
    build_battery_model,
    extract_values,
    get_solver,
    scenario_profit_expression,
)


def optimize_stochastic(
    scenarios: PriceScenarios,
    battery: BatteryProfile,
    duration_hours: float = 0.25,
    objective: str = "expected",
    risk_aversion: float = 0.0,
    time_limit_s: Optional[int] = 120,
    enforce_disjunction: bool = False,
) -> Schedule:
    """Two-stage stochastic MILP.

    The schedule (charge/discharge/SoC trajectory) is one common decision
    that must be feasible across all scenarios. Each scenario contributes
    its own profit expression; the objective combines them.

    Objective options:
        expected: maximize sum_s w_s * profit_s
        mean_variance: maximize expected_profit - lambda * variance
        worst_case: maximize min_s profit_s (max-min via auxiliary var)
    """
    horizon = scenarios.horizon
    model = build_battery_model(
        battery,
        horizon,
        duration_hours,
        name="battery_stoch",
        enforce_disjunction=enforce_disjunction,
    )

    profits = [
        scenario_profit_expression(model, scenarios.prices[s], battery.degradation_cost_eur_per_mwh)
        for s in range(scenarios.n_scenarios)
    ]
    expected_profit = pulp.lpSum(scenarios.weights[s] * profits[s] for s in range(scenarios.n_scenarios))

    if objective == "expected":
        model.prob += expected_profit
    elif objective == "worst_case":
        worst = pulp.LpVariable("worst_case_profit")
        for s in range(scenarios.n_scenarios):
            model.prob += worst <= profits[s]
        model.prob += worst
    elif objective == "mean_variance":
        # LP-friendly mean absolute deviation surrogate (true variance is QP).
        if risk_aversion < 0:
            raise ValueError("risk_aversion must be >= 0")
        dev_pos = [
            pulp.LpVariable(f"dev_pos_{s}", lowBound=0) for s in range(scenarios.n_scenarios)
        ]
        dev_neg = [
            pulp.LpVariable(f"dev_neg_{s}", lowBound=0) for s in range(scenarios.n_scenarios)
        ]
        for s in range(scenarios.n_scenarios):
            model.prob += profits[s] - expected_profit == dev_pos[s] - dev_neg[s]
        mad = pulp.lpSum(
            scenarios.weights[s] * (dev_pos[s] + dev_neg[s])
            for s in range(scenarios.n_scenarios)
        )
        model.prob += expected_profit - risk_aversion * mad
    else:
        raise ValueError(
            "objective must be one of: 'expected', 'worst_case', 'mean_variance'"
        )

    solver = get_solver(time_limit_s=time_limit_s)
    status = model.prob.solve(solver)

    charge = extract_values(model.p_ch)
    discharge = extract_values(model.p_dis)
    soc = extract_values(model.soc)

    realized_per_scenario = []
    for s in range(scenarios.n_scenarios):
        prices_s = scenarios.prices[s]
        market = float(
            np.sum(prices_s * (np.array(discharge) - np.array(charge))) * duration_hours
        )
        deg = float(
            battery.degradation_cost_eur_per_mwh
            * np.sum(np.array(charge) + np.array(discharge))
            * duration_hours
        )
        realized_per_scenario.append(market - deg)

    df = build_schedule_frame(
        scenarios.timestamps,
        scenarios.expected_prices(),
        charge,
        discharge,
        soc,
        duration_hours,
        battery.degradation_cost_eur_per_mwh,
    )

    return Schedule(
        df=df,
        duration_hours=duration_hours,
        objective_value=float(pulp.value(model.prob.objective) or 0.0),
        solver_status=pulp.LpStatus[status],
        metadata={
            "solver": solver.name,
            "objective": objective,
            "risk_aversion": risk_aversion,
            "n_scenarios": scenarios.n_scenarios,
            "scenario_labels": list(scenarios.labels),
            "scenario_weights": scenarios.weights.tolist(),
            "scenario_profits_eur": realized_per_scenario,
            "expected_profit_eur": float(scenarios.weights @ np.array(realized_per_scenario)),
            "worst_profit_eur": float(min(realized_per_scenario)),
            "best_profit_eur": float(max(realized_per_scenario)),
        },
    )
