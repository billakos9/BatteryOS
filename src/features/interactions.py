"""Interaction feature engineering for electricity price forecasting."""

import pandas as pd


def add_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add non-linear interaction terms to the master DataFrame.
    Mutates in-place and returns the DataFrame.
    """
    df = df.copy()

    # 1. Load × Cost interaction: scarcity amplifies marginal cost effect
    if "Residual_Load" in df.columns and "Break_Even_Gas_Price" in df.columns:
        df["Load_Cost_Interaction"] = (
            df["Residual_Load"] * df["Break_Even_Gas_Price"]
        )

    # 2. Solar × Hour interaction: solar effect is only relevant midday
    if "Forecast_Solar" in df.columns and "Hour_Sin" in df.columns:
        df["Solar_Hour_Interaction"] = df["Forecast_Solar"] * df["Hour_Sin"]

    # 3. Temperature × August interaction: cooling demand differs in August
    if "Temp_Athens" in df.columns and "Is_August_Exodus" in df.columns:
        df["Temp_August_Interaction"] = (
            df["Temp_Athens"] * df["Is_August_Exodus"]
        )

    return df
