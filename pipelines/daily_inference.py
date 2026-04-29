#!/usr/bin/env python3
"""
Daily inference pipeline for Greek DAM MCP forecasting.

Designed to run as a cron job every morning (~9:00 AM Europe/Athens).
Fetches day-ahead forecasts for TOMORROW, engineers features using
historical lags, loads pre-trained LightGBM models, and predicts
p10/p50/p90 MCP for the next day.

Usage:
    cd /home/dimit/BatteryOS
    source .venv/bin/activate
    python pipelines/daily_inference.py
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import holidays
import joblib
import numpy as np
import pandas as pd

# Resolve repo root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from dotenv import load_dotenv

from src.features.inference import engineer_inference_features
from src.ingest.entsoe import fetch_entsoe_forecasts
from src.ingest.weather import fetch_weather_forecast

load_dotenv()

TIMEZONE = "Europe/Athens"

print("=" * 70)
print("Daily Inference Pipeline")
print(f"Now (local) : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

# ---------------------------------------------------------------------------
# 0. Determine dates
# ---------------------------------------------------------------------------
print("\n[0/8] Determining target date ...")

DATA_PROCESSED = REPO_ROOT / "data" / "processed"

hist_path = DATA_PROCESSED / "df_master_ml_ready_advanced.csv"
if not hist_path.exists():
    print(f"  ERROR: Historical data not found at {hist_path}")
    sys.exit(1)

hist_df = pd.read_csv(hist_path, index_col=0)
hist_df.index = pd.to_datetime(hist_df.index, utc=True).tz_convert(TIMEZONE)
last_hist_date = hist_df.index.max().date()

target_date = last_hist_date + timedelta(days=1)
print(f"  Last historical date : {last_hist_date}")
print(f"  Target forecast date : {target_date}")

# ---------------------------------------------------------------------------
# 1. Fetch ENTSO-E day-ahead forecasts for target date
# ---------------------------------------------------------------------------
print(f"\n[1/8] Fetching ENTSO-E day-ahead forecasts for {target_date} ...")

try:
    tomorrow_base = fetch_entsoe_forecasts(
        start=pd.Timestamp(target_date, tz=TIMEZONE),
        end=pd.Timestamp(target_date + timedelta(days=1), tz=TIMEZONE),
    )
    # Upsample to 15 minutes (forward-fill)
    tomorrow_base = tomorrow_base.resample("15min").ffill()
    print(f"  -> Fetched {len(tomorrow_base)} intervals")
except Exception as exc:
    print(f"  WARNING: ENTSO-E fetch failed ({exc}). Using mock forecasts.")
    idx = pd.date_range(
        start=pd.Timestamp(target_date, tz=TIMEZONE), periods=96, freq="15min"
    )
    tomorrow_base = pd.DataFrame(index=idx)
    tomorrow_base["Forecast_Load"] = 4000.0
    tomorrow_base["Forecast_Solar"] = 0.0
    tomorrow_base["Forecast_Wind"] = 300.0
    tomorrow_base["Forecast_Aggregated_Gen"] = 3500.0

# ---------------------------------------------------------------------------
# 2. Fetch weather forecast for target date
# ---------------------------------------------------------------------------
print(f"\n[2/8] Fetching weather forecast for {target_date} ...")

try:
    weather_athens = fetch_weather_forecast("Athens", 37.98, 23.72, str(target_date))
    weather_thessaly = fetch_weather_forecast("Thessaly", 39.63, 22.41, str(target_date))
    weather_evia = fetch_weather_forecast("Evia", 38.05, 24.45, str(target_date))

    for w in (weather_athens, weather_thessaly, weather_evia):
        if w is not None:
            w.index = w.index.tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="shift_forward")

    for prefix, w in [
        ("Athens", weather_athens),
        ("Thessaly", weather_thessaly),
        ("Evia", weather_evia),
    ]:
        if w is not None:
            tomorrow_base[f"Temp_{prefix}"] = w["temperature_2m"].reindex(tomorrow_base.index).values
            tomorrow_base[f"Solar_Rad_{prefix}"] = w["shortwave_radiation"].reindex(tomorrow_base.index).values
            tomorrow_base[f"Wind_Spd_{prefix}"] = w["wind_speed_100m"].reindex(tomorrow_base.index).values

    print(f"  -> Fetched weather for 3 hubs")
except Exception as exc:
    print(f"  WARNING: Weather fetch failed ({exc}). Using mock values.")
    for col in [
        "Temp_Athens", "Solar_Rad_Athens", "Wind_Spd_Athens",
        "Temp_Thessaly", "Solar_Rad_Thessaly", "Wind_Spd_Thessaly",
        "Temp_Evia", "Solar_Rad_Evia", "Wind_Spd_Evia",
    ]:
        tomorrow_base[col] = 10.0 if "Temp" in col else (0.0 if "Solar" in col else 5.0)

# ---------------------------------------------------------------------------
# 3. Build raw columns for tomorrow
# ---------------------------------------------------------------------------
print(f"\n[3/8] Building raw feature rows for {target_date} ...")

tomorrow_base["Cooling_Demand_Athens"] = (tomorrow_base["Temp_Athens"] - 22.0).clip(lower=0.0)
tomorrow_base["Heating_Demand_Athens"] = (18.0 - tomorrow_base["Temp_Athens"]).clip(lower=0.0)

tomorrow_base["Total_RES"] = tomorrow_base["Forecast_Solar"].fillna(0) + tomorrow_base["Forecast_Wind"].fillna(0)
tomorrow_base["Residual_Load"] = tomorrow_base["Forecast_Load"] - tomorrow_base["Total_RES"]
tomorrow_base["Is_Holiday"] = int(target_date in holidays.Greece(years=target_date.year))

# Financial
try:
    import yfinance as yf
    ttf = yf.Ticker("TTF=F").history(period="5d")["Close"].iloc[-1]
    eua = yf.Ticker("CO2.L").history(period="5d")["Close"].iloc[-1]
    tomorrow_base["Break_Even_Gas_Price"] = (ttf / 0.50) + (eua * 0.20)
    print(f"  -> TTF={ttf:.2f}, EUA={eua:.2f}")
except Exception:
    last_be = hist_df["Break_Even_Gas_Price"].iloc[-1]
    tomorrow_base["Break_Even_Gas_Price"] = last_be
    print(f"  -> Using last known Break_Even={last_be:.2f}")

# Volume lags: carry forward yesterday's actuals
vol_cols = [c for c in hist_df.columns if "Vol_" in c or "Total_Domestic_Load" in c]
last_day_vols = hist_df[vol_cols].iloc[-96:]
if len(last_day_vols) == 96:
    for col in vol_cols:
        tomorrow_base[col] = last_day_vols[col].values
else:
    for col in vol_cols:
        tomorrow_base[col] = 0.0

# Placeholders that preprocessing expects
tomorrow_base["MCP"] = np.nan
tomorrow_base["DDAY"] = int(target_date.strftime("%Y%m%d"))
tomorrow_base["DELIVERY_MTU"] = tomorrow_base.index.strftime("%Y-%m-%d %H:%M:%S")

print(f"  -> Built {len(tomorrow_base)} raw rows with {len(tomorrow_base.columns)} columns")

# ---------------------------------------------------------------------------
# 4. Concatenate with historical data and re-engineer features
# ---------------------------------------------------------------------------
print(f"\n[4/8] Re-engineering features (lags, cyclical, interactions) ...")

hist_context = hist_df.iloc[-30 * 96 :].copy()
common_cols = list(set(hist_context.columns) & set(tomorrow_base.columns))
hist_subset = hist_context[common_cols].copy()
tomorrow_aligned = tomorrow_base[common_cols].copy()

combined = pd.concat([hist_subset, tomorrow_aligned])
combined = combined.sort_index()

# Use centralized inference feature engineering
tomorrow_engineered = engineer_inference_features(combined, target_date)

# Ensure same column order as training
with open(REPO_ROOT / "models" / "feature_columns.json") as f:
    feature_cols = json.load(f)

for col in feature_cols:
    if col not in tomorrow_engineered.columns:
        tomorrow_engineered[col] = 0.0

tomorrow_engineered = tomorrow_engineered[feature_cols]

print(f"  -> Tomorrow engineered: {tomorrow_engineered.shape}")

# ---------------------------------------------------------------------------
# 5. Load models and predict
# ---------------------------------------------------------------------------
print(f"\n[5/8] Loading models and predicting ...")

models_dir = REPO_ROOT / "models"
predictions = {}

for alpha in [0.10, 0.50, 0.90]:
    model_path = models_dir / f"lgbm_quantile_alpha{int(alpha*100):02d}.joblib"
    model = joblib.load(model_path)
    preds = model.predict(tomorrow_engineered)
    predictions[alpha] = preds
    print(f"  Alpha={alpha:.2f}: {preds.min():.2f} to {preds.max():.2f}")

# ---------------------------------------------------------------------------
# 6. Build output DataFrame
# ---------------------------------------------------------------------------
print(f"\n[6/8] Building prediction output ...")

result_df = pd.DataFrame(
    {
        "Pred_p10": predictions[0.10],
        "Pred_p50": predictions[0.50],
        "Pred_p90": predictions[0.90],
    },
    index=tomorrow_engineered.index,
)

# Sort quantiles to enforce monotonicity
vals = result_df[["Pred_p10", "Pred_p50", "Pred_p90"]].values.copy()
vals.sort(axis=1)
result_df["Pred_p10"], result_df["Pred_p50"], result_df["Pred_p90"] = vals[:, 0], vals[:, 1], vals[:, 2]

print(f"  -> {len(result_df)} predictions for {target_date}")

# ---------------------------------------------------------------------------
# 7. Append to daily forecasts log
# ---------------------------------------------------------------------------
print(f"\n[7/8] Saving predictions ...")

output_dir = REPO_ROOT / "outputs"
output_dir.mkdir(exist_ok=True)
logs_dir = REPO_ROOT / "logs"
logs_dir.mkdir(exist_ok=True)

daily_log = output_dir / "daily_forecasts.csv"
if daily_log.exists():
    existing = pd.read_csv(daily_log, index_col=0, parse_dates=True)
    existing.index = existing.index.tz_convert(TIMEZONE)
    existing = existing[existing.index.date != target_date]
    combined_log = pd.concat([existing, result_df])
else:
    combined_log = result_df

combined_log.to_csv(daily_log)
print(f"  -> Saved: {daily_log}")

dated_path = output_dir / f"forecast_{target_date}.csv"
result_df.to_csv(dated_path)
print(f"  -> Saved: {dated_path}")

# ---------------------------------------------------------------------------
# 8. Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("DAILY INFERENCE COMPLETE")
print("=" * 70)
print(f"Target date      : {target_date}")
print(f"Intervals        : {len(result_df)}")
print(f"p50 range        : {result_df['Pred_p50'].min():.2f} - {result_df['Pred_p50'].max():.2f} €/MWh")
print(f"p10-p90 spread   : {(result_df['Pred_p90'] - result_df['Pred_p10']).mean():.2f} €/MWh (avg)")
print(f"\nFiles:")
print(f"  Daily log : {daily_log}")
print(f"  Dated file: {dated_path}")
print("\nTo schedule as a cron job, run:")
print("  bash scripts/setup_cron.sh")
