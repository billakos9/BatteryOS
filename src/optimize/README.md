# src/optimize

The BatteryOS dispatch optimizer. **One** optimizer.

## What it does

Takes the forecaster's scenario output, returns a day-ahead dispatch
plan, a HEnEx bid ladder, a rainflow-based degradation score, and a
battery-parameter robustness panel — in a single function call.

## Architecture: who owns what

```text
┌──────────────────── forecaster (separate module) ────────────────────┐
│  features → predictive distribution (probabilistic forecast)         │
│           → Monte Carlo sampling      (N price paths, N up to ~1000) │
│           → scenario reduction        (Heitsch-Romisch / k-means /   │
│                                        Wasserstein, S = 20-50)       │
│           → emits PriceScenarios      (S weighted scenarios)         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  PriceScenarios
                                ▼
┌──────────────────── optimizer (this module) ─────────────────────────┐
│  optimize_dispatch(scenarios, battery, ...)                          │
│           → Mean-CVaR LP                                             │
│           → bid curves                                               │
│           → rainflow degradation                                     │
│           → robustness sweep                                         │
│           → DispatchResult                                           │
└──────────────────────────────────────────────────────────────────────┘
```

**The forecaster owns scenario generation and reduction.** Sampling and
reduction are concerns about *how to represent uncertainty*, which the
forecaster has the most context to do well (it knows the predictive
density, the cross-time copula, conditional dependence on weather and
load). The optimizer just consumes the resulting `PriceScenarios`.

For convenience during prototyping (before the forecaster pipeline
emits its own reduced bundle), `optimize_dispatch` will *also* accept a
raw `(N, T)` NumPy array and run `scenarios_fast_forward` internally.
This is a fallback, not the production path.

The forecaster team should import the reducer it needs from
`src.optimize.scenarios` (or copy the algorithm into its own module —
it's ~80 lines of NumPy):

```python
from src.optimize.scenarios import (
    scenarios_fast_forward,    # Heitsch-Romisch (production-standard)
    scenarios_from_samples,    # k-means (faster, less tail-aware)
    scenarios_from_quantiles,  # 3-curve p10/p50/p90 (hackathon-grade)
    PriceScenarios,            # the output contract
)
```

```text
forecaster scenarios + battery profile
              │
              ▼
       optimize_dispatch
              │
              ▼
   ┌───────── DispatchResult ─────────┐
   │ schedule         96-period plan   │
   │ bid_curves       HEnEx ladder     │
   │ rainflow         aging cost       │
   │ feasibility      constraint check │
   │ robustness       worst-case panel │
   └───────────────────────────────────┘
```

## The technique (one combined optimizer, not three)

Mean-CVaR scenario-based stochastic optimization with Heitsch-Romisch
scenario reduction and the Rockafellar-Uryasev CVaR LP. Same
architecture used in production by Habitat Energy, Fluence Mosaic,
Tesla Autobidder, Gridmatic, Stem Athena.

Single objective:

```text
maximize  (1 - lambda) * E[profit]   +   lambda * CVaR_alpha[profit]
                ▲                              ▲
                │                              │
        risk-neutral term            tail-protection term
```

When the forecaster only emits a point forecast, the input collapses to
a single-scenario problem and the math reduces to ordinary deterministic
optimization automatically. There are no separate "deterministic" /
"stochastic" / "CVaR" modes for the user.

## Usage

```python
from src.optimize import (
    BatteryProfile, load_profile,
    optimize_dispatch, DispatchResult,
)

# 1. The asset
battery = load_profile("config/storage_profiles.yaml", "liion_100_2h")
# or:
battery = BatteryProfile.custom(
    name="my_megapack",
    power_mw=200, energy_mwh=400,
    round_trip_efficiency=0.88,
    max_cycles_per_day=1.5,
    degradation_cost_eur_per_mwh=2.5,
)

# 2. The forecaster output (Monte Carlo price paths)
samples = forecaster.predict(...)        # shape (N, 96), N up to ~1000

# 3. Run the optimizer — one call
result = optimize_dispatch(
    scenarios=samples,
    timestamps=ts,
    battery=battery,
    alpha=0.10,            # CVaR tail mass
    risk_aversion=0.5,     # weight on CVaR vs expected profit
    n_reduced_scenarios=30,
)

# 4. Use the outputs
schedule_df = result.schedule.df          # DAM dispatch plan
bid_ladder  = result.bid_curves           # to submit to HEnEx
aging_cost  = result.rainflow.aging_cost_eur
worst_case  = result.robustness.worst_case_profit
print(result.summary())
```

## What's in DispatchResult

| Field | Type | What it carries |
|---|---|---|
| `schedule` | `Schedule` | timestamp / forecast price / charge_mw / discharge_mw / SoC / action / profit per period |
| `bid_curves` | `BidCurves` | HEnEx-style price-quantity ladder per delivery period (resolve method) |
| `rainflow` | `RainflowScore` | ASTM E1049 rainflow cycles + Wöhler aging cost (replaces the constant €/MWh stand-in) |
| `feasibility` | `FeasibilityReport` | SoC / power / cycle / dynamics / terminal-SoC violations |
| `robustness` | `ParameterSweepResult` | realized PnL across efficiency × degradation perturbations |
| `scenarios` | `PriceScenarios` | the (possibly reduced) scenario set actually used |
| `battery` | `BatteryProfile` | the asset spec |
| `realized_evaluation` | `dict \| None` | ex-post PnL when realized prices are supplied |
| `metadata` | `dict` | the run knobs (alpha, lambda, horizon, …) |

## Tuning the knobs (industry-typical defaults)

| Knob | Default | Range used in industry |
|---|---|---|
| `alpha` | 0.10 | 0.05 – 0.20 (CVaR tail mass) |
| `risk_aversion` | 0.5 | 0.3 – 0.7 (weight on tail vs expected) |
| `n_reduced_scenarios` | 30 | 20 – 50 (post-reduction scenario count) |
| `duration_hours` | 0.25 | matches the SDAC 15-minute MTU |

## Files in this module

```text
dispatch.py          THE entry point: optimize_dispatch + DispatchResult
battery.py           BatteryProfile (incl. .custom builder + YAML loader)
schedule.py          Schedule output + period_profit / action labels
scenarios.py         PriceScenarios + reducers (forecaster-side utilities)
economics.py         period_profit, cycle counting, feasibility checks
degradation.py       Rainflow counter + Wöhler aging cost
bid_curves.py        Bid-curve construction (resolve method)
robust.py            CVaR LP engine + battery-parameter sweep   (private)
milp.py              Single-curve LP used inside bid_curves      (private)
_milp_core.py        Shared MILP scaffolding                     (private)
```

`robust.py`, `milp.py`, and `_milp_core.py` are the engine room of
`optimize_dispatch`. They are not part of the public API; only
`optimize_dispatch` is.

## Customizing the asset

Three ways to build a battery, all reach the same `BatteryProfile`:

```python
# Bundled catalog
load_profile("config/storage_profiles.yaml", "liion_100_2h")

# Multiple files (bundled + user)
load_profile(
    ["config/storage_profiles.yaml", "config/custom_profiles.yaml"],
    "my_megapack",
)

# Direct kwargs (the dashboard's "Create custom battery" form maps to this)
BatteryProfile.custom(
    name="my_megapack",
    power_mw=200,
    energy_mwh=400,
    soc_min_frac=0.10,
    soc_max_frac=0.90,
    round_trip_efficiency=0.88,
    max_cycles_per_day=1.5,
    degradation_cost_eur_per_mwh=2.5,
)
```
