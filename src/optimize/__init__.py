"""BatteryOS dispatch optimizer.

There is exactly one user-facing optimizer:

    from src.optimize import optimize_dispatch, BatteryProfile, load_profile

    result = optimize_dispatch(scenarios, battery)

It runs Mean-CVaR scenario-based stochastic optimization, builds the
HEnEx bid curve, scores rainflow-based degradation, and reports
battery-parameter robustness — all in one call. See dispatch.py.
"""
from .battery import BatteryProfile, list_profiles, load_profile, save_profile
from .bid_curves import BidCurves
from .degradation import (
    RainflowCycle,
    RainflowScore,
    cycle_aging_cost_eur,
    rainflow_count,
    score_schedule_rainflow,
    soc_banded_throughput_costs,
)
from .dispatch import DispatchResult, optimize_dispatch
from .economics import (
    FeasibilityReport,
    equivalent_full_cycles,
    evaluate_schedule,
    feasibility_report,
    period_profit,
)
from .robust import ParameterSweepResult
from .risk_profiles import (
    CUSTOM_RISK_PROFILE,
    DEFAULT_RISK_PROFILE,
    RISK_PROFILE_PRESETS,
    RiskProfilePreset,
    resolve_risk_profile,
)
from .scenarios import (
    PriceScenarios,
    scenarios_fast_forward,
    scenarios_from_quantiles,
    scenarios_from_samples,
)
from .schedule import SCHEDULE_COLUMNS, Schedule

__all__ = [
    # The single public optimizer
    "optimize_dispatch",
    "DispatchResult",
    # Battery
    "BatteryProfile",
    "load_profile",
    "list_profiles",
    "save_profile",
    # Forecaster output contract
    "PriceScenarios",
    "scenarios_from_quantiles",
    "scenarios_from_samples",
    "scenarios_fast_forward",
    # Schedule + diagnostics consumed by the dashboard
    "Schedule",
    "SCHEDULE_COLUMNS",
    "evaluate_schedule",
    "period_profit",
    "equivalent_full_cycles",
    "feasibility_report",
    "FeasibilityReport",
    # Result components
    "BidCurves",
    "RainflowCycle",
    "RainflowScore",
    "ParameterSweepResult",
    "RiskProfilePreset",
    "RISK_PROFILE_PRESETS",
    "DEFAULT_RISK_PROFILE",
    "CUSTOM_RISK_PROFILE",
    "resolve_risk_profile",
    # Degradation utilities (also used by score_schedule_rainflow)
    "rainflow_count",
    "score_schedule_rainflow",
    "cycle_aging_cost_eur",
    "soc_banded_throughput_costs",
]
