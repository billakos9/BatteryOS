"""BatteryOS API server.

Serves the built UI from src/ui/dist/ and exposes a single endpoint
POST /api/optimize that re-runs the optimizer with user-selected parameters.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.optimize import (  # noqa: E402
    BatteryProfile,
    DispatchResult,
    PriceScenarios,
    scenarios_from_quantiles,
    resolve_risk_profile,
    load_profile,
    optimize_dispatch,
)
from src.backtest.metrics import (  # noqa: E402
    perfect_foresight_pnl,
    point_metrics,
    quantile_pinball_score,
)

app = FastAPI(title="BatteryOS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
PUBLIC_DATA = ROOT / "src" / "ui" / "public" / "data"
DIST_DATA = ROOT / "src" / "ui" / "dist" / "data"
SCENARIO_PANEL_PATH = PUBLIC_DATA / "scenario_panel.json"
SCHEDULE_PATH = PUBLIC_DATA / "schedule.json"


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy values to ordinary JSON values."""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _demo_price_at(i: int) -> float:
    """Synthetic Greek DAM-shaped curve used only when no forecaster file exists."""
    h = i / 4
    price = 80.0
    price += -10 * np.exp(-((h - 3.5) / 2.4) ** 2)
    price += 60 * np.exp(-((h - 7.8) / 1.4) ** 2)
    price += -42 * np.exp(-((h - 13) / 1.6) ** 2)
    price += 18 * np.exp(-((h - 16) / 2.4) ** 2)
    price += 95 * np.exp(-((h - 19.5) / 1.5) ** 2)
    price += -8 * np.exp(-((h - 23) / 2.0) ** 2)
    price += np.sin(i * 0.71) * 2.4 + np.cos(i * 0.31) * 1.7
    return float(max(28, price))


def _demo_scenarios() -> PriceScenarios:
    """Create the temporary 20-scenario optimizer input until the forecaster ships."""
    timestamps = pd.date_range("2026-04-29", periods=96, freq="15min").astype(str).tolist()
    realized = np.array([_demo_price_at(i) for i in range(96)], dtype=float)
    forecast = np.array(
        [
            v * (0.96 + 0.04 * np.cos(i * 0.21)) + np.sin(i * 0.5) * 1.5
            for i, v in enumerate(realized)
        ],
        dtype=float,
    )
    paths = []
    for k in range(20):
        rng = np.random.default_rng(7 * (k + 1) + 13)
        bias = (rng.random() - 0.5) * 16
        path = []
        for i in range(96):
            drift = np.sin(i * 0.1 + k * 0.3) * 6
            path.append(forecast[i] + bias + drift + (rng.random() - 0.5) * 12)
        paths.append(path)
    return PriceScenarios(
        timestamps=timestamps,
        prices=np.asarray(paths, dtype=float),
        weights=np.full(20, 1 / 20),
        labels=[f"ff{i}" for i in range(20)],
    )


def _read_scenario_panel(path: Path) -> PriceScenarios:
    """Reconstruct PriceScenarios from the flat scenario_panel JSON."""
    if not path.exists():
        return _demo_scenarios()

    with open(path, "r") as f:
        rows = json.load(f)

    df = pd.DataFrame(rows)
    # Pivot to (scenario_label, timestamp) -> price
    pivot = df.pivot(index="scenario_label", columns="timestamp", values="price_eur_per_mwh")
    timestamps = list(pivot.columns)
    prices = pivot.to_numpy(dtype=float)

    # Extract weights per scenario (take first row per label)
    weights_df = df.groupby("scenario_label")["scenario_weight"].first()
    weights = weights_df.reindex(pivot.index).to_numpy(dtype=float)
    weights = weights / weights.sum()
    labels = list(pivot.index)

    return PriceScenarios(
        timestamps=timestamps,
        prices=prices,
        weights=weights,
        labels=labels,
    )


def _extract_schedule_json(result: DispatchResult) -> list[dict]:
    """Convert Schedule DataFrame to the frontend schedule.json format."""
    df = result.schedule.df.copy()
    # Ensure realized_price column exists (frontend expects it)
    if "realized_price_eur_per_mwh" not in df.columns:
        df["realized_price_eur_per_mwh"] = df["forecast_price_eur_per_mwh"]
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"]).map(lambda ts: ts.isoformat())
    return _json_safe(df.to_dict(orient="records"))


def _extract_scenario_panel(result: DispatchResult) -> list[dict]:
    """Convert PriceScenarios to flat scenario_panel.json format."""
    ps = result.scenarios
    rows = []
    for s_idx, label in enumerate(ps.labels):
        for t_idx, ts in enumerate(ps.timestamps):
            rows.append(
                {
                    "timestamp": ts,
                    "scenario_label": label,
                    "scenario_weight": float(ps.weights[s_idx]),
                    "price_eur_per_mwh": float(ps.prices[s_idx, t_idx]),
                }
            )
    return _json_safe(rows)


def _extract_run_metadata(result: DispatchResult, runtime_ms: float) -> dict:
    """Build run_metadata.json from DispatchResult."""
    meta = result.schedule.metadata or {}
    bp = result.battery
    delivery_day = ""
    if len(result.schedule.df) > 0:
        delivery_day = pd.to_datetime(result.schedule.df["timestamp"].iloc[0]).date().isoformat()

    return {
        "delivery_day": delivery_day,
        "battery_profile": {
            "name": bp.name,
            "technology": bp.technology,
            "power_mw": bp.power_mw,
            "energy_mwh": bp.energy_mwh,
            "eta_rt": bp.round_trip_efficiency,
            "soc_min_mwh": bp.soc_min_mwh,
            "soc_max_mwh": bp.soc_max_mwh,
            "initial_soc_mwh": bp.initial_soc_mwh,
            "max_cycles_per_day": bp.max_cycles_per_day,
        },
        "optimizer": "optimize_dispatch",
        "optimizer_display_name": "Optimizer V1",
        "risk_profile": meta.get("risk_profile"),
        "risk_profile_label": meta.get("risk_profile_label"),
        "risk_profile_description": meta.get("risk_profile_description"),
        "objective_value_eur": meta.get("expected_profit_eur", 0.0),
        "solver_status": result.schedule.solver_status,
        "expected_profit_eur": meta.get("expected_profit_eur", 0.0),
        "realized_profit_eur": (
            result.realized_evaluation.get("realized_profit_eur", 0.0)
            if result.realized_evaluation
            else meta.get("expected_profit_eur", 0.0)
        ),
        "worst_profit_eur": meta.get("worst_profit_eur", 0.0),
        "best_profit_eur": meta.get("best_profit_eur", 0.0),
        "cvar_eur": meta.get("cvar_eur", 0.0),
        "cvar_alpha": meta.get("alpha", 0.1),
        "cvar_lambda": meta.get("risk_aversion", 0.5),
        "risk_setting": "Mean-CVaR run",
        "scenario_labels": result.scenarios.labels,
        "scenario_weights": [float(w) for w in result.scenarios.weights],
        "scenario_profits_eur": meta.get("scenario_profits_eur", []),
        "feasibility": {
            "feasible": result.feasibility.feasible,
            "soc_min_violation_mwh": result.feasibility.soc_min_violation_mwh,
            "soc_max_violation_mwh": result.feasibility.soc_max_violation_mwh,
            "power_violation_mw": result.feasibility.power_violation_mw,
            "simultaneity_violation_mw": result.feasibility.simultaneity_violation_mw,
            "cycles_used": result.feasibility.cycles_used,
            "cycle_violation": result.feasibility.cycle_violation,
            "dynamics_residual_mwh": result.feasibility.dynamics_residual_mwh,
            "terminal_soc_violation_mwh": result.feasibility.terminal_soc_violation_mwh,
        },
        "rainflow_aging_cost_eur": result.rainflow.aging_cost_eur,
        "rainflow_net_profit_eur": result.rainflow.net_profit_eur,
        "equivalent_full_cycles": result.rainflow.equivalent_full_cycles,
        "deep_cycle_count": result.rainflow.deep_cycle_count,
        "cycles_used": result.feasibility.cycles_used,
        "runtime_ms": runtime_ms,
        "scenarios_used": result.scenarios.n_scenarios,
        "horizon": result.scenarios.horizon,
        "degradation_model": meta.get("degradation_model", "constant"),
    }


def _extract_robustness(result: DispatchResult) -> list[dict]:
    """Convert ParameterSweepResult to robustness_sweep.json format."""
    if result.robustness is None or result.robustness.table is None:
        return []
    return _json_safe(result.robustness.table.to_dict(orient="records"))


def _build_artifacts(result: DispatchResult, runtime_ms: float) -> dict[str, Any]:
    return {
        "schedule": _extract_schedule_json(result),
        "scenario_panel": _extract_scenario_panel(result),
        "run_metadata": _json_safe(_extract_run_metadata(result, runtime_ms)),
        "robustness_sweep": _extract_robustness(result),
    }


def _demo_feature_importance() -> list[dict[str, Any]]:
    return [
        {"name": "residual_load_forecast", "group": "Fundamentals", "imp": 0.184},
        {"name": "price_lag_1d_same_hour", "group": "Market Memory", "imp": 0.142},
        {"name": "gas_price", "group": "Fuel & Carbon", "imp": 0.108},
        {"name": "DE_residual_load", "group": "Cross-border", "imp": 0.094},
        {"name": "rolling_volatility_7d", "group": "Market Memory", "imp": 0.078},
        {"name": "solar_irradiance_fc", "group": "Weather", "imp": 0.072},
        {"name": "carbon_price", "group": "Fuel & Carbon", "imp": 0.061},
        {"name": "hour_of_day", "group": "Calendar", "imp": 0.058},
        {"name": "wind_speed_fc", "group": "Weather", "imp": 0.044},
        {"name": "GR_IT_atc", "group": "Cross-border", "imp": 0.041},
        {"name": "weekend_flag", "group": "Calendar", "imp": 0.034},
        {"name": "price_lag_7d", "group": "Market Memory", "imp": 0.029},
        {"name": "BG_residual_load", "group": "Cross-border", "imp": 0.024},
        {"name": "temperature_fc", "group": "Weather", "imp": 0.021},
        {"name": "holiday_flag", "group": "Calendar", "imp": 0.012},
    ]


def _demo_model_ladder() -> list[dict[str, Any]]:
    return [
        {"id": "naive_1d", "name": "Naive 1d", "kind": "Baseline", "mae": 22.4, "rmse": 31.1, "smape": 24.2, "profit_capture_pct": 41, "pinball_q90": 10.2},
        {"id": "naive_7d", "name": "Naive 7d", "kind": "Baseline", "mae": 18.9, "rmse": 27.3, "smape": 21.6, "profit_capture_pct": 48, "pinball_q90": 8.8},
        {"id": "sarimax", "name": "SARIMAX", "kind": "Statistical", "mae": 14.3, "rmse": 21.8, "smape": 16.4, "profit_capture_pct": 61, "pinball_q90": 6.1},
        {"id": "lgbm", "name": "LightGBM-q50", "kind": "ML", "mae": 9.8, "rmse": 15.2, "smape": 11.7, "profit_capture_pct": 72, "pinball_q90": 3.8},
        {"id": "lgbm_q", "name": "LightGBM Quantile", "kind": "ML+Quantile", "mae": 9.6, "rmse": 15.0, "smape": 11.5, "profit_capture_pct": 74, "pinball_q90": 3.4},
    ]


def _build_demo_forecast_overview(horizon_h: int = 24) -> dict[str, Any]:
    n_periods = max(24, horizon_h) * 4
    timestamps = pd.date_range("2026-04-30", periods=n_periods, freq="15min")
    realized = np.array([_demo_price_at(i % 96) + 3.5 * np.sin(i / 19.0) for i in range(n_periods)], dtype=float)
    p50 = np.array(
        [
            realized[i] * (0.965 + 0.03 * np.cos(i * 0.18)) + np.sin(i * 0.33) * 1.8
            for i in range(n_periods)
        ],
        dtype=float,
    )
    p10 = np.array([v - 8 - 5 * abs(np.sin(i * 0.17)) for i, v in enumerate(p50)], dtype=float)
    p90 = np.array([v + 9 + 6 * abs(np.cos(i * 0.21)) for i, v in enumerate(p50)], dtype=float)

    scenarios = scenarios_from_quantiles(timestamps, p10, p50, p90)
    metrics = point_metrics(p50, realized)
    pinball = quantile_pinball_score(scenarios, realized)
    battery = load_profile(ROOT / "config" / "storage_profiles.yaml", "liion_100_2h")
    result = optimize_dispatch(
        scenarios,
        battery,
        alpha=0.10,
        risk_aversion=0.35,
        build_bid_curves=False,
        run_robustness_sweep=False,
        realized_prices=realized,
    )
    perfect = perfect_foresight_pnl(realized, battery, timestamps=timestamps)
    perfect_profit = float(perfect["perfect_foresight_profit_eur"])
    realized_profit = float(result.realized_evaluation["realized_profit_eur"]) if result.realized_evaluation else 0.0
    profit_capture_pct = 100.0 * realized_profit / perfect_profit if perfect_profit > 0 else 0.0

    residuals = (p50 - realized).astype(float)
    q95 = float(np.percentile(np.abs(residuals), 95))

    return {
        "source": "backend_demo",
        "market": "Greek DAM",
        "unit": "EUR/MWh",
        "resolution_minutes": 15,
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "quantiles": {
            "timestamps": [ts.isoformat() for ts in timestamps],
            "p10": p10.tolist(),
            "p50": p50.tolist(),
            "p90": p90.tolist(),
            "realized": realized.tolist(),
        },
        "diagnostics": {
            "mae_eur_per_mwh": float(metrics["mae_eur_per_mwh"]),
            "rmse_eur_per_mwh": float(metrics["rmse_eur_per_mwh"]),
            "profit_capture_pct": float(profit_capture_pct),
            "pinball_q90_eur_per_mwh": float(pinball["pinball_q90"]),
            "bias_eur_per_mwh": float(metrics["bias_eur_per_mwh"]),
            "sigma_eur_per_mwh": float(np.std(residuals)),
            "p95_abs_error_eur_per_mwh": q95,
            "skew": float(pd.Series(residuals).skew()),
        },
        "models": _demo_model_ladder(),
        "features": _demo_feature_importance(),
        "residuals": residuals.tolist(),
        "calibration": {
            "nominal": [0.1, 0.3, 0.5, 0.7, 0.9],
            "empirical": [0.12, 0.31, 0.52, 0.68, 0.86],
        },
    }


def _write_artifacts(
    result: DispatchResult,
    runtime_ms: float,
) -> dict[str, Any]:
    """Write all frontend artifacts to public/data and dist/data."""
    artifacts = _build_artifacts(result, runtime_ms)
    for target_dir in (PUBLIC_DATA, DIST_DATA):
        target_dir.mkdir(parents=True, exist_ok=True)

        with open(target_dir / "schedule.json", "w") as f:
            json.dump(artifacts["schedule"], f, indent=2)

        with open(target_dir / "scenario_panel.json", "w") as f:
            json.dump(artifacts["scenario_panel"], f, indent=2)

        with open(target_dir / "run_metadata.json", "w") as f:
            json.dump(artifacts["run_metadata"], f, indent=2)

        with open(target_dir / "robustness_sweep.json", "w") as f:
            json.dump(artifacts["robustness_sweep"], f, indent=2)

        # Placeholders for files the frontend may request
        with open(target_dir / "feature_importance.json", "w") as f:
            json.dump({}, f)
        with open(target_dir / "zone_coverage.json", "w") as f:
            json.dump({}, f)

    return artifacts


class OptimizeRequest(BaseModel):
    battery_profile_name: str = "liion_100_2h"
    risk_profile: Optional[str] = None
    risk_lambda: Optional[float] = None
    risk_alpha: Optional[float] = None
    build_bid_curves: bool = False
    run_robustness_sweep: bool = True


@app.post("/api/optimize")
async def api_optimize(req: OptimizeRequest) -> dict[str, Any]:
    t0 = time.time()
    try:
        risk_profile_key, risk_profile_label, risk_lambda, risk_alpha, risk_profile_description = resolve_risk_profile(
            req.risk_profile,
            req.risk_lambda,
            req.risk_alpha,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Load battery profile
    try:
        battery = load_profile(ROOT / "config" / "storage_profiles.yaml", req.battery_profile_name)
    except KeyError:
        # Fallback: try custom
        battery = BatteryProfile.custom(
            name=req.battery_profile_name,
            power_mw=100,
            energy_mwh=200,
            round_trip_efficiency=0.90,
        )

    # Reconstruct scenarios from current artifact
    ps = _read_scenario_panel(SCENARIO_PANEL_PATH)

    # Run optimizer
    result: DispatchResult = optimize_dispatch(
        scenarios=ps,
        battery=battery,
        alpha=risk_alpha,
        risk_aversion=risk_lambda,
        build_bid_curves=req.build_bid_curves,
        run_robustness_sweep=req.run_robustness_sweep,
    )
    result.schedule.metadata.update(
        {
            "risk_profile": risk_profile_key,
            "risk_profile_label": risk_profile_label,
            "risk_profile_description": risk_profile_description,
        }
    )

    runtime_ms = int((time.time() - t0) * 1000)
    artifacts = _write_artifacts(result, runtime_ms)

    payload = {
        "ok": True,
        "runtime_ms": runtime_ms,
        "battery_profile": battery.name,
        "risk_profile": risk_profile_key,
        "risk_profile_label": risk_profile_label,
        "risk_lambda": risk_lambda,
        "risk_alpha": risk_alpha,
        "artifacts": artifacts,
    }
    # Refresh the per-battery dashboard cache so the dashboard reflects
    # the most recent re-tune from the optimizer page.
    _DASHBOARD_CACHE[battery.name] = payload
    return payload


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/forecast/overview")
async def forecast_overview(horizon_h: int = 24) -> dict[str, Any]:
    """Return forecaster diagnostics and quantiles from the local backend.

    Until the real forecaster artifact pipeline is persisted to disk, this
    endpoint serves a backend-generated demo payload with the same shape the
    frontend expects.
    """
    horizon_h = 48 if horizon_h >= 48 else 24
    return _build_demo_forecast_overview(horizon_h=horizon_h)


_DASHBOARD_CACHE: dict[str, dict[str, Any]] = {}


def _build_dashboard_for_battery(battery_name: str) -> dict[str, Any]:
    """Run the unified optimizer for a single battery profile and return
    artifacts in the same shape `/api/optimize` produces. Result cached
    per battery name so repeat dashboard loads are instant.
    """
    if battery_name in _DASHBOARD_CACHE:
        return _DASHBOARD_CACHE[battery_name]

    t0 = time.time()
    try:
        battery = load_profile(ROOT / "config" / "storage_profiles.yaml", battery_name)
    except KeyError:
        # Custom assets created in the UI are not persisted server-side yet.
        # Fall back to a sane Li-ion default so the page never breaks.
        battery = BatteryProfile.custom(
            name=battery_name,
            power_mw=100,
            energy_mwh=200,
            round_trip_efficiency=0.90,
        )

    risk_profile_key, risk_profile_label, risk_lambda, risk_alpha, risk_profile_description = (
        resolve_risk_profile(None, None, None)
    )

    ps = _read_scenario_panel(SCENARIO_PANEL_PATH)
    result: DispatchResult = optimize_dispatch(
        scenarios=ps,
        battery=battery,
        alpha=risk_alpha,
        risk_aversion=risk_lambda,
        build_bid_curves=False,
        run_robustness_sweep=True,
    )
    result.schedule.metadata.update(
        {
            "risk_profile": risk_profile_key,
            "risk_profile_label": risk_profile_label,
            "risk_profile_description": risk_profile_description,
        }
    )
    runtime_ms = int((time.time() - t0) * 1000)
    artifacts = _build_artifacts(result, runtime_ms)
    payload = {
        "ok": True,
        "runtime_ms": runtime_ms,
        "battery_profile": battery.name,
        "risk_profile": risk_profile_key,
        "risk_profile_label": risk_profile_label,
        "risk_lambda": risk_lambda,
        "risk_alpha": risk_alpha,
        "artifacts": artifacts,
    }
    _DASHBOARD_CACHE[battery_name] = payload
    return payload


@app.get("/api/artifacts")
async def api_artifacts(battery: Optional[str] = None) -> dict[str, Any]:
    """Return per-asset dashboard artifacts.

    Each battery profile gets its own dispatch run (cached after the
    first request). Pass `?battery=<id>` from the frontend to switch
    which asset's dashboard is rendered.
    """
    battery_name = battery or "liion_100_2h"
    return _build_dashboard_for_battery(battery_name)


@app.get("/api/sources")
async def api_sources() -> list[dict[str, Any]]:
    """Health and freshness of every data ingestion feed.

    The frontend renders the Sources page exclusively from this payload.
    """
    return [
        {
            "id": "henex",
            "name": "HEnEx DAM",
            "desc": "Day-ahead clearing prices, market curves",
            "status": "ok",
            "latency": "8 min",
            "rows": "2.4M",
            "lastSync": "12:42",
        },
        {
            "id": "ipto",
            "name": "IPTO / ADMIE",
            "desc": "Greek load + RES forecasts, ATC, system data",
            "status": "ok",
            "latency": "21 min",
            "rows": "1.1M",
            "lastSync": "12:42",
        },
        {
            "id": "openmeteo",
            "name": "Open-Meteo",
            "desc": "Weather: temp, wind, irradiance, clouds",
            "status": "ok",
            "latency": "4 min",
            "rows": "640k",
            "lastSync": "12:43",
        },
        {
            "id": "entsoe",
            "name": "ENTSO-E",
            "desc": "Pan-European load, generation, cross-border",
            "status": "ok",
            "latency": "33 min",
            "rows": "8.2M",
            "lastSync": "12:34",
        },
        {
            "id": "ttf",
            "name": "TTF Gas",
            "desc": "Dutch TTF gas benchmark",
            "status": "warn",
            "latency": "2 h 04m",
            "rows": "12k",
            "lastSync": "10:42",
        },
        {
            "id": "eua",
            "name": "EEX EUA Carbon",
            "desc": "EU carbon allowance prices",
            "status": "ok",
            "latency": "55 min",
            "rows": "9.8k",
            "lastSync": "12:00",
        },
        {
            "id": "remit",
            "name": "REMIT Outages",
            "desc": "Plant outage notifications",
            "status": "err",
            "latency": "—",
            "rows": "—",
            "lastSync": "yest. 18:11",
        },
    ]


def _profile_to_asset(name: str, raw: dict) -> dict[str, Any]:
    """Map a YAML battery profile (frac form) into the UI's BatteryAsset shape."""
    energy = float(raw.get("energy_mwh", 0.0))
    eta = float(raw.get("charge_efficiency", 0.95))
    tech_label = {
        "lithium_ion": "Li-Ion",
        "pumped_hydro": "Pumped Hydro",
        "vanadium_flow": "Vanadium Flow",
    }.get(str(raw.get("technology", "")).lower(), str(raw.get("technology", "Custom")))
    return {
        "id": name,
        "tech": tech_label,
        "power": float(raw.get("power_mw", 0.0)),
        "energy": energy,
        "eff": eta,
        "socMinPct": float(raw.get("soc_min_frac", 0.10)),
        "socMaxPct": float(raw.get("soc_max_frac", 0.90)),
        "cyclesPerDay": float(raw.get("max_cycles_per_day", 1.5)),
        "agingCost": float(raw.get("degradation_cost_eur_per_mwh", 2.0)),
        "status": "active",
        "utilization": 0.5,
    }


@app.get("/api/batteries")
async def api_batteries() -> list[dict[str, Any]]:
    """List of battery profiles read from config/storage_profiles.yaml.

    Returned in the frontend's BatteryAsset shape so the Assets page and the
    optimizer dropdown can consume it directly.
    """
    import yaml

    catalog_path = ROOT / "config" / "storage_profiles.yaml"
    if not catalog_path.exists():
        return []
    with open(catalog_path, "r") as f:
        catalog = yaml.safe_load(f) or {}
    profiles = catalog.get("profiles", catalog) or {}

    fixed_utilization = {
        "liion_100_2h": 0.62,
        "liion_200_2h": 0.71,
        "liion_300_2h": 0.58,
        "phs_100_8h": 0.44,
        "phs_200_8h": 0.0,
        "flow_100_6h": 0.39,
    }
    fixed_status = {"phs_200_8h": "paused"}

    out: list[dict[str, Any]] = []
    for name, raw in profiles.items():
        asset = _profile_to_asset(name, raw)
        asset["utilization"] = fixed_utilization.get(name, asset["utilization"])
        asset["status"] = fixed_status.get(name, asset["status"])
        out.append(asset)
    return out


@app.get("/api/ticker")
async def api_ticker() -> list[dict[str, Any]]:
    """Top-of-page ticker for the dashboard."""
    return [
        {"l": "EL DAM", "v": "€84.2/MWh", "d": "+2.1%", "up": True},
        {"l": "TTF gas", "v": "€31.4", "d": "−0.4%", "up": False},
        {"l": "EUA", "v": "€72.8", "d": "+0.8%", "up": True},
        {"l": "GR load fc", "v": "6.4 GW", "d": "+1.2%", "up": True},
        {"l": "RES share", "v": "38%", "d": "+3.0%", "up": True},
        {"l": "DE residual", "v": "42 GW", "d": "−1.1%", "up": False},
        {"l": "GR-IT ATC", "v": "500 MW", "d": "—", "up": None},
    ]


def _build_backtest_summary(days: int = 90) -> dict[str, Any]:
    """Synthetic walk-forward summary served by the API.

    Will be replaced by `run_walk_forward_backtest` outputs once we have
    persisted historical price data on disk.
    """
    rng = np.random.default_rng(42)
    equity_bos: list[float] = []
    equity_naive: list[float] = []
    equity_perfect: list[float] = []
    day_profits: list[dict[str, Any]] = []
    acc = {"b": 0.0, "n": 0.0, "p": 0.0}
    for d in range(days):
        baseline = 22000.0 + np.sin(d * 0.21) * 3000 + (rng.random() - 0.5) * 4000
        perfect = baseline * 1.45 + (rng.random() - 0.5) * 1500
        bos = baseline * 1.05 + (rng.random() - 0.5) * 2200
        naive = baseline * 0.65 + (rng.random() - 0.5) * 2500
        acc["b"] += bos
        acc["n"] += naive
        acc["p"] += perfect
        equity_bos.append(acc["b"])
        equity_naive.append(acc["n"])
        equity_perfect.append(acc["p"])
        day_profits.append(
            {
                "d": d,
                "bos": float(bos),
                "naive": float(naive),
                "perfect": float(perfect),
                "capture": float(bos / perfect) if perfect > 0 else 0.0,
            }
        )

    heat: list[list[float]] = []
    for d in range(30):
        rng_d = np.random.default_rng(d * 31 + 17)
        row: list[float] = []
        for h in range(24):
            peak = np.exp(-((h - 8) / 2) ** 2) + 1.4 * np.exp(-((h - 19) / 1.6) ** 2)
            trough = -0.7 * np.exp(-((h - 13) / 1.7) ** 2)
            row.append(float(peak + trough + 0.4 + (rng_d.random() - 0.5) * 0.5))
        heat.append(row)

    return {
        "days": days,
        "equity": {
            "batteryOS": [float(v) for v in equity_bos],
            "naive": [float(v) for v in equity_naive],
            "perfect": [float(v) for v in equity_perfect],
        },
        "dayProfits": day_profits,
        "heatmap": heat,
        "source": "backend_demo",
    }


@app.get("/api/backtest/summary")
async def api_backtest_summary(days: int = 90) -> dict[str, Any]:
    """Walk-forward backtest summary: equity curve, daily profits, heatmap."""
    days = max(7, min(365, int(days)))
    return _build_backtest_summary(days=days)


@app.get("/api/workflow")
async def api_workflow() -> dict[str, Any]:
    """Pipeline diagram for the Dashboard's "How it works" panel.

    Returns a directed graph of the BatteryOS workflow with each node's
    role, primary inputs/outputs, and the backend modules that implement
    it. The frontend renders this as an SVG / flow visualization.
    """
    nodes = [
        {
            "id": "ingest",
            "label": "Data Ingestion",
            "lane": "data",
            "modules": ["src/ingest/*"],
            "summary": "HEnEx, IPTO, ENTSO-E, Open-Meteo, TTF, EUA, REMIT",
            "inputs": ["external APIs"],
            "outputs": ["raw price + weather + load curves"],
        },
        {
            "id": "features",
            "label": "Feature Engineering",
            "lane": "data",
            "modules": ["src/features/*"],
            "summary": "184 PIT features, gate-close-aware",
            "inputs": ["raw curves"],
            "outputs": ["feature panel"],
        },
        {
            "id": "forecaster",
            "label": "Probabilistic Forecaster",
            "lane": "forecast",
            "modules": ["src/forecast/*"],
            "summary": "ML quantile/ensemble model → Monte Carlo price paths",
            "inputs": ["feature panel"],
            "outputs": ["N price samples (N≈500)"],
        },
        {
            "id": "scenarios",
            "label": "Scenario Reduction",
            "lane": "forecast",
            "modules": ["src/optimize/scenarios.py"],
            "summary": "Heitsch–Römisch fast-forward → ~30 weighted scenarios",
            "inputs": ["N raw samples"],
            "outputs": ["PriceScenarios bundle"],
        },
        {
            "id": "optimizer",
            "label": "Mean-CVaR Optimizer",
            "lane": "optimize",
            "modules": ["src/optimize/dispatch.py", "src/optimize/robust.py"],
            "summary": "max  (1−λ)·E[π] + λ·CVaRα[π]  s.t. battery + cycle limits",
            "inputs": ["PriceScenarios", "BatteryProfile"],
            "outputs": ["DAM schedule, bid curves"],
        },
        {
            "id": "degradation",
            "label": "Rainflow Degradation",
            "lane": "optimize",
            "modules": ["src/optimize/degradation.py"],
            "summary": "ASTM E1049 rainflow + Wöhler aging cost",
            "inputs": ["schedule SoC trajectory"],
            "outputs": ["aging cost €, equivalent full cycles"],
        },
        {
            "id": "robustness",
            "label": "Robustness Sweep",
            "lane": "optimize",
            "modules": ["src/optimize/robust.py"],
            "summary": "Replay schedule under perturbed efficiency × deg-cost",
            "inputs": ["schedule", "battery"],
            "outputs": ["worst-case PnL surface"],
        },
        {
            "id": "bidcurves",
            "label": "Bid Curves",
            "lane": "optimize",
            "modules": ["src/optimize/bid_curves.py"],
            "summary": "Per-period q(p) ladder for HEnEx submission",
            "inputs": ["schedule baseline"],
            "outputs": ["price-quantity ladder"],
        },
        {
            "id": "backtest",
            "label": "Walk-forward Backtest",
            "lane": "evaluate",
            "modules": ["src/backtest/*"],
            "summary": "Day-by-day replay vs realized prices and benchmarks",
            "inputs": ["forecaster", "optimizer", "realized prices"],
            "outputs": ["realized PnL, % of perfect, forecast metrics"],
        },
        {
            "id": "dashboard",
            "label": "Dashboard / API",
            "lane": "evaluate",
            "modules": ["api/server.py", "src/ui/*"],
            "summary": "Single source of truth for visualizations",
            "inputs": ["all artifacts"],
            "outputs": ["KPIs, charts, schedule + scenario panel"],
        },
    ]
    edges = [
        {"from": "ingest", "to": "features"},
        {"from": "features", "to": "forecaster"},
        {"from": "forecaster", "to": "scenarios"},
        {"from": "scenarios", "to": "optimizer"},
        {"from": "optimizer", "to": "degradation"},
        {"from": "optimizer", "to": "robustness"},
        {"from": "optimizer", "to": "bidcurves"},
        {"from": "degradation", "to": "dashboard"},
        {"from": "robustness", "to": "dashboard"},
        {"from": "bidcurves", "to": "dashboard"},
        {"from": "optimizer", "to": "backtest", "kind": "loopback"},
        {"from": "forecaster", "to": "backtest", "kind": "loopback"},
        {"from": "backtest", "to": "dashboard"},
    ]
    lanes = [
        {"id": "data", "label": "Data", "color": "#5B6CFF"},
        {"id": "forecast", "label": "Forecasting", "color": "#22D3EE"},
        {"id": "optimize", "label": "Optimization", "color": "#F59E0B"},
        {"id": "evaluate", "label": "Evaluation", "color": "#10B981"},
    ]
    return {"nodes": nodes, "edges": edges, "lanes": lanes}


# Mount built UI at root
app.mount("/", StaticFiles(directory=ROOT / "src" / "ui" / "dist", html=True), name="static")
