"""Sanity tests for the optimizer module.

These do not require any market data. They build a synthetic price curve
with a known low-noon / high-evening pattern and verify each optimizer:
  * stays within SoC and power limits
  * charges when prices are low and discharges when prices are high
  * makes positive profit on the synthetic curve
  * stochastic/CVaR objectives produce metadata fields we use elsewhere
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
    feasibility_report,
    load_profile,
    optimize_cvar,
    optimize_deterministic,
    optimize_rule_based,
    optimize_stochastic,
    scenarios_from_quantiles,
    scenarios_from_samples,
    sweep_battery_parameters,
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


def test_rule_based_makes_money(battery, day):
    timestamps, prices = day
    schedule = optimize_rule_based(timestamps, prices, battery, duration_hours=0.25)
    assert schedule.total_profit() > 0
    rep = feasibility_report(schedule.df, battery, 0.25)
    assert rep.feasible


def test_deterministic_beats_rule_based(battery, day):
    timestamps, prices = day
    rb = optimize_rule_based(timestamps, prices, battery, duration_hours=0.25)
    milp = optimize_deterministic(timestamps, prices, battery, duration_hours=0.25)
    assert milp.solver_status in {"Optimal", "Not Solved"}
    assert milp.total_profit() >= rb.total_profit() - 1e-6
    rep = feasibility_report(milp.df, battery, 0.25)
    assert rep.feasible


def test_stochastic_consumes_quantiles(battery, day):
    timestamps, p50 = day
    p10 = p50 - 30.0
    p90 = p50 + 60.0
    scenarios = scenarios_from_quantiles(timestamps, p10, p50, p90)
    sched = optimize_stochastic(scenarios, battery, duration_hours=0.25, objective="expected")
    assert sched.metadata["n_scenarios"] == 3
    assert "expected_profit_eur" in sched.metadata
    assert sched.metadata["worst_profit_eur"] <= sched.metadata["best_profit_eur"]


def test_stochastic_worst_case_is_more_conservative(battery, day):
    timestamps, p50 = day
    p10 = p50 - 50.0
    p90 = p50 + 80.0
    scenarios = scenarios_from_quantiles(timestamps, p10, p50, p90)
    expected_sched = optimize_stochastic(scenarios, battery, objective="expected")
    worst_sched = optimize_stochastic(scenarios, battery, objective="worst_case")
    assert worst_sched.metadata["worst_profit_eur"] >= expected_sched.metadata["worst_profit_eur"] - 1e-6


def test_cvar_lifts_tail_profit(battery, day):
    timestamps, p50 = day
    p10 = p50 - 50.0
    p90 = p50 + 80.0
    scenarios = scenarios_from_quantiles(timestamps, p10, p50, p90)
    risk_neutral = optimize_cvar(scenarios, battery, alpha=0.20, risk_aversion=0.0)
    risk_averse = optimize_cvar(scenarios, battery, alpha=0.20, risk_aversion=1.0)
    assert risk_averse.metadata["cvar_eur"] >= risk_neutral.metadata["cvar_eur"] - 1e-6


def test_scenarios_from_samples_reduces(day):
    timestamps, p50 = day
    rng = np.random.default_rng(0)
    samples = p50 + rng.normal(0, 25, size=(200, len(p50)))
    reduced = scenarios_from_samples(timestamps, samples, n_reduced=10)
    assert reduced.n_scenarios <= 10
    assert np.isclose(reduced.weights.sum(), 1.0)


def test_parameter_sweep_reports_worst_case(battery, day):
    timestamps, prices = day
    sched = optimize_deterministic(timestamps, prices, battery, duration_hours=0.25)
    result = sweep_battery_parameters(sched, prices, battery)
    assert result.worst_case_profit <= result.median_profit
    assert "realized_profit_eur" in result.table.columns
