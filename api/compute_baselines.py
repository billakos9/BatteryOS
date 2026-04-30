#!/usr/bin/env python3
"""
Compute Perfect-Foresight and Naive baselines for the honest backtest period.

Perfect: deterministic optimizer fed actual realized prices (clairvoyant upper bound).
Naive:   greedy heuristic — charge at cheapest N intervals, discharge at most expensive N.

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
from pathlib import Path

import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.optimize import load_profile
from src.optimize.battery import BatteryProfile
from src.optimize.economics import evaluate_schedule
from src.optimize.milp import optimize_deterministic

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("Loading walk-forward predictions ...")
df_pred = pd.read_csv(
    ROOT / "data" / "processed" / "walkforward_predictions.csv", index_col=0
)
df_pred.index = pd.to_datetime(df_pred.index, utc=True).tz_convert("Europe/Athens")

# Use a generic Li-ion profile for baselines (same across all assets for fair comparison)
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
# 3. Naive baseline (greedy heuristic)
# ---------------------------------------------------------------------------
print("\n[2/2] Computing NAIVE baseline ...")
print("-" * 70)

naive_rows = []

for profile_name in BATTERY_PROFILES:
    battery = load_profile(profile_path, profile_name)
    print(f"  -> {profile_name} ...")

    unique_dates = sorted(df_pred["date"].unique())

    for date in tqdm(unique_dates, desc=f"{profile_name}", unit="day"):
        day_df = df_pred[df_pred["date"] == date]
        if len(day_df) != 96:
            continue

        actual = day_df["Actual"].values
        n = len(actual)

        # Greedy: sort by price, charge cheapest until full, discharge most expensive until empty
        charge_mw = [0.0] * n
        discharge_mw = [0.0] * n
        soc = battery.initial_soc_mwh
        usable = battery.usable_energy_mwh
        power = battery.power_mw
        dt = DURATION_HOURS
        eta_c = battery.charge_efficiency
        eta_d = battery.discharge_efficiency

        # Charge phase: cheapest intervals
        sorted_idx = sorted(range(n), key=lambda i: actual[i])
        for idx in sorted_idx:
            if soc >= battery.soc_max_mwh:
                break
            max_charge = min(power, (battery.soc_max_mwh - soc) / (eta_c * dt))
            charge_mw[idx] = max_charge
            soc += max_charge * eta_c * dt

        # Discharge phase: most expensive intervals
        sorted_idx_desc = sorted(range(n), key=lambda i: actual[i], reverse=True)
        for idx in sorted_idx_desc:
            if soc <= battery.soc_min_mwh:
                break
            max_discharge = min(power, (soc - battery.soc_min_mwh) / dt * eta_d)
            discharge_mw[idx] = max_discharge
            soc -= max_discharge / eta_d * dt

        # Evaluate
        throughput = sum(charge_mw) + sum(discharge_mw)
        market_profit = sum(actual[i] * (discharge_mw[i] - charge_mw[i]) for i in range(n)) * dt
        deg_cost = battery.degradation_cost_eur_per_mwh * throughput * dt
        tx_cost = battery.transaction_cost_eur_per_mwh * throughput * dt
        realized_profit = market_profit - deg_cost - tx_cost
        cycles = throughput / (2.0 * usable) if usable > 0 else 0.0

        naive_rows.append({
            "date": str(date),
            "profile": profile_name,
            "realized_profit_eur": realized_profit,
            "cycles_used": cycles,
            "throughput_mwh": throughput * dt,
        })

df_naive = pd.DataFrame(naive_rows)
df_naive.to_csv(ROOT / "outputs" / "backtest_baseline_naive.csv", index=False)
print(f"  Saved {len(df_naive)} rows -> outputs/backtest_baseline_naive.csv")

print("\n" + "=" * 70)
print("BASELINE COMPUTATION COMPLETE")
print("=" * 70)

# Quick sanity check
total_bos = df_pred["Actual"].sum()  # placeholder
print(f"\nPerfect baseline total profit (all profiles, all days):")
for profile in BATTERY_PROFILES:
    total = df_perfect[df_perfect["profile"] == profile]["realized_profit_eur"].sum()
    print(f"  {profile:15s}: €{total:,.0f}")

print(f"\nNaive baseline total profit:")
for profile in BATTERY_PROFILES:
    total = df_naive[df_naive["profile"] == profile]["realized_profit_eur"].sum()
    print(f"  {profile:15s}: €{total:,.0f}")
