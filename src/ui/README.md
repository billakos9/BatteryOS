# BatteryOS Dashboard

React/Vite dashboard prototype for the hackathon pitch.

## Run locally

```bash
npm install
npm run dev
```

Open the Vite URL shown in the terminal.

## Routes

```text
/          Live dispatch
/moat      Data moat and feature importance
/business  Business view
```

## Synthetic data

The prototype generates a 96-period synthetic demo day in the browser and mirrors the expected artifact layout under `public/data/`.

To swap in live BatteryOS outputs, pre-convert the Python artifacts to JSON and replace:

```text
public/data/schedule.json
public/data/scenario_panel.json
public/data/run_metadata.json
public/data/robustness_sweep.json
public/data/feature_importance.json
public/data/zone_coverage.json
```

The frontend field names match the contracts in `WORKFLOW_PLAN.md`.
