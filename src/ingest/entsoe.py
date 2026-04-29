"""
ENTSO-E data ingestion for Greece.

Fetches day-ahead load, wind/solar, and generation forecasts from the
ENTSO-E Transparency Platform via ``entsoe-py``.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

load_dotenv()

COUNTRY_CODE = "GR"
TIMEZONE = "Europe/Athens"


def get_client() -> EntsoePandasClient:
    """Return an authenticated ENTSO-E client."""
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        raise ValueError("ENTSOE_API_KEY not set in environment or .env file.")
    return EntsoePandasClient(api_key=api_key)


def _fetch_entsoe_data(
    client: EntsoePandasClient,
    query_func,
    dataset_name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    **kwargs,
) -> pd.DataFrame | None:
    """Wrapper around entsoe-py queries with error handling."""
    print(f"Fetching {dataset_name} ...")
    try:
        result = query_func(country_code=COUNTRY_CODE, start=start, end=end, **kwargs)

        if result is None or (hasattr(result, "empty") and result.empty):
            print(f"  Warning: No data returned for {dataset_name}.")
            return None

        if isinstance(result, pd.Series):
            result = result.to_frame(name=dataset_name)

        if result.index.tz is None:
            result = result.tz_localize(TIMEZONE)
        else:
            result = result.tz_convert(TIMEZONE)

        print(f"  -> Retrieved {len(result):,} rows")
        return result
    except Exception as exc:
        print(f"  Error fetching {dataset_name}: {exc}")
        return None


def normalise_to_15min(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Resample a DataFrame to a strict 15-minute DatetimeIndex (forward-fill)."""
    if df is None or df.empty:
        return df
    return df.resample("15min").ffill()


def fetch_entsoe_forecasts(
    start: pd.Timestamp | str,
    end: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """
    Fetch and merge ENTSO-E day-ahead forecasts for Greece.

    Parameters
    ----------
    start : pd.Timestamp or str
        Start of the date range (inclusive).
    end : pd.Timestamp or str, optional
        End of the date range (exclusive).  Defaults to *start* + 1 day.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``Forecast_Load``, ``Forecast_Solar``,
        ``Forecast_Wind``, ``Forecast_Aggregated_Gen``, ``Total_RES``,
        ``Residual_Load``, indexed at 15-minute frequency in Europe/Athens.
    """
    client = get_client()

    if isinstance(start, str):
        start = pd.Timestamp(start, tz=TIMEZONE)
    if end is None:
        end = start + timedelta(days=1)
    elif isinstance(end, str):
        end = pd.Timestamp(end, tz=TIMEZONE)

    df_load_raw = _fetch_entsoe_data(
        client, client.query_load_forecast, "Day-Ahead Load Forecast", start, end
    )
    df_renew_raw = _fetch_entsoe_data(
        client, client.query_wind_and_solar_forecast, "Day-Ahead Wind & Solar Forecast", start, end
    )
    df_gen_raw = _fetch_entsoe_data(
        client, client.query_generation_forecast, "Day-Ahead Generation Forecast", start, end
    )

    df_load = normalise_to_15min(df_load_raw)
    df_renew = normalise_to_15min(df_renew_raw)
    df_gen = normalise_to_15min(df_gen_raw)

    parts = [p for p in (df_load, df_renew, df_gen) if p is not None]
    if not parts:
        raise RuntimeError("No ENTSO-E datasets could be retrieved.")

    df_forecasts = pd.concat(parts, axis=1)

    # Rename columns
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

    col_rename = {k: v for k, v in col_rename.items() if k in df_forecasts.columns}
    df_forecasts = df_forecasts.rename(columns=col_rename)

    # Feature engineering
    solar = df_forecasts.get("Forecast_Solar", pd.Series(0.0, index=df_forecasts.index))
    wind = df_forecasts.get("Forecast_Wind", pd.Series(0.0, index=df_forecasts.index))
    df_forecasts["Total_RES"] = solar.fillna(0.0) + wind.fillna(0.0)

    if "Forecast_Load" in df_forecasts.columns:
        df_forecasts["Residual_Load"] = (
            df_forecasts["Forecast_Load"].fillna(0.0) - df_forecasts["Total_RES"]
        )
    else:
        df_forecasts["Residual_Load"] = pd.NA
        print("Warning: Forecast_Load missing; Residual_Load set to NA.")

    desired_order = [
        "Forecast_Load",
        "Forecast_Solar",
        "Forecast_Wind",
        "Forecast_Aggregated_Gen",
        "Total_RES",
        "Residual_Load",
    ]
    final_cols = [c for c in desired_order if c in df_forecasts.columns]
    return df_forecasts[final_cols]
