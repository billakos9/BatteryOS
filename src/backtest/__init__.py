"""BatteryOS walk-forward backtester.

End-to-end evaluation harness for the (forecaster + optimize_dispatch)
pipeline. It loops day-by-day across a test period, calls the
forecaster with a strict gate-close `asof` cutoff, runs
`optimize_dispatch`, replays the resulting schedule against the realized
DAM clearing prices, and reports forecast-accuracy and dispatch-economic
metrics versus perfect-foresight and naive baselines.

Public API:

    from src.backtest import (
        Forecaster,                   # the contract the forecaster module satisfies
        run_walk_forward_backtest,    # the main entry
        BacktestResult,
        naive_seasonal_forecaster,    # reference baseline you can run today
    )
"""
from .metrics import (
    crps_ensemble,
    naive_seasonal_forecast,
    perfect_foresight_pnl,
    pinball_loss,
    point_metrics,
    quantile_pinball_score,
)
from .protocols import Forecaster, naive_seasonal_forecaster
from .result import BacktestDay, BacktestResult
from .walk_forward import run_walk_forward_backtest

__all__ = [
    "Forecaster",
    "naive_seasonal_forecaster",
    "run_walk_forward_backtest",
    "BacktestResult",
    "BacktestDay",
    "crps_ensemble",
    "naive_seasonal_forecast",
    "perfect_foresight_pnl",
    "pinball_loss",
    "point_metrics",
    "quantile_pinball_score",
]
