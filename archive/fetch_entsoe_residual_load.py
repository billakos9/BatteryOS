#!/usr/bin/env python3
"""
Production-ready script to fetch ENTSO-E Day-Ahead Market forecasts for Greece
and engineer a Residual Load feature.

Dependencies:
    pip install pandas entsoe-py python-dotenv

Environment:
    ENTSOE_API_KEY must be set in your environment or a .env file.
"""

import os
import sys
from datetime import timedelta

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

# ---------------------------------------------------------------------------
# 1. Load API key
# ---------------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("ENTSOE_API_KEY")
if not API_KEY:
    raise ValueError(
        "ENTSOE_API_KEY environment variable is not set. "
        "Please export it or add it to a .env file."
    )

# ---------------------------------------------------------------------------
# 2. Configuration
# ---------------------------------------------------------------------------
COUNTRY_CODE = "GR"
TIMEZONE = "Europe/Athens"

# Time horizon: Jan 1, 2023 up to the current moment (timezone-aware)
START = pd.Timestamp("2023-01-01", tz=TIMEZONE)
END = pd.Timestamp.now(tz=TIMEZONE)

client = EntsoePandasClient(api_key=API_KEY)


# ---------------------------------------------------------------------------
# 3. Helper functions
# ---------------------------------------------------------------------------
def fetch_entsoe_data(query_func, dataset_name, **kwargs):
    """
    Wrapper around entsoe-py queries with error handling.
    The library internally chunks large date ranges via @year_limited.
    """
    print(f"Fetching {dataset_name} ...")
    try:
        result = query_func(
            country_code=COUNTRY_CODE, start=START, end=END, **kwargs
        )

        if result is None or (hasattr(result, "empty") and result.empty):
            print(f"  Warning: No data returned for {dataset_name}.")
            return None

        # Normalise to DataFrame (generation forecast comes back as a Series)
        if isinstance(result, pd.Series):
            result = result.to_frame(name=dataset_name)

        # Ensure the index is timezone-aware in Europe/Athens
        if result.index.tz is None:
            result = result.tz_localize(TIMEZONE)
        else:
            result = result.tz_convert(TIMEZONE)

        print(f"  -> Retrieved {len(result):,} rows")
        return result

    except Exception as exc:
        print(f"  Error fetching {dataset_name}: {exc}")
        return None


def normalise_to_15min(df):
    """
    Resample a DataFrame to a strict 15-minute DatetimeIndex.
    Forward-fill is used because ENTSO-E forecasts are step-wise constant
    over their native resolution (hourly or 30-minute).
    """
    if df is None or df.empty:
        return df
    return df.resample("15min").ffill()


# ---------------------------------------------------------------------------
# 4. Fetch raw datasets
# ---------------------------------------------------------------------------
df_load_raw = fetch_entsoe_data(
    client.query_load_forecast, "Day-Ahead Load Forecast"
)
df_renew_raw = fetch_entsoe_data(
    client.query_wind_and_solar_forecast, "Day-Ahead Wind & Solar Forecast"
)
df_gen_raw = fetch_entsoe_data(
    client.query_generation_forecast, "Day-Ahead Generation Forecast"
)

# ---------------------------------------------------------------------------
# 5. Normalise frequencies to 15-minute intervals
# ---------------------------------------------------------------------------
df_load = normalise_to_15min(df_load_raw)
df_renew = normalise_to_15min(df_renew_raw)
df_gen = normalise_to_15min(df_gen_raw)

# ---------------------------------------------------------------------------
# 6. Merge into a single master DataFrame
# ---------------------------------------------------------------------------
parts = [p for p in (df_load, df_renew, df_gen) if p is not None]
if not parts:
    print("No datasets could be retrieved. Exiting.")
    sys.exit(1)

df_forecasts = pd.concat(parts, axis=1)

# ---------------------------------------------------------------------------
# 7. Rename columns to clean, readable names
# ---------------------------------------------------------------------------
col_rename = {}
for col in df_forecasts.columns:
    lower = col.lower()
    if "load" in lower and "forecast" in lower:
        col_rename[col] = "Forecast_Load"
    elif col == "Solar":
        col_rename[col] = "Forecast_Solar"
    elif col == "Wind Onshore":
        col_rename[col] = "Forecast_Wind"
    elif col in ("Actual Aggregated", "Day-Ahead Generation Forecast"):
        col_rename[col] = "Forecast_Aggregated_Gen"
    elif "gen" in lower:
        col_rename[col] = "Forecast_Aggregated_Gen"

# Only rename columns that actually exist
col_rename = {k: v for k, v in col_rename.items() if k in df_forecasts.columns}
df_forecasts = df_forecasts.rename(columns=col_rename)

# ---------------------------------------------------------------------------
# 8. Feature Engineering
# ---------------------------------------------------------------------------
# Total_RES = Solar + Wind Onshore (NaN -> 0 before summing)
solar = df_forecasts.get("Forecast_Solar", pd.Series(0.0, index=df_forecasts.index))
wind = df_forecasts.get("Forecast_Wind", pd.Series(0.0, index=df_forecasts.index))

df_forecasts["Total_RES"] = solar.fillna(0.0) + wind.fillna(0.0)

# Residual_Load = Load Forecast - Total_RES
if "Forecast_Load" in df_forecasts.columns:
    df_forecasts["Residual_Load"] = (
        df_forecasts["Forecast_Load"].fillna(0.0) - df_forecasts["Total_RES"]
    )
else:
    df_forecasts["Residual_Load"] = pd.NA
    print("Warning: Forecast_Load missing; Residual_Load set to NA.")

# ---------------------------------------------------------------------------
# 9. Final column ordering
# ---------------------------------------------------------------------------
desired_order = [
    "Forecast_Load",
    "Forecast_Solar",
    "Forecast_Wind",
    "Forecast_Aggregated_Gen",
    "Total_RES",
    "Residual_Load",
]
final_cols = [c for c in desired_order if c in df_forecasts.columns]
df_forecasts = df_forecasts[final_cols]

# ---------------------------------------------------------------------------
# 10. Output
# ---------------------------------------------------------------------------
print(f"\nFinal DataFrame shape : {df_forecasts.shape}")
print(f"Index range           : {df_forecasts.index.min()} -> {df_forecasts.index.max()}")
print(f"Columns               : {list(df_forecasts.columns)}")
print("\nPreview (first 8 rows):")
print(df_forecasts.head(8).to_string())

# Persist to disk
output_csv = "entsoe_greece_dam_forecasts.csv"

df_forecasts.to_csv(output_csv)
print(f"\nSaved CSV: {output_csv}")
