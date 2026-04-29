# BatteryOS Optimizer — Technical Report

> **Scope:** The linear programming (LP/MILP) dispatch engine under `src/optimize/`.  
> **Date:** 2026-04-29

---

## 1. What the Optimizer Does

The optimizer turns a **price forecast** into a **battery dispatch schedule**. It answers:

> *Given a set of possible future Day-Ahead Market (DAM) prices and a battery specification, how much power should the battery charge or discharge in each 15-minute interval to maximize economic value while respecting physical constraints?*

It is **not** a forecaster. It consumes the forecaster's output (a `PriceScenarios` bundle) and produces:
- A charge/discharge schedule
- HEnEx-compatible bid curves
- Feasibility and robustness reports
- Cycle-depth-aware degradation scoring

---

## 2. High-Level Architecture

```
PriceScenarios  (from forecaster)
      |
      v
+----------------------------+
|  _coerce_scenarios()       |  <- reduce raw samples via Heitsch-Romisch
+----------------------------+
      |
      v
+----------------------------+
|  optimize_cvar()           |  <- Mean-CVaR stochastic MILP
+----------------------------+
      |
      v
+----------------------------+
|  feasibility_report()      |  <- validate constraints
|  score_schedule_rainflow() |  <- cycle-depth aging
|  build_bid_curves_resolve()|  <- HEnEx bid ladder
|  sweep_battery_parameters()|  <- robustness check
+----------------------------+
      |
      v
   DispatchResult
```

There is **one public entry point:**

```python
from src.optimize import optimize_dispatch

result = optimize_dispatch(scenarios, battery)
```

Everything else is internal machinery.

---

## 3. Battery Model (`battery.py`)

The battery is an immutable `BatteryProfile` dataclass with strict validation.

### Parameters

| Field | Meaning | Example (Li-ion 100 MW / 2h) |
|-------|---------|------------------------------|
| `power_mw` | Max charge/discharge power | 100 |
| `energy_mwh` | Nameplate energy capacity | 200 |
| `soc_min_mwh` | Minimum allowed state of charge | 20 |
| `soc_max_mwh` | Maximum allowed state of charge | 180 |
| `initial_soc_mwh` | Starting SoC at t=0 | 100 |
| `charge_efficiency` | Charge conversion efficiency | 0.949 |
| `discharge_efficiency` | Discharge conversion efficiency | 0.949 |
| `self_discharge_per_hour` | Standby energy loss per hour | 0.0001 |
| `max_cycles_per_day` | Equivalent full-cycle daily budget | 1.5 |
| `degradation_cost_eur_per_mwh` | Flat degradation penalty per MWh throughput | 2.0 |
| `terminal_soc_mwh` | Optional minimum SoC at end of horizon | — |

**Key derived properties:**
- `round_trip_efficiency = charge_efficiency × discharge_efficiency`
- `usable_energy_mwh = soc_max_mwh - soc_min_mwh`
- `duration_hours = energy_mwh / power_mw`

Profiles are loaded from `config/storage_profiles.yaml` (6 bundled profiles: 3 Li-ion, 2 pumped-hydro, 1 vanadium flow).

---

## 4. The Core MILP/LP (`_milp_core.py`)

All optimizers share the **same constraint scaffolding** via `build_battery_model()`. The model is built with **PuLP** and solved with **CBC** by default (or **HiGHS** if installed).

### 4.1 Decision Variables

For each time period `t = 0 … T-1`:

| Variable | Type | Bounds | Meaning |
|----------|------|--------|---------|
| `p_ch[t]` | Continuous | `[0, power_mw]` | Charge power (MW) |
| `p_dis[t]` | Continuous | `[0, power_mw]` | Discharge power (MW) |
| `soc[t]` | Continuous | `[soc_min, soc_max]` | State of charge (MWh) |
| `z[t]` | Binary (optional) | `{0, 1}` | Charge/discharge disjunction flag |

### 4.2 Constraints

**SoC dynamics (with self-discharge):**

```
soc[0] = decay × initial_soc
         + η_ch × p_ch[0] × Δt
         - p_dis[0] × Δt / η_dis

soc[t] = decay × soc[t-1]
         + η_ch × p_ch[t] × Δt
         - p_dis[t] × Δt / η_dis        for t ≥ 1
```

where `decay = 1 - self_discharge_per_hour × Δt` and `Δt = duration_hours`.

**Terminal SoC (optional):**
```
soc[T-1] ≥ terminal_soc_mwh          (if specified)
```

**Cycle budget (throughput cap):**
```
Σ_t (p_ch[t] + p_dis[t]) × Δt  ≤  2 × max_cycles_per_day × days × usable_energy_mwh
```

This enforces a daily equivalent-full-cycle limit by capping gross MWh moved.

**Mutual exclusion (optional):**
```
p_ch[t] ≤ power_mw × z[t]
p_dis[t] ≤ power_mw × (1 - z[t])
```

### 4.3 The LP Relaxation Trick

By default, `enforce_disjunction=False`. The binary `z[t]` variables are **omitted**, and the model solves as a **pure LP**.

**Why this is safe:**  
If `round_trip_efficiency < 1` (which is true for every real battery), simultaneous charge and discharge is **strictly suboptimal**: you lose energy going in both directions. The LP relaxation will never choose it at optimality, so the LP optimum equals the MILP optimum — but solves **orders of magnitude faster**.

If a user somehow passes a lossless battery (`η_rt ≥ 1`), `build_battery_model()` raises an error forcing `enforce_disjunction=True`.

### 4.4 Profit Expression

The objective contribution for a single price scenario is:

```
Profit = Σ_t [ price[t] × (p_dis[t] - p_ch[t]) × Δt ]
       - Σ_t [ deg_cost[t] × (p_ch[t] + p_dis[t]) × Δt ]
```

The first term is market revenue (discharge revenue minus charge cost).  
The second term is degradation cost proportional to throughput.

---

## 5. Deterministic Optimizer (`milp.py`)

`optimize_deterministic()` is the simplest mode:

1. Builds the shared battery model.
2. Adds a single profit expression for one price curve.
3. Solves the LP.
4. Extracts `p_ch`, `p_dis`, `soc` and wraps them in a `Schedule` DataFrame.

**Use case:** You have one point forecast (e.g., the p50 median) and want the schedule that maximizes profit on that exact curve.

---

## 6. CVaR / Robust Optimizer (`robust.py`)

`optimize_cvar()` is the **production-grade risk-aware optimizer**. It uses the **Rockafellar-Uryasev LP reformulation** of Conditional Value-at-Risk (CVaR).

### 6.1 Mathematical Formulation

Given `S` scenarios with probabilities `w_s` and per-scenario profit expressions `Profit_s`, the objective is:

```
maximize  (1 - λ) × E[Profit] + λ × CVaR_α[Profit]
```

where:
- `λ = risk_aversion` ∈ [0, 1]
- `α = alpha` ∈ (0, 1] is the tail mass (e.g., 0.10 = worst 10%)

**CVaR LP epigraph:**

```
CVaR_α = max_{η, u_s ≥ 0}  η - (1/α) × Σ_s w_s × u_s
s.t.     u_s ≥ η - Profit_s     for all s
```

The optimizer adds:
- One continuous variable `η` (the VaR threshold)
- One auxiliary `u_s ≥ 0` per scenario
- Constraints `u_s ≥ η - Profit_s`

The final objective becomes:

```
maximize  (1 - λ) × Σ_s w_s × Profit_s
        + λ × [ η - (1/α) × Σ_s w_s × u_s ]
```

This remains a **pure LP** (no quadratic terms), so it solves fast and scales to many scenarios.

### 6.2 Degenerate Cases

| Configuration | Behavior |
|---------------|----------|
| Single scenario + λ=0 | Collapses to deterministic optimization |
| λ=0, many scenarios | Pure expected-profit (risk-neutral) stochastic optimization |
| λ=1, α small | Pure worst-case / tail-protection dispatch |

### 6.3 Post-Optimization Diagnostics

After solving, `optimize_cvar()` recomputes the actual realized profit under each scenario and reports:
- `expected_profit_eur`
- `cvar_eur` — realized conditional tail average
- `worst_profit_eur` / `best_profit_eur`
- `scenario_profits_eur` — per-scenario PnL vector

### 6.4 Parameter Sweep (`sweep_battery_parameters()`)

Replays the **fixed schedule** against perturbed battery specs to measure robustness:
- Round-trip efficiency: 85%, 90%, 95%, 100%
- Degradation cost: 1, 2, 3, 5 EUR/MWh

Reports worst-case, p10, median, and nominal profit. This answers: *"What happens to my PnL if the battery doesn't match the spec sheet?"*

---

## 7. Unified Dispatch (`dispatch.py`)

`optimize_dispatch()` is the **single public API**. It orchestrates the full pipeline.

### 7.1 Scenario Coercion

Accepts either:
- A `PriceScenarios` object (production contract)
- A raw `(N, T)` NumPy array (prototyping fallback)

If given a raw array, it reduces via `scenarios_fast_forward()` (Heitsch-Romisch) to `n_reduced_scenarios` (default 30).

### 7.2 SoC-Banded Degradation Fixed-Point Loop

By default (`use_soc_banded_degradation=True`), the optimizer runs a **fixed-point iteration**:

1. **Base solve:** Run CVaR with flat degradation cost.
2. **Map SoC → penalties:** Use the resulting SoC trajectory to compute per-period degradation costs via `soc_banded_throughput_costs()`. Extreme SoC bands (0–15% and 85–100%) get a higher penalty.
3. **Re-solve:** Run CVaR again with the updated cost vector.
4. Repeat for `degradation_fixed_point_iterations` (default 2).

This makes dispatch **avoid marginal trades near the SoC edges** where calendar+cycle aging compounds, without making the MILP nonlinear.

### 7.3 Output Bundle (`DispatchResult`)

| Attribute | Type | What it contains |
|-----------|------|------------------|
| `schedule` | `Schedule` | Charge/discharge/SoC trajectory + period profit |
| `bid_curves` | `BidCurves` | HEnEx price-quantity ladder per period |
| `rainflow` | `RainflowScore` | ASTM E1049 rainflow aging analysis |
| `feasibility` | `FeasibilityReport` | Constraint violation report |
| `robustness` | `ParameterSweepResult` | Perturbed-battery profit distribution |
| `scenarios` | `PriceScenarios` | The (possibly reduced) scenario set used |
| `realized_evaluation` | `dict` | Ex-post PnL when realized prices are supplied |

---

## 8. Scenario Handling (`scenarios.py`)

### 8.1 `PriceScenarios`

A validated dataclass containing:
- `timestamps`: shared time axis (length `T`)
- `prices`: matrix `(S, T)` — one price curve per scenario
- `weights`: probability vector summing to 1 (length `S`)
- `labels`: human-readable scenario names

### 8.2 Scenario Reduction Methods

| Method | Function | Description |
|--------|----------|-------------|
| **Quantiles** | `scenarios_from_quantiles()` | 3-scenario bundle from p10/p50/p90 with weights (0.2, 0.6, 0.2) |
| **k-means** | `scenarios_from_samples()` | Reduce N Monte Carlo paths to k centroids, weighted by cluster size |
| **Fast-forward** | `scenarios_fast_forward()` | Heitsch-Romisch greedy selection minimizing Kantorovich distance |

**Fast-forward** is the production default. It iteratively picks the scenario that most reduces the Wasserstein-1 distance between the original and reduced empirical distributions, then reassigns probability mass of discarded scenarios to their nearest kept neighbor. It is empirically preferred over k-means when tail prices drive most of the PnL.

---

## 9. Economics & Feasibility (`economics.py`)

### 9.1 Period Profit

```python
market = price × (discharge - charge) × Δt
deg = degradation_cost × (charge + discharge) × Δt
profit = market - deg
```

### 9.2 Feasibility Report

After optimization, `feasibility_report()` checks:
- **SoC bounds:** `soc_min ≤ soc[t] ≤ soc_max`
- **Power bounds:** `0 ≤ charge, discharge ≤ power_mw`
- **Simultaneity:** `min(charge, discharge) ≈ 0` (if enforced)
- **Cycle budget:** `cycles_used ≤ max_cycles_per_day × days`
- **Dynamics:** Re-simulates SoC from the schedule and checks `|sim_soc - opt_soc| ≈ 0`
- **Terminal SoC:** `soc[T-1] ≥ terminal_soc_mwh` (if specified)

A schedule is `feasible` only if all violations are within `tol_mw = 1e-4`.

---

## 10. Degradation Models (`degradation.py`)

### 10.1 Rainflow Aging (Post-Hoc)

`score_schedule_rainflow()` analyzes the optimized SoC trajectory with **ASTM E1049 four-point rainflow counting**:

1. Extract extrema from the SoC trajectory.
2. Decompose into half-cycles and full-cycles.
3. Price each cycle with a **Wohler-curve model:**

```
aging_cost = replacement_cost × (depth^wohler_exponent) × soc_stress_term
```

where `soc_stress_term` penalizes extreme mean-SoC operation (very full or very empty).

**Purpose:** Compare the constant EUR/MWh assumption used inside the MILP against a realistic physics-based aging cost.

### 10.2 SoC-Banded Throughput Costs (In-MILP)

`soc_banded_throughput_costs()` returns a per-period degradation cost vector:
- Base cost everywhere
- Multiplied by a factor (default 2×) when the expected SoC falls in stress bands (0–15% or 85–100%)

This is a **linear surrogate** that slots directly into the LP objective. The fixed-point loop in `optimize_dispatch()` iterates between solving and updating the banded cost vector until convergence.

---

## 11. Bid Curves (`bid_curves.py`)

`build_bid_curves_resolve()` constructs a **price-quantity ladder** for each delivery period compatible with HEnEx DAM bidding.

**Method:** For each period `t` and each candidate clearing price `p` on a grid:
1. Perturb the price vector: set `price[t] = p`.
2. Re-run the deterministic optimizer.
3. Record the net dispatch `discharge[t] - charge[t]` as the bid quantity at price `p`.

The result is a step function `q(p)` per period. The optimizer defaults to an 11-point grid spanning `[min_price - 0.5×spread, max_price + 0.5×spread]`.

**Output:** `BidCurves` object with methods:
- `to_long_dataframe()` — flat table of (timestamp, price, quantity)
- `ladder_for_period(t)` — step changes only, for human-readable submission

---

## 12. Schedule Output (`schedule.py`)

A `Schedule` is a dataclass wrapping a pandas DataFrame with columns:

| Column | Meaning |
|--------|---------|
| `timestamp` | Delivery period |
| `forecast_price_eur_per_mwh` | Price used for optimization |
| `charge_mw` | Charge power |
| `discharge_mw` | Discharge power |
| `state_of_charge_mwh` | SoC after the period |
| `action` | `CHARGE`, `DISCHARGE`, or `IDLE` |
| `period_profit_eur` | Revenue - degradation for the period |

Convenience methods:
- `total_profit()` — sum of `period_profit_eur`
- `revenue()` — market revenue only
- `throughput_mwh()` — gross MWh moved

---

## 13. Solver Strategy

The solver hierarchy in `get_solver()`:
1. Try **HiGHS_CMD** (faster, better scaling)
2. Fallback to **PULP_CBC_CMD** (ships with PuLP, always available)

Default time limits:
- Deterministic: 60 s
- CVaR / dispatch: 180 s

All models are **pure LP** by default (no binary variables), so even the stochastic CVaR optimizer with dozens of scenarios solves in well under a second for a 96-period horizon.

---

## 14. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **LP relaxation default** | With η_rt < 1, simultaneous charge+discharge is strictly dominated. Dropping binaries makes the problem a fast LP without losing optimality. |
| **Mean-CVaR objective** | Industry standard (Habitat Energy, Fluence, Tesla, Gridmatic). Captures tail risk in a single LP, no quadratic programming needed. |
| **Scenario reduction outside the optimizer** | The forecaster owns the reduction step. The optimizer only consumes `PriceScenarios`. This keeps the interface clean and lets forecasting teams iterate independently. |
| **Flat + banded degradation** | Flat cost keeps the objective linear. The fixed-point banded upgrade adds physical realism without changing the solver. Rainflow scoring provides a post-hoc reality check. |
| **Parameter sweep on fixed schedule** | Robustness is checked by *evaluating* the schedule under wrong assumptions, not by re-optimizing. This matches how operators think: "If my battery degrades faster than expected, how bad is the schedule I already committed?" |

---

## 15. How to Use It

```python
from src.optimize import optimize_dispatch, BatteryProfile, load_profile

# Load a battery spec
battery = load_profile("config/storage_profiles.yaml", "liion_100_2h")

# Or build a custom one
battery = BatteryProfile.custom(
    name="my_bess",
    power_mw=50,
    energy_mwh=100,
    round_trip_efficiency=0.90,
)

# Run the optimizer (deterministic = single scenario, CVaR disabled)
result = optimize_dispatch(
    scenarios=forecast_prices,   # PriceScenarios or (N, T) array
    battery=battery,
    timestamps=pd.date_range("2026-04-29", periods=96, freq="15min"),
    alpha=0.10,
    risk_aversion=0.5,
    build_bid_curves=True,
    run_robustness_sweep=True,
)

# Access outputs
print(result.schedule.df.head())
print(result.summary())
print(result.feasibility.feasible)
```

---

*End of optimizer technical report.*
