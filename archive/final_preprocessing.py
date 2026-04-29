#!/usr/bin/env python3
"""
Final preprocessing script for df_master_ml_ready.

Actions:
1.  Eliminate data leakage by lagging actual DAM volume columns 24 h (96 × 15 min).
2.  Engineer cyclical time features (sin/cos) for hour, day-of-week, and month.
3.  Optionally pull real TTF Natural Gas futures from yfinance to replace mock data.
4.  Drop NaN rows and print the finalized feature list.

Assumes df_master_ml_ready already exists in memory, indexed by a
 timezone-aware 15-minute DatetimeIndex (Europe/Athens).
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

assert isinstance(
    df_master_ml_ready.index, pd.DatetimeIndex
), "Index must be a DatetimeIndex"
assert df_master_ml_ready.index.freq is not None or len(df_master_ml_ready) > 1, (
    "Index frequency could not be inferred; ensure data is regularly sampled."
)

print("=" * 70)
print("Final Preprocessing Pipeline")
print(f"Input shape: {df_master_ml_ready.shape}")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Fix Data Leakage — Shift actual DAM volumes by 24 h (96 intervals)
# ---------------------------------------------------------------------------
VOLUME_COLS = [
    "Vol_Big_Hydro",
    "Vol_Lignite",
    "Vol_Natural_Gas",
    "Vol_RES",
    "Vol_PUMP",
    "Vol_Storage",
    "Vol_Exports",
    "Vol_Imports",
    "Vol_CRETE_CONVENTIONAL",
    "Vol_CRETE_RENEWABLES",
    "Total_Domestic_Load",
]

# Only shift columns that actually exist
vol_cols_present = [c for c in VOLUME_COLS if c in df_master_ml_ready.columns]
missing = set(VOLUME_COLS) - set(vol_cols_present)
if missing:
    print(f"  Warning: missing volume columns (skipped): {sorted(missing)}")

print("\n[1/4] Lagging actual DAM volumes by 24 h (96 periods) ...")
for col in vol_cols_present:
    lagged_name = f"{col}_Lag_24h"
    df_master_ml_ready[lagged_name] = df_master_ml_ready[col].shift(96)
    print(f"  {col} -> {lagged_name}")

# Drop the originals to eliminate any leakage risk
print(f"  Dropping {len(vol_cols_present)} original (un-lagged) volume columns.")
df_master_ml_ready = df_master_ml_ready.drop(columns=vol_cols_present)

# ---------------------------------------------------------------------------
# 2. Engineer Cyclical Time Features
# ---------------------------------------------------------------------------
print("\n[2/4] Engineering cyclical time features ...")

idx = df_master_ml_ready.index

# Hour (0–23)
hour = idx.hour
# Day-of-week (Mon=0 … Sun=6)
dow = idx.dayofweek
# Month (1–12)
month = idx.month

# Sine / Cosine transforms
df_master_ml_ready["Hour_Sin"] = np.sin(2 * np.pi * hour / 24)
df_master_ml_ready["Hour_Cos"] = np.cos(2 * np.pi * hour / 24)

df_master_ml_ready["DayOfWeek_Sin"] = np.sin(2 * np.pi * dow / 7)
df_master_ml_ready["DayOfWeek_Cos"] = np.cos(2 * np.pi * dow / 7)

df_master_ml_ready["Month_Sin"] = np.sin(2 * np.pi * month / 12)
df_master_ml_ready["Month_Cos"] = np.cos(2 * np.pi * month / 12)

print("  Added: Hour_Sin, Hour_Cos, DayOfWeek_Sin, DayOfWeek_Cos, Month_Sin, Month_Cos")

# ---------------------------------------------------------------------------
# 3. Replace Mock Financial Data with Real TTF (Optional)
# ---------------------------------------------------------------------------
print("\n[3/4] Attempting to fetch real TTF Natural Gas prices via yfinance ...")

try:
    import yfinance as yf

    # Pull daily TTF continuous futures
    ttf = yf.Ticker("TTF=F")
    start_utc = df_master_ml_ready.index.min().tz_convert("UTC").date()
    end_utc = df_master_ml_ready.index.max().tz_convert("UTC").date()
    ttf_hist = ttf.history(start=start_utc, end=end_utc)

    if not ttf_hist.empty and "Close" in ttf_hist.columns:
        ttf_series = ttf_hist["Close"].copy()
        # Localize to midnight UTC then convert to Europe/Athens
        ttf_series.index = (
            pd.to_datetime(ttf_series.index)
            .tz_localize("UTC")
            .tz_convert("Europe/Athens")
        )

        # Upsample daily -> 15-min and forward-fill
        ttf_15min = ttf_series.reindex(df_master_ml_ready.index, method="ffill")

        # Recalculate the clean spark spread using real TTF
        # (EUA remains mocked; replace the line below if you have a real EUA source)
        eua_mock = df_master_ml_ready.get("Break_Even_Gas_Price", pd.Series(np.nan, index=df_master_ml_ready.index))
        # Reverse-engineer mock EUA from existing Break_Even if possible, else keep mock
        # For simplicity we keep the mocked EUA component and only swap TTF
        df_master_ml_ready["TTF_Price_Real"] = ttf_15min
        df_master_ml_ready["Break_Even_Gas_Price"] = (ttf_15min / 0.50) + (
            df_master_ml_ready.get("EUA_Price_Mock", 85.0) * 0.20
        )
        print("  -> Real TTF prices successfully merged. Break_Even_Gas_Price updated.")
    else:
        print("  -> yfinance returned empty TTF data; keeping mocked values.")

except Exception as exc:
    print(f"  -> yfinance failed ({exc}); mocked financial data retained.")

# ---------------------------------------------------------------------------
# 4. Drop redundant / non-numeric identifier columns
# ---------------------------------------------------------------------------
print("\n[4/4] Dropping redundant identifier columns (DDAY, DELIVERY_MTU) ...")
cols_to_drop = [c for c in ("DDAY", "DELIVERY_MTU") if c in df_master_ml_ready.columns]
if cols_to_drop:
    df_master_ml_ready = df_master_ml_ready.drop(columns=cols_to_drop)
    print(f"  Dropped: {cols_to_drop}")
else:
    print("  Already absent.")

# ---------------------------------------------------------------------------
# 5. Final Cleanup — drop NaN rows
# ---------------------------------------------------------------------------
print("\n[5/5] Dropping NaN rows introduced by lagging/shifting ...")
rows_before = len(df_master_ml_ready)
df_master_ml_ready = df_master_ml_ready.dropna()
rows_after = len(df_master_ml_ready)
print(f"  Rows before: {rows_before:,} | Rows after: {rows_after:,} (dropped {rows_before - rows_after:,})")

# ---------------------------------------------------------------------------
# 5. Validation & Output
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print(f"Final DataFrame shape : {df_master_ml_ready.shape}")
print(f"Index range           : {df_master_ml_ready.index.min()} -> {df_master_ml_ready.index.max()}")
print(f"Index timezone        : {df_master_ml_ready.index.tz}")
print("\nFinal column list ({} columns):".format(len(df_master_ml_ready.columns)))
for i, col in enumerate(df_master_ml_ready.columns, 1):
    print(f"  {i:2d}. {col}")

print("\n.head():")
print(df_master_ml_ready.head().to_string())

# Persist
output_csv = "df_master_ml_ready_final.csv"
df_master_ml_ready.to_csv(output_csv)
print(f"\nSaved final dataset: {output_csv}")
