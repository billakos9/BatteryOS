"""BatteryOS API server.

Serves the built UI from src/ui/dist/ and exposes endpoints for:
- Receiving forecaster uploads (POST /api/forecast/upload)
- Serving forecast overview (GET /api/forecast/overview)
- Running the optimizer (POST /api/optimize)
- Serving dashboard artifacts (GET /api/artifacts)
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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.optimize import (  # noqa: E402
    BatteryProfile,
    DispatchResult,
    PriceScenarios,
    resolve_risk_profile,
    load_profile,
    optimize_dispatch,
)
from api.inference import run_inference  # noqa: E402

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
SOURCE_STATUS_PATH = PUBLIC_DATA / "source_status.json"
OUTPUTS_DIR = ROOT / "outputs"

# ---------------------------------------------------------------------------
# In-memory forecast cache
# ---------------------------------------------------------------------------
_FORECAST_CACHE: dict[str, Any] = {}


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


def _load_forecast_from_disk() -> dict[str, Any] | None:
    """Load the most recent forecast payload from outputs/forecast_*.json."""
    if not OUTPUTS_DIR.exists():
        return None
    files = sorted(OUTPUTS_DIR.glob("forecast_*.json"))
    if not files:
        return None
    latest = files[-1]
    try:
        with open(latest, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _warm_forecast_cache() -> None:
    """Hydrate the in-memory cache from disk on startup."""
    global _FORECAST_CACHE
    payload = _load_forecast_from_disk()
    if payload:
        _FORECAST_CACHE = payload
        print(f"[API] Warmed forecast cache from {payload.get('target_date', 'unknown')}")


# Warm cache immediately on module load
_warm_forecast_cache()


def _write_scenario_panel_from_payload(payload: dict[str, Any]) -> None:
    """Convert uploaded quantiles to flat scenario_panel.json format."""
    timestamps = payload["timestamps"]
    p10 = payload["p10"]
    p50 = payload["p50"]
    p90 = payload["p90"]

    rows = []
    for t_idx, ts in enumerate(timestamps):
        rows.append({
            "timestamp": ts,
            "scenario_label": "p10",
            "scenario_weight": 0.2,
            "price_eur_per_mwh": float(p10[t_idx]),
        })
        rows.append({
            "timestamp": ts,
            "scenario_label": "p50",
            "scenario_weight": 0.6,
            "price_eur_per_mwh": float(p50[t_idx]),
        })
        rows.append({
            "timestamp": ts,
            "scenario_label": "p90",
            "scenario_weight": 0.2,
            "price_eur_per_mwh": float(p90[t_idx]),
        })

    for target_dir in (PUBLIC_DATA, DIST_DATA):
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_dir / "scenario_panel.json", "w") as f:
            json.dump(_json_safe(rows), f, indent=2)


def _read_scenario_panel(path: Path) -> PriceScenarios:
    """Reconstruct PriceScenarios from the flat scenario_panel JSON.

    Raises FileNotFoundError if the file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Scenario panel not found at {path}")

    with open(path, "r") as f:
        rows = json.load(f)

    df = pd.DataFrame(rows)
    pivot = df.pivot(index="scenario_label", columns="timestamp", values="price_eur_per_mwh")
    timestamps = list(pivot.columns)
    prices = pivot.to_numpy(dtype=float)

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


def _write_json_to_targets(filename: str, payload: Any) -> None:
    for target_dir in (PUBLIC_DATA, DIST_DATA):
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_dir / filename, "w") as f:
            json.dump(_json_safe(payload), f, indent=2)


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with open(path, "r") as f:
        return json.load(f)


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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class OptimizeRequest(BaseModel):
    battery_profile_name: str = "liion_100_2h"
    risk_profile: Optional[str] = None
    risk_lambda: Optional[float] = None
    risk_alpha: Optional[float] = None
    build_bid_curves: bool = False
    run_robustness_sweep: bool = True


class SourceStatusRow(BaseModel):
    id: str
    name: str
    desc: str
    status: str
    latency: str
    rows: str
    lastSync: str
    latency_minutes: Optional[float] = None
    rows_24h: Optional[int] = None
    last_sync_iso: Optional[str] = None
    feature_freshness_minutes: Optional[float] = None


class SourceStatusPayload(BaseModel):
    generated_at: Optional[str] = None
    source: str = "pipeline_post"
    sources: list[SourceStatusRow]


class ForecastUploadRequest(BaseModel):
    target_date: str
    timestamps: list[str]
    p10: list[float]
    p50: list[float]
    p90: list[float]
    diagnostics: dict[str, Any] = {}
    features: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

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
        battery = BatteryProfile.custom(
            name=req.battery_profile_name,
            power_mw=100,
            energy_mwh=200,
            round_trip_efficiency=0.90,
        )

    # Reconstruct scenarios from current artifact
    try:
        ps = _read_scenario_panel(SCENARIO_PANEL_PATH)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="No forecast scenario panel available. Run the forecaster pipeline or POST to /api/forecast/upload.",
        )

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
    _DASHBOARD_CACHE[battery.name] = payload
    return payload


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/forecast/upload")
async def api_forecast_upload(req: ForecastUploadRequest) -> dict[str, Any]:
    """Receive a new forecast from the forecaster pipeline.

    Validates, caches in memory, writes scenario_panel.json, and persists
    the full payload to disk.
    """
    if not (req.timestamps and req.p10 and req.p50 and req.p90):
        raise HTTPException(status_code=400, detail="timestamps, p10, p50, p90 are all required.")

    n = len(req.timestamps)
    if not (len(req.p10) == n and len(req.p50) == n and len(req.p90) == n):
        raise HTTPException(
            status_code=400,
            detail=f"Length mismatch: timestamps={n}, p10={len(req.p10)}, p50={len(req.p50)}, p90={len(req.p90)}.",
        )

    # Build cache payload
    payload = {
        "target_date": req.target_date,
        "source": "forecaster",
        "market": "Greek DAM",
        "unit": "EUR/MWh",
        "resolution_minutes": 15,
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "timestamps": req.timestamps,
        "p10": req.p10,
        "p50": req.p50,
        "p90": req.p90,
        "diagnostics": req.diagnostics,
        "models": req.models,
        "features": req.features,
    }

    global _FORECAST_CACHE
    _FORECAST_CACHE = payload

    # Write scenario panel for optimizer consumption
    _write_scenario_panel_from_payload(payload)

    # Persist full payload
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    forecast_path = OUTPUTS_DIR / f"forecast_{req.target_date}.json"
    with open(forecast_path, "w") as f:
        json.dump(_json_safe(payload), f, indent=2)

    return {"ok": True, "target_date": req.target_date, "intervals": n}


@app.post("/api/forecast/generate")
async def api_forecast_generate(target_date: str | None = None) -> dict[str, Any]:
    """On-demand forecast generation.

    Runs the full daily inference pipeline (ENTSO-E + weather + feature
    engineering + LightGBM quantile prediction) and returns the forecast
    payload. The result is also cached so /api/forecast/overview serves it.
    """
    from datetime import date as dt_date
    td = dt_date.fromisoformat(target_date) if target_date else None
    try:
        payload = run_inference(target_date=td)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc

    # Write scenario panel for optimizer consumption
    _write_scenario_panel_from_payload(payload)

    # Persist full payload
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    forecast_path = OUTPUTS_DIR / f"forecast_{payload['target_date']}.json"
    with open(forecast_path, "w") as f:
        json.dump(_json_safe(payload), f, indent=2)

    # Update in-memory cache
    global _FORECAST_CACHE
    _FORECAST_CACHE = payload

    return {"ok": True, "target_date": payload["target_date"], "intervals": len(payload["timestamps"])}


@app.get("/api/forecast/overview")
async def forecast_overview(horizon_h: int = 24) -> dict[str, Any]:
    """Return the latest forecaster quantiles and metadata.

    Serves from in-memory cache. Falls back to disk if cache is empty.
    Returns 503 if no forecast has ever been uploaded.
    """
    global _FORECAST_CACHE

    if not _FORECAST_CACHE:
        _FORECAST_CACHE = _load_forecast_from_disk() or {}

    if not _FORECAST_CACHE:
        raise HTTPException(
            status_code=503,
            detail="No forecast available. Run the forecaster pipeline or POST to /api/forecast/upload.",
        )

    # Slice to requested horizon (default 24h = 96 intervals, 48h = 192)
    max_intervals = max(24, horizon_h) * 4
    timestamps = _FORECAST_CACHE.get("timestamps", [])
    n = min(len(timestamps), max_intervals)

    return {
        "source": _FORECAST_CACHE.get("source", "forecaster"),
        "market": _FORECAST_CACHE.get("market", "Greek DAM"),
        "unit": _FORECAST_CACHE.get("unit", "EUR/MWh"),
        "resolution_minutes": 15,
        "generated_at": _FORECAST_CACHE.get("generated_at", ""),
        "quantiles": {
            "timestamps": timestamps[:n],
            "p10": _FORECAST_CACHE.get("p10", [])[:n],
            "p50": _FORECAST_CACHE.get("p50", [])[:n],
            "p90": _FORECAST_CACHE.get("p90", [])[:n],
            "realized": [],  # no realized prices until delivery day ends
        },
        "diagnostics": _FORECAST_CACHE.get("diagnostics") or {
            "mae_eur_per_mwh": 0.0,
            "rmse_eur_per_mwh": 0.0,
            "profit_capture_pct": 0.0,
            "pinball_q90_eur_per_mwh": 0.0,
            "bias_eur_per_mwh": 0.0,
            "sigma_eur_per_mwh": 0.0,
            "p95_abs_error_eur_per_mwh": 0.0,
            "skew": 0.0,
        },
        "models": _FORECAST_CACHE.get("models", []),
        "features": _FORECAST_CACHE.get("features", []),
        "residuals": _FORECAST_CACHE.get("residuals", []),
        "calibration": _FORECAST_CACHE.get("calibration") or {
            "nominal": [],
            "empirical": [],
        },
    }


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
        battery = BatteryProfile.custom(
            name=battery_name,
            power_mw=100,
            energy_mwh=200,
            round_trip_efficiency=0.90,
        )

    risk_profile_key, risk_profile_label, risk_lambda, risk_alpha, risk_profile_description = (
        resolve_risk_profile(None, None, None)
    )

    try:
        ps = _read_scenario_panel(SCENARIO_PANEL_PATH)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="No forecast scenario panel available. Run the forecaster pipeline or POST to /api/forecast/upload.",
        )

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


def _demo_source_status_payload() -> dict[str, Any]:
    return {
        "generated_at": pd.Timestamp.now(tz="Europe/Athens").isoformat(),
        "source": "backend_demo",
        "sources": [
            {
                "id": "henex",
                "name": "HEnEx DAM",
                "desc": "Day-ahead clearing prices, market curves",
                "status": "ok",
                "latency": "8 min",
                "rows": "2.4M",
                "lastSync": "12:42",
                "latency_minutes": 8,
                "rows_24h": 2_400_000,
                "last_sync_iso": "2026-04-30T12:42:00+03:00",
                "feature_freshness_minutes": 8,
            },
            {
                "id": "ipto",
                "name": "IPTO / ADMIE",
                "desc": "Greek load + RES forecasts, ATC, system data",
                "status": "ok",
                "latency": "21 min",
                "rows": "1.1M",
                "lastSync": "12:42",
                "latency_minutes": 21,
                "rows_24h": 1_100_000,
                "last_sync_iso": "2026-04-30T12:42:00+03:00",
                "feature_freshness_minutes": 11,
            },
            {
                "id": "openmeteo",
                "name": "Open-Meteo",
                "desc": "Weather: temp, wind, irradiance, clouds",
                "status": "ok",
                "latency": "4 min",
                "rows": "640k",
                "lastSync": "12:43",
                "latency_minutes": 4,
                "rows_24h": 640_000,
                "last_sync_iso": "2026-04-30T12:43:00+03:00",
                "feature_freshness_minutes": 4,
            },
            {
                "id": "entsoe",
                "name": "ENTSO-E",
                "desc": "Pan-European load, generation, cross-border",
                "status": "ok",
                "latency": "33 min",
                "rows": "8.2M",
                "lastSync": "12:34",
                "latency_minutes": 33,
                "rows_24h": 8_200_000,
                "last_sync_iso": "2026-04-30T12:34:00+03:00",
                "feature_freshness_minutes": 18,
            },
            {
                "id": "ttf",
                "name": "TTF Gas",
                "desc": "Dutch TTF gas benchmark",
                "status": "warn",
                "latency": "2 h 04m",
                "rows": "12k",
                "lastSync": "10:42",
                "latency_minutes": 124,
                "rows_24h": 12_000,
                "last_sync_iso": "2026-04-30T10:42:00+03:00",
                "feature_freshness_minutes": 124,
            },
            {
                "id": "eua",
                "name": "EEX EUA Carbon",
                "desc": "EU carbon allowance prices",
                "status": "ok",
                "latency": "55 min",
                "rows": "9.8k",
                "lastSync": "12:00",
                "latency_minutes": 55,
                "rows_24h": 9_800,
                "last_sync_iso": "2026-04-30T12:00:00+03:00",
                "feature_freshness_minutes": 55,
            },
            {
                "id": "remit",
                "name": "REMIT Outages",
                "desc": "Plant outage notifications",
                "status": "err",
                "latency": "—",
                "rows": "—",
                "lastSync": "yest. 18:11",
                "latency_minutes": None,
                "rows_24h": None,
                "last_sync_iso": "2026-04-29T18:11:00+03:00",
                "feature_freshness_minutes": None,
            },
        ],
    }


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
async def api_sources() -> dict[str, Any]:
    """Health and freshness of every data ingestion feed.

    Returns the latest posted source-status artifact. If no pipeline has
    posted one yet, serves a demo payload in the same contract shape.
    """
    return _json_safe(_read_json(SOURCE_STATUS_PATH, _demo_source_status_payload()))


@app.post("/api/sources/update")
async def api_sources_update(payload: SourceStatusPayload) -> dict[str, Any]:
    """Ingestion pipeline write path for source freshness / health metadata."""
    normalized = payload.model_dump()
    if not normalized.get("generated_at"):
        normalized["generated_at"] = pd.Timestamp.now(tz="Europe/Athens").isoformat()
    _write_json_to_targets("source_status.json", normalized)
    return {
        "ok": True,
        "generated_at": normalized["generated_at"],
        "sources_updated": len(normalized["sources"]),
    }


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


@app.get("/api/backtest/summary")
async def api_backtest_summary(days: int = 90, profile: Optional[str] = None) -> dict[str, Any]:
    """Walk-forward backtest summary.

    Reads honest backtest results (BatteryOS regular scenario) and
    pre-computed perfect / naive baselines from outputs/*.csv.

    Parameters
    ----------
    days : int
        Number of trailing days to return (default 90).
    profile : str | None
        Battery profile to filter by (e.g. "liion_100_2h"). If omitted
        or "all", aggregates across all profiles.
    """
    import pandas as pd

    detailed_path = ROOT / "outputs" / "backtest_detailed.csv"
    perfect_path = ROOT / "outputs" / "backtest_baseline_perfect.csv"
    naive_path = ROOT / "outputs" / "backtest_baseline_naive.csv"

    if not detailed_path.exists():
        raise HTTPException(status_code=503, detail="Backtest detailed results not found. Run 'python pipelines/run_backtest.py' first.")

    # Normalise profile filter
    profile_filter = None if profile is None or profile.lower() == "all" else profile

    df_bos = pd.read_csv(detailed_path)
    df_bos["date"] = pd.to_datetime(df_bos["date"])

    # Use the 'regular' scenario as the canonical BatteryOS strategy
    df_bos = df_bos[df_bos["scenario"] == "regular"]

    # Filter by profile if requested
    if profile_filter:
        df_bos = df_bos[df_bos["profile"] == profile_filter]
        if df_bos.empty:
            raise HTTPException(status_code=404, detail=f"Profile {profile_filter!r} not found in backtest results.")

    # Aggregate per day (across profiles or single profile)
    bos_daily = df_bos.groupby("date")["realized_profit_eur"].sum().reset_index()
    bos_daily = bos_daily.sort_values("date")

    # Limit to last N days
    if len(bos_daily) > days:
        bos_daily = bos_daily.iloc[-days:].reset_index(drop=True)

    # Load perfect baseline if available
    perfect_daily = None
    if perfect_path.exists():
        df_perf = pd.read_csv(perfect_path)
        df_perf["date"] = pd.to_datetime(df_perf["date"])
        if profile_filter:
            df_perf = df_perf[df_perf["profile"] == profile_filter]
        perfect_daily = df_perf.groupby("date")["realized_profit_eur"].sum().reset_index()
        perfect_daily = perfect_daily.sort_values("date")
        if len(perfect_daily) > days:
            perfect_daily = perfect_daily.iloc[-days:].reset_index(drop=True)

    # Load naive baseline if available
    naive_daily = None
    if naive_path.exists():
        df_naive = pd.read_csv(naive_path)
        df_naive["date"] = pd.to_datetime(df_naive["date"])
        if profile_filter:
            df_naive = df_naive[df_naive["profile"] == profile_filter]
        naive_daily = df_naive.groupby("date")["realized_profit_eur"].sum().reset_index()
        naive_daily = naive_daily.sort_values("date")
        if len(naive_daily) > days:
            naive_daily = naive_daily.iloc[-days:].reset_index(drop=True)

    # Build equity curves
    n = len(bos_daily)
    bos_values = bos_daily["realized_profit_eur"].tolist()
    perf_values = perfect_daily["realized_profit_eur"].tolist() if perfect_daily is not None else bos_values[:]
    naive_values = naive_daily["realized_profit_eur"].tolist() if naive_daily is not None else [0.0] * n

    equity_bos = []
    equity_perf = []
    equity_naive = []
    cum_bos = cum_perf = cum_naive = 0.0
    for i in range(n):
        cum_bos += bos_values[i]
        cum_perf += perf_values[i] if i < len(perf_values) else 0.0
        cum_naive += naive_values[i] if i < len(naive_values) else 0.0
        equity_bos.append(round(cum_bos, 2))
        equity_perf.append(round(cum_perf, 2))
        equity_naive.append(round(cum_naive, 2))

    # Build day-by-day profit log
    day_profits = []
    dates = bos_daily["date"].dt.date.astype(str).tolist()
    for i in range(n):
        bos_p = bos_values[i]
        perf_p = perf_values[i] if i < len(perf_values) else bos_p
        naive_p = naive_values[i] if i < len(naive_values) else 0.0
        capture = bos_p / perf_p if perf_p > 0 else 0.0
        day_profits.append({
            "d": i,
            "date": dates[i] if i < len(dates) else "",
            "bos": round(bos_p, 2),
            "naive": round(naive_p, 2),
            "perfect": round(perf_p, 2),
            "capture": round(capture, 4),
        })

    # Build heatmap: 24 hours × days (approximate from 15-min data)
    # Use BOS detailed data to get hourly profit distribution
    heatmap: list[list[float]] = []
    if not df_bos.empty and "date" in df_bos.columns:
        # Get the dates in our window
        window_dates = set(bos_daily["date"].dt.date.astype(str))
        df_window = df_bos[df_bos["date"].dt.date.astype(str).isin(window_dates)]
        if not df_window.empty and "timestamp" in df_bos.columns:
            # Try to read detailed with timestamp for hourly aggregation
            try:
                df_detail = pd.read_csv(detailed_path)
                df_detail = df_detail[df_detail["scenario"] == "regular"]
                df_detail["timestamp"] = pd.to_datetime(df_detail.get("timestamp", df_detail["date"]))
                df_detail["hour"] = df_detail["timestamp"].dt.hour
                df_detail["day_str"] = df_detail["timestamp"].dt.date.astype(str)
                df_detail = df_detail[df_detail["day_str"].isin(window_dates)]
                hourly = df_detail.groupby(["day_str", "hour"])["realized_profit_eur"].sum().unstack(fill_value=0)
                # Ensure 24 columns
                for h in range(24):
                    if h not in hourly.columns:
                        hourly[h] = 0.0
                hourly = hourly[[h for h in range(24)]]
                heatmap = hourly.values.tolist()
            except Exception:
                heatmap = []

    if not heatmap:
        # Fallback: distribute each day's profit uniformly across 24 hours.
        # This preserves daily profit intensity even when hourly backtest
        # breakdown is unavailable.
        heatmap = []
        for i in range(n):
            daily_val = bos_values[i] / 24.0
            heatmap.append([daily_val] * 24)

    return {
        "days": n,
        "equity": {
            "batteryOS": equity_bos,
            "naive": equity_naive,
            "perfect": equity_perf,
        },
        "dayProfits": day_profits,
        "heatmap": heatmap,
        "source": "walk-forward honest backtest (regular scenario, all profiles)",
    }


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
            "summary": "ENTSO-E day-ahead load & generation forecasts, Open-Meteo weather, EnExGroup DAM actuals",
            "inputs": ["ENTSO-E API", "Open-Meteo API", "EnExGroup"],
            "outputs": ["raw price, load, generation and weather curves"],
        },
        {
            "id": "features",
            "label": "Feature Engineering",
            "lane": "data",
            "summary": "Calendar encoding, lagged volumes, residual load, fuel costs, weather interactions",
            "inputs": ["raw curves"],
            "outputs": ["leakage-safe feature matrix (53 columns)"],
        },
        {
            "id": "forecaster",
            "label": "Probabilistic Forecaster",
            "lane": "forecast",
            "summary": "LightGBM quantile regression (p10 / p50 / p90) with walk-forward validation",
            "inputs": ["feature matrix"],
            "outputs": ["quantile price predictions (p10, p50, p90)"],
        },
        {
            "id": "scenarios",
            "label": "Scenario Panel",
            "lane": "forecast",
            "summary": "Convert quantiles to weighted PriceScenarios for stochastic optimization",
            "inputs": ["quantile predictions"],
            "outputs": ["PriceScenarios (3 paths × weights)"],
        },
        {
            "id": "optimizer",
            "label": "MILP Optimizer",
            "lane": "optimize",
            "summary": "Deterministic LP, CVaR and stochastic dispatch with battery + cycle constraints",
            "inputs": ["PriceScenarios", "BatteryProfile"],
            "outputs": ["DAM schedule (charge / discharge / SoC)"],
        },
        {
            "id": "tracker",
            "label": "Degradation Tracker",
            "lane": "optimize",
            "summary": "SOH decay, rolling annual cycle budget, dynamic degradation cost, SoC carry-over",
            "inputs": ["schedule cycles", "previous SoC"],
            "outputs": ["effective battery profile for next day"],
        },
        {
            "id": "bidcurves",
            "label": "Bid Curves",
            "lane": "optimize",
            "summary": "Per-period quantity ladder via price-perturbation re-solve",
            "inputs": ["schedule baseline", "candidate prices"],
            "outputs": ["price-quantity ladder (96 periods)"],
        },
        {
            "id": "backtest",
            "label": "Walk-forward Backtest",
            "lane": "evaluate",
            "summary": "Day-by-day replay with forecast-driven dispatch, perfect-foresight and naive baselines",
            "inputs": ["forecaster", "battery", "realized prices"],
            "outputs": ["realized PnL, % of perfect, degradation trajectories"],
        },
        {
            "id": "dashboard",
            "label": "Dashboard / API",
            "lane": "evaluate",
            "summary": "FastAPI backend serving the React UI with live optimizer artifacts and backtest results",
            "inputs": ["optimizer artifacts", "backtest summary"],
            "outputs": ["KPIs, dispatch chart, equity curves, scenario panel"],
        },
    ]
    edges = [
        {"from": "ingest", "to": "features"},
        {"from": "features", "to": "forecaster"},
        {"from": "forecaster", "to": "scenarios"},
        {"from": "scenarios", "to": "optimizer"},
        {"from": "optimizer", "to": "tracker"},
        {"from": "tracker", "to": "optimizer", "kind": "loopback"},
        {"from": "optimizer", "to": "bidcurves"},
        {"from": "optimizer", "to": "backtest", "kind": "loopback"},
        {"from": "forecaster", "to": "backtest", "kind": "loopback"},
        {"from": "backtest", "to": "dashboard"},
        {"from": "bidcurves", "to": "dashboard"},
    ]
    lanes = [
        {"id": "data", "label": "Data", "color": "#5B6CFF"},
        {"id": "forecast", "label": "Forecasting", "color": "#22D3EE"},
        {"id": "optimize", "label": "Optimization", "color": "#F59E0B"},
        {"id": "evaluate", "label": "Evaluation", "color": "#10B981"},
    ]
    return {"nodes": nodes, "edges": edges, "lanes": lanes}


# SPA catch-all — serve index.html for every frontend route so React Router works.
# This route is registered AFTER all API routes, so API paths still work.
# For static files (JS, CSS, images) we check if the file exists on disk first.
dist_dir = ROOT / "src" / "ui" / "dist"

@app.get("/")
async def serve_root() -> FileResponse:
    return FileResponse(dist_dir / "index.html")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str) -> FileResponse:
    # API routes are already defined above and take precedence,
    # but double-check to avoid accidentally serving HTML for /api/xxx
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    # If the path corresponds to a real static file, serve it
    file_path = dist_dir / full_path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    # Otherwise fall back to index.html (React Router handles the path)
    return FileResponse(dist_dir / "index.html")

# Static assets mount (catches anything not matched by explicit routes above)
app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static")
