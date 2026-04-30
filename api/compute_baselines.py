#!/usr/bin/env python3
"""
Compute Perfect-Foresight and Naive baselines for the honest backtest period.

Perfect: deterministic optimizer fed actual realized prices (clairvoyant upper bound).
Naive:   greedy heuristic using p50 forecasts, with full tracker support
         (SoC carry-over, cycle budgets, SOH decay, dynamic degradation cost).

This gives a fair apples-to-apples comparison: both BatteryOS and the naive
baseline see the same noisy forecast and suffer the same tracker penalties.
The only difference is the scheduling strategy (MILP vs greedy).

Usage:
    cd /home/dimit/BatteryOS
    source .venv/bin/activate
    python api/compute_baselines.py

Output:
    outputs/backtest_baseline_perfect.csv
    outputs/backtest_baseline_naive.csv
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.optimize import load_profile
from src.optimize.battery import BatteryProfile
from src.optimize.economics import evaluate_schedule
from src.optimize.milp import optimize_deterministic
from src.optimize.schedule import build_schedule_frame
from src.optimize.tracker import BatteryStateTracker

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("Loading walk-forward predictions ...")
df_pred = pd.read_csv(
    ROOT / "data" / "processed" / "walkforward_predictions.csv", index_col=0
)
df_pred.index = pd.to_datetime(df_pred.index, utc=True).tz_convert("Europe/Athens")

BATTERY_PROFILES = [
    "liion_100_2h",
    "liion_200_2h",
    "liion_300_2h",
    "phs_100_8h",
    "phs_200_8h",
    "flow_100_6h",
]

DURATION_HOURS = 0.25
profile_path = ROOT / "config" / "storage_profiles.yaml"

# ---------------------------------------------------------------------------
# Helper: greedy heuristic with tracker-aware constraints
# ---------------------------------------------------------------------------
def greedy_schedule(
    forecast: np.ndarray,
    battery: BatteryProfile,
    duration_hours: float,
) -> tuple[list[float], list[float], list[float]]:
    """
    Greedy charge/discharge schedule.

    Sorts intervals by forecast price, charges cheapest first,
    discharges most expensive first, respecting SoC and power limits.
    Also enforces max_cycles_per_day by scaling down if needed.
    """
    n = len(forecast)
    charge_mw = [0.0] * n
    discharge_mw = [0.0] * n
    soc = battery.initial_soc_mwh
    power = battery.power_mw
    dt = duration_hours
    eta_c = battery.charge_efficiency
    eta_d = battery.discharge_efficiency

    # Charge phase: cheapest intervals
    sorted_idx = sorted(range(n), key=lambda i: forecast[i])
    for idx in sorted_idx:
        if soc >= battery.soc_max_mwh:
            break
        max_charge = min(power, (battery.soc_max_mwh - soc) / (eta_c * dt))
        charge_mw[idx] = max_charge
        soc += max_charge * eta_c * dt

    # Discharge phase: most expensive intervals
    sorted_idx_desc = sorted(range(n), key=lambda i: forecast[i], reverse=True)
    for idx in sorted_idx_desc:
        if soc <= battery.soc_min_mwh:
            break
        max_discharge = min(power, (soc - battery.soc_min_mwh) / dt * eta_d)
        discharge_mw[idx] = max_discharge
        soc -= max_discharge / eta_d * dt

    # Enforce max_cycles_per_day by scaling if needed
    throughput = sum(charge_mw) + sum(discharge_mw)
    cycles = throughput / (2.0 * battery.usable_energy_mwh) if battery.usable_energy_mwh > 0 else 0.0
    max_cycles = battery.max_cycles_per_day * (n * dt / 24.0)
    if cycles > max_cycles and cycles > 0:
        scale = max_cycles / cycles
        charge_mw = [c * scale for c in charge_mw]
        discharge_mw = [d * scale for d in discharge_mw]

    # Recompute SOC trajectory for the schedule DataFrame
    soc_traj = [battery.initial_soc_mwh]
    current_soc = battery.initial_soc_mwh
    for i in range(n):
        current_soc = (
            current_soc
            + charge_mw[i] * eta_c * dt
            - discharge_mw[i] / eta_d * dt
        )
        current_soc = max(battery.soc_min_mwh, min(battery.soc_max_mwh, current_soc))
        soc_traj.append(current_soc)

    return charge_mw, discharge_mw, soc_traj[:-1]  # exclude the trailing SOC


# ---------------------------------------------------------------------------
# 2. Perfect foresight baseline
# ---------------------------------------------------------------------------
print("\n[1/2] Computing PERFECT foresight baseline ...")
print("-" * 70)

perfect_rows = []

for profile_name in BATTERY_PROFILES:
    battery = load_profile(profile_path, profile_name)
    print(f"  -> {profile_name} ...")

    df_pred["date"] = df_pred.index.date
    unique_dates = sorted(df_pred["date"].unique())

    for date in tqdm(unique_dates, desc=f"{profile_name}", unit="day"):
        day_df = df_pred[df_pred["date"] == date]
        if len(day_df) != 96:
            continue

        timestamps = day_df.index.tolist()
        actual = day_df["Actual"].values

        try:
            sched = optimize_deterministic(
                timestamps=timestamps,
                forecast_prices=actual,  # clairvoyant!
                battery=battery,
                duration_hours=DURATION_HOURS,
                time_limit_s=5,
                enforce_disjunction=False,
            )
            metrics = evaluate_schedule(sched.df, actual, battery, DURATION_HOURS)
            perfect_rows.append({
                "date": str(date),
                "profile": profile_name,
                "realized_profit_eur": metrics["realized_profit_eur"],
                "cycles_used": metrics["cycles_used"],
                "throughput_mwh": metrics["throughput_mwh"],
            })
        except Exception as exc:
            print(f"    FAIL {date}: {exc}")
            perfect_rows.append({
                "date": str(date),
                "profile": profile_name,
                "realized_profit_eur": 0.0,
                "cycles_used": 0.0,
                "throughput_mwh": 0.0,
            })

df_perfect = pd.DataFrame(perfect_rows)
df_perfect.to_csv(ROOT / "outputs" / "backtest_baseline_perfect.csv", index=False)
print(f"  Saved {len(df_perfect)} rows -> outputs/backtest_baseline_perfect.csv")

# ---------------------------------------------------------------------------
# 3. Naive baseline (tracker-aware greedy using FORECAST prices)
# ---------------------------------------------------------------------------
# FAIR COMPARISON: same forecast input, same tracker penalties,
# same constraints. Only the scheduler differs (greedy vs MILP).
# ---------------------------------------------------------------------------
print("\n[2/2] Computing NAIVE baseline (tracker-aware forecast-driven greedy) ...")
print("-" * 70)

naive_rows = []

for profile_name in BATTERY_PROFILES:
    base_battery = load_profile(profile_path, profile_name)
    # Apply transaction cost (same as backtest)
    base_battery = replace(base_battery, transaction_cost_eur_per_mwh=2.0)
    tracker = BatteryStateTracker(base_battery)
    print(f"  -> {profile_name} ...")

    unique_dates = sorted(df_pred["date"].unique())

    for date in tqdm(unique_dates, desc=f"{profile_name}", unit="day"):
        day_df = df_pred[df_pred["date"] == date]
        if len(day_df) != 96:
            continue

        timestamps = day_df.index.tolist()
        actual = day_df["Actual"].values
        forecast = day_df["Pred_p50"].values
        date_str = str(date)

        state = tracker.get_state(date_str)

        if state.is_eol:
            tracker.record_day(date_str, 0.0, 0.0)
            naive_rows.append({
                "date": date_str,
                "profile": profile_name,
                "realized_profit_eur": 0.0,
                "cycles_used": 0.0,
                "throughput_mwh": 0.0,
            })
            continue

        # Effective battery from tracker (adjusted for SOH, carry-over SoC)
        battery = tracker.get_effective_battery(date_str)

        # Inflated marginal cost so the greedy internalises friction
        opt_battery = replace(
            battery,
            degradation_cost_eur_per_mwh=(
                battery.degradation_cost_eur_per_mwh + battery.transaction_cost_eur_per_mwh
            ),
        )

        # Run greedy heuristic
        charge_mw, discharge_mw, soc_traj = greedy_schedule(
            forecast, opt_battery, DURATION_HOURS
        )

        # Build schedule DataFrame (needed for evaluate_schedule)
        sched_df = build_schedule_frame(
            timestamps=timestamps,
            prices=forecast,
            charge_mw=charge_mw,
            discharge_mw=discharge_mw,
            soc_mwh=soc_traj,
            duration_hours=DURATION_HOURS,
            degradation_cost_eur_per_mwh=battery.degradation_cost_eur_per_mwh,
        )

        # Evaluate against ACTUAL prices using the effective battery
        metrics = evaluate_schedule(sched_df, actual, battery, DURATION_HOURS)

        final_soc = soc_traj[-1] if soc_traj else battery.initial_soc_mwh
        tracker.record_day(date_str, metrics["cycles_used"], final_soc)

        naive_rows.append({
            "date": date_str,
            "profile": profile_name,
            "realized_profit_eur": metrics["realized_profit_eur"],
            "cycles_used": metrics["cycles_used"],
            "throughput_mwh": metrics["throughput_mwh"],
        })

df_naive = pd.DataFrame(naive_rows)
df_naive.to_csv(ROOT / "outputs" / "backtest_baseline_naive.csv", index=False)
print(f"  Saved {len(df_naive)} rows -> outputs/backtest_baseline_naive.csv")

print("\n" + "=" * 70)
print("BASELINE COMPUTATION COMPLETE")
print("=" * 70)

print(f"\nPerfect baseline total profit (all profiles, all days):")
for profile in BATTERY_PROFILES:
    total = df_perfect[df_perfect["profile"] == profile]["realized_profit_eur"].sum()
    print(f"  {profile:15s}: €{total:,.0f}")

print(f"\nNaive baseline total profit:")
for profile in BATTERY_PROFILES:
    total = df_naive[df_naive["profile"] == profile]["realized_profit_eur"].sum()
    print(f"  {profile:15s}: €{total:,.0f}")
