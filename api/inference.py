"""
Re-usable inference engine for the BatteryOS API.

Encapsulates the core prediction logic from pipelines/daily_inference.py
so it can be called both from the cron pipeline and from the API endpoint.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import holidays
import joblib
import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv
from src.features.inference import engineer_inference_features
from src.ingest.entsoe import fetch_entsoe_forecasts
from src.ingest.weather import fetch_weather_forecast

load_dotenv()

TIMEZONE = "Europe/Athens"


def run_inference(target_date: date | None = None) -> dict[str, Any]:
    """
    Run the full daily inference pipeline and return a forecast payload.

    Parameters
    ----------
    target_date
        The delivery day to forecast. If None, defaults to tomorrow
        relative to the latest historical data point.

    Returns
    -------
    dict with keys: target_date, timestamps, p10, p50, p90, diagnostics, features, models
    """
    DATA_PROCESSED = ROOT / "data" / "processed"
    hist_path = DATA_PROCESSED / "df_master_ml_ready_advanced.csv"
    if not hist_path.exists():
        raise RuntimeError(f"Historical data not found at {hist_path}")

    hist_df = pd.read_csv(hist_path, index_col=0)
    hist_df.index = pd.to_datetime(hist_df.index, utc=True).tz_convert(TIMEZONE)
    last_hist_date = hist_df.index.max().date()

    if target_date is None:
        target_date = last_hist_date + timedelta(days=1)

    # ------------------------------------------------------------------
    # 1. Fetch ENTSO-E day-ahead forecasts
    # ------------------------------------------------------------------
    try:
        tomorrow_base = fetch_entsoe_forecasts(
            start=pd.Timestamp(target_date, tz=TIMEZONE),
            end=pd.Timestamp(target_date + timedelta(days=1), tz=TIMEZONE),
        )
        tomorrow_base = tomorrow_base.resample("15min").ffill()
    except Exception as exc:
        idx = pd.date_range(
            start=pd.Timestamp(target_date, tz=TIMEZONE), periods=96, freq="15min"
        )
        tomorrow_base = pd.DataFrame(index=idx)
        tomorrow_base["Forecast_Load"] = 4000.0
        tomorrow_base["Forecast_Solar"] = 0.0
        tomorrow_base["Forecast_Wind"] = 300.0
        tomorrow_base["Forecast_Aggregated_Gen"] = 3500.0

    # ------------------------------------------------------------------
    # 2. Fetch weather forecasts
    # ------------------------------------------------------------------
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
    except Exception:
        for col in [
            "Temp_Athens", "Solar_Rad_Athens", "Wind_Spd_Athens",
            "Temp_Thessaly", "Solar_Rad_Thessaly", "Wind_Spd_Thessaly",
            "Temp_Evia", "Solar_Rad_Evia", "Wind_Spd_Evia",
        ]:
            tomorrow_base[col] = 10.0 if "Temp" in col else (0.0 if "Solar" in col else 5.0)

    # ------------------------------------------------------------------
    # 3. Build raw columns
    # ------------------------------------------------------------------
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
    except Exception:
        last_be = hist_df["Break_Even_Gas_Price"].iloc[-1]
        tomorrow_base["Break_Even_Gas_Price"] = last_be

    # Volume lags
    vol_cols = [c for c in hist_df.columns if "Vol_" in c or "Total_Domestic_Load" in c]
    last_day_vols = hist_df[vol_cols].iloc[-96:]
    if len(last_day_vols) == 96:
        for col in vol_cols:
            tomorrow_base[col] = last_day_vols[col].values
    else:
        for col in vol_cols:
            tomorrow_base[col] = 0.0

    tomorrow_base["MCP"] = np.nan
    tomorrow_base["DDAY"] = int(target_date.strftime("%Y%m%d"))
    tomorrow_base["DELIVERY_MTU"] = tomorrow_base.index.strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------------
    # 4. Engineer features
    # ------------------------------------------------------------------
    hist_context = hist_df.iloc[-30 * 96 :].copy()
    common_cols = list(set(hist_context.columns) & set(tomorrow_base.columns))
    hist_subset = hist_context[common_cols].copy()
    tomorrow_aligned = tomorrow_base[common_cols].copy()

    combined = pd.concat([hist_subset, tomorrow_aligned])
    combined = combined.sort_index()

    tomorrow_engineered = engineer_inference_features(combined, target_date)

    with open(ROOT / "models" / "feature_columns.json") as f:
        feature_cols = json.load(f)

    for col in feature_cols:
        if col not in tomorrow_engineered.columns:
            tomorrow_engineered[col] = 0.0

    tomorrow_engineered = tomorrow_engineered[feature_cols]

    # ------------------------------------------------------------------
    # 5. Load models and predict
    # ------------------------------------------------------------------
    models_dir = ROOT / "models"
    predictions = {}
    for alpha in [0.10, 0.50, 0.90]:
        model_path = models_dir / f"lgbm_quantile_alpha{int(alpha*100):02d}.joblib"
        model = joblib.load(model_path)
        predictions[alpha] = model.predict(tomorrow_engineered)

    result_df = pd.DataFrame(
        {
            "Pred_p10": predictions[0.10],
            "Pred_p50": predictions[0.50],
            "Pred_p90": predictions[0.90],
        },
        index=tomorrow_engineered.index,
    )

    # Enforce monotonicity
    vals = result_df[["Pred_p10", "Pred_p50", "Pred_p90"]].values.copy()
    vals.sort(axis=1)
    result_df["Pred_p10"], result_df["Pred_p50"], result_df["Pred_p90"] = vals[:, 0], vals[:, 1], vals[:, 2]

    # ------------------------------------------------------------------
    # 6. Persist and return payload
    # ------------------------------------------------------------------
    output_dir = ROOT / "outputs"
    output_dir.mkdir(exist_ok=True)
    daily_log = output_dir / "daily_forecasts.csv"
    if daily_log.exists():
        existing = pd.read_csv(daily_log, index_col=0, parse_dates=True)
        existing.index = existing.index.tz_convert(TIMEZONE)
        existing = existing[existing.index.date != target_date]
        combined_log = pd.concat([existing, result_df])
    else:
        combined_log = result_df
    combined_log.to_csv(daily_log)

    dated_path = output_dir / f"forecast_{target_date}.csv"
    result_df.to_csv(dated_path)

    # Load metadata
    metadata_path = ROOT / "models" / "model_metadata.json"
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)

    tm = metadata.get("training_metrics", {})
    payload = {
        "target_date": str(target_date),
        "timestamps": result_df.index.astype(str).tolist(),
        "p10": result_df["Pred_p10"].tolist(),
        "p50": result_df["Pred_p50"].tolist(),
        "p90": result_df["Pred_p90"].tolist(),
        "diagnostics": {
            "mae_eur_per_mwh": tm.get("test_mae_p50"),
            "rmse_eur_per_mwh": tm.get("test_rmse_p50"),
            "profit_capture_pct": tm.get("profit_capture_pct"),
            "pinball_q90_eur_per_mwh": tm.get("pinball_q90_eur_per_mwh"),
            "bias_eur_per_mwh": tm.get("bias_eur_per_mwh"),
            "sigma_eur_per_mwh": tm.get("sigma_eur_per_mwh"),
            "p95_abs_error_eur_per_mwh": tm.get("p95_abs_error_eur_per_mwh"),
            "skew": tm.get("skew"),
        },
        "features": metadata.get("feature_importance", []),
        "models": [
            {
                "id": "lgbm_q",
                "name": "LightGBM Quantile",
                "kind": "ML+Quantile",
                "mae": tm.get("test_mae_p50"),
                "rmse": tm.get("test_rmse_p50"),
                "smape": None,
                "profit_capture_pct": tm.get("profit_capture_pct"),
                "pinball_q90": tm.get("pinball_q90_eur_per_mwh"),
            }
        ],
        "residuals": tm.get("residuals_sample", []),
        "calibration": {
            "nominal": [c["nominal"] for c in tm.get("calibration", [])],
            "empirical": [c["empirical"] for c in tm.get("calibration", [])],
        },
    }
    return payload
