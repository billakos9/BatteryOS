# BatteryOS Forecasting Pipeline — Technical Report

> **Scope:** This document describes the complete data ingestion, feature engineering, and probabilistic forecasting pipeline built for Greek Day-Ahead Market (DAM) Marginal Clearing Price (MCP) prediction. The optimizer (`src/optimize/`) is outside the scope of this report.

---

## 1. Executive Summary

We have built a production-ready, end-to-end forecasting system for the Greek electricity Day-Ahead Market. The pipeline ingests data from three primary sources (Hellenic Energy Exchange, ENTSO-E, and Open-Meteo), engineers 53 features, trains a probabilistic LightGBM quantile regression model, and runs daily automated inference via a cron job.

**Key achievements:**
- **115,795 rows** of 15-minute aligned historical data (Jan 2023 – Apr 2026)
- **53 engineered features** including market lags, weather, calendar, and financial signals
- **Probabilistic forecasts** at p10 / p50 / p90 with early stopping and quantile monotonicity enforcement
- **Test MAE (p50): 16.98 €/MWh**
- **SHAP explainability** for every interval on the last day
- **Automated daily inference** scheduled at 9:00 AM Europe/Athens

---

## 2. Data Sources & Ingestion

### 2.1 Hellenic Energy Exchange (EnExGroup) — Actual DAM Results

**What:** Historical Day-Ahead Market cleared volumes and Marginal Clearing Prices (MCP) for Greece.

**Source:** `cleaned_dam_results.xlsx` (produced by `clean_dam_data.py` from EnExGroup ZIP archives)

**Columns ingested:**
- `MCP` — Marginal Clearing Price (€/MWh) — **this is the prediction target**
- `Vol_Big_Hydro`, `Vol_Lignite`, `Vol_Natural_Gas`, `Vol_RES`, `Vol_PUMP`, `Vol_Storage`
- `Vol_Exports`, `Vol_Imports`
- `Vol_CRETE_CONVENTIONAL`, `Vol_CRETE_RENEWABLES`
- `Total_Domestic_Load`

**Frequency:** 15-minute intervals (historical data was hourly, upsampled to 15-min)

**Scripts:**
- `download_and_combine_dam.py` — Downloads and aggregates raw EnEx data
- `clean_dam_data.py` — Cleans, pivots, and upsamples to 15-minute frequency

---

### 2.2 ENTSO-E Transparency Platform — Day-Ahead Forecasts

**What:** Day-ahead forecasts for load, wind, solar, and total generation published by IPTO (Greek TSO).

**API:** ENTSO-E Transparency Platform via `entsoe-py`

**Queries used:**
| Query | Document | What it returns |
|---|---|---|
| `query_load_forecast` | A65 | Day-ahead total electricity demand forecast (MW) |
| `query_wind_and_solar_forecast` | A71 + psrType | Day-ahead solar PV and wind onshore forecasts (MW) |
| `query_generation_forecast` | A71 | Day-ahead total generation forecast (MW) |

**Frequency:** Hourly (upsampled to 15-minute via forward-fill)

**Key engineered columns:**
- `Forecast_Load`, `Forecast_Solar`, `Forecast_Wind`, `Forecast_Aggregated_Gen`
- `Total_RES = Forecast_Solar + Forecast_Wind`
- `Residual_Load = Forecast_Load - Total_RES` — *net load that must be served by dispatchable plants*

**Script:** `fetch_entsoe_residual_load.py`

---

### 2.3 Open-Meteo — Weather Data

**What:** Historical and forecast weather data for three Greek geographic hubs.

**Hubs:**
| Hub | Lat | Lon | Role |
|---|---|---|---|
| Athens | 37.98 | 23.72 | Demand center |
| Thessaly | 39.63 | 22.41 | Solar generation hub |
| Evia | 38.05 | 24.45 | Wind generation hub |

**Variables fetched:** `temperature_2m`, `shortwave_radiation`, `wind_speed_100m`

**API:** `https://archive-api.open-meteo.com/v1/archive` (historical), `https://api.open-meteo.com/v1/forecast` (inference)

**Processing:**
- Requested in UTC, converted to `Europe/Athens`
- Hourly data resampled to 15-minute via `interpolate(method='linear')`
- Columns prefixed by hub: `Temp_Athens`, `Solar_Rad_Thessaly`, `Wind_Spd_Evia`, etc.

**Script:** `fetch_openmeteo_weather.py`

---

### 2.4 Financial Data — Commodity Prices

**What:** Natural gas and EU carbon allowance prices to compute the break-even gas price (clean spark spread).

| Commodity | Ticker | Source |
|---|---|---|
| Dutch TTF Natural Gas | `TTF=F` | yfinance |
| EUA Carbon (proxy) | `CO2.L` | yfinance (WisdomTree Carbon ETF) |

**Formula:**
```
Break_Even_Gas_Price = (TTF_Price / 0.50) + (EUA_Price × 0.20)
```
- `÷ 0.50` = 50% CCGT plant efficiency
- `× 0.20` = 0.2 tCO₂/MWh emission factor

This feature acts as a **soft price floor** because gas plants are often the marginal price-setter in Greece.

---

## 3. Feature Engineering

The final dataset contains **53 columns** (1 target + 52 features).

### 3.1 Base Features (from raw data)

- `Forecast_Load`, `Forecast_Solar`, `Forecast_Wind`, `Forecast_Aggregated_Gen`
- `Total_RES`, `Residual_Load`
- `Temp_Athens`, `Solar_Rad_Athens`, `Wind_Spd_Athens`, etc. (9 weather columns)
- `Cooling_Demand_Athens = max(0, Temp_Athens - 22)`
- `Heating_Demand_Athens = max(0, 18 - Temp_Athens)`
- `Break_Even_Gas_Price`
- `Is_Holiday` (binary, from `holidays` package)

### 3.2 Lagged Market Features

| Feature | Shift | Rationale |
|---|---|---|
| `MCP_Lag_24h` | 96 periods (1 day) | Yesterday's price at same time — strongest single predictor |
| `MCP_Lag_168h` | 672 periods (7 days) | Same time last week — weekly seasonality |
| `MCP_Rolling_24h_Avg` | 96-period rolling mean | Smoothed recent price level |
| `MCP_Rolling_Std_24h` | 96-period rolling std | Recent price volatility |

### 3.3 Data Leakage Fix — Lagged Volumes

All actual DAM volume columns (`Vol_Big_Hydro`, `Vol_Lignite`, etc.) are **lagged by 24 hours** (96 periods) to prevent data leakage. The original un-lagged columns are dropped.

### 3.4 Cyclical Time Features

```python
Hour_Sin     = sin(2π × hour / 24)
Hour_Cos     = cos(2π × hour / 24)
DayOfWeek_Sin = sin(2π × dayofweek / 7)
DayOfWeek_Cos = cos(2π × dayofweek / 7)
Month_Sin    = sin(2π × month / 12)
Month_Cos    = cos(2π × month / 12)
```

### 3.5 Interaction Features

| Feature | Formula | Rationale |
|---|---|---|
| `Load_Cost_Interaction` | `Residual_Load × Break_Even_Gas_Price` | Scarcity amplifies marginal cost |
| `Solar_Hour_Interaction` | `Forecast_Solar × Hour_Sin` | Solar effect peaks at midday |
| `Temp_August_Interaction` | `Temp_Athens × Is_August_Exodus` | Cooling demand differs in August |

### 3.6 Advanced Non-Linear Features

| Feature | Description |
|---|---|
| `Is_Bridge_Day` | Binary: Monday before Tuesday holiday, or Friday after Thursday holiday |
| `Is_August_Exodus` | Binary: August = massive drop in Athenian industrial demand |
| `Days_Until_Next_Holiday` | Integer count of days until next Greek public holiday |
| `Rolling_48h_Temp_Max` | 48-hour rolling maximum of Athens temperature |
| `Consecutive_Days_Above_35C` | Counter of consecutive days with max temp > 35°C |
| `Solar_Crash_Velocity` | `Forecast_Solar.diff(1)` — rapid sunset ramp detection |
| `Wind_Volatility_6h` | 6-hour rolling standard deviation of wind forecast |
| `Daily_Battery_Spread` | `Daily_Max_MCP - Daily_Min_MCP` per calendar day |
| `Daily_Peak_to_Trough_Ratio` | Safe ratio of daily max/min MCP (handles negative prices) |

### 3.7 Feature Engineering Pipeline

The feature engineering is modular and lives in `src/features/`:

```
src/features/
├── interactions.py      # Load_Cost, Solar_Hour, Temp_August interactions
├── builder.py           # Master dataset builder (financial + merge)
├── preprocessing.py     # Lags, cyclical features, leakage fixes
└── advanced.py          # Calendar, thermal stress, duck curve, volatility
```

---

## 4. Forecasting Models

### 4.1 Model Architecture

We use **LightGBM Quantile Regression** to predict the 10th, 50th, and 90th percentiles of MCP independently.

**Why quantile regression?**
- Provides **confidence intervals** (p10–p90) for downstream decision-making
- Each quantile can capture different aspects of the price distribution
- More robust to heteroscedasticity than mean regression

### 4.2 Hyperparameters

```python
lgb.LGBMRegressor(
    objective="quantile",
    alpha=alpha,              # 0.10, 0.50, 0.90
    n_estimators=1000,
    learning_rate=0.05,
    max_depth=4,
    num_leaves=15,
    subsample=0.8,
    reg_lambda=1.0,
    random_state=42,
)
```

**Anti-overfitting design:**
- `max_depth=4` and `num_leaves=15` strictly limit model complexity
- `reg_lambda=1.0` applies L2 regularization
- `subsample=0.8` introduces row sampling
- **Early stopping** (`stopping_rounds=50`) prevents training past the validation minimum

### 4.3 Training & Validation

**Split:** Chronological (no shuffling)
- **Train:** 2023-01-01 → 2025-06-30 (86,660 rows)
- **Test:** 2025-07-01 → 2026-04-29 (29,040 rows)

**Metrics:**

| Metric | Value |
|---|---|
| **Test MAE (p50 median)** | **16.98 €/MWh** |
| Pinball loss (α=0.10) | 3.98 €/MWh |
| Pinball loss (α=0.50) | 8.50 €/MWh |
| Pinball loss (α=0.90) | 4.19 €/MWh |

### 4.4 Quantile Crossing Fix

Since each quantile is trained independently, there is no guarantee that `p10 ≤ p50 ≤ p90`. We enforce monotonicity via post-processing:

```python
def sort_quantiles(df):
    vals = df[["Pred_p10", "Pred_p50", "Pred_p90"]].values.copy()
    vals.sort(axis=1)
    df["Pred_p10"], df["Pred_p50"], df["Pred_p90"] = vals[:, 0], vals[:, 1], vals[:, 2]
    return df
```

### 4.5 Optuna Hyperparameter Tuning

An optional tuning script (`src/forecast/tune_lightgbm.py`) runs 100 Optuna trials per quantile with `MedianPruner` to find optimal hyperparameters. Tuned params are saved to `config/lightgbm_quantile_params.yaml`.

**Tuning search space:**
- `learning_rate`: log-uniform [0.01, 0.15]
- `max_depth`: integer [3, 8]
- `num_leaves`: integer [10, 50]
- `subsample`: uniform [0.6, 1.0]
- `reg_lambda`: log-uniform [0.1, 5.0]

### 4.6 Model Files

Saved to `models/` using `joblib`:
- `lgbm_quantile_alpha10.joblib`
- `lgbm_quantile_alpha50.joblib`
- `lgbm_quantile_alpha90.joblib`
- `feature_columns.json` — exact column order for inference alignment

---

## 5. SHAP Explainability

### 5.1 What SHAP Provides

SHAP (SHapley Additive exPlanations) gives **individual prediction explanations** — for any single 15-minute interval, we can see exactly which features pushed the predicted price up or down.

### 5.2 Implementation

- **Explainer:** `shap.TreeExplainer` (exact, native to LightGBM)
- **Interaction values:** Computed via `shap_interaction_values()` — captures pairwise feature interactions
- **Main effects:** Summed across the interaction matrix diagonal

### 5.3 Outputs

For the **last day** in the test set (April 29, 2026):

**CSV:** `outputs/df_predictions_shap_last_day_2026-04-29.csv`
- 56 rows (intervals from midnight to 13:45)
- 160 columns:
  - 4 prediction columns (`Pred_p10`, `Pred_p50`, `Pred_p90`, `Actual`)
  - 52 SHAP columns for p10 (`SHAP_MCP_Lag_24h_q10`, `SHAP_Residual_Load_q10`, ...)
  - 52 SHAP columns for p50
  - 52 SHAP columns for p90

**Waterfall plots:** `outputs/shap_last_day_2026-04-29/`
- 56 PNG files (`shap_0000.png` through `shap_1315.png`)
- Each plot shows 3 side-by-side waterfalls (p10, p50, p90)
- Top 10 most influential features per interval
- Red bars = pushed price **up**, Blue bars = pushed price **down**

### 5.4 How to Query SHAP Values

```python
import pandas as pd

df = pd.read_csv(
    "outputs/df_predictions_shap_last_day_2026-04-29.csv",
    index_col=0, parse_dates=True
)

# What drove the p50 prediction at 10:00 AM?
row = df.loc["2026-04-29 10:00:00+03:00"]
shap_cols = [c for c in df.columns if c.startswith("SHAP_") and c.endswith("_q50")]
shap_values = row[shap_cols].sort_values(key=abs, ascending=False)
print(shap_values.head(10))
```

---

## 6. Automated Daily Inference

### 6.1 Cron Job Schedule

Runs **every day at 9:00 AM Europe/Athens**:
```cron
0 9 * * * cd /home/dimit/BatteryOS && .venv/bin/python pipelines/daily_inference.py >> logs/daily_inference.log 2>&1
```

Setup: `bash scripts/setup_cron.sh`

### 6.2 What the Daily Inference Pipeline Does

| Step | Action | Data Source |
|---|---|---|
| 1 | Determine tomorrow's date from historical dataset | Local CSV |
| 2 | Fetch ENTSO-E day-ahead forecasts | `entsoe-py` (load, wind, solar, generation) |
| 3 | Fetch weather forecasts for 3 hubs | Open-Meteo Forecast API |
| 4 | Fetch latest TTF & EUA prices | yfinance |
| 5 | Load last 30 days of historical context | `df_master_ml_ready_advanced.csv` |
| 6 | Engineer all 52 features | Same pipeline as training |
| 7 | Load 3 pre-trained LightGBM models | `models/*.joblib` |
| 8 | Predict p10 / p50 / p90 for 96 intervals | Inference |
| 9 | Enforce monotonicity | `sort_quantiles()` |
| 10 | Save predictions | `outputs/daily_forecasts.csv` + dated file |

### 6.3 Output Files

| File | Description |
|---|---|
| `outputs/daily_forecasts.csv` | Running log of all daily predictions |
| `outputs/forecast_YYYY-MM-DD.csv` | Dated forecast file for archival |
| `logs/daily_inference.log` | Execution log with timestamps |

### 6.4 Sample Forecast Output

```csv
,Pred_p10,Pred_p50,Pred_p90
2026-04-30 00:00:00+03:00,77.57,104.56,122.12
2026-04-30 00:15:00+03:00,73.86,98.74,111.73
2026-04-30 00:30:00+03:00,70.93,94.22,112.22
...
2026-04-30 23:45:00+03:00,48.40,101.23,156.38
```

**Statistics for April 30, 2026:**
- p50 range: 48.40 – 156.38 €/MWh
- Average p10–p90 spread: 66.73 €/MWh

---

## 7. Repository Structure

```
BatteryOS/
│
├── pipelines/
│   ├── run_training_pipeline.py      # End-to-end training
│   ├── run_optuna_tuning.py          # Hyperparameter tuning
│   ├── daily_inference.py            # Daily cron inference script
│   ├── save_trained_models.py        # Serialize models for inference
│   └── explain_last_day_shap.py      # SHAP explainability
│
├── src/
│   ├── features/
│   │   ├── interactions.py           # Interaction feature engineering
│   │   ├── builder.py                # Master dataset builder
│   │   ├── preprocessing.py          # Lags, cyclical, leakage fixes
│   │   └── advanced.py               # Calendar, thermal, volatility
│   └── forecast/
│       ├── utils.py                  # Quantile post-processing
│       └── tune_lightgbm.py          # Optuna tuning logic
│
├── models/
│   ├── lgbm_quantile_alpha10.joblib
│   ├── lgbm_quantile_alpha50.joblib
│   ├── lgbm_quantile_alpha90.joblib
│   └── feature_columns.json
│
├── outputs/
│   ├── df_predictions.csv            # Standard test-set predictions
│   ├── df_predictions_tuned.csv      # Tuned model predictions
│   ├── df_predictions_shap_last_day_*.csv
│   ├── daily_forecasts.csv           # Running daily inference log
│   ├── forecast_YYYY-MM-DD.csv       # Dated daily forecasts
│   └── shap_last_day_*/              # Waterfall plot directories
│
├── scripts/
│   └── setup_cron.sh                 # Cron installation helper
│
├── config/
│   ├── storage_profiles.yaml         # Battery profiles (optimizer)
│   └── lightgbm_quantile_params.yaml # Tuned hyperparameters
│
├── requirements.txt
└── .env                              # ENTSOE_API_KEY
```

---

## 8. Key Scripts & Usage

### Train the full pipeline (one-time or periodic retraining)
```bash
cd /home/dimit/BatteryOS
source .venv/bin/activate
python pipelines/run_training_pipeline.py
```

### Save models for inference
```bash
python pipelines/save_trained_models.py
```

### Run daily inference manually (for testing)
```bash
python pipelines/daily_inference.py
```

### Generate SHAP explanations for the last day
```bash
python pipelines/explain_last_day_shap.py
```

### Run Optuna hyperparameter tuning
```bash
python pipelines/run_optuna_tuning.py
```

### Install cron job
```bash
bash scripts/setup_cron.sh
```

---

## 9. Known Limitations & Future Work

| Limitation | Impact | Potential Fix |
|---|---|---|
| **EUA proxy** | `CO2.L` is an ETF, not direct EUA futures | Scrape EEX settlement prices directly |
| **Mock fallback** | If APIs fail, pipeline falls back to mock data | Add alerting / retry logic |
| **Volume lags** | Yesterday's actual volumes may not be available by 9 AM | Use day-ahead volume forecasts if available |
| **No cross-border flows** | Missing import/export forecasts from ENTSO-E | Add `query_crossborder_flows` |
| **Static hyperparameters** | Default params used unless Optuna is run | Load tuned params from YAML by default |
| **Feature drift** | Model not retrained automatically on new data | Add weekly/monthly retraining cron job |
| **SHAP interaction cost** | Computing interaction values is slow | Cache explainer or compute on-demand |

---

## 10. Performance Summary

| Metric | Value |
|---|---|
| Historical data span | Jan 1, 2023 → Apr 29, 2026 |
| Total rows | 115,795 |
| Features | 52 |
| Frequency | 15-minute intervals |
| Test MAE (p50) | **16.98 €/MWh** |
| Test Pinball (p10) | 3.98 €/MWh |
| Test Pinball (p90) | 4.19 €/MWh |
| Quantile crossings | 0 (post-processed) |
| Daily inference latency | ~30–60 seconds |
| Model load time | <1 second |

---

*Document version: 2026-04-29*
*Last updated after: SHAP explainability + daily inference cron job implementation*
