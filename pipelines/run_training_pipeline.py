#!/usr/bin/env python3
"""
End-to-end training pipeline for Greek DAM MCP forecasting.

Steps:
1. Load raw data (EnEx, ENTSO-E, weather)
2. Build master feature dataset
3. Preprocess (lags, cyclical, interactions)
4. Engineer advanced features
5. Train LightGBM quantile model
6. Post-process quantiles (enforce monotonicity)
7. Save predictions and model artefacts

Usage:
    source .venv/bin/activate
    cd /home/dimit/BatteryOS
    python pipelines/run_training_pipeline.py
"""

import os
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# 0. Resolve repo root
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from src.features.builder import build_master_dataset
from src.features.preprocessing import preprocess_features
from src.features.interactions import add_interaction_features
from src.features.advanced import engineer_advanced_features
from src.forecast.train import train_quantile_models
from src.forecast.utils import sort_quantiles

print("=" * 70)
print(f"Repo root : {REPO_ROOT}")
print(f"CWD       : {Path.cwd()}")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load source data
# ---------------------------------------------------------------------------
print("\n[1/7] Load Source Data")
print("-" * 70)

DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"

try:
    df_wide = pd.read_excel(DATA_RAW / "cleaned_dam_results.xlsx", engine="openpyxl")
    df_wide["timestamp"] = pd.to_datetime(df_wide["DELIVERY_MTU"])
    df_wide = df_wide.set_index("timestamp").sort_index()
    df_wide.index = df_wide.index.tz_localize(
        "Europe/Athens", ambiguous="NaT", nonexistent="shift_forward"
    )
    df_wide = df_wide[df_wide.index.notna()]
    print(f"  OK  cleaned_dam_results.xlsx -> {df_wide.shape}")
except FileNotFoundError as exc:
    print(f"  FAIL {exc}")
    sys.exit(1)

try:
    df_ipto = pd.read_csv(DATA_RAW / "entsoe_greece_dam_forecasts.csv", index_col=0)
    df_ipto.index = pd.to_datetime(df_ipto.index, utc=True).tz_convert("Europe/Athens")
    print(f"  OK  entsoe_greece_dam_forecasts.csv -> {df_ipto.shape}")
except FileNotFoundError as exc:
    print(f"  FAIL {exc}")
    sys.exit(1)

try:
    df_weather = pd.read_csv(DATA_RAW / "openmeteo_weather_master.csv", index_col=0)
    df_weather.index = pd.to_datetime(df_weather.index, utc=True).tz_convert("Europe/Athens")
    print(f"  OK  openmeteo_weather_master.csv -> {df_weather.shape}")
except FileNotFoundError as exc:
    print(f"  FAIL {exc}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 2. Build master dataset
# ---------------------------------------------------------------------------
print("\n[2/7] Build Master Dataset")
print("-" * 70)

df_master_ml_ready = build_master_dataset(df_wide, df_ipto, df_weather)

# ---------------------------------------------------------------------------
# 3. Final preprocessing
# ---------------------------------------------------------------------------
print("\n[3/7] Preprocessing")
print("-" * 70)

df_master_ml_ready = preprocess_features(df_master_ml_ready)

# ---------------------------------------------------------------------------
# 4. Interaction features
# ---------------------------------------------------------------------------
print("\n[4/7] Interaction Features")
print("-" * 70)

df_master_ml_ready = add_interaction_features(df_master_ml_ready)
print(f"  Added interaction features. Shape: {df_master_ml_ready.shape}")

# ---------------------------------------------------------------------------
# 5. Advanced features
# ---------------------------------------------------------------------------
print("\n[5/7] Advanced Features")
print("-" * 70)

df_master_ml_ready = engineer_advanced_features(df_master_ml_ready)

# Persist the fully-engineered dataset
df_master_ml_ready.to_csv(DATA_PROCESSED / "df_master_ml_ready_advanced.csv")
print("  Saved: df_master_ml_ready_advanced.csv")

# ---------------------------------------------------------------------------
# 6. Train / validation split
# ---------------------------------------------------------------------------
print("\n[6/7] Train / Validation Split")
print("-" * 70)

target_col = "MCP"
y = df_master_ml_ready[target_col]
X = df_master_ml_ready.drop(columns=[target_col])
for drop_col in ("DDAY", "DELIVERY_MTU"):
    if drop_col in X.columns:
        X = X.drop(columns=[drop_col])

TRAIN_END = pd.Timestamp("2025-06-30", tz="Europe/Athens")
mask_train = X.index <= TRAIN_END
mask_val = X.index >= pd.Timestamp("2025-07-01", tz="Europe/Athens")

X_train, y_train = X.loc[mask_train], y.loc[mask_train]
X_val, y_val = X.loc[mask_val], y.loc[mask_val]

print(f"  Train: {X_train.shape} | Validation: {X_val.shape}")

# ---------------------------------------------------------------------------
# 7. Train LightGBM quantile model
# ---------------------------------------------------------------------------
print("\n[7/7] Train LightGBM Quantile Model")
print("-" * 70)

models, df_predictions = train_quantile_models(
    X_train, X_val, y_train, y_val, verbose=True
)

# Post-process: enforce monotonic quantiles
df_predictions = sort_quantiles(df_predictions)

# Save artefacts
output_dir = REPO_ROOT / "outputs"
output_dir.mkdir(exist_ok=True)

pred_path = output_dir / "df_predictions.csv"
master_path = DATA_PROCESSED / "df_master_final.csv"

df_predictions.to_csv(pred_path)
print(f"  Saved predictions : {pred_path}")

df_master_ml_ready.to_csv(master_path)
print(f"  Saved master data : {master_path}")

print("\n" + "=" * 70)
print("PIPELINE COMPLETE")
print("=" * 70)
print(f"Output directory: {output_dir}")
print(f"  - {pred_path.name}")
print(f"  - {master_path.name}")
