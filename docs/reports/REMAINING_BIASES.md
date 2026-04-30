# Remaining Biases & Limitations — BatteryOS Honest Backtest

> **Version:** 1.0  
> **Date:** 2026-04-30  
> **Applies to:** BACKTEST_REPORT_HONEST.md (Walk-Forward + SoC Carry-Over + €2/MWh Transaction Costs)

---

## 1. Overview

Three major fixes have been applied to make this backtest academically defensible:

1. ✅ **Walk-forward predictions** — monthly expanding-window retraining, no look-ahead bias
2. ✅ **SoC carry-over** — day *t* final SoC becomes day *t+1* initial SoC
3. ✅ **Transaction costs** — €2/MWh on all charge + discharge throughput, internalised by the optimizer

**This document lists all remaining biases and limitations.** For each issue we state the direction of distortion, a quantitative estimate where possible, and whether a fix is planned.

---

## 2. Remaining Biases (Ranked by Estimated Impact)

### 2.1 Price Execution Slippage
**Status:** Unfixed  
**Direction:** Inflates profit  
**Estimated impact:** +3–8% absolute  
**Description:**
- The backtest assumes the battery can buy/sell at the forecasted day-ahead MCP.
- In reality, bid curves may not clear at the forecasted price.
- The DAM is a uniform-price auction; a large battery bid could itself move the clearing price (market impact), especially in a small market like Greece.
- No imbalance cost is applied when actual dispatch deviates from the day-ahead schedule.

**Why hard to fix:**
- Requires historical bid/offer data and market-depth information not publicly available for Greece DAM.
- Would need a market-impact model (estimate of how battery volume shifts MCP).

**Mitigation:**
- The €2/MWh transaction cost partially captures grid fees but not slippage.
- Could add an additional €1–3/MWh "execution penalty" as a sensitivity.

---

### 2.2 Linear SOH Model
**Status:** Unfixed  
**Direction:** Approximate (direction unclear)  
**Estimated impact:** ±5–10% on long-run EOL timing  
**Description:**
- Current model: `SOH = 1.0 - (cumulative_cycles / lifetime_cycles_eol)`
- Real Li-ion degradation is nonlinear: slower early wear, accelerating after ~80% SOH.
- We do not model:
  - Depth-of-discharge dependence (a 10%–90% cycle ages more than 40%–60%)
  - Temperature effects (high temperature accelerates aging 2–3×)
  - Calendar aging (~2% capacity loss per year even when idle)

**Why hard to fix:**
- Physics-based degradation (rainflow cycle counting + Wöhler curves) exists in `src/optimize/degradation.py` but is not wired into the backtest engine.
- Would require per-cell temperature data and historical ambient temperature during operation.

**Mitigation:**
- Rainflow-based aging can be enabled in `optimize_dispatch()` for single-day optimization.
- For the backtest, using conservative EOL thresholds (80% vs. 70%) provides a safety margin.

---

### 2.3 No Calendar Aging
**Status:** Unfixed  
**Direction:** Overstates lifetime  
**Estimated impact:** +5–10% on battery lifetime  
**Description:**
- Li-ion batteries lose ~1.5–2.5% of capacity per year even when not cycled.
- Our model only counts cycle-based degradation.
- Over a 5-year horizon, this could mean an additional 7–12% SOH drop not captured.

**Why hard to fix:**
- Calendar aging is temperature- and chemistry-dependent.
- Simple fix: add a time-decay term to SOH (e.g., `-0.02 × years`).

**Mitigation:**
- Conservative EOL threshold (80%) and cycle limits provide headroom.
- Could be added to `BatteryStateTracker._compute_soh()` as a one-line enhancement.

---

### 2.4 Single-Day Optimization Horizon
**Status:** By design  
**Direction:** Underestimates value of long-duration storage  
**Estimated impact:** -5–15% for PHS/Flow; minimal for Li-ion  
**Description:**
- Each day is optimised independently with no look-ahead beyond midnight.
- Long-duration storage (PHS 8h, Flow 6h) can profit from multi-day price patterns (e.g., charge during a cheap weekend, discharge on Monday peak).
- Our model cannot exploit these because the terminal SoC constraint resets daily.

**Why hard to fix:**
- Requires rolling-horizon optimization with forecasted prices for day *t+1*, *t+2*, etc.
- Computationally expensive: each day would need a 72–168 hour horizon.

**Mitigation:**
- For PHS/Flow, reported profits are a lower bound. Real-world value is likely higher.
- Could implement a weekly rolling horizon as a future enhancement.

---

### 2.5 Flat Transaction Cost
**Status:** Partial fix applied  
**Direction:** Approximate  
**Estimated impact:** ±2–3%  
**Description:**
- We apply a flat €2/MWh to all trades regardless of time, direction, or grid location.
- Real costs vary:
  - Grid fees: often higher during peak hours
  - Imbalance penalties: asymmetric (over-production vs. under-production)
  - Use-of-system charges: depend on network zone

**Why hard to fix:**
- Greek grid tariff structure is complex and changes annually.
- Would require time-varying cost schedules from IPTO/DAPEEP.

**Mitigation:**
- Sensitivity analysis: run backtest with €1, €2, €3, €5/MWh to bound the effect.
- Currently implemented as a configurable parameter; easy to adjust.

---

### 2.6 No Ancillary Services Revenue
**Status:** Unfixed  
**Direction:** Understates total revenue  
**Estimated impact:** +10–30% potential upside  
**Description:**
- Batteries can earn additional revenue from:
  - FCR (Frequency Containment Reserve)
  - aFRR (automatic Frequency Restoration Reserve)
  - mFRR (manual Frequency Restoration Reserve)
  - Black-start services
- Greek ancillary service markets are developing but historically thin.

**Why hard to fix:**
- Historical ancillary service prices and volumes are not readily available.
- Would require modelling reservation constraints (battery must hold capacity in reserve).

**Mitigation:**
- Reported DAM-only profit is a conservative baseline.
- Could add a fixed €/MW/year ancillary revenue uplift as a scenario.

---

### 2.7 No Intraday / Balancing Market Arbitrage
**Status:** Unfixed  
**Direction:** Understates revenue potential  
**Estimated impact:** +5–15%  
**Description:**
- After day-ahead clearing, the intraday market allows position adjustments.
- If actual prices deviate from DAM forecast, a battery can re-optimise and trade in the intraday session.
- Our model is "DAM-only": once the schedule is set, it is executed blindly.

**Why hard to fix:**
- Requires historical intraday price data (ID1, ID2, ID3, continuous) for Greece.
- Would need a two-stage stochastic model: DAM bid + intraday recourse.

**Mitigation:**
- DAM-only is standard for conservative valuation.
- Intraday arbitrage is a known upside not captured here.

---

### 2.8 Forecast Model Limitations
**Status:** Unfixed  
**Direction:** Mixed  
**Estimated impact:** ±5–10% on profit  
**Description:**
- LightGBM quantile regression is a strong baseline but has known weaknesses:
  - Struggles with regime changes (e.g., sudden gas price spikes)
  - No explicit structural model (supply/demand stack)
  - Quantiles can be poorly calibrated in tails (p10/p90)
- Feature set lacks some potentially useful signals:
  - Cross-border flow forecasts
  - Nuclear/ lignite outage schedules
  - Industrial load forecasts

**Why hard to fix:**
- Structural models (fundamental dispatch stack) require proprietary plant-level data.
- Deep learning alternatives (LSTM, Transformer) need more data and compute.

**Mitigation:**
- Walk-forward validation already guards against overfitting.
- MAE of 16.43 €/MWh is competitive for DAM forecasting.
- Could ensemble with external forecasts (e.g., ENTSO-E transparency platform).

---

### 2.9 Constant Battery Efficiency
**Status:** By design  
**Direction:** Mixed  
**Estimated impact:** ±2–3%  
**Description:**
- We assume constant RTE: 90% (Li-ion), 78.5% (PHS), 75% (Flow).
- Real efficiency varies with:
  - State of charge (lower efficiency near empty/full)
  - Power rate (C-rate): higher power = lower efficiency
  - Temperature
  - Age (older batteries have higher internal resistance)

**Why hard to fix:**
- Would need manufacturer datasheets or empirical efficiency maps.
- Nonlinear efficiency destroys LP convexity; would require MILP or piecewise-linear approximation.

**Mitigation:**
- Conservative RTE assumptions (slightly lower than nameplate) provide a safety margin.
- PHS 78.5% RTE is already on the low end for modern plants.

---

### 2.10 Tax, Insurance, O&M Excluded
**Status:** Unfixed  
**Direction:** Overstates net profit  
**Estimated impact:** -10–20% on net cash flow  
**Description:**
- Reported profit is **gross operating margin** (revenue - degradation - transaction costs).
- Real projects face:
  - Corporate tax (~24% in Greece)
  - Insurance (~0.3–0.5% of capex/year)
  - O&M labour and spare parts
  - Land lease / grid connection fees
  - Debt service (if leveraged)

**Why hard to fix:**
- Project finance structures are highly bespoke.
- Tax incentives (e.g., Greece's fast-track licensing) vary by project.

**Mitigation:**
- This is a **trading strategy backtest**, not an investment feasibility study.
- For NPV analysis, apply a 25–35% "all-in cost haircut" to gross profit.

---

## 3. Summary Table

| # | Bias | Direction | Estimated Impact | Fixable? | Priority |
|---|---|---|---|---|---|
| 1 | Price execution slippage | Inflates profit | +3–8% | Hard | 🔴 High |
| 2 | Linear SOH model | Approximate | ±5–10% EOL | Medium | 🟡 Medium |
| 3 | No calendar aging | Overstates lifetime | +5–10% lifetime | Easy | 🟡 Medium |
| 4 | Single-day horizon | Underestimates long-duration | -5–15% PHS/Flow | Hard | 🟡 Medium |
| 5 | Flat transaction cost | Approximate | ±2–3% | Easy | 🟢 Low |
| 6 | No ancillary services | Understates revenue | +10–30% upside | Hard | 🟡 Medium |
| 7 | No intraday arbitrage | Understates revenue | +5–15% upside | Hard | 🟡 Medium |
| 8 | Forecast model limits | Mixed | ±5–10% | Medium | 🟡 Medium |
| 9 | Constant efficiency | Mixed | ±2–3% | Hard | 🟢 Low |
| 10 | Tax / insurance / O&M excluded | Overstates net profit | -10–20% net | N/A | 🟢 Low |

**Key takeaway:** Even after all three Path A fixes, the absolute profit figures should be treated as **gross operating margins** with a ±10–15% confidence band. The **relative ranking** of technologies (PHS > Flow > Li-ion on per-MWh basis) and scenarios (Safe > Regular > Risky) is robust.

---

## 4. Suggested Sensitivity Analyses

To bound the uncertainty, we recommend running the following variants:

| Sensitivity | Parameter Change | Purpose |
|---|---|---|
| **Transaction cost** | €1, €2, €3, €5/MWh | Bound friction impact |
| **EOL threshold** | 70%, 75%, 80%, 85% | Test durability assumptions |
| **SOH model** | linear vs. sqrt | Test degradation curve shape |
| **Forecast error** | Add ±10% noise to predictions | Test strategy robustness |
| **No degradation cost** | Set deg cost = 0 | Upper bound (naive backtest) |
| **Calendar aging** | -2% SOH/year | Lower bound on lifetime |

---

*Document maintained alongside BACKTEST_REPORT_HONEST.md*  
*Last updated: 2026-04-30*
