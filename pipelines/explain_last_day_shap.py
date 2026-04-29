#!/usr/bin/env python3
"""
SHAP explainability pipeline for the LAST DAY of test-set predictions.

For each 15-minute interval on the most recent day in the test set,
this script:
1. Computes individual SHAP explanations (main + interaction effects)
2. Saves SHAP values as columns alongside predictions
3. Generates waterfall plots for every interval

Usage:
    cd /home/dimit/BatteryOS
    source .venv/bin/activate
    python pipelines/explain_last_day_shap.py
"""

import os
import sys
from pathlib import Path

import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap

# Resolve repo root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from src.forecast.train import train_quantile_models

print("=" * 70)
print("SHAP Explainability — Last Day of Test Set")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Load the final master dataset
# ---------------------------------------------------------------------------
print("\n[1/6] Loading df_master_ml_ready_advanced.csv ...")

DATA_PROCESSED = REPO_ROOT / "data" / "processed"

df = pd.read_csv(DATA_PROCESSED / "df_master_ml_ready_advanced.csv", index_col=0)
df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Athens")

print(f"  Loaded: {df.shape}")
print(f"  Index range: {df.index.min()} -> {df.index.max()}")

# ---------------------------------------------------------------------------
# 2. Train / test split (same logic as before)
# ---------------------------------------------------------------------------
print("\n[2/6] Train / Test split ...")

target_col = "MCP"
y = df[target_col]
X = df.drop(columns=[target_col])
for drop_col in ("DDAY", "DELIVERY_MTU"):
    if drop_col in X.columns:
        X = X.drop(columns=[drop_col])

TRAIN_END = pd.Timestamp("2025-06-30", tz="Europe/Athens")
mask_train = X.index <= TRAIN_END
mask_test = X.index >= pd.Timestamp("2025-07-01", tz="Europe/Athens")

X_train, y_train = X.loc[mask_train], y.loc[mask_train]
X_test, y_test = X.loc[mask_test], y.loc[mask_test]

print(f"  Train: {X_train.shape}")
print(f"  Test : {X_test.shape}")

# ---------------------------------------------------------------------------
# 3. Identify the LAST DAY in the test set
# ---------------------------------------------------------------------------
print("\n[3/6] Identifying last day in test set ...")

last_date = X_test.index.max().date()
last_day_mask = X_test.index.date == last_date
X_last_day = X_test.loc[last_day_mask]
y_last_day = y_test.loc[last_day_mask]

print(f"  Last day: {last_date}")
print(f"  Intervals to explain: {len(X_last_day)}")

# ---------------------------------------------------------------------------
# 4. Train LightGBM quantile models
# ---------------------------------------------------------------------------
print("\n[4/6] Training LightGBM quantile models ...")

models, predictions_df = train_quantile_models(
    X_train, X_test, y_train, y_test, verbose=True
)

predictions_last_day = {
    alpha: predictions_df.loc[last_day_mask, f"Pred_p{int(alpha*100):02d}"].values
    for alpha in [0.10, 0.50, 0.90]
}

# ---------------------------------------------------------------------------
# 5. Compute SHAP values (main + interaction) for last day
# ---------------------------------------------------------------------------
print("\n[5/6] Computing SHAP values (with interactions) for last day ...")
print("  This may take 1-2 minutes ...")

shap_results = {}
QUANTILES = [0.10, 0.50, 0.90]

for alpha in QUANTILES:
    print(f"  Alpha={alpha:.2f} ...")
    model = models[alpha]
    explainer = shap.TreeExplainer(model)

    shap_interaction = explainer.shap_interaction_values(X_last_day)
    shap_main = shap_interaction.sum(axis=2)

    shap_results[alpha] = {
        "main": shap_main,
        "interaction": shap_interaction,
        "base_value": explainer.expected_value,
    }
    print(f"    -> SHAP matrix shape: {shap_main.shape}")

# ---------------------------------------------------------------------------
# 6. Build DataFrame with predictions + SHAP columns
# ---------------------------------------------------------------------------
print("\n[6/6] Building output DataFrame with SHAP columns ...")

result_df = pd.DataFrame(
    {
        "Pred_p10": predictions_last_day[0.10],
        "Pred_p50": predictions_last_day[0.50],
        "Pred_p90": predictions_last_day[0.90],
        "Actual": y_last_day.values,
    },
    index=X_last_day.index,
)

shap_dfs = []
for alpha in QUANTILES:
    q_label = f"q{int(alpha*100):02d}"
    shap_main = shap_results[alpha]["main"]
    shap_df = pd.DataFrame(
        shap_main,
        index=X_last_day.index,
        columns=[f"SHAP_{c}_{q_label}" for c in X_last_day.columns],
    )
    shap_dfs.append(shap_df)

result_df = pd.concat([result_df] + shap_dfs, axis=1)
print(f"  Output DataFrame shape: {result_df.shape}")

# ---------------------------------------------------------------------------
# 7. Save CSV
# ---------------------------------------------------------------------------
output_dir = REPO_ROOT / "outputs"
output_dir.mkdir(exist_ok=True)

csv_path = output_dir / f"df_predictions_shap_last_day_{last_date}.csv"
result_df.to_csv(csv_path)
print(f"\n  Saved: {csv_path}")

# ---------------------------------------------------------------------------
# 8. Generate waterfall plots for every interval
# ---------------------------------------------------------------------------
print("\n[7/7] Generating waterfall plots ...")

plots_dir = output_dir / f"shap_last_day_{last_date}"
plots_dir.mkdir(exist_ok=True)

for idx_pos in range(len(X_last_day)):
    timestamp = X_last_day.index[idx_pos]
    hour_str = timestamp.strftime("%H%M")

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    for ax_idx, alpha in enumerate(QUANTILES):
        q_label = f"q{int(alpha*100):02d}"
        shap_values = shap_results[alpha]["main"][idx_pos]
        base_value = shap_results[alpha]["base_value"]
        prediction = predictions_last_day[alpha][idx_pos]

        base_val = float(base_value) if np.isscalar(base_value) else float(base_value[0])
        explanation = shap.Explanation(
            values=shap_values,
            base_values=base_val,
            data=X_last_day.iloc[idx_pos].values,
            feature_names=X_last_day.columns.tolist(),
        )

        plt.sca(axes[ax_idx])
        shap.waterfall_plot(explanation, max_display=10, show=False)
        axes[ax_idx].set_title(f"{q_label} | Pred: {prediction:.2f}", fontsize=10)

    fig.suptitle(f"SHAP Waterfalls — {timestamp}", fontsize=12)
    plt.tight_layout()
    plot_path = plots_dir / f"shap_{hour_str}.png"
    plt.savefig(plot_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    if (idx_pos + 1) % 10 == 0:
        print(f"    ... {idx_pos + 1}/{len(X_last_day)} plots generated")

print(f"\n  Saved {len(X_last_day)} waterfall plots to: {plots_dir}")

# ---------------------------------------------------------------------------
# 9. Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("SHAP EXPLAINABILITY COMPLETE")
print("=" * 70)
print(f"Last day explained     : {last_date}")
print(f"Intervals explained    : {len(X_last_day)}")
print(f"SHAP columns per quant : {len(X_last_day.columns)}")
print(f"Total output columns   : {len(result_df.columns)}")
print(f"\nFiles:")
print(f"  CSV  : {csv_path}")
print(f"  Plots: {plots_dir}")
