#!/usr/bin/env python3
"""
End-to-end backtest pipeline with cumulative degradation tracking.

Uses walk-forward out-of-sample predictions (monthly expanding window)
if available; otherwise falls back to in-sample predictions with a
prominent warning.

Steps:
1. Load walk-forward predictions (p10 / p50 / p90)
2. For each complete day (96 × 15-min intervals):
   a. Run Safe   (CVaR on quantile scenarios)
   b. Run Regular (deterministic on p50)
   c. Run Risky  (deterministic on p90)
3. Evaluate each schedule against actual realized MCP
4. Track battery health: SOH, cumulative cycles, annual budget, lifetime budget
5. SoC carry-over: final SoC of day t becomes initial SoC of day t+1
6. Save detailed results + degradation history + summary report

Usage:
    cd /home/dimit/BatteryOS
    source .venv/bin/activate
    python pipelines/run_walkforward_training.py   # first, if needed
    python pipelines/run_backtest.py
"""

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# 0. Resolve repo root
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from src.optimize import load_profile
from src.optimize.backtest import (
    run_daily_optimizations,
    backtest_to_dataframe,
    compute_backtest_summary,
)
from src.optimize.tracker import BatteryStateTracker

DATA_PROCESSED = REPO_ROOT / "data" / "processed"
OUTPUTS_DIR = REPO_ROOT / "outputs"

# ---------------------------------------------------------------------------
# 1. Configuration
# ---------------------------------------------------------------------------
BATTERY_PROFILES = [
    "liion_100_2h",
    "liion_200_2h",
    "liion_300_2h",
    "phs_100_8h",
    "phs_200_8h",
    "flow_100_6h",
]

DURATION_HOURS = 0.25
TIME_LIMIT_S = 10

# ---------------------------------------------------------------------------
# 2. Load walk-forward (or fall back to in-sample) predictions
# ---------------------------------------------------------------------------
print("=" * 70)
print("BatteryOS Backtest Pipeline (Honest — Walk-Forward + SoC Carry-Over)")
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

wf_path = DATA_PROCESSED / "walkforward_predictions.csv"
if wf_path.exists():
    print(f"\n[1/3] Loading walk-forward predictions ...")
    df_pred = pd.read_csv(wf_path, index_col=0)
    df_pred.index = pd.to_datetime(df_pred.index, utc=True).tz_convert("Europe/Athens")
    print(f"  Loaded: {df_pred.shape}")
    print(f"  Index: {df_pred.index.min()} -> {df_pred.index.max()}")
    print(f"  >>> Using OUT-OF-SAMPLE walk-forward predictions <<<")
    IS_IN_SAMPLE = False
else:
    print(f"\n[1/3] Walk-forward predictions NOT found at {wf_path}")
    print("  Falling back to IN-SAMPLE predictions (optimistic).")
    print("  Run 'python pipelines/run_walkforward_training.py' first for honest results.")
    df_pred = pd.read_csv(
        DATA_PROCESSED / "df_master_ml_ready_advanced.csv", index_col=0
    )
    df_pred.index = pd.to_datetime(df_pred.index, utc=True).tz_convert("Europe/Athens")
    # In-sample: use actual MCP as perfect forecast (cheating)
    df_pred = df_pred[["MCP"]].copy()
    df_pred.columns = ["Actual"]
    df_pred["Pred_p10"] = df_pred["Actual"]
    df_pred["Pred_p50"] = df_pred["Actual"]
    df_pred["Pred_p90"] = df_pred["Actual"]
    IS_IN_SAMPLE = True
    print(f"  Loaded: {df_pred.shape}")

# ---------------------------------------------------------------------------
# 2. Load battery profiles
# ---------------------------------------------------------------------------
print("\n[2/3] Loading battery profiles ...")
profile_path = REPO_ROOT / "config" / "storage_profiles.yaml"
batteries = {}
for name in BATTERY_PROFILES:
    b = load_profile(profile_path, name)
    # Apply transaction cost (grid fees + imbalance proxy)
    b = replace(b, transaction_cost_eur_per_mwh=2.0)
    batteries[name] = b
    print(
        f"  -> {name}: {b.power_mw} MW / {b.energy_mwh} MWh | "
        f"annual_cap={b.max_cycles_per_year} | lifetime_EOL={b.lifetime_cycles_eol} | "
        f"tx_cost={b.transaction_cost_eur_per_mwh:.1f} €/MWh"
    )

# ---------------------------------------------------------------------------
# 3. Initialize degradation trackers (one per profile per scenario)
# ---------------------------------------------------------------------------
print("\n[3/3] Initializing degradation trackers ...")
trackers: dict[str, dict[str, BatteryStateTracker]] = {}
for profile_name, battery in batteries.items():
    trackers[profile_name] = {
        "regular": BatteryStateTracker(battery),
        "risky": BatteryStateTracker(battery),
        "safe": BatteryStateTracker(battery),
    }
print(f"  -> Created {len(batteries) * 3} trackers")

# ---------------------------------------------------------------------------
# 6. Run backtest day-by-day
# ---------------------------------------------------------------------------
print("\nRunning backtest (this may take 10-30 minutes) ...")
print("-" * 70)

df_pred["date"] = df_pred.index.date
unique_dates = sorted(df_pred["date"].unique())

all_results = []

for date in tqdm(unique_dates, desc="Days", unit="day"):
    day_df = df_pred[df_pred["date"] == date]

    if len(day_df) != 96:
        continue

    timestamps = day_df.index.tolist()
    p10 = day_df["Pred_p10"].values
    p50 = day_df["Pred_p50"].values
    p90 = day_df["Pred_p90"].values
    actual = day_df["Actual"].values

    for profile_name, battery in batteries.items():
        for scenario in ("regular", "risky", "safe"):
            tracker = trackers[profile_name][scenario]

            daily_results = run_daily_optimizations(
                timestamps=timestamps,
                p10=p10,
                p50=p50,
                p90=p90,
                actual=actual,
                tracker=tracker,
                profile_name=profile_name,
                duration_hours=DURATION_HOURS,
                time_limit_s=TIME_LIMIT_S,
            )

            # Record cycles used and final SoC for the scenario that was actually run
            for r in daily_results:
                if r.scenario == scenario:
                    tracker.record_day(str(date), r.cycles_used, r.final_soc_mwh)
                    all_results.append(r)

# ---------------------------------------------------------------------------
# 7. Save & summarize
# ---------------------------------------------------------------------------
OUTPUTS_DIR.mkdir(exist_ok=True)

df_results = backtest_to_dataframe(all_results)
detailed_path = OUTPUTS_DIR / "backtest_detailed.csv"
df_results.to_csv(detailed_path, index=False)
print(f"\n  Saved detailed results: {detailed_path}")

summary = compute_backtest_summary(df_results)
summary_path = OUTPUTS_DIR / "backtest_summary.csv"
summary.to_csv(summary_path)
print(f"  Saved summary:          {summary_path}")

# Save degradation history
for profile_name in batteries:
    for scenario in ("regular", "risky", "safe"):
        tracker = trackers[profile_name][scenario]
        hist_df = tracker.get_history_df()
        hist_path = OUTPUTS_DIR / f"backtest_degradation_{profile_name}_{scenario}.csv"
        hist_df.to_csv(hist_path, index=False)

print(f"  Saved degradation histories: {len(batteries) * 3} files")

# Pretty-print summary
print("\n" + "=" * 70)
print("BACKTEST SUMMARY")
print("=" * 70)
print(summary.to_string())

# Totals per profile
print("\n" + "=" * 70)
print("TOTAL PROFIT PER PROFILE (all scenarios)")
print("=" * 70)
totals = (
    df_results.groupby(["profile", "scenario"])["realized_profit_eur"]
    .sum()
    .unstack("scenario")
    .round(2)
)
print(totals.to_string())

# Daily averages
print("\n" + "=" * 70)
print("AVERAGE DAILY PROFIT PER PROFILE (€/day)")
print("=" * 70)
avg_daily = (
    df_results.groupby(["profile", "scenario"])["realized_profit_eur"]
    .mean()
    .unstack("scenario")
    .round(2)
)
print(avg_daily.to_string())

# Transaction cost summary
print("\n" + "=" * 70)
print("TRANSACTION COST SUMMARY (€2/MWh deducted from all trades)")
print("=" * 70)
tx_summary = (
    df_results.groupby(["profile", "scenario"])["transaction_cost_eur"]
    .agg(total=("sum"), daily_avg=("mean"))
    .round(2)
)
print(tx_summary.to_string())

# Degradation summary
print("\n" + "=" * 70)
print("DEGRADATION SUMMARY (final state)")
print("=" * 70)
deg_rows = []
for profile_name in batteries:
    for scenario in ("regular", "risky", "safe"):
        tracker = trackers[profile_name][scenario]
        if tracker.daily_cycles:
            last_date = tracker.daily_cycles[-1][0]
            state = tracker.get_state(last_date)
            deg_rows.append({
                "profile": profile_name,
                "scenario": scenario,
                "final_soh_%": round(state.soh_frac * 100, 1),
                "cumulative_cycles": round(state.cumulative_cycles, 1),
                "annual_budget_left": round(state.annual_budget_remaining, 1),
                "lifetime_budget_left": round(state.lifetime_budget_remaining, 1),
                "eol_days": int(state.is_eol),
            })
deg_df = pd.DataFrame(deg_rows)
print(
    deg_df.set_index(["profile", "scenario"]).to_string()
)

# Scenario comparison
print("\n" + "=" * 70)
print("AGGREGATE PROFIT BY SCENARIO (all profiles combined)")
print("=" * 70)
agg = df_results.groupby("scenario")["realized_profit_eur"].sum().round(2)
print(agg.to_string())

print("\n" + "=" * 70)
print("BACKTEST COMPLETE")
print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

if IS_IN_SAMPLE:
    print(f"\n⚠️  WARNING: Using IN-SAMPLE predictions (cheating).")
    print(f"   Run 'python pipelines/run_walkforward_training.py' first")
    print(f"   for honest out-of-sample results.")
else:
    print(f"\n✅ Using OUT-OF-SAMPLE walk-forward predictions.")
    print(f"   SoC carry-over is ACTIVE (day t+1 starts at day t's final SoC).")
