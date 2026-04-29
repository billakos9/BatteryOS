#!/usr/bin/env python3
"""
Production-ready script to fetch historical weather data from the Open-Meteo
Archive API for three Greek geographic hubs, process it for ML, and engineer
temperature-demand features.

Dependencies:
    pip install pandas requests
"""

import sys
from datetime import datetime

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# 1. Configuration
# ---------------------------------------------------------------------------
API_URL = "https://archive-api.open-meteo.com/v1/archive"

# Time horizon: Jan 1, 2023 to current date (inclusive)
START_DATE = "2023-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")

# Geographic hubs
HUBS = {
    "Athens": {"lat": 37.98, "lon": 23.72},
    "Thessaly": {"lat": 39.63, "lon": 22.41},
    "Evia": {"lat": 38.05, "lon": 24.45},
}

# Weather variables to fetch
WEATHER_VARS = [
    "temperature_2m",
    "shortwave_radiation",
    "wind_speed_100m",
]

# Target timezone for Greek energy market alignment
TARGET_TZ = "Europe/Athens"


# ---------------------------------------------------------------------------
# 2. Data extraction
# ---------------------------------------------------------------------------
def fetch_weather_hub(name: str, lat: float, lon: float) -> pd.DataFrame | None:
    """
    Query the Open-Meteo Archive API for a single geographic hub.
    Returns a DataFrame indexed by UTC datetime, or None on failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": ",".join(WEATHER_VARS),
        "timezone": "UTC",  # Request in UTC for clean alignment
    }

    print(f"Fetching {name} (lat={lat}, lon={lon}) ...")

    try:
        resp = requests.get(API_URL, params=params, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Error fetching {name}: {exc}")
        return None

    data = resp.json()
    hourly = data.get("hourly")
    if hourly is None:
        print(f"  Warning: No 'hourly' data in response for {name}.")
        return None

    # Build DataFrame from the JSON lists
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(hourly["time"]),
            "temperature_2m": hourly.get("temperature_2m"),
            "shortwave_radiation": hourly.get("shortwave_radiation"),
            "wind_speed_100m": hourly.get("wind_speed_100m"),
        }
    )
    df = df.set_index("timestamp")
    df.index = df.index.tz_localize("UTC")

    print(f"  -> Retrieved {len(df):,} hourly rows")
    return df


# ---------------------------------------------------------------------------
# 3. Processing pipeline
# ---------------------------------------------------------------------------
def process_hub(df: pd.DataFrame | None, name: str) -> pd.DataFrame | None:
    """
    Convert UTC → Europe/Athens, upsample hourly → 15-min with linear
    interpolation, and prefix column names with the hub name.
    """
    if df is None or df.empty:
        return None

    # Convert from UTC to Europe/Athens (handles DST automatically)
    df = df.tz_convert(TARGET_TZ)

    # Upsample from hourly to 15-minute intervals
    df = df.resample("15min").interpolate(method="linear")

    # Prefix columns to avoid collisions during merge
    prefix_map = {
        "temperature_2m": f"Temp_{name}",
        "shortwave_radiation": f"Solar_Rad_{name}",
        "wind_speed_100m": f"Wind_Spd_{name}",
    }
    df = df.rename(columns=prefix_map)

    return df


# ---------------------------------------------------------------------------
# 4. Feature engineering (Athens only)
# ---------------------------------------------------------------------------
def engineer_athens_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add Cooling_Demand_Athens and Heating_Demand_Athens based on the
    2-meter temperature at the Athens hub.
    """
    temp_col = "Temp_Athens"
    if temp_col not in df.columns:
        print("Warning: Temp_Athens not found; skipping feature engineering.")
        return df

    # Cooling demand: positive when temperature exceeds 22 °C
    df["Cooling_Demand_Athens"] = (df[temp_col] - 22.0).clip(lower=0.0)

    # Heating demand: positive when temperature drops below 18 °C
    df["Heating_Demand_Athens"] = (18.0 - df[temp_col]).clip(lower=0.0)

    return df


# ---------------------------------------------------------------------------
# 5. Main orchestration
# ---------------------------------------------------------------------------
def main():
    print(f"Open-Meteo Weather Fetch | {START_DATE} → {END_DATE}")
    print("=" * 60)

    processed_frames = []

    for name, coords in HUBS.items():
        raw = fetch_weather_hub(name, coords["lat"], coords["lon"])
        processed = process_hub(raw, name)
        if processed is not None:
            processed_frames.append(processed)
        print()

    if not processed_frames:
        print("No weather data could be retrieved. Exiting.")
        sys.exit(1)

    # Merge all hubs on the 15-minute Europe/Athens DatetimeIndex
    df_weather_master = pd.concat(processed_frames, axis=1)

    # Engineer Athens-specific temperature-demand features
    df_weather_master = engineer_athens_features(df_weather_master)

    # -----------------------------------------------------------------------
    # 6. Output
    # -----------------------------------------------------------------------
    print("=" * 60)
    print(f"Final DataFrame shape : {df_weather_master.shape}")
    print(f"Index range           : {df_weather_master.index.min()} -> {df_weather_master.index.max()}")
    print(f"Columns               : {list(df_weather_master.columns)}")
    print("\nPreview (first 8 rows):")
    print(df_weather_master.head(8).to_string())

    output_csv = "openmeteo_weather_master.csv"
    df_weather_master.to_csv(output_csv)
    print(f"\nSaved CSV: {output_csv}")


if __name__ == "__main__":
    main()
