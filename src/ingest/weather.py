"""
Open-Meteo weather data ingestion for Greek geographic hubs.

Fetches historical weather from the Archive API and forecasts from the
Forecast API, then processes them to 15-minute frequency.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import requests

TIMEZONE = "Europe/Athens"

HUBS = {
    "Athens": {"lat": 37.98, "lon": 23.72},
    "Thessaly": {"lat": 39.63, "lon": 22.41},
    "Evia": {"lat": 38.05, "lon": 24.45},
}

WEATHER_VARS = [
    "temperature_2m",
    "shortwave_radiation",
    "wind_speed_100m",
]


def fetch_weather_hub(
    name: str,
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    api_url: str = "https://archive-api.open-meteo.com/v1/archive",
) -> pd.DataFrame | None:
    """
    Query the Open-Meteo API for a single geographic hub.
    Returns a DataFrame indexed by UTC datetime, or None on failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(WEATHER_VARS),
        "timezone": "UTC",
    }

    print(f"Fetching {name} (lat={lat}, lon={lon}) ...")
    try:
        resp = requests.get(api_url, params=params, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Error fetching {name}: {exc}")
        return None

    data = resp.json().get("hourly")
    if data is None:
        print(f"  Warning: No 'hourly' data in response for {name}.")
        return None

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(data["time"]),
            "temperature_2m": data.get("temperature_2m"),
            "shortwave_radiation": data.get("shortwave_radiation"),
            "wind_speed_100m": data.get("wind_speed_100m"),
        }
    ).set_index("timestamp")
    df.index = df.index.tz_localize("UTC")
    print(f"  -> Retrieved {len(df):,} hourly rows")
    return df


def fetch_weather_forecast(
    name: str,
    lat: float,
    lon: float,
    target_date: str,
    api_url: str = "https://api.open-meteo.com/v1/forecast",
) -> pd.DataFrame | None:
    """
    Fetch hourly forecast from Open-Meteo for a single day.
    Returns a DataFrame indexed by local time and interpolated to 15 min.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(WEATHER_VARS),
        "start_date": target_date,
        "end_date": target_date,
        "timezone": "auto",
    }
    try:
        resp = requests.get(api_url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()["hourly"]
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(data["time"]),
                "temperature_2m": data.get("temperature_2m"),
                "shortwave_radiation": data.get("shortwave_radiation"),
                "wind_speed_100m": data.get("wind_speed_100m"),
            }
        ).set_index("timestamp")
        df = df.resample("15min").interpolate(method="linear")
        return df
    except Exception as exc:
        print(f"  Error fetching forecast for {name}: {exc}")
        return None


def process_hub(df: pd.DataFrame | None, name: str) -> pd.DataFrame | None:
    """
    Convert UTC → Europe/Athens, upsample hourly → 15-min with linear
    interpolation, and prefix column names with the hub name.
    """
    if df is None or df.empty:
        return None

    df = df.tz_convert(TIMEZONE)
    df = df.resample("15min").interpolate(method="linear")

    prefix_map = {
        "temperature_2m": f"Temp_{name}",
        "shortwave_radiation": f"Solar_Rad_{name}",
        "wind_speed_100m": f"Wind_Spd_{name}",
    }
    return df.rename(columns=prefix_map)


def engineer_athens_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add Cooling_Demand_Athens and Heating_Demand_Athens based on the
    2-meter temperature at the Athens hub.
    """
    df = df.copy()
    if "Temp_Athens" not in df.columns:
        print("Warning: Temp_Athens not found; skipping feature engineering.")
        return df

    df["Cooling_Demand_Athens"] = (df["Temp_Athens"] - 22.0).clip(lower=0.0)
    df["Heating_Demand_Athens"] = (18.0 - df["Temp_Athens"]).clip(lower=0.0)
    return df


def fetch_all_weather(
    start_date: str = "2023-01-01",
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch and merge historical weather data for all configured hubs.

    Returns
    -------
    pd.DataFrame
        15-minute DataFrame with prefixed columns for each hub plus
        Athens-specific demand features.
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    print(f"Open-Meteo Weather Fetch | {start_date} → {end_date}")
    print("=" * 60)

    processed_frames = []
    for name, coords in HUBS.items():
        raw = fetch_weather_hub(name, coords["lat"], coords["lon"], start_date, end_date)
        processed = process_hub(raw, name)
        if processed is not None:
            processed_frames.append(processed)
        print()

    if not processed_frames:
        raise RuntimeError("No weather data could be retrieved.")

    df_weather_master = pd.concat(processed_frames, axis=1)
    df_weather_master = engineer_athens_features(df_weather_master)

    print("=" * 60)
    print(f"Final DataFrame shape : {df_weather_master.shape}")
    print(f"Columns               : {list(df_weather_master.columns)}")
    return df_weather_master
