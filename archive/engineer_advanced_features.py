#!/usr/bin/env python3
"""
Engineer highly advanced, non-linear features representing human behaviour,
grid stress, and market momentum, and append them to df_master_ml_ready.

Assumes df_master_ml_ready already exists in memory, indexed by a timezone-aware
15-minute DatetimeIndex (Europe/Athens).
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 0. Guard
# ---------------------------------------------------------------------------
if "df_master_ml_ready" not in globals():
    raise NameError(
        "df_master_ml_ready must exist in the global namespace before running this script."
    )

print("=" * 70)
print("Advanced Non-Linear Feature Engineering")
print(f"Input shape: {df_master_ml_ready.shape}")
print("=" * 70)

# ---------------------------------------------------------------------------
# Helper: extract a daily view of the holiday flag
# ---------------------------------------------------------------------------
daily_holiday = (
    df_master_ml_ready["Is_Holiday"]
    .groupby(df_master_ml_ready.index.date)
    .first()
)
holiday_dates = pd.to_datetime(daily_holiday[daily_holiday == 1].index)
all_dates = pd.to_datetime(daily_holiday.index)

# ---------------------------------------------------------------------------
# Group 1: Advanced Greek Calendar & Behaviour
# ---------------------------------------------------------------------------
print("\n[Group 1/4] Advanced Greek Calendar & Behaviour ...")

# --- Is_Bridge_Day ---
# A bridge day is a working Monday before a Tuesday holiday,
# or a working Friday after a Thursday holiday.
# We work on daily resolution and map back to the 15-min index.

dow = all_dates.dayofweek  # Monday=0, Friday=4
is_hol = daily_holiday.reindex(all_dates.date).fillna(0).values

daily_hol_s = pd.Series(is_hol, index=all_dates)
tue_is_hol = daily_hol_s.shift(-1, fill_value=0)   # next day is holiday
thu_is_hol = daily_hol_s.shift(1, fill_value=0)    # prev day is holiday

mon_bridge = (dow == 0) & (is_hol == 0) & (tue_is_hol.values == 1)
fri_bridge = (dow == 4) & (is_hol == 0) & (thu_is_hol.values == 1)

bridge_map = pd.Series((mon_bridge | fri_bridge).astype(int), index=all_dates)
# Map back to the 15-min index by re-indexing on date
df_master_ml_ready["Is_Bridge_Day"] = bridge_map.reindex(
    df_master_ml_ready.index.date
).values

# --- Is_August_Exodus ---
# August in Greece sees a massive drop in Athenian industrial/commercial demand.
df_master_ml_ready["Is_August_Exodus"] = (
    df_master_ml_ready.index.month == 8
).astype(int)

# --- Days_Until_Next_Holiday ---
# Integer count of calendar days until the next Is_Holiday == 1.
holiday_arr = holiday_dates.to_numpy()
date_arr = all_dates.to_numpy()

# Vectorised search for the next holiday date
days_until_list = []
for d in date_arr:
    future = holiday_arr[holiday_arr > d]
    if len(future):
        delta = (future[0] - d).astype("timedelta64[D]").astype(int)
    else:
        delta = 0  # No upcoming holiday in the window
    days_until_list.append(delta)

days_until_map = pd.Series(days_until_list, index=all_dates)
df_master_ml_ready["Days_Until_Next_Holiday"] = days_until_map.reindex(
    df_master_ml_ready.index.date
).values

print("  -> Is_Bridge_Day, Is_August_Exodus, Days_Until_Next_Holiday")

# ---------------------------------------------------------------------------
# Group 2: Cumulative Thermal Stress (Weather Memory)
# ---------------------------------------------------------------------------
print("\n[Group 2/4] Cumulative Thermal Stress ...")

# --- Rolling_48h_Temp_Max ---
# The maximum temperature experienced over the last 48 hours (192 × 15 min).
# Captures prolonged heat stress on the grid.
df_master_ml_ready["Rolling_48h_Temp_Max"] = (
    df_master_ml_ready["Temp_Athens"]
    .rolling(window=192, min_periods=1)
    .max()
)

# --- Consecutive_Days_Above_35C ---
# Counter that increments for each consecutive calendar day where the daily
# maximum temperature exceeded 35 °C, and resets to 0 otherwise.

daily_max_temp = (
    df_master_ml_ready["Temp_Athens"]
    .groupby(df_master_ml_ready.index.date)
    .max()
)

above_35 = (daily_max_temp > 35).astype(int)
# Count consecutive True values (1s) and keep 0 for False values (0s)
groups = (above_35 != above_35.shift()).cumsum()
consecutive_days = above_35.groupby(groups).cumsum()

# Map the daily counter back to every 15-minute interval
df_master_ml_ready["Consecutive_Days_Above_35C"] = (
    pd.Series(consecutive_days.values, index=pd.to_datetime(consecutive_days.index))
    .reindex(df_master_ml_ready.index.date)
    .values
)

print("  -> Rolling_48h_Temp_Max, Consecutive_Days_Above_35C")

# ---------------------------------------------------------------------------
# Group 3: The "Duck Curve" Derivatives (Grid Ramps)
# ---------------------------------------------------------------------------
print("\n[Group 3/4] Duck Curve Derivatives ...")

# --- Solar_Crash_Velocity ---
# Period-over-period change in solar forecast.  Highly negative values
# indicate the rapid sunset ramp (the "duck curve" belly dropping).
df_master_ml_ready["Solar_Crash_Velocity"] = (
    df_master_ml_ready["Forecast_Solar"].diff(1)
)

# --- Wind_Volatility_6h ---
# Rolling standard deviation of the wind forecast over a 6-hour window
# (24 periods).  Captures forecast uncertainty / gusty conditions.
df_master_ml_ready["Wind_Volatility_6h"] = (
    df_master_ml_ready["Forecast_Wind"]
    .rolling(window=24, min_periods=1)
    .std()
)

print("  -> Solar_Crash_Velocity, Wind_Volatility_6h")

# ---------------------------------------------------------------------------
# Group 4: Market Volatility & Momentum
# ---------------------------------------------------------------------------
print("\n[Group 4/4] Market Volatility & Momentum ...")

# --- MCP_Rolling_Std_24h ---
# Rolling standard deviation of the 24-hour lagged MCP over a 24-hour window.
# Measures recent price volatility.
df_master_ml_ready["MCP_Rolling_Std_24h"] = (
    df_master_ml_ready["MCP_Lag_24h"]
    .rolling(window=96, min_periods=1)
    .std()
)

# --- Daily_Peak_to_Trough_Ratio ---
# Safe peak-to-trough ratio using yesterday's MCP (MCP_Lag_24h).
# When prices are positive we use Max/Min; when negative pricing occurs
# (min <= 0) we fall back to the absolute spread to avoid division by zero.
daily_max_lag = (
    df_master_ml_ready["MCP_Lag_24h"]
    .groupby(df_master_ml_ready.index.date)
    .transform("max")
)
daily_min_lag = (
    df_master_ml_ready["MCP_Lag_24h"]
    .groupby(df_master_ml_ready.index.date)
    .transform("min")
)
df_master_ml_ready["Daily_Peak_to_Trough_Ratio"] = np.where(
    daily_min_lag > 0,
    daily_max_lag / daily_min_lag,
    daily_max_lag - daily_min_lag,
)

print("  -> MCP_Rolling_Std_24h, Daily_Peak_to_Trough_Ratio")

# ---------------------------------------------------------------------------
# Final Cleanup
# ---------------------------------------------------------------------------
print("\n[Cleanup] Dropping rows with NaN values introduced by diffs/shifts ...")
rows_before = len(df_master_ml_ready)
df_master_ml_ready.dropna(inplace=True)
rows_after = len(df_master_ml_ready)
print(f"  Rows before: {rows_before:,} | Rows after: {rows_after:,} "
      f"(dropped {rows_before - rows_after:,})")

# ---------------------------------------------------------------------------
# Validation & Output
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print(f"Final DataFrame shape : {df_master_ml_ready.shape}")
print(f"Index range           : {df_master_ml_ready.index.min()} -> "
      f"{df_master_ml_ready.index.max()}")
print(f"Index timezone        : {df_master_ml_ready.index.tz}")
print(f"\nFinal column list ({len(df_master_ml_ready.columns)} columns):")
for i, col in enumerate(df_master_ml_ready.columns, 1):
    print(f"  {i:2d}. {col}")

print("\n.head():")
print(df_master_ml_ready.head().to_string())

# Persist
output_csv = "df_master_ml_ready_advanced.csv"
df_master_ml_ready.to_csv(output_csv)
print(f"\nSaved advanced dataset: {output_csv}")
