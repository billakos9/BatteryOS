# BatteryOS — Hackathon Workflow Plan (v4, business + multi-country)

**Topic:** Battery & storage-unit optimization in European day-ahead electricity markets, anchored on Greece.
**Goal:** A tech business — not just a working prototype — built in three days. The product is a **storage-agnostic, country-agnostic dispatch optimization service** that turns the physical asset's capability into economic value, defended by a **proprietary multi-country data pipeline**.

> "The core of the challenge is not the market itself, but the design of a robust battery optimization framework that can operate in a realistic environment with limited asset-specific information." — organizer brief

---

## Table of contents

0. Three-day sprint reframe — what we're actually shipping
1. Customer, market, and TAM
2. Proprietary data strategy — the moat
3. Scope clarifications (storage class, geography, data scarcity)
4. Mental model — four coupled layers
5. Phase 0 — Pre-data setup
6. Phase 1 — Multi-country data layer
7. Phase 2 — **Feature engineering (THE LEVERAGE)**, including the German domino
8. Phase 3 — Forecasting layer
9. Phase 4 — Optimization layer (storage-agnostic, country-aware)
10. Phase 5 — Backtesting
11. Phase 6 — Decision interface (the demo + pitch surface)
12. Risk register
13. Three-day sprint plan
14. Open questions
15. Changelog

---

## 0. Three-day sprint reframe

We are not building a tool. We are building a **tech business** with multiple potential customers, in three days. That changes the shape of the deliverable.

| Track | Day 1 | Day 2 | Day 3 |
|---|---|---|---|
| **Tech** | Greek end-to-end MVP: optimizer + naive forecast + walk-forward PnL | Multi-country data + advanced features (DE domino, supply-curve) + ML forecast | Profile/country sweep, robustness panel |
| **Product** | Customer persona + use case fixed | Demo flow drafted, dashboard skeleton | Polished demo, narrative, pitch deck |
| **Business** | Define moat thesis + TAM | Pricing model + go-to-market | Pitch, Q&A prep, roadmap (30/90/365) |

The technical and business tracks both run from hour 1 — not "tech first, business later." The pitch only lands if the dashboard tells the same story.

---

## 1. Customer, market, and TAM

**Anchor customer (the persona we sell to first):**
- A Greek standalone BESS operator (100–300 MW) entering the DAM in 2026, with new-asset constraints: limited operational history, uncertain parameter calibration, regulatory pressure to monetize cleanly.
- They have engineers but not a quant trading desk. They want a service, not a research project.

**Adjacent customers (Day 2/3 widening):**
- IPPs with hybrid renewables + storage, who need joint dispatch logic.
- Trading desks at utilities, monetizing third-party storage.
- Aggregators / VPP operators rolling up smaller assets into DAM-eligible blocks.
- Storage-unit operators (pumped hydro, flow) who share the same dispatch logic.

**Geography:**
- **Phase 1 (Greek anchor):** HEnEx DAM, IPTO data, the local emerging-storage cohort (April 2026+).
- **Phase 2 (SDAC-coupled neighborhood):** Italy (IT-South direct cable), Bulgaria (land neighbor), Romania, Hungary, Austria, Slovenia.
- **Phase 3 (continental):** Germany, Netherlands, France, Spain, Poland — the large RES-rich markets that *drive* the smaller markets via the coupling chain.

**TAM logic:** ~25+ SDAC bidding zones, hundreds of utility-scale BESS already announced or in pipeline across Europe. Greek anchor proves the pattern; multi-country generality multiplies it. Our pitch is "we already work everywhere SDAC clears."

**Pricing-model options (we pick a default for the pitch):**
- SaaS per-asset / per-MW-month subscription.
- Performance-based: % of profit uplift vs a naive benchmark (defensible from the backtest).
- Tiered: free profile-comparison + paid live dispatch.

Default pitch: hybrid SaaS base + small performance kicker. Aligns incentives, predictable revenue.

---

## 2. Proprietary data strategy — the moat

Anyone can pull HEnEx clearing prices. The defensibility of the business lives in the **data assembly pipeline**, not in any single source. We articulate this in tiers.

### 2.1 Tiered data model

| Tier | What | Who has it | Our edge |
|---|---|---|---|
| **T1 — Commodity** | DAM clearing prices, basic Open-Meteo, IPTO load forecast (single country) | Everyone | None — table stakes |
| **T2 — Operationally hard to assemble** | Multi-country ENTSO-E TP harmonized across 25+ zones, REMIT UMM outage feeds, aggregated buy/sell curves from each exchange (HEnEx, EPEX, GME, IPEX), per-country population-weighted weather, per-country RES-capacity-weighted irradiance/wind | Few competitors | **Our day-1/2 moat** |
| **T3 — Premium / paid** | Refinitiv, ICIS, Argus, ECMWF HRES, Solcast/Reuniwatt nowcasts, paid REMIT feeds | Pay-to-play | Roadmap; we mention but don't license in 3 days |
| **T4 — Network-effect proprietary** | Anonymized customer telemetry, calibrated degradation curves, real efficiency surfaces, observed bidding patterns | Only us, post-customer-1 | The long-term moat |

The pitch: *"We start with a Tier-2 advantage from day one, and every customer we onboard widens the Tier-4 lead."*

### 2.2 The Tier-2 catalog (what we actually build)

- **Multi-country ENTSO-E aggregator.** Harmonize timezones, MTU, late corrections, fuel-type taxonomies across 25+ zones. The plumbing is the moat.
- **REMIT UMM outages.** EEX publishes inside-information messages on plant outages — public, but XML and scattered. Aggregating into a "next-7-days outage signal per fuel type per zone" is feature-engineering gold.
- **Cross-exchange supply-curve store.** Pull aggregated buy/sell curves where exchanges publish them (HEnEx does). Reconstruct supply stack, identify gas-band entry, slope at clearing.
- **Hydro reservoir levels.** Nordic (NVE, Statkraft), Alpine (swissgrid, Verbund). Northern hydro abundance shifts continental supply; signals propagate south through the corridor.
- **Population-weighted temperature** per country (e.g. Athens + Thessaloniki for Greece, Berlin + Munich + Hamburg for Germany). One number that matters for load.
- **RES-capacity-weighted weather.** Where the wind farms actually are, where the solar farms actually are — weight the meteo inputs accordingly. Rarely done well in public projects.
- **Coupling-corridor pressure indices.** Engineered features described in §7 — e.g. central-corridor surplus, continental wind index. These *are* the proprietary IP of the forecaster.

### 2.3 What we say in the pitch

"Our forecast moat isn't a fancier model. It's that no one else has assembled the data layer this way. We harmonize 25+ bidding zones, REMIT outages, hydro reservoirs, exchange-published supply curves, and capacity-weighted meteorology into a single point-in-time feature store. Competitors using public Greek-only data are one-feature deep where we are forty-deep."

---

## 3. Scope clarifications (carried forward, refreshed)

1. **Storage-agnostic.** Same MILP for chemical batteries (Li-ion) and storage units (pumped hydro, flow). Only parameter intervals differ.
2. **Large utility-scale.** 100 / 200 / 300 MW power class. Energy capacity from duration (1–2 h Li-ion, 4–12 h storage units).
3. **No fixed dataset, no fixed constraints.** Parametric design via parameter intervals + robustness sweep.
4. **Data scarcity = battery-side.** Market/system/weather data is plentiful. Battery telemetry is essentially nonexistent (first standalone Greek BESS in test mode April 2026).
5. **Multi-country, Greek-anchored.** Greece is the demo; Europe is the product.
6. **German domino.** German fundamentals enter Greek price features via SDAC coupling chain — DE → AT/CH → IT-N → IT-S → GR, and DE → CZ → SK → HU → RO → BG → GR.
7. **Feature engineering is the highest-leverage forecasting step.** §7.
8. **Price signal = DAM clearing price.**

A *secondary* market-side scarcity: only ~6 months of 15-min DAM data exists in Greece as of late April 2026 (MTU shift on 1 Oct 2025). Forecasting design constraint, not the brief's "data scarcity."

---

## 4. Mental model — four coupled layers (+ a robustness wrapper)

```
   Multi-country data layer ─▶ Feature engineering ─▶ Forecasting layer ─▶ Optimization layer ─▶ Schedule
        (THE MOAT)              (THE LEVERAGE)              ▲                       ▲
                                                             │                       │
                                                         features              storage spec (interval)
                                                                                     │
                                                                          Robustness wrapper
                                                                          (parameter sweep, worst-case)
```

Four rules to defend in the demo:
1. **Forecast first, optimize second.**
2. **Probabilistic forecasts, not just point.**
3. **Storage parameters are intervals, not numbers.**
4. **Country is a config, not a hardcode.**

---

## 5. Phase 0 — Pre-data setup

```
batteryos/
├── data/                          # raw + processed (gitignored)
├── notebooks/
├── src/
│   ├── ingest/
│   │   ├── entsoe.py              # 25+ zones, harmonized
│   │   ├── henex.py               # Greek DAM + supply curves
│   │   ├── ipto.py                # Greek system data
│   │   ├── openmeteo.py           # population/capacity-weighted
│   │   ├── ttf.py                 # ICE TTF gas
│   │   ├── eua.py                 # EEX EUA carbon
│   │   ├── remit.py               # outage messages
│   │   └── hydro.py               # Nordic + Alpine reservoirs
│   ├── features/                  # PIT, leakage-tested feature library
│   ├── forecast/                  # baseline → ML → quantile
│   ├── optimize/                  # MILP + robust wrapper, country-aware
│   ├── backtest/                  # walk-forward, gate-close-aware
│   └── viz/                       # Streamlit demo
├── configs/
│   ├── countries.yaml             # per-zone: MTU, gate-close, holidays, neighbors, RES capacity
│   ├── storage_profiles.yaml      # liion_100_2h, liion_200_2h, ..., phs_100_8h, flow_100_6h
│   └── feature_specs.yaml         # feature catalog with release timestamps
├── tests/
└── WORKFLOW_PLAN.md
```

**Roles (4-person team recommended):**
- **Data lead:** ingestion across all six+ sources, multi-country harmonization.
- **Feature lead:** PIT feature library, leakage tests, importance audits, the German-domino features.
- **Forecast lead:** baseline → ML → quantile, all consuming the feature store.
- **Optimization lead:** MILP, robust wrapper, parameter sweep, backtester. *Most senior — this is the engineering core.*
- **Demo + business lead** *(can overlap with one of the above):* Streamlit app, pitch narrative, slides, pricing model.

**Environment:** Python 3.11, `uv` or `poetry`. `pandas`, `numpy`, `scikit-learn`, `lightgbm`, `statsmodels`, `darts`/`nixtla`, `pyomo` + `highs`, `streamlit`.

---

## 6. Phase 1 — Multi-country data layer

### 6.1 Greek-anchored (per organizer brief)

| Source | What | Resolution |
|---|---|---|
| **HEnEx** market results | target signal | hourly → 15-min (since 2025-10-01) |
| **HEnEx** aggregated buy/sell curves | supply-stack reconstruction | per delivery period |
| **IPTO/ADMIE** load + RES forecast, ATC, ISP | exogenous drivers + cross-border | hourly + ISP |
| **Open-Meteo** | T, wind, cloud, irradiance forecast | hourly |
| **ICE TTF** | gas futures | daily |
| **EEX** EUA | carbon | daily |
| **ENTSO-E TP** | cross-border flows, gen mix, outages | hourly+ |
| Battery telemetry | (none until Apr 2026 onwards) | — |

### 6.2 Multi-country expansion (the moat work)

The same six categories, replicated across the SDAC zones. ENTSO-E TP is the unifying source — it covers all of them. The work is harmonization (timezone, MTU, late corrections, fuel taxonomies).

**Country profile config (`configs/countries.yaml`):**
```yaml
GR:
  mtu_minutes: 15        # since 2025-10-01, else 60
  gate_close: "12:00 CET"
  exchange: HEnEx
  tso: IPTO
  neighbors: [IT_S, BG]
  upstream_via_chain: [AT, CH, DE, CZ, SK, HU, RO]
IT_S:
  mtu_minutes: 15
  gate_close: "12:00 CET"
  exchange: GME
  neighbors: [GR, IT_C, AL, ME]
  upstream_via_chain: [AT, CH, DE]
DE_LU:
  mtu_minutes: 15        # since 2025-10-01 across all SDAC
  gate_close: "12:00 CET"
  exchange: EPEX
  neighbors: [FR, AT, CH, NL, BE, LU, DK_W, PL, CZ]
# ... etc, ~25 zones
```

The "domino chain" is encoded explicitly so feature builders can walk it.

### 6.3 EDA checklist (≤ 1 day)

- Greek DAM seasonality: daily/weekly/yearly.
- **Negative-price periods** — flag explicitly. RES surplus → prime charging windows.
- Daily spread distribution: max(P) − min(P). 15-min MTU widens spread → more arbitrage.
- Correlation: Greek price ↔ Greek residual load (load − wind − solar).
- **Cross-country correlations:** Greek price ↔ DE, IT-S, BG, AT, RO prices at lag 0 and lag 1d. Build the correlation map.
- Gas / EUA regime overlay.
- Hourly era vs 15-min era distributional check.
- Missingness map per source.

---

## 7. Phase 2 — Feature engineering (THE LEVERAGE)

This phase deserves more time than any other in the forecasting stack. Model class matters less than features.

### 7.1 Operating principles

- **Point-in-time / no leakage.** Every feature carries a release timestamp. A feature for delivery day d+1 must be released on or before gate close (**12:00 CET on day d**). Anything later is leakage.
- Use *forecast* versions of exogenous signals (load forecast, RES forecast, weather forecast at gate close), **never actuals**.
- PIT feature store with release-timestamp columns. Unit-test the no-leakage rule.
- Audit feature value with LightGBM gain / SHAP at every rung. Prune ruthlessly.

### 7.2 Single-country feature catalog (Greek base)

**Calendar (cheap, high value):**
- hour, MTU-of-hour, day-of-week, week, month
- weekend, Greek holiday, bridge-day flag
- summer-tourism flag (Jul–Aug)
- Orthodox Easter date
- DST-transition flag
- cyclical sin/cos (hour, day-of-year)

**Lag / rolling:**
- target lags: same-MTU at 1d, 2d, 7d, 14d
- rolling stats over 1d / 7d / 30d
- EWM with halflives 12h / 1d / 7d

**Residual load — *the* single most important feature:**
- `residual_load_fcst = load_fcst − wind_fcst − solar_fcst`
- level + 7d rolling mean (de-seasonalized)
- percentile vs trailing 365d at same hour (regime indicator)
- slope: Δ over 4 MTUs
- `residual_load × gas` interaction

**RES decomposition:**
- wind_fcst, solar_fcst separately
- `RES_share_fcst = (wind+solar) / load_fcst`
- `RES_surplus_flag = 1 if RES > load`
- cloud_cover, irradiance, wind_speed_100m forecasts
- HDD / CDD population-weighted

**Fuels & carbon:**
- TTF gas: level + 7d change
- EUA: level + 7d change
- Implied gas marginal cost: `TTF × heat_rate_ccgt + EUA × emission_factor`
- Spark spread proxy

**Greek supply-curve features (the secret weapon):**
- Supply curve at expected residual demand from previous days' HEnEx aggregated curves
- Slope at clearing point (price elasticity)
- Distance from expected residual demand to gas-band entry on the curve

**Volatility / regime:**
- Realized vol over 24h, 7d
- 15-min era flag (post-2025-10-01)
- Curtailment-prone-day flag

**Interactions (selectively):**
- `residual_load × gas`, `weekend × hour`, `season × hour`, `gas × hour`

### 7.3 Multi-country / German-domino features (the new layer)

These are the features that nobody else has assembled at point-in-time, country-aligned, and which encode the SDAC coupling reality.

**Direct-neighbor features:**
- `IT_S_DA_price_fcst` (or actual at gate close if available — IT-South clears in the same SDAC pass)
- `BG_DA_price_fcst`
- Lagged: `IT_S_price_lag1d`, `BG_price_lag1d`, `BG_price_lag7d`
- Same for residual load, RES forecasts of direct neighbors

**Up-corridor features (the German domino):**
- `DE_LU_residual_load_fcst` — German residual load forecast at gate close
- `DE_LU_wind_fcst`, `DE_LU_solar_fcst`
- `DE_LU_RES_surplus_flag`
- `AT_residual_load_fcst`, `IT_N_residual_load_fcst`
- `central_corridor_surplus = sum(DE+AT+CH+IT_N residual_load_fcst)` — when negative, southbound flow saturates → Greek prices drop
- `eastern_corridor_surplus = sum(DE+CZ+SK+HU+RO+BG residual_load_fcst)`

**Continental indices (large-area RES synchronization):**
- `continental_wind_index = capacity-weighted wind_fcst across DE+DK+PL+NL+BE+FR_N`
- `continental_solar_index = capacity-weighted solar_fcst across DE+IT+ES+FR_S+GR`
- These capture pan-European weather systems that simultaneously affect many zones.

**Cross-border capacity (binding-constraint indicators):**
- `ATC_GR_to_IT`, `ATC_GR_to_BG` (from IPTO + neighboring TSOs)
- Implied flow direction (sign of price differential at lag 1d)
- "Corridor congestion" flag: when capacity binds, prices decouple

**Hydro reservoir signals:**
- Nordic reservoir % (Statkraft, NVE) — abundance signals continental price softening 2–4 weeks out
- Alpine reservoir % (Verbund, swissgrid)

**REMIT outage features:**
- Aggregated MW out by fuel type, by zone, in the next 7 days
- Particularly: gas-fired outage signal in DE, IT, GR

**Coupling-coefficient features (advanced):**
- Rolling-window correlation between DE price and GR price
- Rolling-window beta of GR price on a regression of DE + IT-S + BG prices
- These tell us *when* the domino is binding vs decoupled

### 7.4 Anti-patterns to watch for
- Using **realized** RES instead of **forecast** RES — the most common leakage in DAM forecasting.
- Forgetting that gas/EUA only update daily.
- Over-fitting holiday flags on 6 months of 15-min data.
- Discarding the 5-year hourly era — still informs the hourly-mean component.
- Pulling neighbor prices from a clearing that hasn't happened yet (SDAC clears all zones simultaneously, so cross-zone *prices* are not available pre-gate-close — only their *forecasted drivers* are).

---

## 8. Phase 3 — Forecasting layer

Climb the **ladder** so we always have something working that can feed the optimizer. Features (Phase 2) are the input to *every* rung.

### 8.1 The 15-minute regime shift
Hierarchical decomposition: hourly mean (long history) + intra-hour 15-min shape (short history). Reconstruct 15-min prices = mean + shape. Transfer from neighbor zones that moved to 15-min on similar timelines.

### 8.2 Ladder
- **R1 — Naive:** seasonal & yesterday baselines. Floor we must beat.
- **R2 — Statistical:** SARIMAX with multi-country exogenous (residual loads, gas, EUA, calendar).
- **R3 — ML:** LightGBM, multi-horizon, global model with hour × MTU + country features.
- **R4 — Probabilistic:** quantile LightGBM (α = 0.1, 0.5, 0.9) or conformal wrapper.
- **R5 — Stretch:** TFT / N-HiTS via `darts`; foundation TS models (Chronos, TimesFM, Moirai); HEnEx supply-curve fundamental model.

### 8.3 Metrics
- Point: MAE, RMSE, sMAPE.
- Probabilistic: pinball, CRPS, calibration plot.
- **Decision-aware (the headline):** realized profit when forecast feeds the optimizer vs perfect-foresight. Track from day 1.

---

## 9. Phase 4 — Optimization layer (storage-agnostic, country-aware)

### 9.1 Time discretization
Δt = MTU of the country (15 min for current SDAC zones, hourly for legacy backtests). 96 binaries/day at 15-min → trivially small for HiGHS.

### 9.2 Storage profiles (`configs/storage_profiles.yaml`)

| Profile | Power (MW) | Duration (h) | E_max | η_rt | SoC band | Cycles/day |
|---|---|---|---|---|---|---|
| `liion_100_2h` | 100 | 2 | 200 MWh | 0.86–0.92 | 10–90 % | 1–2 |
| `liion_200_2h` | 200 | 2 | 400 MWh | 0.86–0.92 | 10–90 % | 1–2 |
| `liion_300_2h` | 300 | 2 | 600 MWh | 0.86–0.92 | 10–90 % | 1–2 |
| `phs_100_8h`   | 100 | 8 | 800 MWh | 0.75–0.82 | 5–95 %  | 0.5–1.5 |
| `phs_200_8h`   | 200 | 8 | 1600 MWh| 0.75–0.82 | 5–95 %  | 0.5–1.5 |
| `flow_100_6h`  | 100 | 6 | 600 MWh | 0.70–0.80 | 5–95 %  | 1–3 |

### 9.3 MILP (per t ∈ {1..N_MTUs/day})

Decision vars: `p_ch(t), p_dis(t) ≥ 0`, `soc(t)`, `z(t) ∈ {0,1}`.

```
soc(t)  = (1 − δ·Δt)·soc(t-1) + η_ch·p_ch(t)·Δt − (1/η_dis)·p_dis(t)·Δt
SoC_min·E_max ≤ soc(t) ≤ SoC_max·E_max
0 ≤ p_ch(t)  ≤ P_ch_max  · z(t)
0 ≤ p_dis(t) ≤ P_dis_max · (1 − z(t))
Σ_t (p_ch(t) + p_dis(t))·Δt ≤ 2·n_cyc·E_max·(SoC_max − SoC_min)
soc(N) ≥ SoC_T   (optional terminal)
```

Objectives: deterministic (point P̂), stochastic (S scenarios from quantiles), CVaR (tail-averse).

### 9.4 Robustness wrapper
1. **Sensitivity sweep** — solve nominal MILP, evaluate schedule against parameter grid, report worst-case PnL + violation. Day-1 deliverable.
2. **Robust min-max** — `max_schedule min_θ E[profit]` via cutting-plane wrapper. Day-2 if time.
3. **Adaptive / online** — calibration once telemetry exists post-Apr-2026. Day-3 narrative ("this is how we get smarter as customers onboard").

### 9.5 Bidding nuance
Self-schedule against forecast price for the hackathon. Bid-curve formulation as roadmap (HEnEx aggregated curves enable it).

---

## 10. Phase 5 — Backtesting

Walk-forward, gate-close-aware:
```
for d in test_days:
    asof = (d-1, 12:00 CET)
    train_data    = data up to asof                   # NO leakage past gate close
    feature_panel = features.build_pit(asof=asof)
    price_fcst    = forecast.predict(d, feature_panel)
    schedule      = robust_optimize(price_fcst, profile_interval, soc_at_start)
    realized_pnl  = schedule · actual_price(d)
    soc_at_start_of_(d+1) = simulate_physics(schedule, profile_nominal, soc_at_start)
```

**Headline metrics:**
- Cumulative realized profit (€).
- **% vs perfect-foresight optimum** — *the* number.
- % vs naive forecast — shows our forecast adds value.
- **Worst-case profit across parameter sweep** — robustness number.
- Profile-comparison panel: same backtest run for all six profiles in §9.2.
- **Country-comparison panel** *(Day 2/3):* same harness on Greek + Italian + Bulgarian (and German if time) DAM. Multi-country generality, on screen.

---

## 11. Phase 6 — Decision interface (the demo + pitch surface)

The Streamlit app is also the pitch.

**Page 1 — Live dispatch:**
- Country selector (GR default; IT-S, BG, RO, DE-LU available).
- Storage-profile selector (Li-ion 100/200/300, PHS 100/200, flow).
- Date picker → 96-bar planned schedule, forecast curve with confidence band, SoC trajectory.
- KPI tiles: € earned, % vs perfect foresight, % vs naive, worst-case € across sweep.
- Toggle: nominal vs robust mode.
- Toggle: which feature families are enabled (Greek-only vs +multi-country vs +German-domino) — let the judges *see* that DE features add accuracy.

**Page 2 — Moat visualization:**
- Map of SDAC zones we ingest.
- Feature catalog with importance bars (what's actually pulling weight).
- Coupling chain animation: DE wind glut → corridor flow → Greek price compression.

**Page 3 — Business view (the pitch):**
- TAM map (Europe, by zone).
- Pricing tiers.
- 30 / 90 / 365-day roadmap.
- Customer-telemetry network-effect chart (how Tier-4 compounds).

---

## 12. Risk register

| Risk | Mitigation |
|---|---|
| Optimizer overfits to forecast errors | Always evaluate on walk-forward realized PnL. |
| Simultaneous charge & discharge "free energy" | Binary `z(t)`. Verify η<1 makes it never optimal. |
| Leakage: features released after gate close used in training | PIT feature store + leakage unit test. |
| 15-min model on 6 months → wild predictions | Stay rungs 1–3 of ladder; hourly-mean + 15-min shape decomposition. |
| Multi-country ingestion eats Day 2 entirely | Cap scope: GR + IT-S + BG + DE-LU. Add others post-hackathon. |
| Storage spec wrong → schedule infeasible | Always evaluate against parameter sweep. |
| Cycle-life ignored → schedule kills the asset | Hard cycle constraint; degradation as line item. |
| Demo only Greek, judges ask "what about elsewhere" | Country selector hits ≥3 countries on screen. |
| Pitch sounds like a tool, not a business | Pages 2–3 of dashboard exist on Day 3 — the moat + TAM views. |
| German domino features look sophisticated but don't actually move accuracy | SHAP audit on Day 2. Drop if non-contributing; keep narrative as "scaffolding for richer fundamentals." |

---

## 13. Three-day sprint plan

### Day 1 — Greek MVP + business framing

**Tech:**
1. (30 min) Repo skeleton + env. `configs/storage_profiles.yaml` + `configs/countries.yaml` (GR row).
2. (1 h) MILP at 15-min Δt, 96 periods. Verify on synthetic price.
3. (1 h) Walk-forward harness + perfect-foresight benchmark.
4. (30 min) Pull recent month of HEnEx DAM prices for sanity.
5. (1 h) Naive seasonal forecast → end-to-end realized-profit number. **We are scoring.**
6. (1 h) Parameter sweep evaluation. Worst-case number on dashboard.
7. (parallel) Feature lead: Greek single-country PIT feature store (calendar + lags + residual_load_fcst + RES + gas + EUA).

**Business:**
- Pin anchor customer + persona (1 paragraph).
- Draft moat thesis (the Tier-2 catalog — see §2.2).
- Sketch dashboard pages 1/2/3 wireframe.

### Day 2 — Multi-country + advanced features + ML forecast

**Tech:**
1. (2 h) Multi-country ENTSO-E ingestion: GR + IT-S + BG + DE-LU at minimum. Harmonize timezone, MTU, fuel taxonomy.
2. (1 h) Add German-domino features to the feature store: DE residual load, DE RES, central corridor surplus, continental wind/solar indices, ATCs.
3. (1 h) LightGBM multi-horizon forecast on enriched feature set. Quantile output.
4. (2 h) SHAP audit — which features actually pull weight? Prune feature catalog accordingly.
5. (1 h) Robust min-max optimization wrapper. Compare against sensitivity-sweep numbers.
6. (1 h) Country-comparison backtest: run the harness on GR + IT-S + BG.

**Business:**
- Pricing model defended (per-MW SaaS + performance kicker).
- TAM map drafted.
- Pitch outline written.

### Day 3 — Productize, polish, pitch

**Tech:**
1. (2 h) Streamlit dashboard: pages 1, 2, 3.
2. (1 h) Storage-profile sweep: all six profiles backtested, results tiled in dashboard.
3. (1 h) Final SHAP audit + feature-catalog cleanup.
4. (1 h) End-to-end smoke test of the demo flow.
5. (2 h) Stretch: REMIT outage features OR HEnEx supply-curve fundamental model (whichever has more signal).

**Business:**
- Pitch deck (10–12 slides): problem, customer, product, moat, demo, market, business model, roadmap, team, ask.
- Q&A prep — expected challenges from judges (see §14).
- 30 / 90 / 365-day roadmap on the dashboard's Page 3.

---

## 14. Open questions (to flag in the pitch as deliberate roadmap, not gaps)

- **Storage profiles to demo:** are the six in §9.2 right? We can replace any if the panel asks.
- **Resolution mandate:** 15-min, hourly, both? We support both.
- **Settlement mechanism:** price-taker (default) or self-bid into the curve (roadmap)?
- **Tooling constraints:** any required / forbidden libraries for the final submission?
- **RES curtailment data:** provided directly, or inferred from RES-forecast vs RES-actual gaps?
- **Holiday calendar:** Greek movable feasts (Orthodox Easter) — pull from `python-holidays` and review.

**Anticipated judge questions:**
- "How is your forecast better than my LightGBM on prices alone?" → multi-country feature catalog + SHAP audit.
- "What's your moat?" → §2 — Tier-2 + Tier-4.
- "Why should I pay you instead of building it in-house?" → 25-zone harmonization is engineer-months of work; we sell it as a service.
- "How do you handle a customer with 6h storage instead of 2h?" → §9.2 profiles, on-screen toggle.
- "What about Germany?" → §7.3 — German features already in the model; SHAP shows their weight.

---

## 15. Changelog

**v4 (business + multi-country):**
- Reframed deliverable as a 3-day **tech-business sprint**, not a tool build. Added §0 sprint reframe, §1 customer/TAM, §2 proprietary-data moat strategy.
- Made the framework **multi-country**: country profiles in `configs/countries.yaml`, ENTSO-E multi-zone ingestion, country selector in the demo.
- Added a dedicated **German-domino feature family** (§7.3): up-corridor residual loads, central/eastern corridor surplus indices, continental wind/solar indices, ATCs, hydro reservoirs, REMIT outages, coupling-coefficient features.
- Restructured the demo as a 3-page Streamlit app where Pages 2 and 3 are the **moat** and **business** views — the pitch surface.
- Replaced "first-day action list" with a full **three-day sprint plan** (§13), parallel tech + business tracks each day.
- Added anticipated judge questions (§14).

**v3 (scope-clarified):**
- Storage-agnostic framework (Li-ion + storage units share the MILP, profile-driven).
- 100/200/300 MW size class as named profiles.
- Promoted feature engineering to its own phase with a concrete catalog.

**v2 (post-brief):**
- Reframed "data scarcity" from market-side to battery-side.
- 24 hourly → 96 × 15-min horizon (Greek MTU change of 1 Oct 2025).
- Battery-parameter intervals + robustness wrapper as first-class concern.
- EU ETS / EUA + HEnEx aggregated curves added.
- Hourly-mean + 15-min-shape forecasting decomposition.

---

*Three days, four layers, one story: a storage-agnostic dispatch engine defended by a multi-country data moat — Greek anchor, European product.*
