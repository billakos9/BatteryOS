#!/usr/bin/env python3
"""
Probabilistic MCP forecasting with LightGBM Quantile Regression.

Trains three separate models (p10, p50, p90) with early stopping to
provide confidence intervals for downstream battery optimisation.

Assumes X_train, X_test, y_train, y_test are already chronologically
split and in memory.
"""

import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

try:
    from src.forecast.utils import sort_quantiles
except ModuleNotFoundError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from src.forecast.utils import sort_quantiles

# ---------------------------------------------------------------------------
# 0. Guard
# ---------------------------------------------------------------------------
for _name in ("X_train", "X_test", "y_train", "y_test"):
    if _name not in globals():
        raise NameError(
            f"'{_name}' must exist in the global namespace before running this script."
        )

print("=" * 70)
print("LightGBM Quantile Regression — Probabilistic MCP Forecast")
print(f"Train: {X_train.shape} | Test: {X_test.shape}")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Quantile Loop — Train p10, p50, p90
# ---------------------------------------------------------------------------
QUANTILES = [0.10, 0.50, 0.90]
models = {}
predictions = {}

print("\n[1/3] Training quantile models ...")
for alpha in QUANTILES:
    print(f"\n  Training alpha={alpha:.2f} ...")

    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        n_estimators=1000,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        subsample=0.8,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
        verbose=-1,  # suppress per-tree output; early stopping prints key info
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=True)],
    )

    models[alpha] = model
    preds = model.predict(X_test, num_iteration=model.best_iteration_)
    predictions[alpha] = preds

    print(f"    Best iteration: {model.best_iteration_} / {model.n_estimators}")

# ---------------------------------------------------------------------------
# 2. Compile predictions into a DataFrame
# ---------------------------------------------------------------------------
print("\n[2/3] Compiling prediction DataFrame ...")

df_predictions = pd.DataFrame(
    {
        "Pred_p10": predictions[0.10],
        "Pred_p50": predictions[0.50],
        "Pred_p90": predictions[0.90],
        "Actual": y_test.values,
    },
    index=y_test.index,
)

# Post-process: enforce monotonic quantiles
print("  Post-processing quantiles (enforcing monotonicity) ...")
df_predictions = sort_quantiles(df_predictions)

print(f"  df_predictions shape: {df_predictions.shape}")
print(df_predictions.head().to_string())

# ---------------------------------------------------------------------------
# 3. Evaluation — MAE on the median (p50)
# ---------------------------------------------------------------------------
print("\n[3/3] Evaluation")

mae_p50 = mean_absolute_error(y_test, df_predictions["Pred_p50"])
print(f"  Test MAE (p50 median) : {mae_p50:,.2f} €/MWh")

# Also report pinball loss for each quantile
for alpha in QUANTILES:
    q_pred = predictions[alpha]
    pinball = np.where(
        y_test >= q_pred,
        alpha * (y_test - q_pred),
        (1 - alpha) * (q_pred - y_test),
    ).mean()
    print(f"  Pinball loss (α={alpha:.2f}) : {pinball:,.2f} €/MWh")

# ---------------------------------------------------------------------------
# 4. Visualisation — First 7 days of the Test set
# ---------------------------------------------------------------------------
print("\nPlotting first 7 days of test set ...")

N_INTERVALS = 96 * 7  # 7 days × 96 quarters/day
plot_slice = df_predictions.iloc[:N_INTERVALS]

plt.figure(figsize=(14, 6))

# Actual price (solid black)
plt.plot(
    plot_slice.index,
    plot_slice["Actual"],
    color="black",
    linewidth=1.2,
    label="Actual MCP",
)

# Median forecast (dashed blue)
plt.plot(
    plot_slice.index,
    plot_slice["Pred_p50"],
    color="blue",
    linewidth=1.2,
    linestyle="--",
    label="Pred p50 (median)",
)

# Confidence band (p10–p90)
plt.fill_between(
    plot_slice.index,
    plot_slice["Pred_p10"],
    plot_slice["Pred_p90"],
    color="lightblue",
    alpha=0.3,
    label="p10–p90 Interval",
)

plt.title("Probabilistic Forecast: Actual vs p10-p90 Intervals", fontsize=14)
plt.xlabel("Timestamp (Europe/Athens)", fontsize=12)
plt.ylabel("MCP (€/MWh)", fontsize=12)
plt.legend(loc="upper right")
plt.tight_layout()
plt.savefig("lightgbm_quantile_forecast.png", dpi=300)
print("Saved plot: lightgbm_quantile_forecast.png")
plt.show()

print("\n" + "=" * 70)
print("Probabilistic forecasting complete.")
print("=" * 70)
