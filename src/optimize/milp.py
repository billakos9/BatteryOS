from __future__ import annotations

from typing import Optional, Sequence

import pulp

from .battery import BatteryProfile
from .schedule import Schedule, build_schedule_frame
from ._milp_core import (
    build_battery_model,
    extract_values,
    get_solver,
    scenario_profit_expression,
)


def optimize_deterministic(
    timestamps: Sequence,
    forecast_prices: Sequence[float],
    battery: BatteryProfile,
    duration_hours: float = 0.25,
    time_limit_s: Optional[int] = 60,
    enforce_disjunction: bool = False,
) -> Schedule:
    """Deterministic optimizer: maximize profit on a single price curve.

    Defaults to the LP relaxation (`enforce_disjunction=False`), which
    matches the stochastic and CVaR optimizers. With round-trip
    efficiency < 1 the LP optimum coincides with the MILP optimum
    because simultaneous charge+discharge is dominated. The
    `build_battery_model` guard enforces this assumption.
    """
    horizon = len(forecast_prices)
    if horizon == 0:
        raise ValueError("forecast_prices is empty")
    if horizon != len(timestamps):
        raise ValueError("timestamps and forecast_prices must have the same length")

    model = build_battery_model(
        battery,
        horizon,
        duration_hours,
        name="battery_det",
        enforce_disjunction=enforce_disjunction,
    )
    model.prob += scenario_profit_expression(
        model, forecast_prices, battery.degradation_cost_eur_per_mwh
    )

    solver = get_solver(time_limit_s=time_limit_s)
    status = model.prob.solve(solver)

    df = build_schedule_frame(
        timestamps,
        forecast_prices,
        extract_values(model.p_ch),
        extract_values(model.p_dis),
        extract_values(model.soc),
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
            "enforce_disjunction": enforce_disjunction,
            "horizon": horizon,
        },
    )
