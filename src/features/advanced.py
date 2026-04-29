"""
Engineer highly advanced, non-linear features representing human behaviour,
grid stress, and market momentum.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def engineer_advanced_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Append advanced calendar, thermal stress, duck-curve, and volatility
    features to *df*.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain ``Is_Holiday``, ``Temp_Athens``, ``Forecast_Solar``,
        ``Forecast_Wind``, ``MCP_Lag_24h``.

    Returns
    -------
    pd.DataFrame
        DataFrame with additional columns and NaN rows dropped.
    """
    print("=" * 70)
    print("Advanced Non-Linear Feature Engineering")
    print(f"Input shape: {df.shape}")
    print("=" * 70)

    df = df.copy()

    # -----------------------------------------------------------------------
    # Helper: extract a daily view of the holiday flag
    # -----------------------------------------------------------------------
    daily_holiday = (
        df["Is_Holiday"]
        .groupby(df.index.date)
        .first()
    )
    holiday_dates = pd.to_datetime(daily_holiday[daily_holiday == 1].index)
    all_dates = pd.to_datetime(daily_holiday.index)

    # -----------------------------------------------------------------------
    # Group 1: Advanced Greek Calendar & Behaviour
    # -----------------------------------------------------------------------
    print("\n[Group 1/4] Advanced Greek Calendar & Behaviour ...")

    dow = all_dates.dayofweek
    is_hol = daily_holiday.reindex(all_dates.date).fillna(0).values

    daily_hol_s = pd.Series(is_hol, index=all_dates)
    tue_is_hol = daily_hol_s.shift(-1, fill_value=0)
    thu_is_hol = daily_hol_s.shift(1, fill_value=0)

    mon_bridge = (dow == 0) & (is_hol == 0) & (tue_is_hol.values == 1)
    fri_bridge = (dow == 4) & (is_hol == 0) & (thu_is_hol.values == 1)

    bridge_map = pd.Series((mon_bridge | fri_bridge).astype(int), index=all_dates)
    df["Is_Bridge_Day"] = bridge_map.reindex(df.index.date).values

    df["Is_August_Exodus"] = (df.index.month == 8).astype(int)

    holiday_arr = holiday_dates.to_numpy()
    date_arr = all_dates.to_numpy()

    days_until_list = []
    for d in date_arr:
        future = holiday_arr[holiday_arr > d]
        if len(future):
            delta = (future[0] - d).astype("timedelta64[D]").astype(int)
        else:
            delta = 0
        days_until_list.append(delta)

    days_until_map = pd.Series(days_until_list, index=all_dates)
    df["Days_Until_Next_Holiday"] = days_until_map.reindex(df.index.date).values

    print("  -> Is_Bridge_Day, Is_August_Exodus, Days_Until_Next_Holiday")

    # -----------------------------------------------------------------------
    # Group 2: Cumulative Thermal Stress
    # -----------------------------------------------------------------------
    print("\n[Group 2/4] Cumulative Thermal Stress ...")

    df["Rolling_48h_Temp_Max"] = (
        df["Temp_Athens"]
        .rolling(window=192, min_periods=1)
        .max()
    )

    daily_max_temp = (
        df["Temp_Athens"]
        .groupby(df.index.date)
        .max()
    )

    above_35 = (daily_max_temp > 35).astype(int)
    groups = (above_35 != above_35.shift()).cumsum()
    consecutive_days = above_35.groupby(groups).cumsum()

    df["Consecutive_Days_Above_35C"] = (
        pd.Series(consecutive_days.values, index=pd.to_datetime(consecutive_days.index))
        .reindex(df.index.date)
        .values
    )

    print("  -> Rolling_48h_Temp_Max, Consecutive_Days_Above_35C")

    # -----------------------------------------------------------------------
    # Group 3: The "Duck Curve" Derivatives
    # -----------------------------------------------------------------------
    print("\n[Group 3/4] Duck Curve Derivatives ...")

    df["Solar_Crash_Velocity"] = df["Forecast_Solar"].diff(1)

    df["Wind_Volatility_6h"] = (
        df["Forecast_Wind"]
        .rolling(window=24, min_periods=1)
        .std()
    )

    print("  -> Solar_Crash_Velocity, Wind_Volatility_6h")

    # -----------------------------------------------------------------------
    # Group 4: Market Volatility & Momentum
    # -----------------------------------------------------------------------
    print("\n[Group 4/4] Market Volatility & Momentum ...")

    df["MCP_Rolling_Std_24h"] = (
        df["MCP_Lag_24h"]
        .rolling(window=96, min_periods=1)
        .std()
    )

    daily_max_lag = (
        df["MCP_Lag_24h"]
        .groupby(df.index.date)
        .transform("max")
    )
    daily_min_lag = (
        df["MCP_Lag_24h"]
        .groupby(df.index.date)
        .transform("min")
    )
    df["Daily_Peak_to_Trough_Ratio"] = np.where(
        daily_min_lag > 0,
        daily_max_lag / daily_min_lag,
        daily_max_lag - daily_min_lag,
    )

    print("  -> MCP_Rolling_Std_24h, Daily_Peak_to_Trough_Ratio")

    # -----------------------------------------------------------------------
    # Final Cleanup
    # -----------------------------------------------------------------------
    print("\n[Cleanup] Dropping rows with NaN values introduced by diffs/shifts ...")
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
