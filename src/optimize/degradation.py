"""Cycle-depth-aware degradation models.

Two complementary tools:

  rainflow_count + score_schedule_rainflow
      Post-hoc analysis of an already-optimized schedule. Decomposes the SoC
      trajectory into half-cycles via the standard ASTM E1049 rainflow rule
      and prices each cycle by its depth using a Wohler-style aging curve.
      Use this to compare the "constant euro/MWh" cost we put in the MILP
      against a realistic aging cost.

  soc_banded_throughput_costs
      Per-period euro/MWh cost vector that the in-MILP objective can consume.
      Charges a higher penalty for charge/discharge in extreme SoC bands
      (e.g. 0-15 percent and 85-100 percent), where calendar+cycle aging
      compounds. Stays linear so it slots into the existing LP/MILP build.

The constant euro/MWh model in BatteryProfile.degradation_cost_eur_per_mwh
is a stand-in. These are the upgrades.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from .battery import BatteryProfile


@dataclass
class RainflowCycle:
    depth_frac: float
    mean_soc_frac: float
    is_full_cycle: bool


def rainflow_count(soc_trajectory: Sequence[float], energy_max_mwh: float) -> list[RainflowCycle]:
    """ASTM E1049 four-point rainflow counting on a SoC trajectory.

    Returns a list of cycles where depth_frac is normalized to [0, 1] of the
    battery's full energy. Both half- and full-cycles are returned; downstream
    aging cost weights them equally because two half-cycles equal one full.
    """
    soc = np.asarray(soc_trajectory, dtype=float) / energy_max_mwh
    extrema = _extract_extrema(soc)
    cycles: list[RainflowCycle] = []
    stack: list[float] = []

    for x in extrema:
        stack.append(x)
        while len(stack) >= 4:
            a, b, c, d = stack[-4], stack[-3], stack[-2], stack[-1]
            range1 = abs(b - c)
            range2 = abs(a - b)
            range3 = abs(c - d)
            if range1 <= range2 and range1 <= range3:
                cycles.append(
                    RainflowCycle(
                        depth_frac=range1,
                        mean_soc_frac=(b + c) / 2.0,
                        is_full_cycle=True,
                    )
                )
                stack.pop(-2)
                stack.pop(-2)
            else:
                break

    while len(stack) >= 2:
        a, b = stack[0], stack[1]
        cycles.append(
            RainflowCycle(
                depth_frac=abs(a - b),
                mean_soc_frac=(a + b) / 2.0,
                is_full_cycle=False,
            )
        )
        stack.pop(0)
    return cycles


def _extract_extrema(series: np.ndarray) -> list[float]:
    if len(series) == 0:
        return []
    extrema = [float(series[0])]
    for i in range(1, len(series) - 1):
        prev, cur, nxt = series[i - 1], series[i], series[i + 1]
        if (cur - prev) * (nxt - cur) < 0:
            extrema.append(float(cur))
    extrema.append(float(series[-1]))
    return extrema


def cycle_aging_cost_eur(
    cycle: RainflowCycle,
    energy_max_mwh: float,
    replacement_cost_eur_per_mwh_capacity: float = 150_000.0,
    wohler_exponent: float = 2.0,
    cycles_to_eol_at_full_dod: float = 5_000.0,
    soc_stress_factor: float = 1.5,
) -> float:
    """Wohler-curve-style aging cost for one rainflow cycle.

    The capacity throughput required to fully replace the battery is
    `2 * cycles_to_eol_at_full_dod` MWh per MWh of nameplate capacity.
    A cycle of depth d shortens life by `d^wohler_exponent` of one full cycle.
    Mid-SoC operation (around 50 percent) costs the baseline; extreme SoC
    (very full or very empty) is penalized by `soc_stress_factor`.
    """
    nameplate_value_eur = replacement_cost_eur_per_mwh_capacity * energy_max_mwh
    cost_per_full_equivalent_cycle = nameplate_value_eur / max(cycles_to_eol_at_full_dod, 1.0)
    depth_term = cycle.depth_frac ** wohler_exponent
    if not cycle.is_full_cycle:
        depth_term *= 0.5
    soc_distance_from_mid = abs(cycle.mean_soc_frac - 0.5) / 0.5
    soc_term = 1.0 + (soc_stress_factor - 1.0) * soc_distance_from_mid
    return cost_per_full_equivalent_cycle * depth_term * soc_term


@dataclass
class RainflowScore:
    cycles: list[RainflowCycle]
    aging_cost_eur: float
    equivalent_full_cycles: float
    market_profit_eur: float
    net_profit_eur: float
    average_cycle_depth: float
    deep_cycle_count: int


def score_schedule_rainflow(
    schedule_df: pd.DataFrame,
    battery: BatteryProfile,
    realized_prices: Sequence[float] | None = None,
    duration_hours: float = 0.25,
    deep_cycle_threshold: float = 0.50,
    **aging_kwargs,
) -> RainflowScore:
    """Replace the constant euro/MWh assumption with rainflow-based aging.

    If realized_prices is None, the schedule's forecast_price column is used.
    """
    soc = schedule_df["state_of_charge_mwh"].to_numpy()
    cycles = rainflow_count(soc, battery.energy_mwh)
    aging_cost = sum(
        cycle_aging_cost_eur(c, battery.energy_mwh, **aging_kwargs) for c in cycles
    )

    prices = (
        np.asarray(realized_prices, dtype=float)
        if realized_prices is not None
        else schedule_df["forecast_price_eur_per_mwh"].to_numpy()
    )
    charge = schedule_df["charge_mw"].to_numpy()
    discharge = schedule_df["discharge_mw"].to_numpy()
    market_profit = float(np.sum(prices * (discharge - charge)) * duration_hours)

    eq_full_cycles = sum(
        c.depth_frac * (1.0 if c.is_full_cycle else 0.5) for c in cycles
    )
    avg_depth = float(np.mean([c.depth_frac for c in cycles])) if cycles else 0.0
    deep = sum(1 for c in cycles if c.depth_frac >= deep_cycle_threshold)

    return RainflowScore(
        cycles=cycles,
        aging_cost_eur=aging_cost,
        equivalent_full_cycles=eq_full_cycles,
        market_profit_eur=market_profit,
        net_profit_eur=market_profit - aging_cost,
        average_cycle_depth=avg_depth,
        deep_cycle_count=deep,
    )


def soc_banded_throughput_costs(
    base_cost_eur_per_mwh: float,
    bands: Sequence[tuple[float, float, float]] = (
        (0.00, 0.15, 2.0),
        (0.85, 1.00, 2.0),
    ),
    horizon: int = 96,
    soc_frac_estimate: Sequence[float] | None = None,
) -> np.ndarray:
    """Per-period euro/MWh penalty vector for use inside the MILP objective.

    Returns an array of length `horizon`. For periods whose expected SoC
    falls inside a stress band [low, high], the cost is multiplied by the
    band's `factor`; otherwise the base cost applies. Pass the previous
    iteration's SoC trajectory as `soc_frac_estimate` to drive convergence.

    This is a fixed-point linearization: solve once with base cost, plug the
    realized SoC back in here, re-solve. Two iterations is usually enough.
    """
    costs = np.full(horizon, base_cost_eur_per_mwh, dtype=float)
    if soc_frac_estimate is None:
        return costs
    est = np.asarray(soc_frac_estimate, dtype=float)
    for low, high, factor in bands:
        in_band = (est >= low) & (est <= high)
        costs[in_band] = base_cost_eur_per_mwh * factor
    return costs