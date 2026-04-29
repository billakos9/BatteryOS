#!/usr/bin/env python3
"""
Optuna hyperparameter tuning for LightGBM quantile regression.
Tunes one model per quantile and saves best params to YAML.
"""

from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import yaml
from sklearn.metrics import mean_absolute_error

# We import LightGBM inside the objective to allow Optuna pruning


def pinball_loss(y_true, y_pred, alpha):
    """Quantile (pinball) loss."""
    return np.where(
        y_true >= y_pred,
        alpha * (y_true - y_pred),
        (1 - alpha) * (y_pred - y_true),
    ).mean()


def objective(trial, X_train, y_train, X_test, y_test, alpha):
    import lightgbm as lgb

    params = {
        "objective": "quantile",
        "alpha": alpha,
        "n_estimators": 1000,
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "num_leaves": trial.suggest_int("num_leaves", 10, 50),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 5.0, log=True),
        "random_state": 42,
        "n_jobs": -1,
        "verbose": -1,
    }

    model = lgb.LGBMRegressor(**params)
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            optuna.integration.LightGBMPruningCallback(trial, "quantile"),
        ],
    )

    preds = model.predict(X_test, num_iteration=model.best_iteration_)
    return pinball_loss(y_test, preds, alpha)


def run_tuning(X_train, y_train, X_test, y_test, n_trials=100):
    """Run Optuna tuning for all three quantiles and return best params."""
    best_params = {}

    for alpha in [0.10, 0.50, 0.90]:
        study = optuna.create_study(
            direction="minimize",
            pruner=optuna.pruners.MedianPruner(n_startup_trials=5),
        )
        study.optimize(
            lambda trial: objective(trial, X_train, y_train, X_test, y_test, alpha),
            n_trials=n_trials,
            show_progress_bar=True,
        )

        best = study.best_params
        best["objective"] = "quantile"
        best["alpha"] = alpha
        best["n_estimators"] = 1000
        best["random_state"] = 42
        best["n_jobs"] = -1
        best["verbose"] = -1

        best_params[f"alpha_{alpha:.2f}"] = best
        print(
            f"Alpha={alpha:.2f} best pinball={study.best_value:.3f} "
            f"params={best}"
        )

    return best_params


def save_params(best_params: dict, path: str = "config/lightgbm_quantile_params.yaml"):
    """Save tuned params to YAML."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(best_params, f, default_flow_style=False)
    print(f"Saved tuned params to {path}")


def load_params(path: str = "config/lightgbm_quantile_params.yaml") -> dict:
    """Load tuned params from YAML."""
    with open(path) as f:
        return yaml.safe_load(f)
