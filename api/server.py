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
    resolve_risk_profile,
    load_profile,
    optimize_dispatch,
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
    risk_profile: str | None = None
    risk_lambda: float | None = None
    risk_alpha: float | None = None
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

    return {
        "ok": True,
        "runtime_ms": runtime_ms,
        "battery_profile": battery.name,
        "risk_profile": risk_profile_key,
        "risk_profile_label": risk_profile_label,
        "risk_lambda": risk_lambda,
        "risk_alpha": risk_alpha,
        "artifacts": artifacts,
    }


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/artifacts")
async def api_artifacts() -> dict[str, Any]:
    """Return the latest artifacts, generating the demo run when none exist."""
    if not SCHEDULE_PATH.exists():
        req = OptimizeRequest()
        return await api_optimize(req)

    def read_json(path: Path, fallback: Any) -> Any:
        if not path.exists():
            return fallback
        with open(path, "r") as f:
            return json.load(f)

    return {
        "ok": True,
        "artifacts": {
            "schedule": read_json(PUBLIC_DATA / "schedule.json", []),
            "scenario_panel": read_json(PUBLIC_DATA / "scenario_panel.json", []),
            "run_metadata": read_json(PUBLIC_DATA / "run_metadata.json", {}),
            "robustness_sweep": read_json(PUBLIC_DATA / "robustness_sweep.json", []),
        },
    }


# Mount built UI at root
app.mount("/", StaticFiles(directory=ROOT / "src" / "ui" / "dist", html=True), name="static")
