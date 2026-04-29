"""
Backtest engine for battery dispatch optimization with cumulative degradation
and rolling annual cycle budget tracking.

Runs the optimizer over historical price forecasts, evaluates realized profit
against actual MCP, and tracks battery health (SOH, cumulative cycles,
remaining annual/lifetime budget) day-by-day.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Sequence

import numpy as np
import pandas as pd

from src.optimize.battery import BatteryProfile
from src.optimize.economics import evaluate_schedule
from src.optimize.milp import optimize_deterministic
from src.optimize.scenarios import PriceScenarios, scenarios_from_quantiles
from src.optimize.robust import optimize_cvar
from src.optimize.tracker import BatteryStateTracker


@dataclass
class DailyBacktestResult:
    """Result of optimizing one day for one battery profile."""

    date: str
    profile: str
    scenario: str
    realized_profit_eur: float
    market_profit_eur: float
    degradation_cost_eur: float
    transaction_cost_eur: float
    cycles_used: float
    throughput_mwh: float
    solver_status: str
    objective_value: float
    soh_frac: float
    cumulative_cycles: float
    annual_budget_remaining: float
    lifetime_budget_remaining: float
    dynamic_degradation_cost: float
    is_eol: bool
    final_soc_mwh: float
    metadata: dict = field(default_factory=dict)


def run_daily_optimizations(
    timestamps: Sequence,
    p10: Sequence[float],
    p50: Sequence[float],
    p90: Sequence[float],
    actual: Sequence[float],
    tracker: BatteryStateTracker,
    profile_name: str,
    duration_hours: float = 0.25,
    time_limit_s: int = 10,
) -> list[DailyBacktestResult]:
    """
    Run Safe (CVaR), Regular (deterministic p50), and Risky
    (deterministic p90) optimizations for a single day.

    Uses the tracker's effective battery profile (adjusted for SOH and
    remaining cycle budget). Records cycles used back into the tracker.
    """
    date_label = timestamps[0].strftime("%Y-%m-%d")
    state = tracker.get_state(date_label)

    results: list[DailyBacktestResult] = []

    # If battery is EOL, return zero-profit results for all scenarios
    if state.is_eol:
        for scenario in ("regular", "risky", "safe"):
            results.append(
                DailyBacktestResult(
                    date=date_label,
                    profile=profile_name,
                    scenario=scenario,
                    realized_profit_eur=0.0,
                    market_profit_eur=0.0,
                    degradation_cost_eur=0.0,
                    transaction_cost_eur=0.0,
                    cycles_used=0.0,
                    throughput_mwh=0.0,
                    solver_status="EOL",
                    objective_value=0.0,
                    soh_frac=state.soh_frac,
                    cumulative_cycles=state.cumulative_cycles,
                    annual_budget_remaining=state.annual_budget_remaining,
                    lifetime_budget_remaining=state.lifetime_budget_remaining,
                    dynamic_degradation_cost=state.dynamic_degradation_cost_eur_per_mwh,
                    is_eol=True,
                    final_soc_mwh=0.0,
                )
            )
        return results

    battery = tracker.get_effective_battery(date_label)

    # Optimizer sees total marginal cost (degradation + transaction) so it
    # internalises the friction and trades less aggressively.
    opt_battery = replace(
        battery,
        degradation_cost_eur_per_mwh=(
            battery.degradation_cost_eur_per_mwh + battery.transaction_cost_eur_per_mwh
        ),
    )

    # --- Regular: deterministic on p50 -----------------------------------
    try:
        sched_reg = optimize_deterministic(
            timestamps=timestamps,
            forecast_prices=p50,
            battery=opt_battery,
            duration_hours=duration_hours,
            time_limit_s=time_limit_s,
            enforce_disjunction=False,
        )
        metrics_reg = evaluate_schedule(
            sched_reg.df, actual, battery, duration_hours
        )
        results.append(
            DailyBacktestResult(
                date=date_label,
                profile=profile_name,
                scenario="regular",
                realized_profit_eur=metrics_reg["realized_profit_eur"],
                market_profit_eur=metrics_reg["market_profit_eur"],
                degradation_cost_eur=metrics_reg["degradation_cost_eur"],
                transaction_cost_eur=metrics_reg["transaction_cost_eur"],
                cycles_used=metrics_reg["cycles_used"],
                throughput_mwh=metrics_reg["throughput_mwh"],
                solver_status=sched_reg.solver_status,
                objective_value=sched_reg.objective_value,
                soh_frac=state.soh_frac,
                cumulative_cycles=state.cumulative_cycles,
                annual_budget_remaining=state.annual_budget_remaining,
                lifetime_budget_remaining=state.lifetime_budget_remaining,
                dynamic_degradation_cost=state.dynamic_degradation_cost_eur_per_mwh,
                is_eol=state.is_eol,
                final_soc_mwh=sched_reg.df["state_of_charge_mwh"].iloc[-1],
                metadata=sched_reg.metadata,
            )
        )
    except Exception as exc:
        results.append(
            DailyBacktestResult(
                date=date_label,
                profile=profile_name,
                scenario="regular",
                realized_profit_eur=0.0,
                market_profit_eur=0.0,
                degradation_cost_eur=0.0,
                transaction_cost_eur=0.0,
                cycles_used=0.0,
                throughput_mwh=0.0,
                solver_status=f"ERROR: {exc}",
                objective_value=0.0,
                soh_frac=state.soh_frac,
                cumulative_cycles=state.cumulative_cycles,
                annual_budget_remaining=state.annual_budget_remaining,
                lifetime_budget_remaining=state.lifetime_budget_remaining,
                dynamic_degradation_cost=state.dynamic_degradation_cost_eur_per_mwh,
                is_eol=state.is_eol,
                final_soc_mwh=battery.initial_soc_mwh,
            )
        )

    # --- Risky: deterministic on p90 -------------------------------------
    try:
        sched_risk = optimize_deterministic(
            timestamps=timestamps,
            forecast_prices=p90,
            battery=opt_battery,
            duration_hours=duration_hours,
            time_limit_s=time_limit_s,
            enforce_disjunction=False,
        )
        metrics_risk = evaluate_schedule(
            sched_risk.df, actual, battery, duration_hours
        )
        results.append(
            DailyBacktestResult(
                date=date_label,
                profile=profile_name,
                scenario="risky",
                realized_profit_eur=metrics_risk["realized_profit_eur"],
                market_profit_eur=metrics_risk["market_profit_eur"],
                degradation_cost_eur=metrics_risk["degradation_cost_eur"],
                transaction_cost_eur=metrics_risk["transaction_cost_eur"],
                cycles_used=metrics_risk["cycles_used"],
                throughput_mwh=metrics_risk["throughput_mwh"],
                solver_status=sched_risk.solver_status,
                objective_value=sched_risk.objective_value,
                soh_frac=state.soh_frac,
                cumulative_cycles=state.cumulative_cycles,
                annual_budget_remaining=state.annual_budget_remaining,
                lifetime_budget_remaining=state.lifetime_budget_remaining,
                dynamic_degradation_cost=state.dynamic_degradation_cost_eur_per_mwh,
                is_eol=state.is_eol,
                final_soc_mwh=sched_risk.df["state_of_charge_mwh"].iloc[-1],
                metadata=sched_risk.metadata,
            )
        )
    except Exception as exc:
        results.append(
            DailyBacktestResult(
                date=date_label,
                profile=profile_name,
                scenario="risky",
                realized_profit_eur=0.0,
                market_profit_eur=0.0,
                degradation_cost_eur=0.0,
                transaction_cost_eur=0.0,
                cycles_used=0.0,
                throughput_mwh=0.0,
                solver_status=f"ERROR: {exc}",
                objective_value=0.0,
                soh_frac=state.soh_frac,
                cumulative_cycles=state.cumulative_cycles,
                annual_budget_remaining=state.annual_budget_remaining,
                lifetime_budget_remaining=state.lifetime_budget_remaining,
                dynamic_degradation_cost=state.dynamic_degradation_cost_eur_per_mwh,
                is_eol=state.is_eol,
                final_soc_mwh=battery.initial_soc_mwh,
            )
        )

    # --- Safe: CVaR on p10/p50/p90 scenarios -----------------------------
    try:
        scenarios = scenarios_from_quantiles(
            timestamps=timestamps,
            p10=p10,
            p50=p50,
            p90=p90,
            weights=(0.2, 0.6, 0.2),
        )
        sched_safe = optimize_cvar(
            scenarios=scenarios,
            battery=opt_battery,
            duration_hours=duration_hours,
            alpha=0.10,
            risk_aversion=0.5,
            time_limit_s=time_limit_s,
            enforce_disjunction=False,
        )
        metrics_safe = evaluate_schedule(
            sched_safe.df, actual, battery, duration_hours
        )
        results.append(
            DailyBacktestResult(
                date=date_label,
                profile=profile_name,
                scenario="safe",
                realized_profit_eur=metrics_safe["realized_profit_eur"],
                market_profit_eur=metrics_safe["market_profit_eur"],
                degradation_cost_eur=metrics_safe["degradation_cost_eur"],
                transaction_cost_eur=metrics_safe["transaction_cost_eur"],
                cycles_used=metrics_safe["cycles_used"],
                throughput_mwh=metrics_safe["throughput_mwh"],
                solver_status=sched_safe.solver_status,
                objective_value=sched_safe.objective_value,
                soh_frac=state.soh_frac,
                cumulative_cycles=state.cumulative_cycles,
                annual_budget_remaining=state.annual_budget_remaining,
                lifetime_budget_remaining=state.lifetime_budget_remaining,
                dynamic_degradation_cost=state.dynamic_degradation_cost_eur_per_mwh,
                is_eol=state.is_eol,
                final_soc_mwh=sched_safe.df["state_of_charge_mwh"].iloc[-1],
                metadata=sched_safe.metadata,
            )
        )
    except Exception as exc:
        results.append(
            DailyBacktestResult(
                date=date_label,
                profile=profile_name,
                scenario="safe",
                realized_profit_eur=0.0,
                market_profit_eur=0.0,
                degradation_cost_eur=0.0,
                transaction_cost_eur=0.0,
                cycles_used=0.0,
                throughput_mwh=0.0,
                solver_status=f"ERROR: {exc}",
                objective_value=0.0,
                soh_frac=state.soh_frac,
                cumulative_cycles=state.cumulative_cycles,
                annual_budget_remaining=state.annual_budget_remaining,
                lifetime_budget_remaining=state.lifetime_budget_remaining,
                dynamic_degradation_cost=state.dynamic_degradation_cost_eur_per_mwh,
                is_eol=state.is_eol,
                final_soc_mwh=battery.initial_soc_mwh,
            )
        )

    return results


def backtest_to_dataframe(results: list[DailyBacktestResult]) -> pd.DataFrame:
    """Convert a list of DailyBacktestResult to a flat DataFrame."""
    rows = []
    for r in results:
        rows.append(
            {
                "date": r.date,
                "profile": r.profile,
                "scenario": r.scenario,
                "realized_profit_eur": r.realized_profit_eur,
                "market_profit_eur": r.market_profit_eur,
                "degradation_cost_eur": r.degradation_cost_eur,
                "transaction_cost_eur": r.transaction_cost_eur,
                "cycles_used": r.cycles_used,
                "throughput_mwh": r.throughput_mwh,
                "solver_status": r.solver_status,
                "objective_value": r.objective_value,
                "soh_frac": r.soh_frac,
                "cumulative_cycles": r.cumulative_cycles,
                "annual_budget_remaining": r.annual_budget_remaining,
                "lifetime_budget_remaining": r.lifetime_budget_remaining,
                "dynamic_degradation_cost": r.dynamic_degradation_cost,
                "is_eol": r.is_eol,
            }
        )
    return pd.DataFrame(rows)


def compute_backtest_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily results to per-profile, per-scenario summary."""
    summary = (
        df.groupby(["profile", "scenario"])
        .agg(
            total_profit_eur=("realized_profit_eur", "sum"),
            avg_daily_profit_eur=("realized_profit_eur", "mean"),
            profit_std_eur=("realized_profit_eur", "std"),
            worst_day_eur=("realized_profit_eur", "min"),
            best_day_eur=("realized_profit_eur", "max"),
            avg_cycles=("cycles_used", "mean"),
            total_throughput_mwh=("throughput_mwh", "sum"),
            final_soh=("soh_frac", "last"),
            final_cumulative_cycles=("cumulative_cycles", "last"),
            n_days=("date", "count"),
            eol_days=("is_eol", "sum"),
        )
        .round(2)
    )
    return summary
