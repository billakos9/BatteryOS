# data

Static dashboard artifacts live here after converting BatteryOS backend outputs for browser loading.

The React UI only fetches and visualizes these files. It does not optimize,
calculate dispatch decisions, calculate degradation, or calculate robustness.

Expected files:

```text
schedule.json
scenario_panel.json
run_metadata.json
robustness_sweep.json
```

Replace these demo JSON files with exported BatteryOS run artifacts to show a
real backend run.
