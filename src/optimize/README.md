# src/optimize

Battery scheduling optimizers and economic dispatch logic live here.

## What this module owns

The optimizer does not collect data and does not forecast prices.

It starts after the forecaster has already produced a price forecast.

```text
forecaster output -> optimizer -> battery schedule + expected profit
```

## Input from the forecaster

The optimizer only needs a clean forecast table like this:

```text
timestamp
forecast_price_eur_per_mwh
```

Optional later:

```text
p10_price_eur_per_mwh
p50_price_eur_per_mwh
p90_price_eur_per_mwh
```

That means the optimizer does not care whether the forecast came from:

```text
naive model
LightGBM
statistical model
manual forecast
perfect-foresight benchmark
```

As long as it receives the same interface, it can work.

## Other inputs

The optimizer also needs a storage profile:

```text
power_mw
energy_mwh
min_soc_mwh
max_soc_mwh
initial_soc_mwh
charge_efficiency
discharge_efficiency
max_cycles_per_day
degradation_cost_eur_per_mwh
```

Example:

```text
power_mw = 100
energy_mwh = 200
min_soc_mwh = 20
max_soc_mwh = 180
initial_soc_mwh = 100
charge_efficiency = 0.95
discharge_efficiency = 0.95
max_cycles_per_day = 1.5
degradation_cost_eur_per_mwh = 2
```

## Decision

For every timestamp, the optimizer decides:

```text
charge_mw[t]
discharge_mw[t]
state_of_charge_mwh[t]
action[t]
```

Where:

```text
action = CHARGE, DISCHARGE, or IDLE
```

## Core constraints

The battery must obey:

```text
0 <= charge_mw[t] <= power_mw
0 <= discharge_mw[t] <= power_mw
min_soc_mwh <= state_of_charge_mwh[t] <= max_soc_mwh
cannot charge and discharge at the same time
state_of_charge evolves correctly through time
daily cycle limit is respected
```

State of charge update:

```text
soc[t] =
  soc[t-1]
  + charge_mw[t] * charge_efficiency * duration_hours
  - discharge_mw[t] / discharge_efficiency * duration_hours
```

For 15-minute DAM data:

```text
duration_hours = 0.25
```

## Economic objective

The optimizer maximizes expected profit:

```text
profit =
  revenue_from_discharge
  - cost_of_charge
  - degradation_cost
```

For each timestamp:

```text
market_profit[t] =
  forecast_price[t]
  * (discharge_mw[t] - charge_mw[t])
  * duration_hours
```

Total:

```text
maximize sum(market_profit[t]) - degradation_cost
```

## Stochastic optimization

The deterministic version above trusts a single forecast price curve.

The stochastic version optimizes across many possible price curves at once.

Forecaster output with uncertainty:

```text
timestamp | p10 | p50 | p90
12:00     | 10  | 20  | 50
19:00     | 90  | 180 | 300
```

Convert this into scenarios:

```text
low scenario   = p10 curve
base scenario  = p50 curve
high scenario  = p90 curve
```

The optimizer chooses ONE schedule before knowing which scenario happens, then evaluates profit under each scenario:

```text
profit_low
profit_base
profit_high
```

### Objective options

Expected profit (probability weighted):

```text
maximize  w_low * profit_low + w_base * profit_base + w_high * profit_high
```

Example weights:

```text
0.2 * profit_low + 0.6 * profit_base + 0.2 * profit_high
```

Risk-adjusted profit:

```text
maximize  expected_profit - lambda * risk_penalty
```

Robust / worst-case (CVaR-style):

```text
maximize  worst_case_profit
```

### What stays the same

```text
SoC limits
power limits
cycle limits
no simultaneous charge/discharge
state-of-charge update equation
```

Only the objective function changes. Constraints are enforced on the single schedule that must work across all scenarios.

### Why it matters

A deterministic optimizer can pick a schedule that looks great on the p50 forecast but loses money if reality lands near p10. The stochastic optimizer prefers schedules that are decent across the whole distribution.

Example tradeoff:

```text
Schedule A:  profit_low = -1000,  profit_base =  5000,  profit_high = 12000
Schedule B:  profit_low =  1000,  profit_base =  4000,  profit_high =  7000
```

Maximizing upside picks A. Maximizing worst case picks B.

### Implementation order

```text
1. deterministic optimizer on forecast_price (or p50)
2. scenario evaluator: replay one schedule across p10/p50/p90 to score robustness
3. stochastic optimizer: jointly optimize across scenarios with expected-profit objective
4. robust optimizer: worst-case or CVaR objective
```

Build step 1 first. Steps 2-4 reuse the same battery model and constraints.

## Output

The optimizer should return a schedule:

```text
timestamp
forecast_price_eur_per_mwh
charge_mw
discharge_mw
state_of_charge_mwh
action
period_profit_eur
```

Example:

```text
00:00 | 60 EUR/MWh  | charge 100 MW    | soc increases
12:00 | 20 EUR/MWh  | charge 100 MW    | soc increases
19:00 | 180 EUR/MWh | discharge 100 MW | soc decreases
```

## Files in this module

```text
battery.py        BatteryProfile dataclass + YAML loader
schedule.py       Schedule output format + period_profit/action labels
economics.py      profit, cycles, feasibility checks
scenarios.py      PriceScenarios + quantile/sample reduction (k-means)
_milp_core.py     shared MILP building blocks (variables, constraints, solver)
rule_based.py     greedy rank-based heuristic (no solver)
milp.py           deterministic single-curve optimizer
stochastic.py     two-stage scenario MILP (expected / worst-case / mean-MAD)
robust.py         CVaR optimizer + battery-parameter sweep
__init__.py       public API
```

Public API:

```python
from src.optimize import (
    BatteryProfile, load_profile,
    optimize_rule_based, optimize_deterministic,
    scenarios_from_quantiles, scenarios_from_samples,
    optimize_stochastic, optimize_cvar,
    sweep_battery_parameters, feasibility_report,
)
```

Solver: PuLP with CBC by default; auto-switches to HiGHS if installed.

## First implementation target

Build this first:

```text
forecast_price curve -> simple optimizer -> schedule -> expected profit
```

This can be tested with fake prices, so it does not block on the data team.

Example fake forecast:

```text
low prices at noon
high prices in the evening
```

Expected behavior:

```text
charge at low prices
discharge at high prices
stay idle when spread is not worth it
```

## Boundary with the forecasting teammate

Your teammate owns:

```text
raw HEnEx/IPTO/weather data
feature engineering
price forecasting
forecast accuracy metrics
```

The optimizer owns:

```text
battery constraints
charge/discharge decisions
profit calculation
robustness to battery parameter uncertainty
schedule feasibility
```

The contract between both parts is only:

```text
timestamp + forecast_price
```

Later, if the forecaster produces uncertainty, the contract becomes:

```text
timestamp + p10_price + p50_price + p90_price
```
