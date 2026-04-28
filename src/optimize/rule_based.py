from __future__ import annotations

from typing import Sequence

import numpy as np

from .battery import BatteryProfile
from .schedule import Schedule, build_schedule_frame


def optimize_rule_based(
    timestamps: Sequence,
    forecast_prices: Sequence[float],
    battery: BatteryProfile,
    duration_hours: float = 0.25,
) -> Schedule:
    """Threshold-based heuristic.

    Picks a charge price threshold and a discharge price threshold from the
    price quantiles such that the implied number of trades fits the daily
    cycle budget. Simulates forward, charging when price <= charge_threshold
    and discharging when price >= discharge_threshold, with each period's
    actual MW determined by remaining SoC headroom and remaining cycle
    budget. Never plans more than one action per timestamp and never
    over-counts throughput.
    """
    prices = np.asarray(forecast_prices, dtype=float)
    n = len(prices)
    if n == 0:
        raise ValueError("forecast_prices is empty")
    if n != len(timestamps):
        raise ValueError("timestamps and forecast_prices must have the same length")
    if duration_hours <= 0:
        raise ValueError(f"duration_hours must be > 0, got {duration_hours}")

    days = n * duration_hours / 24.0
    target_throughput = 2.0 * battery.max_cycles_per_day * days * battery.usable_energy_mwh
    energy_per_full_step = battery.power_mw * duration_hours
    breakeven = (
        battery.degradation_cost_eur_per_mwh * 2.0
        / max(battery.round_trip_efficiency, 1e-6)
    )

    p_ch = np.zeros(n)
    p_dis = np.zeros(n)
    soc = np.zeros(n)
    metadata: dict = {"breakeven_eur_per_mwh": breakeven}

    if target_throughput <= 1e-9 or energy_per_full_step <= 1e-9:
        soc_state = battery.initial_soc_mwh
        for t in range(n):
            soc_state = (
                1.0 - battery.self_discharge_per_hour * duration_hours
            ) * soc_state
            soc[t] = soc_state
        df = build_schedule_frame(
            timestamps,
            prices,
            p_ch,
            p_dis,
            soc,
            duration_hours,
            battery.degradation_cost_eur_per_mwh,
        )
        return Schedule(
            df=df,
            duration_hours=duration_hours,
            objective_value=float(df["period_profit_eur"].sum()),
            solver_status="heuristic",
            metadata={**metadata, "reason": "no cycle budget"},
        )

    n_action_slots = int(target_throughput / energy_per_full_step)
    n_each_side = max(1, n_action_slots // 2)
    n_each_side = min(n_each_side, n // 2)

    sorted_asc = np.sort(prices)
    sorted_desc = np.sort(prices)[::-1]
    charge_threshold = sorted_asc[min(n_each_side - 1, n - 1)]
    discharge_threshold = sorted_desc[min(n_each_side - 1, n - 1)]

    if discharge_threshold - charge_threshold <= breakeven:
        soc_state = battery.initial_soc_mwh
        for t in range(n):
            soc_state = (
                1.0 - battery.self_discharge_per_hour * duration_hours
            ) * soc_state
            soc[t] = soc_state
        df = build_schedule_frame(
            timestamps,
            prices,
            p_ch,
            p_dis,
            soc,
            duration_hours,
            battery.degradation_cost_eur_per_mwh,
        )
        return Schedule(
            df=df,
            duration_hours=duration_hours,
            objective_value=float(df["period_profit_eur"].sum()),
            solver_status="heuristic",
            metadata={
                **metadata,
                "reason": "spread below breakeven",
                "charge_threshold_eur_per_mwh": float(charge_threshold),
                "discharge_threshold_eur_per_mwh": float(discharge_threshold),
            },
        )

    decay_per_step = 1.0 - battery.self_discharge_per_hour * duration_hours

    soc_state = battery.initial_soc_mwh
    used_throughput = 0.0
    for t in range(n):
        soc_state = decay_per_step * soc_state
        remaining = n - t
        # Leave headroom so future decay-only periods cannot push soc below soc_min.
        soc_floor = battery.soc_min_mwh / max(decay_per_step ** remaining, 1e-9)
        soc_ceiling = battery.soc_max_mwh
        budget_remaining = target_throughput - used_throughput
        if budget_remaining > 1e-9:
            if prices[t] <= charge_threshold and soc_state < soc_ceiling - 1e-9:
                room = soc_ceiling - soc_state
                inflow_capacity = room / max(
                    battery.charge_efficiency * duration_hours, 1e-9
                )
                power = min(
                    battery.power_mw,
                    inflow_capacity,
                    budget_remaining / duration_hours,
                )
                if power > 1e-6:
                    p_ch[t] = power
                    soc_state += battery.charge_efficiency * power * duration_hours
                    used_throughput += power * duration_hours
            elif prices[t] >= discharge_threshold and soc_state > soc_floor + 1e-9:
                avail = soc_state - soc_floor
                outflow_capacity = (
                    avail * battery.discharge_efficiency / max(duration_hours, 1e-9)
                )
                power = min(
                    battery.power_mw,
                    outflow_capacity,
                    budget_remaining / duration_hours,
                )
                if power > 1e-6:
                    p_dis[t] = power
                    soc_state -= power * duration_hours / battery.discharge_efficiency
                    used_throughput += power * duration_hours

        soc[t] = soc_state

    df = build_schedule_frame(
        timestamps,
        prices,
        p_ch,
        p_dis,
        soc,
        duration_hours,
        battery.degradation_cost_eur_per_mwh,
    )
    return Schedule(
        df=df,
        duration_hours=duration_hours,
        objective_value=float(df["period_profit_eur"].sum()),
        solver_status="heuristic",
        metadata={
            **metadata,
            "charge_threshold_eur_per_mwh": float(charge_threshold),
            "discharge_threshold_eur_per_mwh": float(discharge_threshold),
            "throughput_used_mwh": float(used_throughput),
            "throughput_budget_mwh": float(target_throughput),
        },
    )
