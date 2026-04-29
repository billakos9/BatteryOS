"""
Production-ready feature builder that merges raw energy grid DataFrames
into a single master training dataset for Greek DAM forecasting.

Handles financial data fetching (TTF gas, EUA carbon) and holiday
calendar construction, then engineers base features and merges everything.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TIMEZONE = "Europe/Athens"

# ---------------------------------------------------------------------------
# 1. Financial & Calendar Data Fetchers
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
        df = ticker.history(start=str(start.date()), end=str(end.date()))
        if df.empty:
            raise ValueError("Empty TTF history")

        series = df["Close"].copy()
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
    Pull EUA Carbon Allowance proxy from yfinance (CO2.L).
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
    daily_index = pd.date_range(
        start=start.normalize(), end=end.normalize(), freq="D", tz=TIMEZONE
    )
    increments = np.random.normal(loc=0.0, scale=std / np.sqrt(252), size=len(daily_index))
    prices = mean + np.cumsum(increments)
    prices = np.clip(prices, mean * 0.3, mean * 3.0)
    return pd.Series(data=prices, index=daily_index, name=name)


def build_greek_holiday_series(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """
    Build a binary holiday indicator (1 = holiday, 0 = normal) for Greece.
    Returns a daily Series indexed at midnight Europe/Athens.
    """
    import holidays

    gr_hols = holidays.Greece(years=range(start.year, end.year + 1))
    daily_index = pd.date_range(
        start=start.normalize(), end=end.normalize(), freq="D", tz=TIMEZONE
    )
    is_holiday = [1 if d.date() in gr_hols else 0 for d in daily_index]
    return pd.Series(data=is_holiday, index=daily_index, name="Is_Holiday")


# ---------------------------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------------------------

def _upsample_daily_to_15min(series: pd.Series, df_target: pd.DataFrame) -> pd.Series:
    """Reindex a daily Series to match the 15-minute DatetimeIndex of df_target and forward-fill."""
    return series.reindex(df_target.index, method="ffill")


# ---------------------------------------------------------------------------
# 3. Feature Engineering
# ---------------------------------------------------------------------------

def engineer_features(
    df_wide: pd.DataFrame,
    df_ipto: pd.DataFrame,
    df_ttf: pd.Series,
    df_eua: pd.Series,
    df_holiday: pd.Series,
) -> pd.DataFrame:
    """
    Compute advanced financial and market features.
    Returns a DataFrame with the new columns, indexed like the inputs.
    """
    df_features = pd.DataFrame(index=df_wide.index)

    # --- 3.1 Break-Even Gas Price (Clean Spark Spread proxy) ---
    ttf = _upsample_daily_to_15min(df_ttf, df_wide)
    eua = _upsample_daily_to_15min(df_eua, df_wide)
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
        df_features["MCP_Lag_24h"] = mcp.shift(96)
        df_features["MCP_Lag_168h"] = mcp.shift(672)
        df_features["MCP_Rolling_24h_Avg"] = mcp.rolling(window=96, min_periods=1).mean()
    else:
        print("Warning: MCP not found in df_wide; skipping lag/rolling features.")
        df_features["MCP_Lag_24h"] = np.nan
        df_features["MCP_Lag_168h"] = np.nan
        df_features["MCP_Rolling_24h_Avg"] = np.nan

    # --- 3.4 Daily Battery Spread ---
    if "MCP" in df_wide.columns:
        daily_max = df_wide["MCP"].groupby(df_wide.index.date).transform("max")
        daily_min = df_wide["MCP"].groupby(df_wide.index.date).transform("min")
        df_features["Daily_Battery_Spread"] = daily_max - daily_min
    else:
        df_features["Daily_Battery_Spread"] = np.nan

    # --- 3.5 Greek Holiday Indicator ---
    df_features["Is_Holiday"] = _upsample_daily_to_15min(df_holiday, df_wide)

    return df_features


# ---------------------------------------------------------------------------
# 4. Master Merge
# ---------------------------------------------------------------------------

def build_master_dataset(
    df_wide: pd.DataFrame,
    df_ipto: pd.DataFrame,
    df_weather_master: pd.DataFrame,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Concatenate all DataFrames and drop rows with NaNs introduced by lagging.

    Parameters
    ----------
    df_wide : pd.DataFrame
        Hellenic Energy Exchange DAM volumes & MCP.
    df_ipto : pd.DataFrame
        ENTSO-E Load, Wind, Solar, Residual_Load forecasts.
    df_weather_master : pd.DataFrame
        Open-Meteo weather + Cooling/Heating demand.
    start_date, end_date : pd.Timestamp, optional
        Time window for fetching financial/calendar data.  If None, inferred
        from ``df_wide.index``.

    Returns
    -------
    pd.DataFrame
        Master training dataset with engineered features.
    """
    print("\nMerging datasets into master training frame ...")

    if start_date is None:
        start_date = df_wide.index.min()
    if end_date is None:
        end_date = df_wide.index.max()

    # Align all inputs to the intersection of their indices
    common_idx = (
        df_wide.index
        .intersection(df_ipto.index)
        .intersection(df_weather_master.index)
    )
    if len(common_idx) == 0:
        raise ValueError("No overlapping timestamps between the three source DataFrames.")

    df_w = df_wide.loc[common_idx].copy()
    df_i = df_ipto.loc[common_idx].copy()
    df_m = df_weather_master.loc[common_idx].copy()

    # Fetch / build daily financial / calendar series
    print("\n[1/4] Fetching / mocking daily financial data ...")
    df_ttf = fetch_ttf_gas(start_date, end_date)
    df_eua = fetch_eua_carbon(start_date, end_date)
    df_holiday = build_greek_holiday_series(start_date, end_date)

    # Build engineered features
    print("\n[2/4] Engineering features ...")
    df_f = engineer_features(df_w, df_i, df_ttf, df_eua, df_holiday)

    # Concatenate side-by-side
    print("\n[3/4] Building master dataset ...")
    df_master = pd.concat([df_w, df_i, df_m, df_f], axis=1)

    # Drop NaNs caused by the 7-day lag (and any other incomplete rows)
    df_master = df_master.dropna()

    # Persist
    print("\n[4/4] Validation")
    print("-" * 70)
    print(f"Final shape : {df_master.shape}")
    print(f"Index range : {df_master.index.min()} -> {df_master.index.max()}")
    print(f"Index freq  : {pd.infer_freq(df_master.index)}")

    return df_master
