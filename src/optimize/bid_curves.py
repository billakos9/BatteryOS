"""Bid-curve construction from forecast prices.

A bid curve is a step function `q(p)` that says, for each delivery period,
how many MW we are willing to buy/sell at each candidate clearing price p.
Self-scheduling submits a single (q, t) commitment; bid curves submit a
schedule of (q, p, t) triples and let the market clear them.

Two construction methods, both consume only forecasts (no live market data):

  build_bid_curves_resolve
      Sweep a grid of price perturbations per period and re-solve the
      deterministic optimizer for each. The resulting q-vs-p relationship
      is the period's bid curve. Slow (K solves per period) but robust
      and works with any optimizer (CVaR, stochastic, MILP).

  build_bid_curves_from_duals
      For the LP relaxation, the shadow prices on the SoC constraint give
      the marginal value of stored energy at each timestamp. The optimal
      bid is "discharge if forecast price > shadow price, charge if
      forecast price + losses < shadow price". One solve, exact for the LP.

For HEnEx-style markets that accept ladder bids (multiple price-quantity
points per period), the resolve method gives a richer ladder; the duals
method gives a single break-even price.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd
import pulp

from .battery import BatteryProfile
from .milp import optimize_deterministic
from ._milp_core import (
    build_battery_model,
    extract_values,
    get_solver,
    scenario_profit_expression,
)


@dataclass
class BidCurves:
    timestamps: list
    price_grid: np.ndarray
    bid_quantities_mw: np.ndarray
    method: str
    metadata: dict

    def to_long_dataframe(self) -> pd.DataFrame:
        rows = []
        for i, ts in enumerate(self.timestamps):
            for j, price in enumerate(self.price_grid):
                rows.append(
                    {
                        "timestamp": ts,
                        "candidate_price_eur_per_mwh": float(price),
                        "bid_quantity_mw": float(self.bid_quantities_mw[i, j]),
                    }
                )
        return pd.DataFrame(rows)

    def ladder_for_period(self, t_index: int, tol_mw: float = 0.1) -> pd.DataFrame:
        q = self.bid_quantities_mw[t_index]
        breaks = [0]
        for j in range(1, len(q)):
            if abs(q[j] - q[j - 1]) > tol_mw:
                breaks.append(j)
        rows = [
            {
                "candidate_price_eur_per_mwh": float(self.price_grid[j]),
                "bid_quantity_mw": float(q[j]),
            }
            for j in breaks
        ]
        return pd.DataFrame(rows)


def build_bid_curves_resolve(
    timestamps: Sequence,
    forecast_prices: Sequence[float],
    battery: BatteryProfile,
    duration_hours: float = 0.25,
    price_grid_eur_per_mwh: Sequence[float] | None = None,
    perturb_around_each_period: bool = True,
    time_limit_s: Optional[int] = 60,
) -> BidCurves:
    """Sweep candidate clearing prices per period; re-solve the optimizer.

    For each period t and each candidate price p in the grid, we set
    period t's price to p and re-optimize. The resulting net dispatch
    (discharge - charge) at period t becomes the bid quantity for that
    candidate price. Repeating across the grid traces the bid curve.
    """
    base = np.asarray(forecast_prices, dtype=float)
    horizon = len(base)
    if horizon != len(timestamps):
        raise ValueError("timestamps and forecast_prices must have the same length")

    if price_grid_eur_per_mwh is None:
        lo, hi = float(base.min()), float(base.max())
        spread = max(hi - lo, 1.0)
        grid = np.linspace(lo - 0.5 * spread, hi + 0.5 * spread, 11)
    else:
        grid = np.asarray(price_grid_eur_per_mwh, dtype=float)

    K = len(grid)
    bids = np.zeros((horizon, K))

    for t in range(horizon):
        for j, candidate in enumerate(grid):
            perturbed = base.copy()
            perturbed[t] = candidate
            sched = optimize_deterministic(
                timestamps,
                perturbed,
                battery,
                duration_hours=duration_hours,
                time_limit_s=time_limit_s,
            )
            net_mw = float(sched.df["discharge_mw"].iloc[t] - sched.df["charge_mw"].iloc[t])
            bids[t, j] = net_mw

    return BidCurves(
        timestamps=list(timestamps),
        price_grid=grid,
        bid_quantities_mw=bids,
        method="resolve",
        metadata={
            "horizon": horizon,
            "n_price_points": K,
            "n_solves": horizon * K,
            "perturb_around_each_period": perturb_around_each_period,
        },
    )


def build_bid_curves_from_duals(
    timestamps: Sequence,
    forecast_prices: Sequence[float],
    battery: BatteryProfile,
    duration_hours: float = 0.25,
    time_limit_s: Optional[int] = 60,
) -> BidCurves:
    """Extract bid prices from the LP relaxation's shadow prices.

    The shadow price of the SoC balance constraint at time t is the
    marginal value of stored energy at that period. Combined with one-way
    efficiencies and degradation cost, it gives the period's break-even
    discharge price (above which we sell) and break-even charge price
    (below which we buy):

        sell_threshold[t] = shadow[t] / discharge_efficiency + deg_cost
        buy_threshold[t]  = shadow[t] * charge_efficiency    - deg_cost

    These are the Lagrangian-optimal bid prices for the LP relaxation.
    Returns a two-point ladder per period.
    """
    horizon = len(forecast_prices)
    model = build_battery_model(
        battery,
        horizon,
        duration_hours,
        name="battery_dual",
        enforce_disjunction=False,
    )
    model.prob += scenario_profit_expression(
        model, forecast_prices, battery.degradation_cost_eur_per_mwh
    )
    solver = get_solver(time_limit_s=time_limit_s)
    status = model.prob.solve(solver)
    if pulp.LpStatus[status] not in {"Optimal"}:
        raise RuntimeError(f"LP did not solve to optimality: {pulp.LpStatus[status]}")

    shadow_prices = np.zeros(horizon)
    for t, soc_var in enumerate(model.soc):
        constraints_with_var = [
            c for c in model.prob.constraints.values() if soc_var in c
        ]
        if constraints_with_var:
            shadow_prices[t] = float(constraints_with_var[0].pi or 0.0)

    deg = battery.degradation_cost_eur_per_mwh
    sell_threshold = shadow_prices / max(battery.discharge_efficiency, 1e-6) + deg
    buy_threshold = shadow_prices * battery.charge_efficiency - deg

    grid_per_period = np.column_stack([buy_threshold, sell_threshold])
    bid_quantities = np.zeros_like(grid_per_period)
    bid_quantities[:, 0] = -battery.power_mw
    bid_quantities[:, 1] = battery.power_mw

    common_grid = np.linspace(
        float(min(buy_threshold.min(), float(np.min(forecast_prices)))) - 5.0,
        float(max(sell_threshold.max(), float(np.max(forecast_prices)))) + 5.0,
        21,
    )
    bids = np.zeros((horizon, len(common_grid)))
    for t in range(horizon):
        for j, p in enumerate(common_grid):
            if p <= buy_threshold[t]:
                bids[t, j] = -battery.power_mw
            elif p >= sell_threshold[t]:
                bids[t, j] = battery.power_mw
            else:
                bids[t, j] = 0.0

    return BidCurves(
        timestamps=list(timestamps),
        price_grid=common_grid,
        bid_quantities_mw=bids,
        method="duals",
        metadata={
            "horizon": horizon,
            "shadow_prices_eur_per_mwh": shadow_prices.tolist(),
            "buy_thresholds_eur_per_mwh": buy_threshold.tolist(),
            "sell_thresholds_eur_per_mwh": sell_threshold.tolist(),
            "solver_status": pulp.LpStatus[status],
        },
    )
