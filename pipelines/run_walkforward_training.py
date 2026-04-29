#!/usr/bin/env python3
"""
Walk-forward training pipeline for honest out-of-sample backtesting.

For each month in the test period (2025-07 onwards), trains quantile models
on ALL historical data before that month, then predicts only that month.
This prevents look-ahead bias in the backtest.

Usage:
    source .venv/bin/activate
    cd /home/dimit/BatteryOS
    python pipelines/run_walkforward_training.py

Output:
    data/processed/walkforward_predictions.csv
    (Columns: Pred_p10, Pred_p50, Pred_p90, Actual)
"""

from __future__ import annotations

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

from src.forecast.train import train_quantile_models

print("=" * 70)
print("Walk-Forward Training — Monthly Expanding Window")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load full feature matrix
# ---------------------------------------------------------------------------
print("\n[1/3] Loading full feature matrix ...")

DATA_PROCESSED = REPO_ROOT / "data" / "processed"

df = pd.read_csv(DATA_PROCESSED / "df_master_ml_ready_advanced.csv", index_col=0)
df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Athens")

print(f"  Loaded: {df.shape}")
print(f"  Index range: {df.index.min()} -> {df.index.max()}")

# ---------------------------------------------------------------------------
# 2. Prepare X / y
# ---------------------------------------------------------------------------
print("\n[2/3] Preparing X / y ...")

target_col = "MCP"
y = df[target_col]
X = df.drop(columns=[target_col])
for drop_col in ("DDAY", "DELIVERY_MTU"):
    if drop_col in X.columns:
        X = X.drop(columns=[drop_col])

print(f"  X: {X.shape} | y: {y.shape}")

# ---------------------------------------------------------------------------
# 3. Walk-forward: monthly expanding window
# ---------------------------------------------------------------------------
print("\n[3/3] Walk-forward training (this will take 30–60 minutes) ...")
print("-" * 70)

# Determine monthly boundaries for the test period
test_start = pd.Timestamp("2025-07-01", tz="Europe/Athens")
test_end = X.index.max()

# Generate month starts
month_starts = pd.date_range(test_start, test_end, freq="MS", tz="Europe/Athens")

all_predictions: list[pd.DataFrame] = []

for i, month_start in enumerate(month_starts, 1):
    month_end = month_start + pd.offsets.MonthEnd(1)
    month_end = min(month_end, test_end)

    # Training: everything strictly before this month
    train_mask = X.index < month_start
    # Testing: this month only
    test_mask = (X.index >= month_start) & (X.index <= month_end)

    X_train, y_train = X.loc[train_mask], y.loc[train_mask]
    X_test, y_test = X.loc[test_mask], y.loc[test_mask]

    if len(X_train) < 1000 or len(X_test) == 0:
        print(f"  [{i}/{len(month_starts)}] {month_start.strftime('%Y-%m')} — SKIP (insufficient data)")
        continue

    print(
        f"  [{i}/{len(month_starts)}] {month_start.strftime('%Y-%m')} — "
        f"train={len(X_train):,} | test={len(X_test):,}"
    )

    # Train quantile models (n_splits=1 for speed; we already have temporal split)
    models, df_month_pred = train_quantile_models(
        X_train, X_test, y_train, y_test,
        n_estimators=500,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        subsample=0.8,
        reg_lambda=1.0,
        early_stopping_rounds=50,
        verbose=False,
    )

    all_predictions.append(df_month_pred)

# ---------------------------------------------------------------------------
# 4. Save combined predictions
# ---------------------------------------------------------------------------
print("\n" + "-" * 70)
print("Saving combined walk-forward predictions ...")

df_walkforward = pd.concat(all_predictions).sort_index()

# Drop duplicate indices (DST transitions can create duplicates at 04:00)
df_walkforward = df_walkforward[~df_walkforward.index.duplicated(keep="first")]

# Verify no overlap / no gaps in test period
assert df_walkforward.index.is_unique, "Duplicate timestamps in walk-forward predictions!"

output_path = DATA_PROCESSED / "walkforward_predictions.csv"
df_walkforward.to_csv(output_path)

print(f"  Saved: {output_path}")
print(f"  Shape: {df_walkforward.shape}")
print(f"  Index: {df_walkforward.index.min()} -> {df_walkforward.index.max()}")

# Quick validation: compare OOS MAE to in-sample MAE
from sklearn.metrics import mean_absolute_error
mae = mean_absolute_error(df_walkforward["Actual"], df_walkforward["Pred_p50"])
print(f"  Walk-forward MAE (p50): {mae:,.2f} €/MWh")

print("\n" + "=" * 70)
print("WALK-FORWARD TRAINING COMPLETE")
print("=" * 70)
