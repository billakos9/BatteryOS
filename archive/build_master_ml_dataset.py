#!/usr/bin/env python3
"""
Production-ready script to engineer advanced financial & market features
and merge them with existing energy grid DataFrames into a single
master training dataset for Greek DAM forecasting.

Assumes the following DataFrames already exist in the environment,
all indexed by a timezone-aware DatetimeIndex (Europe/Athens) at
15-minute frequency:

    df_wide          – Hellenic Energy Exchange DAM volumes & MCP
    df_ipto          – ENTSO-E Load, Wind, Solar, Residual_Load forecasts
    df_weather_master – Open-Meteo weather + Cooling/Heating demand

Dependencies:
    pip install pandas numpy yfinance holidays
"""

import sys
from datetime import datetime

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 0. Guard: ensure the three source DataFrames exist
# ---------------------------------------------------------------------------
for _name in ("df_wide", "df_ipto", "df_weather_master"):
    if _name not in globals():
        raise NameError(
            f"Expected '{_name}' to exist in the global namespace. "
            "Please load or construct it before running this script."
        )

TIMEZONE = "Europe/Athens"
START_DATE = pd.Timestamp("2023-01-01", tz=TIMEZONE)
END_DATE = pd.Timestamp.now(tz=TIMEZONE)

# ---------------------------------------------------------------------------
# 1. Fetch / Mock Financial & Calendar Data
# ---------------------------------------------------------------------------

def fetch_ttf_gas(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """
    Pull Dutch TTF Natural Gas futures from yfinance.
    Falls back to a realistic random-walk mock only if the API fails.
    Returns a daily Series indexed at midnight Europe/Athens.
    """
    try:
        import yfinance as yf

        ticker = yf.Ticker("TTF=F")
        # yfinance returns tz-aware UTC indices; pass naive dates
        df = ticker.history(start=str(start.date()), end=str(end.date()))
        if df.empty:
            raise ValueError("Empty TTF history")

        series = df["Close"].copy()
        # Convert yfinance UTC index -> Europe/Athens
        series.index = (
            pd.to_datetime(series.index)
            .tz_convert(TIMEZONE)
            .normalize()
        )
        print(f"  -> TTF fetched from yfinance: {len(series)} days")
        return series
    except Exception as exc:
        print(f"  Warning: yfinance TTF failed ({exc}). Using mock data.")
        return _mock_commodity_series(start, end, mean=35.0, std=8.0, name="TTF_Price")


def fetch_eua_carbon(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """
    Pull EUA Carbon Allowance proxy from yfinance (CO2.L = WisdomTree
    Carbon ETF tracking EUA futures on the London Stock Exchange).
    Falls back to mock data if unavailable.
    Returns a daily Series indexed at midnight Europe/Athens.
    """
    try:
        import yfinance as yf

        ticker = yf.Ticker("CO2.L")
        df = ticker.history(start=str(start.date()), end=str(end.date()))
        if df.empty:
            raise ValueError("Empty EUA history")

        series = df["Close"].copy()
        series.index = (
            pd.to_datetime(series.index)
            .tz_convert(TIMEZONE)
            .normalize()
        )
        print(f"  -> EUA (CO2.L proxy) fetched from yfinance: {len(series)} days")
        return series
    except Exception as exc:
        print(f"  Warning: yfinance EUA failed ({exc}). Using mock data.")
        return _mock_commodity_series(start, end, mean=72.0, std=10.0, name="EUA_Price")


def _mock_commodity_series(
    start: pd.Timestamp, end: pd.Timestamp, mean: float, std: float, name: str
) -> pd.Series:
    """Generate a daily random-walk commodity price series."""
    daily_index = pd.date_range(start=start.normalize(), end=end.normalize(), freq="D", tz=TIMEZONE)
    # Random walk: cumulative sum of normal increments
    increments = np.random.normal(loc=0.0, scale=std / np.sqrt(252), size=len(daily_index))
    prices = mean + np.cumsum(increments)
    prices = np.clip(prices, mean * 0.3, mean * 3.0)  # keep within realistic bounds
    return pd.Series(data=prices, index=daily_index, name=name)


def build_greek_holiday_series(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """
    Build a binary holiday indicator (1 = holiday, 0 = normal) for Greece.
    Returns a daily Series indexed at midnight Europe/Athens.
    """
    import holidays

    gr_hols = holidays.Greece(years=range(start.year, end.year + 1))
    daily_index = pd.date_range(start=start.normalize(), end=end.normalize(), freq="D", tz=TIMEZONE)
    is_holiday = [1 if d.date() in gr_hols else 0 for d in daily_index]
    return pd.Series(data=is_holiday, index=daily_index, name="Is_Holiday")


# ---------------------------------------------------------------------------
# 2. Upsample daily financial/calendar data to 15-min
# ---------------------------------------------------------------------------

def upsample_daily_to_15min(series: pd.Series, df_target: pd.DataFrame) -> pd.Series:
    """
    Reindex a daily Series to match the 15-minute DatetimeIndex of df_target
    and forward-fill.
    """
    return series.reindex(df_target.index, method="ffill")


# ---------------------------------------------------------------------------
# 3. Feature Engineering
# ---------------------------------------------------------------------------

def engineer_features(df_wide: pd.DataFrame, df_ipto: pd.DataFrame) -> pd.DataFrame:
    """
    Compute advanced financial and market features.
    Returns a DataFrame with the new columns, indexed like the inputs.
    """
    df_features = pd.DataFrame(index=df_wide.index)

    # --- 3.1 Break-Even Gas Price (Clean Spark Spread proxy) ---
    # Formula: (TTF / 0.50) + (EUA * 0.20)
    ttf = upsample_daily_to_15min(df_ttf, df_wide)
    eua = upsample_daily_to_15min(df_eua, df_wide)
    df_features["Break_Even_Gas_Price"] = (ttf / 0.50) + (eua * 0.20)

    # --- 3.2 Residual Load Ramp Rate ---
    if "Residual_Load" in df_ipto.columns:
        df_features["Residual_Load_Ramp"] = df_ipto["Residual_Load"].diff(1)
    else:
        print("Warning: Residual_Load not found in df_ipto; skipping ramp feature.")
        df_features["Residual_Load_Ramp"] = np.nan

    # --- 3.3 MCP Lags (short-term memory) ---
    if "MCP" in df_wide.columns:
        mcp = df_wide["MCP"]
        df_features["MCP_Lag_24h"] = mcp.shift(96)     # 96 × 15-min = 24 h
        df_features["MCP_Lag_168h"] = mcp.shift(672)   # 672 × 15-min = 7 d
        df_features["MCP_Rolling_24h_Avg"] = mcp.rolling(window=96, min_periods=1).mean()
    else:
        print("Warning: MCP not found in df_wide; skipping lag/rolling features.")
        df_features["MCP_Lag_24h"] = np.nan
        df_features["MCP_Lag_168h"] = np.nan
        df_features["MCP_Rolling_24h_Avg"] = np.nan

    # --- 3.4 Daily Battery Spread (Max - Min MCP per calendar day) ---
    if "MCP" in df_wide.columns:
        daily_max = df_wide["MCP"].groupby(df_wide.index.date).transform("max")
        daily_min = df_wide["MCP"].groupby(df_wide.index.date).transform("min")
        df_features["Daily_Battery_Spread"] = daily_max - daily_min
    else:
        df_features["Daily_Battery_Spread"] = np.nan

    # --- 3.5 Greek Holiday Indicator ---
    df_features["Is_Holiday"] = upsample_daily_to_15min(df_holiday, df_wide)

    return df_features


# ---------------------------------------------------------------------------
# 4. Master Merge
# ---------------------------------------------------------------------------

def build_master_dataset() -> pd.DataFrame:
    """
    Concatenate all DataFrames and drop rows with NaNs introduced by lagging.
    """
    print("\nMerging datasets into master training frame ...")

    # Align all inputs to the intersection of their indices
    common_idx = df_wide.index.intersection(df_ipto.index).intersection(df_weather_master.index)
    if len(common_idx) == 0:
        raise ValueError("No overlapping timestamps between the three source DataFrames.")

    df_w = df_wide.loc[common_idx].copy()
    df_i = df_ipto.loc[common_idx].copy()
    df_m = df_weather_master.loc[common_idx].copy()

    # Build engineered features
    df_f = engineer_features(df_w, df_i)

    # Concatenate side-by-side
    df_master = pd.concat([df_w, df_i, df_m, df_f], axis=1)

    # Drop NaNs caused by the 7-day lag (and any other incomplete rows)
    df_master = df_master.dropna()

    return df_master


# ---------------------------------------------------------------------------
# 5. Execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("Feature Engineering & Master Dataset Builder")
    print(f"Time range: {START_DATE.date()} → {END_DATE.date()}")
    print("=" * 70)

    # -- Step 1: Build daily financial / calendar series --
    print("\n[1/4] Fetching / mocking daily financial data ...")
    df_ttf = fetch_ttf_gas(START_DATE, END_DATE)
    df_eua = fetch_eua_carbon(START_DATE, END_DATE)
    df_holiday = build_greek_holiday_series(START_DATE, END_DATE)

    # -- Step 2-4: Merge & engineer --
    print("\n[2/4] Engineering features ...")
    print("\n[3/4] Building master dataset ...")
    df_master_ml_ready = build_master_dataset()

    # -- Step 5: Validate & output --
    print("\n[4/4] Validation")
    print("-" * 70)
    print(f"Final shape : {df_master_ml_ready.shape}")
    print(f"Index range : {df_master_ml_ready.index.min()} -> {df_master_ml_ready.index.max()}")
    print(f"Index freq  : {pd.infer_freq(df_master_ml_ready.index)}")
    print("\nColumn inventory:")
    for col in df_master_ml_ready.columns:
        print(f"  - {col}")

    print("\n.info():")
    df_master_ml_ready.info()

    print("\n.head():")
    print(df_master_ml_ready.head().to_string())

    # Persist
    output_csv = "df_master_ml_ready.csv"
    df_master_ml_ready.to_csv(output_csv)
    print(f"\nSaved master dataset: {output_csv}")
