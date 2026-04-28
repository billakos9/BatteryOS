# BatteryOS Workflow Plan

**Goal:** Build a battery optimization framework for the Greek Day-Ahead Market.

The framework must answer one practical question:

> Given market data, forecasts, and a storage asset specification, when should the battery charge, discharge, or stay idle to maximize economic value?

This document is organized around the actual system we need to build:

1. Data sources
2. Feature engineering
3. Forecasting model
4. Optimizer / economic model
5. Backtesting
6. Demo and business layer

---

## 0. The Whole Workflow

The system should be understood as a pipeline:

```text
Raw Data
  ↓
Cleaned Data
  ↓
Feature Engineering
  ↓
Forecasting Model
  ↓
Optimizer / Economic Model
  ↓
Battery Schedule
  ↓
Backtesting and Evaluation
```

Each block has one job.

| Block | Question it answers | Output |
|---|---|---|
| Data sources | What information do we have? | Raw and cleaned time series |
| Feature engineering | Which signals are useful for prediction? | Model-ready feature table |
| Forecasting | What will DAM prices be tomorrow? | Price forecast |
| Optimizer | Given prices, what should the battery do? | Charge/discharge schedule |
| Backtesting | Would this have worked historically? | Profit, accuracy, robustness metrics |

Important distinction:

```text
Forecasting predicts prices.
Optimization turns predicted prices into battery decisions.
Backtesting tests whether the whole framework makes money.
```

---

## 1. Repository Structure

The project should be structured like this:

```text
BatteryOS/
├── data/
│   ├── raw/                         # Downloaded source files, unchanged
│   ├── processed/                   # Cleaned and aligned market/system/weather data
│   └── features/                    # Final model-ready feature tables
│
├── src/
│   ├── ingest/                      # 1. Data collection
│   │   ├── henex.py                 # HEnEx DAM prices and market curves
│   │   ├── ipto.py                  # IPTO load, RES, ATC, system data
│   │   ├── openmeteo.py             # Weather forecasts
│   │   ├── entsoe.py                # ENTSO-E European market/system data
│   │   ├── gas.py                   # TTF gas price data
│   │   └── carbon.py                # EUA carbon price data
│   │
│   ├── features/                    # 2. Feature engineering
│   │   ├── calendar.py              # Hour, weekday, holiday, season
│   │   ├── market.py                # Price lags, rolling spreads, volatility
│   │   ├── fundamentals.py          # Load, RES, residual load, fuel cost
│   │   ├── cross_border.py          # Neighbor/coupling/German-domino features
│   │   └── build_features.py        # Main feature table builder
│   │
│   ├── forecast/                    # 3. Forecasting models
│   │   ├── naive.py                 # Yesterday/same-hour baseline
│   │   ├── statistical.py           # SARIMAX or similar
│   │   ├── ml.py                    # LightGBM / sklearn model
│   │   └── predict.py               # Common forecast interface
│   │
│   ├── optimize/                    # 4. Optimizer / economic model
│   │   ├── battery.py               # Battery/storage asset definitions
│   │   ├── milp.py                  # Charge/discharge optimization
│   │   ├── robust.py                # Parameter sweep / robust wrapper
│   │   └── economics.py             # Profit, costs, degradation assumptions
│   │
│   ├── backtest/                    # 5. Backtesting
│   │   ├── walk_forward.py          # Gate-close-aware historical simulation
│   │   ├── benchmarks.py            # Perfect foresight and naive benchmarks
│   │   └── metrics.py               # MAE, RMSE, profit, % vs perfect foresight
│   │
│   └── viz/                         # 6. Demo dashboard
│       └── app.py                   # Streamlit app
│
├── configs/
│   ├── countries.yaml               # Market settings by country/zone
│   ├── storage_profiles.yaml        # Battery and storage unit profiles
│   └── feature_specs.yaml           # Feature definitions and release timing
│
├── tests/
│   ├── test_no_leakage.py
│   ├── test_optimizer_constraints.py
│   └── test_backtest.py
│
├── notebooks/                       # Exploration only, not production logic
├── WORKFLOW_PLAN.md
└── .gitignore
```

---

## 2. Module 1: Data Sources

### Purpose

Collect all external information needed to forecast Greek DAM prices and optimize battery dispatch.

### Main Data Sources

| Source | What we need | Why it matters |
|---|---|---|
| HEnEx | DAM clearing prices, aggregated buy/sell curves | Main price signal and market structure |
| IPTO / ADMIE | Load forecasts, RES forecasts, ATC, system data | Greek supply-demand fundamentals |
| Open-Meteo | Temperature, wind, irradiance, cloud cover | Weather drives load, wind, and solar |
| TTF gas | Dutch TTF gas benchmark | Gas often sets marginal electricity price |
| EEX EUA | Carbon allowance price | Carbon cost affects thermal generation cost |
| ENTSO-E | Load, generation, cross-border, outage data | Multi-country context and coupling signals |
| REMIT / outage feeds | Plant outage information | Outages affect supply and price spikes |

### HEnEx DAM Results File Shape

Example file:

```text
20260429_EL-DAM_Results_EN_v01.xlsx
```

This file has one sheet:

```text
EL-DAM_Results
```

Columns:

```text
TARGET
BIDDING_ZONE_DESCR
SIDE_DESCR
DDAY
ASSET_DESCR
CLASSIFICATION
DELIVERY_MTU
DELIVERY_DURATION
SORT
MCP
TOTAL_TRADES
PUB_TIME
VER
```

Important interpretation:

```text
DDAY = delivery day
DELIVERY_MTU = 15-minute delivery timestamp
DELIVERY_DURATION = MTU length, usually 15 minutes after 2025-10-01
MCP = market clearing price, the target price signal
TOTAL_TRADES = cleared/traded quantity for that row category
PUB_TIME = when this version of the market result was published
```

The file is not one row per price. It repeats each 15-minute period across many market categories.

That means one `DELIVERY_MTU` can have many rows:

```text
2026-04-29 00:00:00 + LOAD   + HV           + Buy
2026-04-29 00:00:00 + SUPPLY + Natural Gas  + Sell
2026-04-29 00:00:00 + SUPPLY + RES          + Sell
2026-04-29 00:00:00 + GR-AL  + Exports      + Buy
2026-04-29 00:00:00 + AL-GR  + Imports      + Sell
...
```

So the timestamp is shared, but the row category changes.

```text
Buy / Sell
LOAD / SUPPLY / STORAGE / cross-border assets
RES / Natural Gas / Lignite / Big Hydro / Imports / Exports / etc.
```

For the forecasting target, we should collapse those repeated rows into one price per delivery MTU, because `MCP` is the same across all categories for the same timestamp:

```text
target_timestamp = DELIVERY_MTU
target_price = MCP
country = GR
market = DAM
published_at = PUB_TIME
```

For market-structure features, we can aggregate the repeated rows:

```text
load_quantity = sum TOTAL_TRADES where SIDE_DESCR = Buy and ASSET_DESCR = LOAD
res_sell_quantity = sum TOTAL_TRADES where CLASSIFICATION = RES and SIDE_DESCR = Sell
gas_sell_quantity = sum TOTAL_TRADES where CLASSIFICATION = Natural Gas
import_quantity = sum TOTAL_TRADES where CLASSIFICATION = Imports
export_quantity = sum TOTAL_TRADES where CLASSIFICATION = Exports
storage_buy_quantity = sum TOTAL_TRADES where ASSET_DESCR = STORAGE and SIDE_DESCR = Buy
storage_sell_quantity = sum TOTAL_TRADES where ASSET_DESCR = STORAGE and SIDE_DESCR = Sell
```

So the HEnEx ingestion should create two processed tables:

```text
dam_prices.parquet
  one row per DELIVERY_MTU
  this is the clean price target table

dam_market_results_by_category.parquet
  one row per DELIVERY_MTU × SIDE_DESCR × ASSET_DESCR × CLASSIFICATION
  this keeps the repeated category rows for feature engineering
```

### Output

The data layer should produce cleaned time series such as:

```text
timestamp
country
dam_price
load_forecast
wind_forecast
solar_forecast
temperature_forecast
gas_price
carbon_price
cross_border_capacity
```

### Rule

Raw data should be saved unchanged in `data/raw/`.

Cleaned, aligned data should be saved in `data/processed/`.

---

## 3. Module 2: Feature Engineering

### Purpose

Turn raw data into useful prediction signals.

Feature engineering is where we:

- remove useless/noisy data
- combine useful data
- create stronger signals
- prevent data leakage
- prepare the final model input table

### Core Features

#### Calendar Features

```text
hour
day_of_week
weekend_flag
month
season
holiday_flag
dst_flag
```

These capture repeated price patterns.

#### Price Lag Features

```text
price_lag_1d
price_lag_2d
price_lag_7d
rolling_mean_7d
rolling_volatility_7d
daily_spread_lag_1d
```

These capture market memory.

#### Residual Load Features

Residual load is one of the most important electricity-market features:

```text
residual_load_forecast = load_forecast - wind_forecast - solar_forecast
```

Why it matters:

- high residual load usually means higher prices
- low residual load usually means lower prices
- negative or very low residual load can indicate curtailment or negative-price risk

#### Fuel and Carbon Features

```text
gas_price
carbon_price
gas_price_7d_change
carbon_price_7d_change
implied_gas_generation_cost
```

These estimate the cost of thermal generation.

#### Weather Features

```text
temperature_forecast
wind_speed_forecast
solar_irradiance_forecast
cloud_cover_forecast
heating_degree_days
cooling_degree_days
```

Weather affects both demand and renewable production.

#### Cross-Border / German-Domino Features

Greek prices are affected by European market coupling, not only Greek fundamentals.

Useful features:

```text
DE_residual_load_forecast
IT_S_residual_load_forecast
BG_residual_load_forecast
central_corridor_surplus
eastern_corridor_surplus
continental_wind_index
continental_solar_index
GR_IT_cross_border_capacity
GR_BG_cross_border_capacity
```

These capture whether cheap or expensive electricity pressure is moving through Europe toward Greece.

### Leakage Rule

For day-ahead forecasting, we must only use data that would have been available before the market gate close.

```text
If the model predicts delivery day D,
features must be available by gate close on D-1.
```

Do not use realized load, realized RES, or final data that would only be known after delivery.

### Output

The feature layer should produce a table like:

```text
target_timestamp
asof_timestamp
country
target_price
hour
weekday
price_lag_1d
residual_load_forecast
gas_price
carbon_price
DE_residual_load_forecast
...
```

`target_price` is what the model tries to predict.

`asof_timestamp` is when the feature was known.

---

## 4. Module 3: Forecasting Model

### Purpose

Predict future DAM prices.

The optimizer needs a price curve for the next delivery day.

For Greece after 1 October 2025, this means:

```text
96 prices per day = 24 hours × 4 quarter-hours
```

### Forecasting Ladder

Build models in order of complexity.

| Level | Model | Why we need it |
|---|---|---|
| R1 | Naive baseline | Minimum benchmark |
| R2 | Statistical model | Interpretable time-series baseline |
| R3 | ML model | Uses engineered features well |
| R4 | Quantile model | Gives uncertainty, not only point forecasts |
| R5 | Advanced time-series model | Stretch goal if time allows |

### R1: Naive Baseline

Examples:

```text
tomorrow_price = yesterday_same_period_price
tomorrow_price = last_week_same_period_price
```

This is simple but essential. If the advanced model cannot beat this, the advanced model is useless.

### R2: Statistical Model

Possible model:

```text
SARIMAX(price ~ residual_load + gas + carbon + calendar)
```

Good for interpretability.

### R3: Machine Learning Model

Preferred hackathon model:

```text
LightGBM / RandomForest / XGBoost-style tabular model
```

Inputs:

```text
engineered feature table
```

Output:

```text
predicted DAM price for each future 15-minute period
```

### R4: Probabilistic Forecast

Instead of predicting only one price:

```text
p10_price
p50_price
p90_price
```

This helps the optimizer become more robust.

### Forecast Metrics

Use normal forecast metrics:

```text
MAE
RMSE
sMAPE
pinball loss for quantiles
```

But the most important metric is decision-aware:

```text
How much profit did the forecast create after optimization?
```

---

## 5. Module 4: Optimizer / Economic Model

### Purpose

Turn the price forecast into a battery schedule.

The optimizer answers:

```text
When should the battery charge?
When should it discharge?
When should it stay idle?
```

### Important Correction

The optimizer does not forecast prices.

The optimizer consumes the forecast and applies:

- battery physics
- operational constraints
- economic objective
- robustness assumptions

### Inputs

```text
forecasted_price[t]
battery_power_mw
battery_energy_mwh
round_trip_efficiency
minimum_soc
maximum_soc
starting_soc
cycle_limit
degradation_cost
```

### Decision Variables

For every time period `t`:

```text
charge_power[t]
discharge_power[t]
state_of_charge[t]
is_charging[t]
```

### Constraints

The optimizer must respect:

```text
0 <= charge_power[t] <= max_charge_power
0 <= discharge_power[t] <= max_discharge_power
min_soc <= state_of_charge[t] <= max_soc
cannot charge and discharge at the same time
state_of_charge evolves correctly through time
cycle limit is not exceeded
terminal state_of_charge rule is respected
```

### Objective

Maximize expected profit:

```text
profit =
  revenue from discharging
  - cost of charging
  - degradation cost
```

Simple version:

```text
maximize Σ price[t] × (discharge_power[t] - charge_power[t]) × Δt
```

More realistic version:

```text
maximize market_profit - degradation_cost - risk_penalty
```

### Storage Profiles

Example profiles:

| Profile | Power | Duration | Energy |
|---|---:|---:|---:|
| liion_100_2h | 100 MW | 2 h | 200 MWh |
| liion_200_2h | 200 MW | 2 h | 400 MWh |
| liion_300_2h | 300 MW | 2 h | 600 MWh |
| phs_100_8h | 100 MW | 8 h | 800 MWh |
| phs_200_8h | 200 MW | 8 h | 1600 MWh |
| flow_100_6h | 100 MW | 6 h | 600 MWh |

### Output

The optimizer should produce:

```text
timestamp
forecasted_price
charge_power
discharge_power
state_of_charge
expected_profit
action
```

Where action is:

```text
CHARGE
DISCHARGE
IDLE
```

---

## 6. Module 5: Backtesting

### Purpose

Test the whole framework as if we were operating historically.

Backtesting is not just model accuracy. It tests the complete chain:

```text
data → features → forecast → optimizer → realized profit
```

### Walk-Forward Backtest

For every historical test day:

```text
1. Pretend we are at gate close on D-1.
2. Use only data available at that time.
3. Build features.
4. Predict prices for delivery day D.
5. Optimize the battery schedule.
6. Apply the schedule to the actual realized prices of D.
7. Calculate realized profit.
8. Move to the next day.
```

### Pseudocode

```text
for each delivery_day in test_period:
    asof = delivery_day - 1 at gate_close

    train_data = data_available_before(asof)
    features = build_features(asof)
    price_forecast = model.predict(features)
    schedule = optimizer.solve(price_forecast, battery_profile)

    actual_prices = get_actual_prices(delivery_day)
    realized_profit = evaluate(schedule, actual_prices)

    save_result(delivery_day, price_forecast, schedule, realized_profit)
```

### Benchmarks

We need benchmarks to know whether the system is good.

| Benchmark | Meaning |
|---|---|
| Naive forecast | What happens with a simple forecast |
| Perfect foresight | Best possible result if prices were known exactly |
| No operation | Battery does nothing |
| Greek-only features | Model without multi-country features |
| Multi-country features | Model with European coupling features |

### Metrics

Forecast metrics:

```text
MAE
RMSE
sMAPE
```

Economic metrics:

```text
cumulative_profit
profit_per_mw
profit_vs_naive
profit_vs_perfect_foresight
number_of_cycles
worst_case_profit
```

The headline metric should be:

```text
realized profit as % of perfect-foresight profit
```

---

## 7. Demo Layer

The dashboard is not the core system. It is just how we show the system.

Suggested Streamlit pages:

### Page 1: Dispatch

Inputs:

```text
country
date
storage profile
forecast model
robust mode on/off
```

Outputs:

```text
forecast price curve
charge/discharge schedule
state of charge curve
expected profit
```

### Page 2: Backtest Results

Show:

```text
cumulative profit
profit vs naive
profit vs perfect foresight
forecast error
worst-case robustness result
```

### Page 3: Feature / Moat View

Show:

```text
which feature groups are used
which features matter most
Greek-only vs multi-country performance
German-domino feature effect
```

### Page 4: Business View

Show:

```text
target customer
pricing model
TAM
roadmap
why the data pipeline is defensible
```

---

## 8. Build Order

Do not build everything at once.

### Day 1: Working Greek MVP

Goal:

```text
one end-to-end pipeline that works, even if simple
```

Tasks:

1. Create repo structure.
2. Add storage profiles config.
3. Add country config for Greece.
4. Load or mock Greek DAM prices.
5. Build naive forecast.
6. Build optimizer.
7. Run one backtest.
8. Report profit vs perfect foresight.

Day 1 success means:

```text
we can go from price data to battery schedule to realized profit
```

### Day 2: Better Features and Better Forecasting

Goal:

```text
make the forecast better and prove it improves profit
```

Tasks:

1. Add IPTO load and RES data.
2. Add Open-Meteo weather.
3. Create residual load features.
4. Add gas and carbon features.
5. Train ML model.
6. Compare against naive forecast.
7. Add multi-country features if time allows.

Day 2 success means:

```text
engineered features improve economic backtest results
```

### Day 3: Robustness, Demo, Business Story

Goal:

```text
turn the framework into a convincing product demo
```

Tasks:

1. Add parameter sweep for battery uncertainty.
2. Add dashboard.
3. Show multiple storage profiles.
4. Show backtest results.
5. Show feature importance.
6. Prepare pitch narrative.

Day 3 success means:

```text
the demo shows a realistic battery optimization business, not just a model
```

---

## 9. What To Build First

The first real implementation should be minimal:

```text
src/optimize/battery.py
src/optimize/milp.py
src/forecast/naive.py
src/backtest/walk_forward.py
configs/storage_profiles.yaml
configs/countries.yaml
```

Why this first?

Because the optimizer and backtest prove the business value. A beautiful forecast is useless unless it makes better battery decisions.

The first target is:

```text
historical prices → naive forecast → optimized schedule → realized profit
```

After that works, improve the data and features.

---

## 10. Critical Rules

### Rule 1: No Leakage

Never use information that would not have been available at decision time.

Bad:

```text
using actual solar production to forecast tomorrow's price
```

Good:

```text
using solar forecast available before gate close
```

### Rule 2: Forecast First, Optimize Second

Do not mix the model and optimizer into one unclear block.

Correct:

```text
features → forecast → optimizer → schedule
```

### Rule 3: Evaluate Profit, Not Only Accuracy

A model with lower MAE is not automatically better.

The real question:

```text
did it create more battery profit?
```

### Rule 4: Use Perfect Foresight as the Ceiling

Perfect foresight tells us the maximum possible profit for that day.

Then we can say:

```text
our system captured 72% of perfect-foresight value
```

### Rule 5: Battery Parameters Are Uncertain

Because battery telemetry is scarce, use parameter ranges:

```text
round_trip_efficiency: 86% to 92%
state_of_charge_min: 10% to 20%
state_of_charge_max: 80% to 90%
cycle_limit: 1 to 2 cycles/day
```

Then test whether the schedule still works under different assumptions.

---

## 11. Business Framing

The technical product is:

```text
a storage-agnostic battery dispatch optimization service
```

The first customer is:

```text
a Greek standalone BESS operator entering the Day-Ahead Market
```

The business value is:

```text
turn uncertain market data and limited battery telemetry into feasible, profitable dispatch decisions
```

The moat is not just the model.

The moat is:

```text
multi-source data assembly
point-in-time feature engineering
cross-border market coupling features
backtested economic performance
customer telemetry over time
```

---

## 12. Final Mental Model

Remember the system like this:

```text
DATA SOURCE
    gives raw information

FEATURE ENGINEERING
    creates useful predictive signals

FORECASTING MODEL
    predicts future prices

OPTIMIZER / ECONOMIC MODEL
    converts prices into battery actions

BACKTESTING
    proves whether the whole chain works
```

That is the structure of BatteryOS.
