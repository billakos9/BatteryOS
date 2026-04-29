#!/usr/bin/env python3
"""
Run Optuna hyperparameter tuning for LightGBM quantile regression.

This script loads the engineered dataset, runs 100 Optuna trials per
quantile (p10, p50, p90), saves the best params, and retrains the
final model with those params.

Usage:
    cd /home/dimit/BatteryOS
    source .venv/bin/activate
    python pipelines/run_optuna_tuning.py

Runtime: ~20-40 minutes depending on hardware.
"""

import os
import sys
from pathlib import Path

import lightgbm as lgb
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import mean_absolute_error

# Resolve repo root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from src.features.builder import build_master_dataset
from src.features.preprocessing import preprocess_features
from src.features.interactions import add_interaction_features
from src.features.advanced import engineer_advanced_features
from src.forecast.tune_lightgbm import run_tuning, save_params
from src.forecast.utils import sort_quantiles

print("=" * 70)
print("Optuna Hyperparameter Tuning for LightGBM Quantile Regression")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("\n[1/4] Loading data ...")

DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"

df_wide = pd.read_excel(DATA_RAW / "cleaned_dam_results.xlsx", engine="openpyxl")
df_wide["timestamp"] = pd.to_datetime(df_wide["DELIVERY_MTU"])
df_wide = df_wide.set_index("timestamp").sort_index()
df_wide.index = df_wide.index.tz_localize(
    "Europe/Athens", ambiguous="NaT", nonexistent="shift_forward"
)
df_wide = df_wide[df_wide.index.notna()]

df_ipto = pd.read_csv(DATA_RAW / "entsoe_greece_dam_forecasts.csv", index_col=0)
df_ipto.index = pd.to_datetime(df_ipto.index, utc=True).tz_convert("Europe/Athens")

df_weather = pd.read_csv(DATA_RAW / "openmeteo_weather_master.csv", index_col=0)
df_weather.index = pd.to_datetime(df_weather.index, utc=True).tz_convert("Europe/Athens")

df_master_ml_ready = build_master_dataset(df_wide, df_ipto, df_weather)
df_master_ml_ready = preprocess_features(df_master_ml_ready)
df_master_ml_ready = add_interaction_features(df_master_ml_ready)
df_master_ml_ready = engineer_advanced_features(df_master_ml_ready)

# Train/test split
target_col = "MCP"
y = df_master_ml_ready[target_col]
X = df_master_ml_ready.drop(columns=[target_col])
for drop_col in ("DDAY", "DELIVERY_MTU"):
    if drop_col in X.columns:
        X = X.drop(columns=[drop_col])

TRAIN_END = pd.Timestamp("2025-06-30", tz="Europe/Athens")
mask_train = X.index <= TRAIN_END
mask_test = X.index >= pd.Timestamp("2025-07-01", tz="Europe/Athens")

X_train, y_train = X.loc[mask_train], y.loc[mask_train]
X_test, y_test = X.loc[mask_test], y.loc[mask_test]

print(f"  Train: {X_train.shape} | Test: {X_test.shape}")

# ---------------------------------------------------------------------------
# 2. Run Optuna tuning
# ---------------------------------------------------------------------------
print("\n[2/4] Running Optuna tuning (100 trials x 3 quantiles) ...")
print("This will take 20-40 minutes. Grab a coffee.")
print("-" * 70)

best_params = run_tuning(X_train, y_train, X_test, y_test, n_trials=100)

# ---------------------------------------------------------------------------
# 3. Save tuned params
# ---------------------------------------------------------------------------
print("\n[3/4] Saving tuned parameters ...")

save_params(best_params, path="config/lightgbm_quantile_params.yaml")

# ---------------------------------------------------------------------------
# 4. Retrain final model with tuned params
# ---------------------------------------------------------------------------
print("\n[4/4] Retraining final model with tuned parameters ...")

predictions = {}
for alpha in [0.10, 0.50, 0.90]:
    params = best_params[f"alpha_{alpha:.2f}"].copy()
    params["n_estimators"] = params.get("best_iteration", 1000)

    model = lgb.LGBMRegressor(**params)
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    predictions[alpha] = preds

    mae = mean_absolute_error(y_test, preds)
    print(f"  Alpha={alpha:.2f} -> MAE: {mae:.2f} €/MWh")

# Compile predictions
df_predictions = pd.DataFrame(
    {
        "Pred_p10": predictions[0.10],
        "Pred_p50": predictions[0.50],
        "Pred_p90": predictions[0.90],
        "Actual": y_test.values,
    },
    index=y_test.index,
)
df_predictions = sort_quantiles(df_predictions)

# Save
output_dir = REPO_ROOT / "outputs"
output_dir.mkdir(exist_ok=True)

pred_path = output_dir / "df_predictions_tuned.csv"
df_predictions.to_csv(pred_path)
print(f"\n  Saved tuned predictions: {pred_path}")

# Plot first 7 days
N_INTERVALS = 96 * 7
plot_slice = df_predictions.iloc[:N_INTERVALS]

plt.figure(figsize=(14, 6))
plt.plot(plot_slice.index, plot_slice["Actual"], color="black", linewidth=1.2, label="Actual MCP")
plt.plot(plot_slice.index, plot_slice["Pred_p50"], color="blue", linewidth=1.2, linestyle="--", label="Pred p50")
plt.fill_between(plot_slice.index, plot_slice["Pred_p10"], plot_slice["Pred_p90"], color="lightblue", alpha=0.3, label="p10-p90 Interval")
plt.title("Tuned Probabilistic Forecast: Actual vs p10-p90 Intervals", fontsize=14)
plt.xlabel("Timestamp (Europe/Athens)", fontsize=12)
plt.ylabel("MCP (€/MWh)", fontsize=12)
plt.legend(loc="upper right")
plt.tight_layout()
plot_path = REPO_ROOT / "lightgbm_quantile_forecast_tuned.png"
plt.savefig(plot_path, dpi=300)
print(f"  Saved plot: {plot_path}")

print("\n" + "=" * 70)
print("TUNING COMPLETE")
print("=" * 70)
print(f"Best params saved to: config/lightgbm_quantile_params.yaml")
print(f"Tuned predictions:    {pred_path}")
print(f"Tuned plot:           {plot_path}")
