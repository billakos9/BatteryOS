"""
Final preprocessing for the master feature matrix.

Actions:
1.  Eliminate data leakage by lagging actual DAM volume columns.
2.  Engineer cyclical time features (sin/cos).
3.  Optionally pull real TTF Natural Gas futures from yfinance.
4.  Drop NaN rows and redundant identifier columns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TIMEZONE = "Europe/Athens"

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


def lag_volume_columns(df: pd.DataFrame, shift_periods: int = 96) -> pd.DataFrame:
    """
    Shift actual DAM volume columns by *shift_periods* to eliminate data leakage.
    Drops the original un-lagged columns.
    """
    df = df.copy()
    vol_cols_present = [c for c in VOLUME_COLS if c in df.columns]
    missing = set(VOLUME_COLS) - set(vol_cols_present)
    if missing:
        print(f"  Warning: missing volume columns (skipped): {sorted(missing)}")

    for col in vol_cols_present:
        lagged_name = f"{col}_Lag_24h"
        df[lagged_name] = df[col].shift(shift_periods)
        print(f"  {col} -> {lagged_name}")

    print(f"  Dropping {len(vol_cols_present)} original (un-lagged) volume columns.")
    df = df.drop(columns=vol_cols_present)
    return df


def add_cyclical_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add sine/cosine transforms for hour, day-of-week, and month."""
    df = df.copy()
    idx = df.index

    hour = idx.hour
    dow = idx.dayofweek
    month = idx.month

    df["Hour_Sin"] = np.sin(2 * np.pi * hour / 24)
    df["Hour_Cos"] = np.cos(2 * np.pi * hour / 24)

    df["DayOfWeek_Sin"] = np.sin(2 * np.pi * dow / 7)
    df["DayOfWeek_Cos"] = np.cos(2 * np.pi * dow / 7)

    df["Month_Sin"] = np.sin(2 * np.pi * month / 12)
    df["Month_Cos"] = np.cos(2 * np.pi * month / 12)

    print("  Added: Hour_Sin, Hour_Cos, DayOfWeek_Sin, DayOfWeek_Cos, Month_Sin, Month_Cos")
    return df


def replace_mock_ttf(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attempt to fetch real TTF Natural Gas prices via yfinance and recalculate
    Break_Even_Gas_Price.  Falls back silently on failure.
    """
    df = df.copy()
    try:
        import yfinance as yf

        start_utc = df.index.min().tz_convert("UTC").date()
        end_utc = df.index.max().tz_convert("UTC").date()
        ttf_hist = yf.Ticker("TTF=F").history(start=start_utc, end=end_utc)

        if not ttf_hist.empty and "Close" in ttf_hist.columns:
            ttf_series = ttf_hist["Close"].copy()
            ttf_series.index = (
                pd.to_datetime(ttf_series.index)
                .tz_localize("UTC")
                .tz_convert(TIMEZONE)
            )
            ttf_15min = ttf_series.reindex(df.index, method="ffill")
            df["TTF_Price_Real"] = ttf_15min
            df["Break_Even_Gas_Price"] = (ttf_15min / 0.50) + (
                df.get("EUA_Price_Mock", 85.0) * 0.20
            )
            print("  -> Real TTF prices successfully merged. Break_Even_Gas_Price updated.")
        else:
            print("  -> yfinance returned empty TTF data; keeping mocked values.")
    except Exception as exc:
        print(f"  -> yfinance failed ({exc}); mocked financial data retained.")

    return df


def preprocess_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run the full preprocessing pipeline on *df*.

    Returns
    -------
    pd.DataFrame
        Cleaned feature matrix ready for modelling.
    """
    print("=" * 70)
    print("Final Preprocessing Pipeline")
    print(f"Input shape: {df.shape}")
    print("=" * 70)

    assert isinstance(df.index, pd.DatetimeIndex), "Index must be a DatetimeIndex"

    # 1. Lag volumes
    print("\n[1/4] Lagging actual DAM volumes by 24 h (96 periods) ...")
    df = lag_volume_columns(df, shift_periods=96)

    # 2. Cyclical time
    print("\n[2/4] Engineering cyclical time features ...")
    df = add_cyclical_time_features(df)

    # 3. Real TTF (optional)
    print("\n[3/4] Attempting to fetch real TTF Natural Gas prices via yfinance ...")
    df = replace_mock_ttf(df)

    # 4. Drop redundant identifiers
    print("\n[4/4] Dropping redundant identifier columns (DDAY, DELIVERY_MTU) ...")
    cols_to_drop = [c for c in ("DDAY", "DELIVERY_MTU") if c in df.columns]
    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)
        print(f"  Dropped: {cols_to_drop}")
    else:
        print("  Already absent.")

    # 5. Drop NaN rows
    print("\n[5/5] Dropping NaN rows introduced by lagging/shifting ...")
    rows_before = len(df)
    df = df.dropna()
    rows_after = len(df)
    print(
        f"  Rows before: {rows_before:,} | Rows after: {rows_after:,} "
        f"(dropped {rows_before - rows_after:,})"
    )

    print("\n" + "=" * 70)
    print(f"Final DataFrame shape : {df.shape}")
    print(f"Index range           : {df.index.min()} -> {df.index.max()}")
    print(f"Index timezone        : {df.index.tz}")

    return df
