# BatteryOS

**End-to-end forecasting, optimization, and backtesting for grid-scale battery energy storage systems (BESS) trading on the Greek Day-Ahead Market (DAM).**

BatteryOS couples a probabilistic price forecaster with a stochastic dispatch optimizer to produce day-ahead charge / discharge schedules and Hellenic Energy Exchange (HEnEx) bid curves. Every component — from raw data ingestion to multi-year degradation tracking — is reproducible, version-controlled, and ready for production deployment.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Data Sources & Challenges](#data-sources--challenges)
3. [Feature Engineering](#feature-engineering)
4. [Forecasting Model](#forecasting-model)
5. [Explainability (SHAP)](#explainability-shap)
6. [Dispatch Optimizer](#dispatch-optimizer)
7. [Backtesting & Evaluation](#backtesting--evaluation)
8. [Quick Start](#quick-start)
9. [Repository Layout](#repository-layout)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            DATA INGESTION                               │
│  ├─ EnExGroup (web scrape) ──► cleaned_dam_results.xlsx                 │
│  ├─ ENTSO-E API ─────────────► entsoe_greece_dam_forecasts.csv          │
│  └─ Open-Meteo API ──────────► openmeteo_weather_master.csv             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         FEATURE ENGINEERING                             │
│  Build master dataset → preprocess → interactions → advanced features   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PROBABILISTIC FORECASTING                           │
│  LightGBM quantile regression → p10 / p50 / p90 price curves            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     STOCHASTIC DISPATCH OPTIMIZER                       │
│  CVaR scenario optimization → day-ahead schedule + bid curves           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     BACKTEST & HEALTH TRACKING                          │
│  Walk-forward evaluation → realized PnL → SOH & cycle budget tracking   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Sources & Challenges

### 1. Hellenic Energy Exchange (EnExGroup) — DAM Results
- **What:** Historical Day-Ahead Market clearing prices (MCP), traded volumes by unit type (lignite, natural gas, RES, hydro, imports/exports), and load classifications.
- **How:** The EnExGroup publications portal is scraped (`src/ingest/enex.py`). Yearly archive ZIPs are downloaded and extracted; recent daily `EL-DAM_Results_EN` Excel files are scraped from paginated asset publishers.
- **Challenge:** EnExGroup switched from **hourly to 15-minute delivery periods (MTUs)** mid-2024. The ingestion layer detects daily resolution automatically and upsamples hourly data by splitting each hour into four 15-minute slots (volume ÷ 4).

### 2. ENTSO-E Transparency Platform — Grid Forecasts
- **What:** Day-ahead load forecasts, wind & solar generation forecasts, and aggregated generation forecasts for Greece ( bidding zone `GR` ).
- **How:** Queried via the official `entsoe-py` client (`src/ingest/entsoe.py`). Requires an `ENTSOE_API_KEY` in your `.env` file.
- **Challenge:** ENTSO-E data is published at **60-minute resolution** (or irregular). It is resampled to a strict 15-minute index with forward-fill so it aligns with DAM prices.
- **Output columns:** `Forecast_Load`, `Forecast_Solar`, `Forecast_Wind`, `Forecast_Aggregated_Gen`, `Total_RES`, `Residual_Load`.

### 3. Open-Meteo — Weather Data
- **What:** Temperature, shortwave radiation, and 100 m wind speed for three Greek geographic hubs: Athens, Thessaly, and Evia.
- **How:** REST calls to `archive-api.open-meteo.com` (historical) and `api.open-meteo.com` (forecasts) (`src/ingest/weather.py`).
- **Challenge:** Hourly observations must be **linearly interpolated** to 15-minute granularity to match the energy datasets.
- **Engineered:** `Cooling_Demand_Athens` and `Heating_Demand_Athens` derived from temperature via degree-day logic.

### 4. Financial & Calendar Data
- **TTF Natural Gas futures** (`TTF=F`) and **EUA Carbon Allowance proxy** (`CO2.L`) are fetched from Yahoo Finance via `yfinance` to compute a break-even gas price (`Break_Even_Gas_Price`).
- **Greek holiday calendar** is built with the `holidays` Python package and used as a binary indicator (`Is_Holiday`).
- **Challenge:** Yahoo Finance can be unavailable or return sparse history. The pipeline falls back to realistic random-walk mocks and attempts to backfill real data during preprocessing.

---

## Feature Engineering

The raw data is merged into a single master feature matrix (`df_master_ml_ready_advanced.csv`) through four stages:

### Stage 1 — Master Dataset Merge (`src/features/builder.py`)
Aligns the three source DataFrames to their common 15-minute timestamps and computes:
- `Break_Even_Gas_Price` — clean spark spread proxy from TTF + EUA
- `Residual_Load_Ramp` — rate of change in residual demand
- `MCP_Lag_24h`, `MCP_Lag_168h` — short and weekly price memory
- `MCP_Rolling_24h_Avg` — recent price level
- `Daily_Battery_Spread` — daily max-min MCP (theoretical arbitrage envelope)
- `Is_Holiday` — binary Greek holiday flag

### Stage 2 — Preprocessing (`src/features/preprocessing.py`)
- **Anti-leakage lagging:** All actual DAM volume columns (`Vol_*`, `Total_Domestic_Load`) are shifted by 96 periods (24 h) so the model never sees future-traded volumes.
- **Cyclical encoding:** Hour, day-of-week, and month are encoded as sine/cosine pairs to preserve circular topology.
- **Real TTF backfill:** A second `yfinance` call attempts to replace mocked TTF prices with real closing prices.
- **Cleanup:** Drops `DDAY`, `DELIVERY_MTU`, and any rows with NaNs introduced by lagging.

### Stage 3 — Interaction Features (`src/features/interactions.py`)
Creates multiplicative and ratio terms that capture physical coupling:
- `Temp_Athens × Forecast_Solar` — hot, sunny afternoons
- `Temp_Athens × Residual_Load` — cooling-driven demand stress
- `Forecast_Wind / Forecast_Load` — wind penetration ratio
- `Is_Holiday × Hour_Sin` — holiday intra-day shape

### Stage 4 — Advanced Features (`src/features/advanced.py`)
- `Rolling_48h_Temp_Max` — heat-wave persistence
- `Consecutive_Days_Above_35C` — cumulative cooling stress
- `Solar_Crash_Velocity` — rate of solar drop-off (evening ramp)
- `Wind_Volatility_6h` — forecast uncertainty proxy
- `MCP_Rolling_Std_24h` — recent price volatility
- `Daily_Peak_to_Trough_Ratio` — asymmetry of the daily price profile
- Greek-specific calendar flags: `Is_Bridge_Day`, `Is_August_Exodus`, `Days_Until_Next_Holiday`

**Final feature count:** ~50–60 columns (varies with available raw data).

---

## Forecasting Model

### Why LightGBM Quantile Regression?
Battery arbitrage is not a point-prediction game. A schedule optimized on a single median forecast can fail catastrophically if prices spike or collapse. We need a **predictive distribution** — specifically low, median, and high scenarios — to feed the stochastic optimizer.

LightGBM was chosen because:
- It handles heterogeneous features (cyclical, weather, financial) without scaling.
- It trains fast on tabular data with ~100k–1M rows.
- It natively supports **quantile regression** via `objective="quantile"`.
- It is robust to missing values and correlated inputs.

### Model Architecture
Three independent models are trained:

| Model | Quantile (α) | Role |
|-------|-------------|------|
| `lgbm_quantile_alpha10` | 0.10 | Lower bound / cheap-price scenario |
| `lgbm_quantile_alpha50` | 0.50 | Median point forecast |
| `lgbm_quantile_alpha90` | 0.90 | Upper bound / expensive-price scenario |

**Hyperparameters (shared):**
- `n_estimators=1000` with early stopping (50 rounds)
- `learning_rate=0.05`, `max_depth=4`, `num_leaves=15`
- `subsample=0.8`, `reg_lambda=1.0`

### Post-Processing
After inference, quantiles are **sorted row-wise** to enforce monotonicity (`p10 ≤ p50 ≤ p90`). This guarantees that the optimizer receives a logically consistent scenario tree.

### Dataset Split Strategy

Because energy time-series have strong temporal autocorrelation, all splits are **strictly chronological** — no random shuffling.

| Split | Date Range | Role |
|-------|-----------|------|
| **Train** | Jan 2023 → 30 Jun 2025 | Fit the gradient boosting trees |
| **Validation** | 1 Jul 2025 → end of data | Early stopping + best-iteration selection |

**Important:** The Jul 2025+ data is used for **validation** (early stopping), not as a hold-out test set. This means the model indirectly "sees" this data to decide when to stop training. The **true** out-of-sample evaluation comes from the **walk-forward backtest** (`run_walkforward_training.py`), which retrains from scratch on expanding windows and evaluates on genuinely unseen future months.

### Evaluation Metrics

After training, the pipeline reports validation-set metrics:

- **MAE (p50):** Mean absolute error of the median forecast
- **Pinball loss:** Proper scoring rule for each quantile
  - Lower pinball loss = better calibrated quantiles

Typical validation performance:
- MAE (p50): **~5–8 €/MWh**
- Pinball loss scales with quantile: p10 and p90 losses are asymmetric by design, reflecting the cost of under- vs over-prediction.

### Daily Inference Pipeline (`pipelines/daily_inference.py`)
Designed to run as a **cron job every morning (~09:00 Europe/Athens)**:
1. Fetches ENTSO-E day-ahead forecasts for tomorrow.
2. Fetches Open-Meteo weather forecasts for tomorrow.
3. Engineers features using 30 days of historical context.
4. Loads pre-trained `.joblib` models and predicts p10/p50/p90.
5. Saves `forecast_YYYY-MM-DD.csv` and appends to `daily_forecasts.csv`.

---

## Explainability (SHAP)

Black-box forecasts are unacceptable for regulated energy assets. BatteryOS uses **SHAP (SHapley Additive exPlanations)** to decompose every prediction.

### Pipeline (`pipelines/explain_last_day_shap.py`)
For the most recent day in the validation period:
1. Trains the three quantile models.
2. Computes **TreeSHAP interaction values** for all 96 intervals.
3. Aggregates main effects (sum over interaction tensor diagonal).
4. Generates a CSV with predictions + per-feature SHAP columns for each quantile.
5. Produces **waterfall plots** for every 15-minute interval showing which features pushed the price up or down.

### Output
- `outputs/df_predictions_shap_last_day_YYYY-MM-DD.csv` — tabular SHAP values
- `outputs/shap_last_day_YYYY-MM-DD/shap_HHMM.png` — 96 waterfall plots (one per interval, 3 quantiles each)

This allows operators to answer: *"Why did the model predict a 120 €/MWh spike at 19:00?"*

---

## Dispatch Optimizer

The optimizer transforms probabilistic price forecasts into a **day-ahead dispatch schedule** and an optional **HEnEx bid curve**. It is the same Mean-CVaR architecture used in production by Habitat Energy, Fluence Mosaic, Tesla Autobidder, and Stem Athena.

### Battery Profiles
Batteries are defined by `BatteryProfile` (`src/optimize/battery.py`) and stored in `config/storage_profiles.yaml`. Six profiles are bundled:

| Profile | Technology | Power | Energy | Duration | RTE |
|---------|-----------|-------|--------|----------|-----|
| `liion_100_2h` | Lithium-ion | 100 MW | 200 MWh | 2 h | 90% |
| `liion_200_2h` | Lithium-ion | 200 MW | 400 MWh | 2 h | 90% |
| `liion_300_2h` | Lithium-ion | 300 MW | 600 MWh | 2 h | 90% |
| `phs_100_8h` | Pumped Hydro | 100 MW | 800 MWh | 8 h | 78.5% |
| `phs_200_8h` | Pumped Hydro | 200 MW | 1,600 MWh | 8 h | 78.5% |
| `flow_100_6h` | Vanadium Flow | 100 MW | 600 MWh | 6 h | 75% |

### Battery Attributes
Each profile specifies:
- **Power & energy** (`power_mw`, `energy_mwh`)
- **SoC bounds** (`soc_min_frac`, `soc_max_frac`)
- **Efficiencies** (`charge_efficiency`, `discharge_efficiency`, `self_discharge_per_hour`)
- **Cycle budgets** (`max_cycles_per_day`, `max_cycles_per_year`, `lifetime_cycles_eol`)
- **Degradation economics** (`degradation_cost_eur_per_mwh`, `cost_escalation_factor`, `eol_soh_threshold`)
- **Transaction cost** (`transaction_cost_eur_per_mwh`) — grid fees and imbalance proxy

### Constraints
The optimizer enforces:
1. **Power limits:** `0 ≤ charge ≤ power_mw`, `0 ≤ discharge ≤ power_mw`
2. **SoC bounds:** `soc_min ≤ state_of_charge ≤ soc_max`
3. **Simultaneity:** Charge and discharge cannot occur in the same period
4. **Cycle cap:** Daily equivalent full cycles ≤ `max_cycles_per_day`
5. **Dynamics:** SoC evolves with efficiency losses and self-discharge
6. **Terminal SoC (optional):** End-of-horizon SoC can be pinned for multi-day linkage

### Optimization Modes
Three scenarios are solved for every day:

| Scenario | Method | Input | Risk Philosophy |
|----------|--------|-------|-----------------|
| **Safe** | `optimize_cvar` | p10 / p50 / p90 as 3 weighted scenarios | Balances expected profit + tail protection (λ = 0.5, α = 0.10) |
| **Regular** | `optimize_deterministic` | p50 median only | Maximize profit on the median forecast |
| **Risky** | `optimize_deterministic` | p90 optimistic | Maximize profit if best-case prices realize |

### CVaR Formulation
The Safe scenario solves:

```
maximize  λ × ExpectedProfit + (1 − λ) × CVaR_α(profit)
```

where:
- `λ = risk_aversion` (0 = risk-neutral, 1 = pure tail protection)
- `α = 0.10` means "average outcome over the worst 10% of scenarios"

This is implemented as a **linear program** via the Rockafellar-Uryasev reformulation (PuLP / CBC).

### Degradation-Aware Dispatch
The optimizer supports **SoC-banded degradation** (`use_soc_banded_degradation`):
1. Solves once with base degradation cost.
2. Maps the resulting SoC trajectory onto stress bands (very low / very high SoC are more damaging).
3. Re-solves with adjusted per-period degradation penalties.
This is a fixed-point linearization that discourages dispatch decisions which park the battery at damaging extremes when the price spread is marginal.

### Output Bundle (`DispatchResult`)
- `schedule` — DataFrame with `charge_mw`, `discharge_mw`, `state_of_charge_mwh`, `action`, `period_profit_eur`
- `bid_curves` — HEnEx-style price-quantity ladder per delivery period
- `rainflow` — Cycle-depth-aware aging score (Wohler-curve based)
- `feasibility` — Constraint compliance report
- `robustness` — Worst-case PnL under battery-parameter perturbations
- `realized_evaluation` — Ex-post PnL when actual MCP is supplied

---

## Backtesting & Evaluation

### Walk-Forward Honesty (`pipelines/run_walkforward_training.py`)
To avoid data leakage, the backtest uses **walk-forward expanding windows**:
- For each month, train on all data up to the end of the previous month.
- Predict the next month.
- Concatenate out-of-sample predictions into `walkforward_predictions.csv`.

If walk-forward predictions are not available, the backtest falls back to in-sample predictions with a prominent warning.

### Daily Backtest Loop (`pipelines/run_backtest.py`)
For every complete day (96 intervals) and every battery profile:
1. Load the effective battery profile adjusted for current **State of Health (SOH)**.
2. Run Safe, Regular, and Risky optimizations.
3. Evaluate each schedule against **actual realized MCP**.
4. Record:
   - Realized profit, market profit, degradation cost, transaction cost
   - Cycles used, throughput MWh, solver status
5. **Update the degradation tracker**:
   - Add cycles to cumulative and rolling-365-day counters
   - Recompute SOH (`linear` or `sqrt` model)
   - Escalate dynamic degradation cost as SOH drops
6. **SoC carry-over:** Final SoC of day *t* becomes initial SoC of day *t*+1.

### Degradation Tracking (`src/optimize/tracker.py`)
`BatteryStateTracker` maintains:
- **Cumulative equivalent full cycles** (lifetime budget)
- **Rolling 365-day cycle count** (annual cap enforcement)
- **State of Health (SOH)** fraction of original capacity
- **Dynamic degradation cost** that rises exponentially as the battery ages
- **End-of-life (EOL) flag** — when SOH drops below `eol_soh_threshold`, the battery is disabled (zero power)

### Backtest Metrics
The backtest produces:
- `outputs/backtest_detailed.csv` — 21,564 rows (1,198 days × 6 profiles × 3 scenarios)
- `outputs/backtest_summary.csv` — aggregated per-profile, per-scenario statistics
- `outputs/backtest_degradation_*_{scenario}.csv` — daily SOH and cycle histories

Key metrics reported:
- **Total realized profit** (€) per profile × scenario
- **Average daily profit** (€/day)
- **Worst / best day** (tail risk)
- **Profit standard deviation** (volatility)
- **Final SOH (%)**, cumulative cycles, annual budget remaining

### Representative Results (1,198 days, Jan 2023 – Apr 2026)

| Profile | Safe (€) | Regular (€) | Risky (€) | Safe vs Risky |
|---------|----------|-------------|-----------|---------------|
| `liion_100_2h` | 33.3 M | 33.3 M | 33.0 M | **+0.9%** |
| `phs_100_8h` | 92.8 M | 93.0 M | 92.2 M | **+0.7%** |
| `flow_100_6h` | 75.6 M | 75.8 M | 75.0 M | **+0.9%** |

**Key finding:** The CVaR-based Safe strategy consistently outperforms the optimistic Risky strategy. Optimizing on p90 causes the battery to discharge too aggressively; when actual prices disappoint, the schedule underperforms. Safe hedges across scenarios and maintains SoC headroom for unexpected spikes.

---

## Quick Start

### Prerequisites
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with your ENTSO-E API key:
```
ENTSOE_API_KEY=your_key_here
```

### Run the Full Pipeline
```bash
# 1. Ingest raw data (EnEx, ENTSO-E, weather)
python -m src.ingest.enex
python -m src.ingest.entsoe
python -m src.ingest.weather

# 2. Train models and build master dataset
python pipelines/run_training_pipeline.py

# 3. Run walk-forward backtest (honest out-of-sample)
python pipelines/run_walkforward_training.py
python pipelines/run_backtest.py

# 4. Explain the most recent day
python pipelines/explain_last_day_shap.py

# 5. Daily cron job (run every morning ~09:00)
python pipelines/daily_inference.py
```

### Key Output Files
| File | Description |
|------|-------------|
| `data/processed/df_master_ml_ready_advanced.csv` | Full feature matrix |
| `outputs/df_predictions.csv` | Test-set p10/p50/p90 + actual |
| `outputs/daily_forecasts.csv` | Running log of daily predictions |
| `outputs/backtest_detailed.csv` | Per-day, per-profile, per-scenario results |
| `outputs/backtest_summary.csv` | Aggregated backtest statistics |
| `outputs/df_predictions_shap_last_day_*.csv` | SHAP explanations |
| `models/lgbm_quantile_alpha*.joblib` | Saved LightGBM models |
| `models/feature_columns.json` | Training column order for inference |

---

## Repository Layout

```
BatteryOS/
├── config/
│   └── storage_profiles.yaml          # Battery catalog
├── data/
│   ├── raw/                           # EnEx, ENTSO-E, weather CSVs/XLSXs
│   └── processed/                     # Master feature matrices
├── models/                            # Saved LightGBM .joblib + feature list
├── outputs/                           # Predictions, backtests, SHAP data
├── pipelines/                         # End-to-end runnable scripts
│   ├── run_training_pipeline.py
│   ├── run_walkforward_training.py
│   ├── run_backtest.py
│   ├── daily_inference.py
│   ├── explain_last_day_shap.py
│   └── save_trained_models.py
├── src/
│   ├── ingest/                        # Data fetchers
│   │   ├── entsoe.py
│   │   ├── weather.py
│   │   └── enex.py
│   ├── features/                      # Feature engineering
│   │   ├── builder.py
│   │   ├── preprocessing.py
│   │   ├── interactions.py
│   │   ├── advanced.py
│   │   └── inference.py
│   ├── forecast/                      # Model training & utilities
│   │   ├── train.py
│   │   ├── utils.py
│   │   └── tune_lightgbm.py
│   └── optimize/                      # Dispatch optimizer
│       ├── battery.py
│       ├── dispatch.py
│       ├── milp.py
│       ├── robust.py
│       ├── schedule.py
│       ├── economics.py
│       ├── tracker.py
│       ├── degradation.py
│       ├── backtest.py
│       └── bid_curves.py
├── tests/                             # Unit tests
├── BACKTEST_REPORT.md                 # Detailed backtest analysis
└── README.md                          # This file
```

---

## License

This project is proprietary and confidential. All rights reserved.
