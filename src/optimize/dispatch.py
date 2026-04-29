"""Unified BatteryOS DAM dispatch optimizer.

This is the single public optimizer entry point. It consumes the
forecaster's scenario output, produces a day-ahead dispatch schedule,
builds the bid curve to submit to HEnEx, and reports rainflow-based
degradation cost and battery-parameter robustness.

The technique is Mean-CVaR scenario-based stochastic optimization with
the Rockafellar-Uryasev CVaR LP reformulation - the same architecture
used in production by Habitat Energy, Fluence Mosaic, Tesla Autobidder,
Gridmatic, and Stem Athena.

ARCHITECTURE - WHO OWNS SCENARIO REDUCTION
------------------------------------------
Scenario generation AND reduction belong to the forecaster, not the
optimizer. The forecaster:

  1. samples N Monte Carlo price paths from its predictive distribution
  2. reduces them to a representative weighted set (~20-50 scenarios)
     using its own preferred technique (Heitsch-Romisch, k-means,
     Wasserstein, or a domain-specific copula-aware method)
  3. hands the reduced bundle off as a `PriceScenarios` object

The optimizer then receives `PriceScenarios` and just optimizes.
This is the production contract.

For prototyping and tests, `optimize_dispatch` will *also* accept a
raw (N, T) array and call `scenarios_fast_forward` internally. This is
a convenience fallback - it lets the forecaster team build incrementally
without blocking the optimizer side. Once the forecaster ships its own
reducer, callers should pass `PriceScenarios` directly.

Single-scenario inputs collapse the math to ordinary deterministic
optimization (alpha=1, risk_aversion=0). There is exactly one optimizer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Union

import numpy as np
import pandas as pd

from .battery import BatteryProfile
from .bid_curves import BidCurves, build_bid_curves_resolve
from .degradation import (
    RainflowScore,
    score_schedule_rainflow,
    soc_banded_throughput_costs,
)
from .economics import FeasibilityReport, evaluate_schedule, feasibility_report
from .robust import ParameterSweepResult, optimize_cvar, sweep_battery_parameters
from .scenarios import PriceScenarios, scenarios_fast_forward
from .schedule import Schedule


@dataclass
class DispatchResult:
    """Bundle of everything the unified optimizer produces.

    The dashboard / pitch deck consumes this directly. Each attribute is
    self-contained and can be exported independently to parquet / json.
    """

    schedule: Schedule
    bid_curves: Optional[BidCurves]
    rainflow: RainflowScore
    feasibility: FeasibilityReport
    robustness: Optional[ParameterSweepResult]
    scenarios: PriceScenarios
    battery: BatteryProfile
    realized_evaluation: Optional[dict] = None
    metadata: dict = field(default_factory=dict)

    def summary(self) -> dict:
        meta = self.schedule.metadata or {}
        return {
            "battery_profile": self.battery.name,
            "n_scenarios": self.scenarios.n_scenarios,
            "expected_profit_eur": meta.get("expected_profit_eur"),
            "cvar_eur": meta.get("cvar_eur"),
            "worst_profit_eur": meta.get("worst_profit_eur"),
            "best_profit_eur": meta.get("best_profit_eur"),
            "alpha": meta.get("alpha"),
            "risk_aversion": meta.get("risk_aversion"),
            "rainflow_aging_cost_eur": self.rainflow.aging_cost_eur,
            "rainflow_net_profit_eur": self.rainflow.net_profit_eur,
            "equivalent_full_cycles": self.rainflow.equivalent_full_cycles,
            "deep_cycle_count": self.rainflow.deep_cycle_count,
            "feasible": self.feasibility.feasible,
            "dynamics_residual_mwh": self.feasibility.dynamics_residual_mwh,
            "robust_worst_case_profit_eur": (
                self.robustness.worst_case_profit if self.robustness else None
            ),
            "robust_p10_profit_eur": (
                self.robustness.p10_profit if self.robustness else None
            ),
            "realized_profit_eur": (
                self.realized_evaluation.get("realized_profit_eur")
                if self.realized_evaluation
                else None
            ),
            "horizon": meta.get("horizon")
            or (self.scenarios.horizon if self.scenarios else None),
        }


def _coerce_scenarios(
    scenarios: Union[PriceScenarios, np.ndarray],
    timestamps: Optional[Sequence],
    sample_weights: Optional[np.ndarray],
    n_reduced_scenarios: Optional[int],
) -> PriceScenarios:
    """Accept the production input (PriceScenarios) or the prototyping
    fallback (raw (N, T) sample array). The production forecaster should
    ship `PriceScenarios` directly; the array path is a convenience that
    runs Heitsch-Romisch reduction in the optimizer.
    """
    if isinstance(scenarios, PriceScenarios):
        return scenarios

    samples = np.asarray(scenarios, dtype=float)
    if samples.ndim == 1:
        samples = samples[None, :]
    if samples.ndim != 2:
        raise ValueError("scenarios array must be 1D (T,) or 2D (N, T)")
    if timestamps is None:
        raise ValueError("timestamps must be provided when scenarios is an array")
    if len(timestamps) != samples.shape[1]:
        raise ValueError("timestamps length must match samples columns")

    n_samples = samples.shape[0]
    if n_reduced_scenarios is None or n_samples <= n_reduced_scenarios:
        if sample_weights is None:
            weights = np.full(n_samples, 1.0 / n_samples)
        else:
            weights = np.asarray(sample_weights, dtype=float)
            weights = weights / weights.sum()
        return PriceScenarios(
            timestamps=list(timestamps),
            prices=samples,
            weights=weights,
            labels=[f"s{i}" for i in range(n_samples)],
        )

    return scenarios_fast_forward(
        list(timestamps),
        samples,
        sample_weights=sample_weights,
        n_reduced=n_reduced_scenarios,
    )


def optimize_dispatch(
    scenarios: Union[PriceScenarios, np.ndarray, Sequence[Sequence[float]]],
    battery: BatteryProfile,
    *,
    timestamps: Optional[Sequence] = None,
    sample_weights: Optional[Sequence[float]] = None,
    duration_hours: float = 0.25,
    alpha: float = 0.10,
    risk_aversion: float = 0.5,
    n_reduced_scenarios: Optional[int] = 30,
    build_bid_curves: bool = True,
    bid_price_grid: Optional[Sequence[float]] = None,
    run_robustness_sweep: bool = True,
    realized_prices: Optional[Sequence[float]] = None,
    rainflow_aging_kwargs: Optional[dict] = None,
    use_soc_banded_degradation: bool = True,
    degradation_fixed_point_iterations: int = 2,
    degradation_bands: Optional[Sequence[tuple[float, float, float]]] = None,
    time_limit_s: Optional[int] = 180,
) -> DispatchResult:
    """Run the BatteryOS dispatch optimizer end-to-end.

    Inputs
    ------
    scenarios
        Production contract: a `PriceScenarios` bundle emitted by the
        forecaster - already sampled from the predictive distribution and
        reduced to a representative weighted set. This is what the
        forecaster team should ship.

        Convenience fallback: a raw NumPy array of shape (N, T) of Monte
        Carlo price paths. The optimizer will reduce these internally via
        Heitsch-Romisch fast-forward to `n_reduced_scenarios` scenarios.
        Use this only during prototyping, before the forecaster pipeline
        emits its own reduced bundle.
    battery
        `BatteryProfile`, either bundled or custom (see `BatteryProfile.custom`).
    timestamps
        Required when `scenarios` is a raw array; ignored otherwise.
    sample_weights
        Optional per-sample probabilities. Defaults to uniform.
    duration_hours
        Time-step length. Default 0.25h matches the SDAC 15-minute MTU.
    alpha
        CVaR tail mass. 0.10 means "the average outcome over the worst
        10% of scenarios". Industry typical range: 0.05 - 0.20.
    risk_aversion
        Convex weight on CVaR vs expected profit, in [0, 1]. 0 = pure
        risk-neutral, 1 = pure tail protection. Industry typical: 0.3 - 0.7.
    n_reduced_scenarios
        Target scenario count after reduction. Set to `None` to skip
        reduction (use all input samples directly).
    build_bid_curves
        Build a HEnEx-style price-quantity ladder per delivery period.
    bid_price_grid
        Optional custom EUR/MWh price grid for the bid curve. Defaults
        to a span around the expected-price min/max.
    run_robustness_sweep
        Sweep battery-parameter perturbations and report worst-case PnL.
    realized_prices
        Optional realized DAM clearing prices. When supplied, the result
        includes ex-post realized profit, plus rainflow scoring uses
        realized rather than forecast prices.
    rainflow_aging_kwargs
        Overrides for the Wohler-curve aging-cost defaults
        (replacement_cost_eur_per_mwh_capacity, wohler_exponent,
        cycles_to_eol_at_full_dod, soc_stress_factor).
    use_soc_banded_degradation
        If true, the optimizer uses a fixed-point linearization of
        SoC-aware degradation. It solves once with the base cost, turns the
        resulting SoC path into per-period degradation penalties via
        `soc_banded_throughput_costs`, then re-solves. This makes dispatch
        decisions avoid extreme SoC bands when the spread is marginal.
    degradation_fixed_point_iterations
        Number of fixed-point solves. Two is usually enough: base-cost solve
        plus one SoC-banded re-solve.
    degradation_bands
        Optional `(low_soc_frac, high_soc_frac, multiplier)` bands. Defaults
        to the stress bands in `soc_banded_throughput_costs`.
    time_limit_s
        Solver wall-clock cap.

    Returns
    -------
    DispatchResult bundling:
      - schedule         : Schedule (the DAM dispatch plan)
      - bid_curves       : BidCurves (HEnEx bid ladder per period)
      - rainflow         : RainflowScore (cycle-depth-aware aging)
      - feasibility      : FeasibilityReport (constraint compliance)
      - robustness       : ParameterSweepResult (worst-case under wrong specs)
      - scenarios        : the (possibly reduced) PriceScenarios used
      - battery          : the BatteryProfile used
      - realized_evaluation : ex-post PnL when realized_prices given
      - metadata         : run knobs

    Notes on degenerate cases:
      * One scenario in (or `risk_aversion=0`): the optimizer collapses
        to ordinary deterministic single-curve optimization. Same code
        path; no separate "deterministic mode" needed.
      * `risk_aversion=1`, `alpha` small: pure worst-case dispatch.
      * `risk_aversion=0`, many scenarios: pure expected-profit dispatch.
    """
    ps = _coerce_scenarios(
        scenarios,
        timestamps,
        np.asarray(sample_weights, dtype=float) if sample_weights is not None else None,
        n_reduced_scenarios,
    )

    n_degradation_iterations = (
        max(1, int(degradation_fixed_point_iterations))
        if use_soc_banded_degradation
        else 1
    )
    schedule: Schedule | None = None
    soc_frac_estimate = None
    degradation_costs = None
    for iteration in range(n_degradation_iterations):
        if use_soc_banded_degradation:
            kwargs = {
                "base_cost_eur_per_mwh": battery.degradation_cost_eur_per_mwh,
                "horizon": ps.horizon,
                "soc_frac_estimate": soc_frac_estimate,
            }
            if degradation_bands is not None:
                kwargs["bands"] = degradation_bands
            degradation_costs = soc_banded_throughput_costs(**kwargs)

        schedule = optimize_cvar(
            ps,
            battery,
            duration_hours=duration_hours,
            alpha=alpha,
            risk_aversion=risk_aversion,
            time_limit_s=time_limit_s,
            degradation_costs_eur_per_mwh=degradation_costs,
        )
        soc_frac_estimate = (
            schedule.df["state_of_charge_mwh"].to_numpy(dtype=float)
            / battery.energy_mwh
        )

    assert schedule is not None
    schedule.metadata.update(
        {
            "soc_banded_degradation_enabled": use_soc_banded_degradation,
            "degradation_fixed_point_iterations": n_degradation_iterations,
            "degradation_costs_eur_per_mwh": (
                None
                if degradation_costs is None
                else np.asarray(degradation_costs, dtype=float).tolist()
            ),
        }
    )

    feas = feasibility_report(schedule.df, battery, duration_hours)

    rainflow_kwargs = rainflow_aging_kwargs or {}
    rainflow = score_schedule_rainflow(
        schedule.df,
        battery,
        realized_prices=realized_prices,
        duration_hours=duration_hours,
        **rainflow_kwargs,
    )

    bid_curves: Optional[BidCurves] = None
    if build_bid_curves:
        bid_curves = build_bid_curves_resolve(
            ps.timestamps,
            ps.expected_prices(),
            battery,
            duration_hours=duration_hours,
            price_grid_eur_per_mwh=bid_price_grid,
            time_limit_s=time_limit_s,
        )

    robustness: Optional[ParameterSweepResult] = None
    if run_robustness_sweep:
        eval_prices = (
            np.asarray(realized_prices, dtype=float)
            if realized_prices is not None
            else ps.expected_prices()
        )
        robustness = sweep_battery_parameters(schedule, eval_prices, battery)

    realized_eval: Optional[dict] = None
    if realized_prices is not None:
        realized_eval = evaluate_schedule(
            schedule.df,
            np.asarray(realized_prices, dtype=float),
            battery,
            duration_hours,
        )

    return DispatchResult(
        schedule=schedule,
        bid_curves=bid_curves,
        rainflow=rainflow,
        feasibility=feas,
        robustness=robustness,
        scenarios=ps,
        battery=battery,
        realized_evaluation=realized_eval,
        metadata={
            "alpha": alpha,
            "risk_aversion": risk_aversion,
            "n_input_scenarios": ps.n_scenarios,
            "n_reduced_target": n_reduced_scenarios,
            "duration_hours": duration_hours,
            "horizon": ps.horizon,
            "build_bid_curves": build_bid_curves,
            "run_robustness_sweep": run_robustness_sweep,
            "had_realized_prices": realized_prices is not None,
            "soc_banded_degradation_enabled": use_soc_banded_degradation,
            "degradation_fixed_point_iterations": n_degradation_iterations,
        },
    )
