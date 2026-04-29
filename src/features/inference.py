"""
Feature engineering specifically for daily inference.

Takes a combined DataFrame of historical context + tomorrow's raw data
and applies the same preprocessing, interaction, and advanced feature
engineering used during training.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.preprocessing import add_cyclical_time_features, lag_volume_columns
from src.features.interactions import add_interaction_features
from src.features.advanced import engineer_advanced_features


def engineer_inference_features(
    combined: pd.DataFrame,
    target_date,
) -> pd.DataFrame:
    """
    Recompute all time-dependent features on a combined historical +
    tomorrow DataFrame, then return only tomorrow's rows.

    Parameters
    ----------
    combined : pd.DataFrame
        Concatenation of historical engineered data (for rolling context)
        and tomorrow's raw base columns. Must include ``MCP`` (NaN for
        tomorrow), ``Temp_Athens``, ``Forecast_Solar``, ``Forecast_Wind``,
        ``Forecast_Load``, ``Break_Even_Gas_Price``, volume columns, etc.
    target_date : date or pd.Timestamp
        The forecast target date — used for calendar-specific features.

    Returns
    -------
    pd.DataFrame
        Only the rows belonging to *target_date*, with all engineered
        features, and identifier columns ``MCP``, ``DDAY``, ``DELIVERY_MTU``
        dropped.
    """
    df = combined.copy().sort_index()
    idx = df.index

    # --- Cyclical time ---
    df = add_cyclical_time_features(df)

    # --- Residual_Load_Ramp ---
    if "Residual_Load" in df.columns:
        df["Residual_Load_Ramp"] = df["Residual_Load"].diff(1)

    # --- MCP lags (historical MCP provides lags for tomorrow) ---
    if "MCP" in df.columns:
        df["MCP_Lag_24h"] = df["MCP"].shift(96)
        df["MCP_Lag_168h"] = df["MCP"].shift(672)
        df["MCP_Rolling_24h_Avg"] = df["MCP"].rolling(window=96, min_periods=1).mean()
        df["MCP_Rolling_Std_24h"] = df["MCP"].rolling(window=96, min_periods=1).std()

    # --- Daily battery spread (using lag) ---
    if "MCP_Lag_24h" in df.columns:
        daily_max = df["MCP_Lag_24h"].groupby(df.index.date).transform("max")
        daily_min = df["MCP_Lag_24h"].groupby(df.index.date).transform("min")
        df["Daily_Battery_Spread"] = daily_max - daily_min
        df["Daily_Peak_to_Trough_Ratio"] = np.where(
            daily_min > 0, daily_max / daily_min, daily_max - daily_min
        )

    # --- Duck curve ---
    if "Forecast_Solar" in df.columns:
        df["Solar_Crash_Velocity"] = df["Forecast_Solar"].diff(1)
    if "Forecast_Wind" in df.columns:
        df["Wind_Volatility_6h"] = df["Forecast_Wind"].rolling(window=24, min_periods=1).std()

    # --- Thermal stress ---
    if "Temp_Athens" in df.columns:
        df["Rolling_48h_Temp_Max"] = df["Temp_Athens"].rolling(window=192, min_periods=1).max()
        daily_max_temp = df["Temp_Athens"].groupby(df.index.date).max()
        above_35 = (daily_max_temp > 35).astype(int)
        groups = (above_35 != above_35.shift()).cumsum()
        consec = above_35.groupby(groups).cumsum()
        df["Consecutive_Days_Above_35C"] = (
            pd.Series(consec.values, index=pd.to_datetime(consec.index))
            .reindex(df.index.date)
            .values
        )

    # --- Calendar ---
    df["Is_August_Exodus"] = (df.index.month == 8).astype(int)

    import holidays
    gr_hols = holidays.Greece(years=target_date.year)
    df["Is_Bridge_Day"] = 0  # Simplified; full logic is in advanced.py
    # TODO: reuse engineer_advanced_features for bridge-day logic when MCP is available

    days_until_list = []
    for d in df.index.date:
        future = pd.to_datetime([h for h in gr_hols if h > d])
        if len(future):
            delta = (future[0] - pd.Timestamp(d)).days
        else:
            delta = 0
        days_until_list.append(delta)
    df["Days_Until_Next_Holiday"] = days_until_list

    # --- Interactions ---
    df = add_interaction_features(df)

    # --- Extract tomorrow ---
    tomorrow = df.loc[df.index.date == target_date].copy()

    # Drop non-feature columns
    for col in ("MCP", "DDAY", "DELIVERY_MTU"):
        if col in tomorrow.columns:
            tomorrow = tomorrow.drop(columns=[col])

    return tomorrow
