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

# ---------------------------------------------------------------------------
# 4. Save model metadata (feature importance, training info)
# ---------------------------------------------------------------------------
print("\n[4/4] Saving model metadata ...")

# Use alpha=0.50 model as representative for feature importance
rep_model = lgb.LGBMRegressor(
    objective="quantile",
    alpha=0.50,
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
rep_model.fit(X, y)

feature_imp = sorted(
    zip(rep_model.feature_name_, rep_model.feature_importances_),
    key=lambda x: x[1],
    reverse=True,
)

# Simple feature grouping heuristic
def _group_feature(name: str) -> str:
    if "Lag" in name or "Rolling" in name or "volatility" in name.lower():
        return "Market Memory"
    if "Solar" in name or "Wind" in name or "Temp" in name or "Weather" in name or "Rad" in name or "Cloud" in name:
        return "Weather"
    if "Load" in name or "Residual" in name or "Gen" in name:
        return "Fundamentals"
    if "Gas" in name or "EUA" in name or "Carbon" in name or "Break_Even" in name:
        return "Fuel & Carbon"
    if "GR_" in name or "DE_" in name or "IT_" in name or "BG_" in name or "ATC" in name:
        return "Cross-border"
    if "hour" in name.lower() or "day" in name.lower() or "month" in name.lower() or "weekend" in name.lower() or "holiday" in name.lower() or "bridge" in name.lower() or "exodus" in name.lower():
        return "Calendar"
    if "Spread" in name or "Ratio" in name or "Crash" in name or "Volatility" in name or "Interaction" in name:
        return "Market Memory"
    return "Other"

metadata = {
    "training_date": pd.Timestamp.utcnow().isoformat(),
    "model_type": "LightGBM Quantile Regression",
    "quantiles": [0.10, 0.50, 0.90],
    "n_features": len(X.columns),
    "feature_names": X.columns.tolist(),
    "feature_importance": [
        {"name": name, "group": _group_feature(name), "imp": float(imp)}
        for name, imp in feature_imp
    ],
    "training_metrics": {},  # empty — no validation split on full-data training
}

metadata_path = models_dir / "model_metadata.json"
with open(metadata_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"    -> Saved model metadata: {metadata_path}")

print("\n" + "=" * 70)
print("MODELS SAVED")
print("=" * 70)
print(f"Directory: {models_dir}")
print("Run 'python pipelines/daily_inference.py' to perform daily inference.")
