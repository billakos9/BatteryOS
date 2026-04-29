# BatteryOS UI Guide

This document explains what a user sees in the current BatteryOS frontend and what each page is trying to communicate.

Important distinction:

- The Dashboard and Optimizer pages now read optimizer artifacts from the FastAPI backend.
- Several Forecaster, Backtest, Sources, and ticker values are still static or synthetic demo UI data until those backend modules are connected.

## Shared Layout

Every main app page uses the same dark BatteryOS shell.

### Left Sidebar

The sidebar is the main navigation.

- Dashboard: latest dispatch overview.
- Forecaster: price forecast workflow and forecast diagnostics.
- Optimizer: Optimizer V1 controls, solve output, scenario input, and robustness.
- Backtest: historical economic replay.
- Assets: storage asset profiles.
- Data Sources: market/feed health and feature pipeline context.

At the bottom of the sidebar:

- `HEnEx · live`: the UI is anchored to the Greek HEnEx Day-Ahead Market.
- `EEST`: timestamps are shown in Greek/Eastern European Summer Time.

### Top Bar

The top bar shows:

- Breadcrumb: where the user is in the app.
- Demo operator identity: `ops@batteryos.gr`.

## Dashboard

Route: `/`

Purpose: give the user a fast operational summary of the latest dispatch run.

Backend connection: this page fetches optimizer artifacts through `/api/artifacts`.

### Header

The header says:

- Page context: `Operations · <live Athens date/time>`.
- Title: `Dispatch at a glance`.
- Description: the page is showing the last settled delivery day alongside the next-day expected KPI view.
- `LIVE · gate close in <live countdown>`: live countdown to the configured gate-close hour.
- `Refresh`: visual control.
- `Run optimizer`: navigates to the Optimizer page.

### KPI Tiles

The top four KPI tiles summarize the latest optimizer run:

- Next delivery day expected: ex-ante profit from the backend optimizer schedule for the next DAM delivery day.
- Previous day realization: ex-post realized profit divided by previous expected profit, expressed as a percentage.
- Risk profile: the tail-protected profit level, shown together with the lambda and alpha risk settings.
  It now reads as a backend-supported category such as `Balanced` or `Defensive`, with the tuple shown underneath.
- Cycles used: cycles reported by the backend feasibility/rainflow output versus the asset cycle cap.

### Last Day Diagram

This is the main chart.

It shows:

- Realized price curve.
- Forecast price curve.
- P10-P90 scenario band.
- Charge bars.
- Discharge bars.
- State of charge line.

Data source: backend artifacts converted by `src/ui/src/lib/backend.ts`.

The footer of the chart explains:

- Blue line: realized price.
- Magenta dashed line: forecast/median price.
- Green/blue bars: charge.
- Amber bars: discharge.
- State of charge line.
- `96 quarter-hourly periods · MTU=15min`: the day is split into 96 market time units of 15 minutes each.

### Last Day Battery State

This card shows one selected period snapshot:

- SoC in MWh.
- Action.
- Power.
- Period.

Current limitation: the period shown is fixed around index 28 in the UI, so it is a demo snapshot rather than an interactive selected timestamp.

### Last Day Profit Path

This chart shows:

- Per-period profit bars.
- Cumulative profit line.

It answers: where during the day did the schedule make or lose money?

### Recent Optimizer Runs

This table shows stored UI run history:

- Run id.
- Time.
- Day.
- Asset.
- Risk lambda.
- Status.
- Capture.
- Profit.

Current state: newly solved runs are recorded client-side in the Zustand store. Seed rows are static demo rows.

### Pipeline Card

This card shows the conceptual pipeline:

1. Ingest
2. Features
3. Forecast
4. Optimize
5. Backtest

Current state: this is a static workflow explanation, not live pipeline telemetry.

## Forecaster

Route: `/forecaster`

Purpose: explain the future forecasting module and show what the optimizer expects to receive from a forecaster.

Current state: the user has said the forecaster is not implemented yet. This page is therefore mostly demo/explanatory UI, not the production forecasting backend.

### Header

Shows:

- `Analytics · Forecaster`.
- `Price forecasting for the Greek DAM`.
- Buttons for export/re-train.

### KPI Tiles

Shows forecast model diagnostics:

- MAE.
- RMSE.
- Profit capture.
- Pinball loss.

Current state: these are synthetic/static model metrics from `src/ui/src/lib/data.ts`.

### Forecasting Workflow

A six-step explanation:

1. Ingest data.
2. Build features.
3. Validate.
4. Train.
5. Predict.
6. Score.

This is educational: it explains what the forecaster should eventually do before sending scenarios to Optimizer V1.

### Day-Ahead Forecast Chart

Shows:

- P10/P50/P90 forecast band.
- Optional realized DAM overlay.
- 24h/48h horizon toggle.

Current state: the page tries to fetch quantile forecasts from a Supabase edge function. If that service fails, it shows an error panel.

### Model Ladder

Shows possible forecasting models:

- Naive 1d.
- Naive 7d.
- SARIMAX.
- LightGBM.
- LightGBM Quantile.

Current state: static model comparison data.

### Feature Importance

Shows feature names, families, and importance bars.

Current state: static demo feature importances.

### Residuals and Calibration

These charts explain forecast error behavior:

- Residual distribution.
- Calibration curve.

Current state: synthetic values from demo arrays.

## Optimizer

Route: `/optimizer`

Purpose: show Optimizer V1 end to end: inputs, parameters, solve output, schedule, economics, and robustness.

Backend connection: this page calls `/api/optimize` and displays returned artifacts.

### Header

Shows:

- `Analytics · Optimizer`.
- `Mean-CVaR dispatch with rainflow aging`.
- Explanation that the page calls backend Optimizer V1.
- Export schedule button.
- Solve button.

### KPI Tiles

Shows:

- Expected profit.
- CVaR alpha profit.
- Worst-case robust profit.
- Cycles used and aging cost.

These values come from backend `run_metadata`.

### Parameters Card

User can select:

- Battery asset/profile.
- Risk profile preset.
- Custom lambda/alpha when `Custom` is selected.
- Robust sweep on/off.

The card also shows read-only backend profile values:

- Power.
- Energy.
- Round-trip efficiency.
- Degradation model.

Important: the UI no longer changes optimizer physics locally. It sends supported backend parameters and waits for backend artifacts.

### Optimized Dispatch Chart

Shows the schedule produced by Optimizer V1:

- Price curve.
- Charge/discharge decisions.
- State of charge trajectory.

This is the core output: what the optimizer decided.

### Profit Waterfall

Shows:

- Profit/loss per MTU.
- Cumulative profit for the day.

This answers: how the schedule turns into money.

### Solver Workflow

Shows the optimizer pipeline:

1. External scenarios.
2. Battery constraints.
3. Cycle envelope.
4. Mean-CVaR objective.
5. LP/MILP solve.
6. Feasibility check.
7. Period economics.
8. Rainflow aging.
9. Robust sweep.
10. Bid curves.

This section is for understanding the process, not for editing all internals.

### Scenario Fan

Shows the scenario bundle the optimizer received.

Current backend fallback: if no forecaster artifact exists, the backend generates a 20-scenario demo bundle.

### Robustness Sweep

Shows realized profit under perturbations of:

- Round-trip efficiency.
- Degradation cost.

This answers: how sensitive is the dispatch to battery assumptions?

## Backtest

Route: `/backtest`

Purpose: explain how the full system should be judged historically.

Current state: this page uses synthetic demo backtest data, not live backend backtest artifacts.

### Header

Shows:

- `Analytics · Backtest`.
- `Walk-forward economic backtest`.
- 30D/90D/1Y period selector.
- CSV and re-run buttons.

### KPI Tiles

Shows:

- BatteryOS cumulative profit.
- Percent of perfect foresight captured.
- Uplift versus naive baseline.
- Worst day.

Current state: synthetic values from `equityCurve`.

### Equity Curve

Compares:

- BatteryOS.
- Naive baseline.
- Perfect foresight.

This answers: does the whole framework make money over time?

### Daily Profit Heatmap

Shows which hours/days create the most dispatch value.

Current state: synthetic heatmap.

### Daily Profit Distribution

Shows distribution of daily profits:

- P10.
- Median.
- Mean.
- P90.

### Day-by-Day Results

Shows recent daily backtest rows:

- Date.
- Asset.
- Lambda.
- Naive profit.
- BatteryOS profit.
- Perfect profit.
- Capture.
- Status.

## Assets

Route: `/assets`

Purpose: manage storage profiles that can be dispatched by the optimizer.

### KPI Tiles

Shows:

- Active assets.
- Fleet power.
- Fleet energy.
- Average utilization.

Current state: asset data is client-side Zustand state seeded from demo defaults.

### Asset Cards

Each card shows:

- Asset id.
- Technology.
- Duration.
- Status.
- Power.
- Energy.
- Round-trip efficiency.
- Cycle cap.
- Aging cost.
- SoC band.
- Utilization.

Actions:

- Dispatch: selects asset and opens Optimizer.
- Edit: opens the asset editor.
- Pause/activate.

Important limitation: custom asset edits currently live in frontend state. Backend support for arbitrary custom asset physics needs a matching API contract before those values can fully drive backend optimization.

### Profile Comparison

Table comparing all assets:

- Profile.
- Technology.
- Power.
- Energy.
- Duration.
- Efficiency.
- Cycles/day.
- Aging cost.
- Utilization.
- Approximate daily value.

## Data Sources

Route: `/sources`

Purpose: show the market data and feature pipeline concept.

Current state: mostly static demo source-health data.

### KPI Tiles

Shows:

- Sources online.
- Last full sync.
- Rows ingested over 24h.
- Feature freshness.

### Source Registry

Shows external feeds:

- HEnEx DAM.
- IPTO / ADMIE.
- Open-Meteo.
- ENTSO-E.
- TTF Gas.
- EEX EUA Carbon.
- REMIT Outages.

For each source:

- Description.
- Health status.
- Latency.
- Row count.
- Last sync time.

### Pipeline Map

Visualizes:

Raw feeds -> processed data -> features -> model.

This is there to help users understand why the model does not optimize raw data directly.

### Feature Build Log

Shows example logs from the feature pipeline:

- Pulling HEnEx prices.
- Loading IPTO forecasts.
- Loading weather.
- Building calendar, market, fundamentals, and cross-border features.
- Checking no leakage.

Current state: static explanatory log.

## Current Backend Artifact Contract

The UI adapter expects backend artifacts shaped like:

- `schedule`: one row per 15-minute period.
- `scenario_panel`: one row per scenario and timestamp.
- `run_metadata`: optimizer status, profit metrics, battery profile, feasibility, cycles, runtime.
- `robustness_sweep`: parameter sweep rows.

The adapter lives in:

```text
src/ui/src/lib/backend.ts
```

The backend routes are:

```text
GET  /api/artifacts
POST /api/optimize
GET  /api/health
```

## What Is Real vs Demo Right Now

Backend-connected:

- Dashboard dispatch chart.
- Dashboard expected profit/CVaR/cycles from latest optimizer artifacts.
- Optimizer solve button.
- Optimizer dispatch chart.
- Optimizer scenario fan.
- Optimizer profit chart.
- Optimizer robustness sweep.

Static or synthetic demo context:

- Market ticker.
- Forecaster model metrics and feature importance.
- Most Data Sources page values.
- Backtest equity/daily results.
- Seed recent optimizer run history.
- Asset utilization and approximate daily value.

This split is intentional for the current MVP: the optimizer is the implemented backend core, while forecaster/backtest/source telemetry are still presentation scaffolding until those modules are wired in.
