# src/backtest

Walk-forward backtester for the **(forecaster + optimize_dispatch)** pipeline.

## What it does

Loops day-by-day over a test period. For each delivery day it:

1. Calls the forecaster with `asof = target_day - 12h` (gate close)
2. Runs `optimize_dispatch` on the returned `PriceScenarios`
3. Replays the resulting schedule against the **realized** clearing prices
4. Computes:
   - **Realized PnL** (the headline number)
   - **Perfect-foresight PnL** (the upper bound — solve with realized prices as input)
   - **Naive baseline PnL** (last-7-days same-MTU mean → optimizer)
   - **% of perfect foresight captured** — *the* slide-deck metric
   - **Forecast accuracy:** MAE, RMSE, sMAPE, pinball at p10/p50/p90, CRPS

```text
                    asof = target_day - 12h
                          │
                          ▼
       ┌─────────── forecaster ────────────┐
       │  PriceScenarios for target_day    │
       └─────────────────┬─────────────────┘
                         │
                         ▼
       ┌────────── optimize_dispatch ───────────┐
       │  schedule + bid_curves + rainflow ...  │
       └─────────────────┬──────────────────────┘
                         │
                         ▼
       ┌─── replay vs realized DAM prices ───┐
       │  realized PnL, % of perfect, accuracy│
       └─────────────────────────────────────┘
                         │
                         ▼
                   BacktestResult
```

## Public API

```python
from src.backtest import (
    Forecaster,                 # the contract — what your forecaster must satisfy
    naive_seasonal_forecaster,  # reference baseline (use it now to test the harness)
    run_walk_forward_backtest,  # the entry point
    BacktestResult,
)
```

## What the FORECASTER needs to expose (the connection)

The backtester only knows one thing about your forecaster: a **single
callable** with this signature:

```python
def forecaster(
    asof: pd.Timestamp,                       # gate-close cutoff (no data after this!)
    target_day: pd.Timestamp,                 # midnight of the delivery day, naive tz
    n_scenarios: int = 30,                    # hint, not strict
    timestamps: pd.DatetimeIndex | None = None,  # the exact delivery-day MTU axis
) -> PriceScenarios:                          # whose .timestamps == timestamps
    ...
```

Hard requirements:

1. **Output is a `PriceScenarios` from `src.optimize`**. That bundle is
   already the optimizer's input contract — same object on both sides.
2. **`scenarios.timestamps` must equal the `timestamps` argument** the
   backtester passes in (the delivery day's MTU axis taken from
   `realized_prices.index`).
3. **PIT discipline:** the forecaster must not consume any feature with
   release time > `asof`. The backtester does not enforce this — your
   forecaster owns the leakage check.
4. **Ensemble form:** at least one scenario; ideally 20-50 reduced
   scenarios with weights summing to 1. Single-scenario (point forecast)
   is allowed; the optimizer collapses to deterministic on it.

If your forecaster needs additional state (model weights, feature store,
TimescaleDB connection, …), close over it in a factory function:

```python
class MyForecaster:
    def __init__(self, model, feature_store): ...
    def __call__(self, asof, target_day, n_scenarios=30, timestamps=None):
        feats = self.feature_store.as_of(asof)
        samples = self.model.sample(feats, n=500)
        return scenarios_fast_forward(timestamps, samples, n_reduced=n_scenarios)
```

## What the BACKTESTER needs from YOU (the connection)

Three things:

1. **`realized_prices`**: a `pandas.Series` of historical DAM clearing
   prices, **DateTime-indexed at the same MTU as `duration_hours`**.
   Must cover the test horizon plus enough history for the forecaster's
   features and the naive baseline's lookback (default 7 days).

   ```python
   realized_prices = pd.read_parquet("data/processed/dam_prices.parquet")
   realized_prices = realized_prices.set_index("timestamp")["MCP"]
   ```

2. **`battery`**: a `BatteryProfile` (use `load_profile(...)` or
   `BatteryProfile.custom(...)`).

3. **`forecaster`**: a callable as defined above.

## Minimal working example (no real forecaster yet)

```python
import pandas as pd
from src.optimize import load_profile
from src.backtest import (
    naive_seasonal_forecaster,
    run_walk_forward_backtest,
)

# 1. Historical clearing prices (DateTime-indexed)
realized = (
    pd.read_parquet("data/processed/dam_prices.parquet")
      .set_index("timestamp")["MCP"]
)

# 2. Battery
battery = load_profile("config/storage_profiles.yaml", "liion_100_2h")

# 3. Naive forecaster as a placeholder
forecaster = naive_seasonal_forecaster(
    history=realized, lookback_days=7, noise_std_eur_per_mwh=20.0,
)

# 4. Pick the test days
test_days = pd.date_range("2026-03-01", "2026-03-14", freq="D")

# 5. Run
bt = run_walk_forward_backtest(
    realized_prices=realized,
    forecaster=forecaster,
    battery=battery,
    test_days=test_days,
    duration_hours=0.25,
    alpha=0.10, risk_aversion=0.5,
    carry_soc=True,
)

print(bt.headline_metrics())
bt.daily_table().to_parquet("reports/backtest_naive_2026-03.parquet")
```

When the real forecaster is ready, swap in:

```python
from src.forecast import build_forecaster   # your teammate's module
forecaster = build_forecaster(...)
```

Nothing else changes.

## Outputs

```python
result = run_walk_forward_backtest(...)

result.headline_metrics()
# {
#   "n_days": 14,
#   "total_realized_pnl_eur": 412_580.12,
#   "total_perfect_foresight_pnl_eur": 528_104.07,
#   "total_naive_pnl_eur": 318_211.66,
#   "overall_pct_of_perfect": 0.781,        # 78.1% of perfect foresight
#   "overall_lift_over_naive": 0.297,       # +29.7% vs naive
#   "avg_forecast_mae_eur_per_mwh": 19.42,
#   "avg_forecast_rmse_eur_per_mwh": 28.07,
#   "avg_forecast_crps_eur_per_mwh": 14.83,
# }

result.daily_table()
# A DataFrame with one row per day, ready for plotting.

result.to_long_dispatch_frame()
# A long frame: every period of every backtested schedule plus the
# realized clearing price. This is what the dashboard consumes.
```

## Files

```text
__init__.py        public API
protocols.py       Forecaster Protocol + naive reference forecaster
metrics.py         point + pinball + CRPS + perfect-foresight + naive baseline
result.py          BacktestDay + BacktestResult containers
walk_forward.py    the run loop
README.md          this file
```

## Notes / gotchas

- **Time zones:** `realized_prices.index` should be in the country's
  delivery-period local time (Europe/Athens for HEnEx). The harness
  strips tz info to keep arithmetic predictable; align your data first.
- **Gate-close convention:** SDAC clears at 12:00 CET on day d-1 for
  delivery on day d. That's the default `gate_close_offset=12h`.
- **15-min vs hourly:** pass `duration_hours=0.25` for SDAC 15-min era,
  `1.0` for the legacy hourly era. The harness does not auto-detect
  this — be deliberate.
- **Carry-over SoC:** `carry_soc=True` is the realistic setting; only
  use `False` for daily-isolated ablations.
- **Cost of bid-curve evaluation:** `build_bid_curves=True` performs
  H × K extra LP solves per day. Default is `False`. Turn it on for the
  dashboard's deep-dive view, not for a 90-day sweep.
- **Forecaster contract leakage:** the harness can't tell whether your
  forecaster cheated (used data after `asof`). Add unit tests on your
  forecaster side that assert PIT correctness.
