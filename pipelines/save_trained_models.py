#!/usr/bin/env python3
"""
Save trained LightGBM quantile models to disk for later inference.

Trains on the FULL historical dataset (all available data up to the latest
point) and serializes the models using joblib.

Usage:
    cd /home/dimit/BatteryOS
    source .venv/bin/activate
    python pipelines/save_trained_models.py
"""

import json
import os
import sys
from pathlib import Path

import joblib
import lightgbm as lgb
import pandas as pd

# Resolve repo root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from src.forecast.train import train_quantile_models

print("=" * 70)
print("Save Trained LightGBM Quantile Models")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load the full feature matrix
# ---------------------------------------------------------------------------
print("\n[1/3] Loading full feature matrix ...")

DATA_PROCESSED = REPO_ROOT / "data" / "processed"

df = pd.read_csv(DATA_PROCESSED / "df_master_ml_ready_advanced.csv", index_col=0)
df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Athens")

print(f"  Loaded: {df.shape}")
print(f"  Index range: {df.index.min()} -> {df.index.max()}")

# ---------------------------------------------------------------------------
# 2. Prepare X / y (use ALL data for production model)
# ---------------------------------------------------------------------------
print("\n[2/3] Preparing training data (full history) ...")

target_col = "MCP"
y = df[target_col]
X = df.drop(columns=[target_col])
for drop_col in ("DDAY", "DELIVERY_MTU"):
    if drop_col in X.columns:
        X = X.drop(columns=[drop_col])

print(f"  X: {X.shape} | y: {y.shape}")

# ---------------------------------------------------------------------------
# 3. Train and save models
# ---------------------------------------------------------------------------
print("\n[3/3] Training and saving models ...")

models_dir = REPO_ROOT / "models"
models_dir.mkdir(exist_ok=True)

QUANTILES = [0.10, 0.50, 0.90]

for alpha in QUANTILES:
    print(f"  Training alpha={alpha:.2f} ...")
    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        n_estimators=500,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        subsample=0.8,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(X, y)

    model_path = models_dir / f"lgbm_quantile_alpha{int(alpha*100):02d}.joblib"
    joblib.dump(model, model_path)
    print(f"    -> Saved: {model_path}")

# Save feature column order (critical for inference alignment)
feature_cols_path = models_dir / "feature_columns.json"
with open(feature_cols_path, "w") as f:
    json.dump(X.columns.tolist(), f)
print(f"    -> Saved feature column order: {feature_cols_path}")

print("\n" + "=" * 70)
print("MODELS SAVED")
print("=" * 70)
print(f"Directory: {models_dir}")
print("Run 'python pipelines/daily_inference.py' to perform daily inference.")
