"""Tests for the unified BatteryOS dispatch optimizer.

There is exactly one optimizer (`optimize_dispatch`); these tests
exercise the four canonical input forms, the degenerate cases, and the
DispatchResult bundle.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.optimize import (  # noqa: E402
    BatteryProfile,
    DEFAULT_RISK_PROFILE,
    DispatchResult,
    PriceScenarios,
    feasibility_report,
    load_profile,
    optimize_dispatch,
    resolve_risk_profile,
    scenarios_from_quantiles,
)


@pytest.fixture
def battery() -> BatteryProfile:
    return load_profile(ROOT / "config" / "storage_profiles.yaml", "liion_100_2h")


@pytest.fixture
def day():
    horizon = 96
    timestamps = pd.date_range("2026-04-29", periods=horizon, freq="15min")
    base = 80.0 + 30.0 * np.sin(2 * np.pi * np.arange(horizon) / horizon)
    base[44:60] = 20.0
    base[72:84] = 220.0
    return timestamps, base


def test_dispatch_with_pricescenarios(battery, day):
    timestamps, p50 = day
    sc = scenarios_from_quantiles(timestamps, p50 - 30, p50, p50 + 50)
    result = optimize_dispatch(
        sc,
        battery,
        alpha=0.20,
        risk_aversion=0.5,
        build_bid_curves=False,
        run_robustness_sweep=False,
    )
    assert isinstance(result, DispatchResult)
    assert result.scenarios.n_scenarios == 3
    assert result.feasibility.feasible
    assert result.summary()["expected_profit_eur"] > 0


def test_dispatch_with_raw_samples(battery, day):
    timestamps, p50 = day
    rng = np.random.default_rng(0)
    samples = p50 + rng.normal(0, 25, size=(200, len(p50)))
    result = optimize_dispatch(
        samples,
        battery,
        timestamps=timestamps,
        n_reduced_scenarios=20,
        build_bid_curves=False,
        run_robustness_sweep=False,
    )
    assert result.scenarios.n_scenarios == 20
    assert result.feasibility.feasible


def test_dispatch_single_scenario_collapses_to_deterministic(battery, day):
    timestamps, p50 = day
    single = p50.reshape(1, -1)
    result = optimize_dispatch(
        single,
        battery,
        timestamps=timestamps,
        n_reduced_scenarios=None,
        alpha=1.0,
        risk_aversion=0.0,
        build_bid_curves=False,
        run_robustness_sweep=False,
    )
    assert result.scenarios.n_scenarios == 1
    sc = scenarios_from_quantiles(timestamps, p50, p50, p50)
    twin = optimize_dispatch(
        sc,
        battery,
        alpha=1.0,
        risk_aversion=0.0,
        build_bid_curves=False,
        run_robustness_sweep=False,
    )
    assert abs(result.schedule.total_profit() - twin.schedule.total_profit()) < 1e-3


def test_dispatch_full_bundle(battery, day):
    timestamps, p50 = day
    short_ts = timestamps[:24]
    short_p = p50[:24]
    sc = scenarios_from_quantiles(short_ts, short_p - 25, short_p, short_p + 40)
    result = optimize_dispatch(
        sc,
        battery,
        duration_hours=0.25,
        alpha=0.20,
        risk_aversion=0.5,
        build_bid_curves=True,
        bid_price_grid=np.linspace(0, 250, 6),
        run_robustness_sweep=True,
        realized_prices=short_p,
    )
    assert result.bid_curves is not None
    assert result.bid_curves.bid_quantities_mw.shape == (24, 6)
    assert result.robustness is not None
    assert result.robustness.worst_case_profit <= result.robustness.median_profit
    assert result.realized_evaluation is not None
    assert "realized_profit_eur" in result.realized_evaluation
    assert result.rainflow.aging_cost_eur >= 0
    assert result.feasibility.feasible


def test_dispatch_rejects_empty_horizon(battery):
    with pytest.raises(ValueError):
        optimize_dispatch(
            np.zeros((1, 0)),
            battery,
            timestamps=[],
            build_bid_curves=False,
            run_robustness_sweep=False,
        )


def test_dispatch_rejects_lossless_battery(day):
    """LP relaxation is unsafe with eta_rt >= 1; engine should refuse."""
    timestamps, p50 = day
    lossless = BatteryProfile(
        name="lossless",
        technology="ideal",
        power_mw=100,
        energy_mwh=200,
        soc_min_mwh=20,
        soc_max_mwh=180,
        initial_soc_mwh=100,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
    )
    sc = scenarios_from_quantiles(timestamps, p50 - 30, p50, p50 + 50)
    with pytest.raises(ValueError):
        optimize_dispatch(
            sc,
            lossless,
            build_bid_curves=False,
            run_robustness_sweep=False,
        )


def test_dispatch_summary_keys(battery, day):
    timestamps, p50 = day
    sc = scenarios_from_quantiles(timestamps, p50 - 30, p50, p50 + 50)
    result = optimize_dispatch(
        sc,
        battery,
        build_bid_curves=False,
        run_robustness_sweep=False,
    )
    s = result.summary()
    expected_keys = {
        "battery_profile",
        "n_scenarios",
        "expected_profit_eur",
        "cvar_eur",
        "worst_profit_eur",
        "best_profit_eur",
        "rainflow_aging_cost_eur",
        "rainflow_net_profit_eur",
        "equivalent_full_cycles",
        "feasible",
        "dynamics_residual_mwh",
    }
    assert expected_keys.issubset(s.keys())


def test_soc_banded_degradation_changes_in_milp_objective(battery, day):
    timestamps, p50 = day
    sc = scenarios_from_quantiles(timestamps, p50 - 30, p50, p50 + 50)
    result = optimize_dispatch(
        sc,
        battery,
        alpha=0.20,
        risk_aversion=0.5,
        build_bid_curves=False,
        run_robustness_sweep=False,
        use_soc_banded_degradation=True,
        degradation_fixed_point_iterations=2,
        degradation_bands=((0.0, 0.60, 10.0), (0.85, 1.0, 10.0)),
    )
    costs = result.schedule.metadata["degradation_costs_eur_per_mwh"]
    assert costs is not None
    assert max(costs) > battery.degradation_cost_eur_per_mwh
    assert result.schedule.metadata["degradation_model"] == "soc_banded_fixed_point"
    assert result.feasibility.feasible


def test_resolve_default_risk_profile():
    key, label, risk_lambda, risk_alpha, description = resolve_risk_profile(None, None, None)
    assert key == DEFAULT_RISK_PROFILE
    assert label == "Balanced"
    assert risk_lambda == 0.35
    assert risk_alpha == 0.10
    assert description


def test_resolve_custom_risk_profile():
    key, label, risk_lambda, risk_alpha, _ = resolve_risk_profile("custom", 0.72, 0.05)
    assert key == "custom"
    assert label == "Custom"
    assert risk_lambda == 0.72
    assert risk_alpha == 0.05


def test_resolve_named_risk_profile_ignores_raw_overrides():
    key, label, risk_lambda, risk_alpha, _ = resolve_risk_profile("defensive", 0.12, 0.20)
    assert key == "defensive"
    assert label == "Defensive"
    assert risk_lambda == 0.60
    assert risk_alpha == 0.10
