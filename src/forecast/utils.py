"""Forecasting utilities — quantile post-processing and calibration."""

import numpy as np
import pandas as pd


def sort_quantiles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enforce monotonicity: Pred_p10 <= Pred_p50 <= Pred_p90.
    Performs row-wise sorting of the three quantile columns.
    Mutates and returns the DataFrame.
    """
    df = df.copy()
    q_cols = ["Pred_p10", "Pred_p50", "Pred_p90"]
    missing = [c for c in q_cols if c not in df.columns]
    if missing:
        raise KeyError(f"Missing quantile columns: {missing}")

    vals = df[q_cols].values.copy()
    vals.sort(axis=1)
    df["Pred_p10"], df["Pred_p50"], df["Pred_p90"] = vals[:, 0], vals[:, 1], vals[:, 2]

    violations = (df["Pred_p10"] > df["Pred_p50"]).sum() + (
        df["Pred_p50"] > df["Pred_p90"]
    ).sum()
    if violations == 0:
        print("  Quantiles are monotonic (no crossings).")
    else:
        print(f"  Warning: {violations} crossing violations remain after sorting.")
    return df
