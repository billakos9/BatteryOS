"""
Probabilistic MCP forecasting with LightGBM Quantile Regression.

Trains three separate models (p10, p50, p90) with early stopping to
provide confidence intervals for downstream battery optimisation.
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

from src.forecast.utils import sort_quantiles


def train_quantile_models(
    X_train: pd.DataFrame,
    X_val: pd.DataFrame,
    y_train: pd.Series,
    y_val: pd.Series,
    quantiles: list[float] | None = None,
    n_estimators: int = 1000,
    learning_rate: float = 0.05,
    max_depth: int = 4,
    num_leaves: int = 15,
    subsample: float = 0.8,
    reg_lambda: float = 1.0,
    random_state: int = 42,
    early_stopping_rounds: int = 50,
    verbose: bool = True,
) -> tuple[dict[float, lgb.LGBMRegressor], pd.DataFrame]:
    """
    Train independent LightGBM quantile regressors.

    Parameters
    ----------
    X_train, X_val, y_train, y_val
        Chronologically-split feature matrices and targets.
        ``X_val`` / ``y_val`` are used for early stopping and best-iteration
        selection only; they are *not* the final test set.
    quantiles
        List of quantiles to model (default: [0.10, 0.50, 0.90]).
    n_estimators, learning_rate, max_depth, num_leaves, subsample, reg_lambda
        LightGBM hyperparameters.
    random_state
        Random seed for reproducibility.
    early_stopping_rounds
        Number of rounds without improvement before stopping.
    verbose
        Print progress to stdout.

    Returns
    -------
    models : dict[float, lgb.LGBMRegressor]
        Mapping quantile → fitted model.
    df_predictions : pd.DataFrame
        DataFrame indexed like *y_val* with columns
        ``Pred_p10``, ``Pred_p50``, ``Pred_p90``, ``Actual``.
    """
    if quantiles is None:
        quantiles = [0.10, 0.50, 0.90]

    if verbose:
        print("=" * 70)
        print("LightGBM Quantile Regression — Probabilistic MCP Forecast")
        print(f"Train: {X_train.shape} | Validation: {X_val.shape}")
        print("=" * 70)

    models: dict[float, lgb.LGBMRegressor] = {}
    predictions: dict[float, np.ndarray] = {}

    if verbose:
        print("\n[1/3] Training quantile models ...")

    for alpha in quantiles:
        if verbose:
            print(f"\n  Training alpha={alpha:.2f} ...")

        model = lgb.LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max_depth,
            num_leaves=num_leaves,
            subsample=subsample,
            reg_lambda=reg_lambda,
            random_state=random_state,
            n_jobs=-1,
            verbose=-1,
        )

        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(stopping_rounds=early_stopping_rounds, verbose=verbose)],
        )

        models[alpha] = model
        preds = model.predict(X_val, num_iteration=model.best_iteration_)
        predictions[alpha] = preds

        if verbose:
            print(f"    Best iteration: {model.best_iteration_} / {model.n_estimators}")

    # ------------------------------------------------------------------
    # Compile predictions
    # ------------------------------------------------------------------
    if verbose:
        print("\n[2/3] Compiling prediction DataFrame ...")

    df_predictions = pd.DataFrame(
        {
            "Pred_p10": predictions[0.10],
            "Pred_p50": predictions[0.50],
            "Pred_p90": predictions[0.90],
            "Actual": y_val.values,
        },
        index=y_val.index,
    )

    df_predictions = sort_quantiles(df_predictions)

    if verbose:
        print(f"  df_predictions shape: {df_predictions.shape}")
        print(df_predictions.head().to_string())

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    if verbose:
        print("\n[3/3] Evaluation")

    mae_p50 = mean_absolute_error(y_val, df_predictions["Pred_p50"])
    if verbose:
        print(f"  Validation MAE (p50 median) : {mae_p50:,.2f} €/MWh")

    for alpha in quantiles:
        q_pred = predictions[alpha]
        pinball = np.where(
            y_val >= q_pred,
            alpha * (y_val - q_pred),
            (1 - alpha) * (q_pred - y_val),
        ).mean()
        if verbose:
            print(f"  Validation Pinball loss (α={alpha:.2f}) : {pinball:,.2f} €/MWh")

    if verbose:
        print("\n" + "=" * 70)
        print("Probabilistic forecasting complete.")
        print("=" * 70)

    return models, df_predictions
