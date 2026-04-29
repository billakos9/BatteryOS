"""Bid-curve construction.

A bid curve is a step function `q(p)` that says, for each delivery
period, how many MW we are willing to buy/sell at each candidate
clearing price `p`. Self-scheduling submits a single (q, t) commitment;
bid curves submit a schedule of (q, p, t) triples and let the market
clear them.

We construct curves by sweeping candidate clearing prices per period
and re-solving the underlying LP for each — the response of optimal
dispatch to candidate prices traces the curve. This works on top of any
single-curve optimization run, so it composes cleanly with the unified
`optimize_dispatch` pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from .battery import BatteryProfile
from .milp import optimize_deterministic


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
    if horizon == 0:
        raise ValueError("forecast_prices is empty")
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
        },
    )
