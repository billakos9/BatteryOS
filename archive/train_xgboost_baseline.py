#!/usr/bin/env python3
"""
Production-ready XGBoost baseline training & evaluation script for
Greek Day-Ahead Market Clearing Price (MCP) forecasting.

Assumes df_master_ml_ready is in memory, indexed by a timezone-aware
15-minute DatetimeIndex (Europe/Athens).
"""

import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor, plot_importance

# ---------------------------------------------------------------------------
# 0. Guard
# ---------------------------------------------------------------------------
if "df_master_ml_ready" not in globals():
    raise NameError(
        "df_master_ml_ready must exist in the global namespace before running this script."
    )

print("=" * 70)
print("XGBoost Baseline — MCP Forecasting")
print(f"Input shape: {df_master_ml_ready.shape}")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Data Preparation & Chronological Split
# ---------------------------------------------------------------------------
print("\n[1/4] Data Preparation & Chronological Split")

# Target
target_col = "MCP"
if target_col not in df_master_ml_ready.columns:
    raise KeyError(f"Target column '{target_col}' not found in DataFrame.")

y = df_master_ml_ready[target_col]

# Feature matrix — drop target and any leftover text/date identifiers
X = df_master_ml_ready.drop(columns=[target_col])
for drop_col in ("DDAY", "DELIVERY_MTU"):
    if drop_col in X.columns:
        X = X.drop(columns=[drop_col])
        print(f"  Dropped identifier column: {drop_col}")

# Ensure all features are numeric
non_numeric = X.select_dtypes(exclude=[np.number]).columns.tolist()
if non_numeric:
    print(f"  Warning: dropping non-numeric columns: {non_numeric}")
    X = X.drop(columns=non_numeric)

# Chronological split (no shuffling!)
TRAIN_END = pd.Timestamp("2025-06-30", tz="Europe/Athens")
TEST_START = pd.Timestamp("2025-07-01", tz="Europe/Athens")

mask_train = X.index <= TRAIN_END
mask_test = X.index >= TEST_START

X_train, y_train = X.loc[mask_train], y.loc[mask_train]
X_test, y_test = X.loc[mask_test], y.loc[mask_test]

print(f"  Train range : {X_train.index.min()} -> {X_train.index.max()}")
print(f"  Test range  : {X_test.index.min()} -> {X_test.index.max()}")
print(f"  X_train shape: {X_train.shape} | y_train shape: {y_train.shape}")
print(f"  X_test shape : {X_test.shape}  | y_test shape : {y_test.shape}")

# Safety check: no overlap
overlap = X_train.index.intersection(X_test.index)
if len(overlap) > 0:
    print(f"  Warning: {len(overlap)} overlapping timestamps between train and test!")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 2. Model Initialization & Training
# ---------------------------------------------------------------------------
print("\n[2/4] Model Initialization & Training")

xgb_model = XGBRegressor(
    n_estimators=500,
    learning_rate=0.05,
    max_depth=6,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    objective="reg:squarederror",
    n_jobs=-1,
)

xgb_model.fit(
    X_train,
    y_train,
    eval_set=[(X_train, y_train), (X_test, y_test)],
    verbose=50,
)

# ---------------------------------------------------------------------------
# 3. Evaluation Metrics
# ---------------------------------------------------------------------------
print("\n[3/4] Evaluation")

y_pred = xgb_model.predict(X_test)

mae = mean_absolute_error(y_test, y_pred)
rmse = np.sqrt(mean_squared_error(y_test, y_pred))

print(f"  Mean Absolute Error (MAE) : {mae:,.2f} €/MWh")
print(f"  Root Mean Squared Error    : {rmse:,.2f} €/MWh")

# ---------------------------------------------------------------------------
# 4. Feature Importance Interpretation
# ---------------------------------------------------------------------------
print("\n[4/4] Feature Importance")

importance_df = pd.DataFrame(
    {
        "feature": X_train.columns,
        "importance": xgb_model.feature_importances_,
    }
).sort_values("importance", ascending=False)

print("\nTop 15 features:")
print(importance_df.head(15).to_string(index=False))

# Plot
plt.figure(figsize=(10, 7))
top_n = 15
top_features = importance_df.head(top_n)
sns.barplot(
    data=top_features,
    y="feature",
    x="importance",
    palette="viridis",
    orient="h",
)
plt.title("Top 15 Most Important Features - XGBoost Baseline", fontsize=14)
plt.xlabel("Importance Score", fontsize=12)
plt.ylabel("Feature", fontsize=12)
plt.tight_layout()
plt.savefig("xgboost_feature_importance.png", dpi=300)
print("\nSaved plot: xgboost_feature_importance.png")
plt.show()

# ---------------------------------------------------------------------------
# 5. Optional: Actual vs Predicted scatter
# ---------------------------------------------------------------------------
plt.figure(figsize=(8, 8))
plt.scatter(y_test, y_pred, alpha=0.3, s=10)
max_val = max(y_test.max(), y_pred.max())
plt.plot([0, max_val], [0, max_val], "r--", lw=2, label="Perfect Prediction")
plt.xlabel("Actual MCP (€/MWh)", fontsize=12)
plt.ylabel("Predicted MCP (€/MWh)", fontsize=12)
plt.title("Actual vs Predicted MCP — XGBoost Baseline", fontsize=14)
plt.legend()
plt.tight_layout()
plt.savefig("xgboost_actual_vs_predicted.png", dpi=300)
print("Saved plot: xgboost_actual_vs_predicted.png")
plt.show()

print("\n" + "=" * 70)
print("Training complete.")
print("=" * 70)
