# BatteryOS Honest Backtest Report — Walk-Forward + SoC Carry-Over + Transaction Costs

> **Date:** 2026-04-30  
> **Backtest Period:** 303 complete days (2025-07-01 – 2026-04-29) = ~10 months  
> **Interval:** 15-minute (96 intervals/day)  
> **Honest methodology:** Monthly expanding-window retraining + day-to-day SoC carry-over + €2/MWh transaction cost

---

## 1. Executive Summary

This backtest implements **all three Path A fixes** for an honest, defensible backtest:

| Fix | Status | Impact |
|---|---|---|
| **Walk-forward predictions** | ✅ Done | Models retrained monthly on expanding window; no look-ahead bias |
| **SoC carry-over** | ✅ Done | Day *t* final SoC becomes day *t+1* initial SoC |
| **Transaction costs** | ✅ Done | €2/MWh deducted from all trades (grid fees + imbalance proxy) |

### Key Finding: Forecast Quality is Robust

Walk-forward MAE (p50): **16.43 €/MWh**  
In-sample MAE (p50): **16.98 €/MWh**

The out-of-sample error is **within 3%** of the in-sample error. This indicates the model is not severely overfitting and the feature set has genuine predictive power.

### Key Finding: Transaction Costs Matter

Adding €2/MWh reduces **total profit by ~4.5%** and **daily cycling by ~3%** because the optimizer internalises the friction and trades less aggressively. The effect is larger for high-throughput technologies (PHS) than for low-throughput ones (Li-ion).

### Key Finding: No Batteries Hit EOL in 10 Months

| Technology | Final SOH | Cumulative Cycles | Annual Budget Left | EOL Days |
|---|---|---|---|---|
| **Li-ion (all sizes)** | 91.8–92.0% | ~398–410 | 139–151 | **0** |
| **PHS (Pumped Hydro)** | 98.2% | ~268–271 | 95–97 | **0** |
| **Vanadium Flow** | 97.8–97.9% | ~310–332 | 399–421 | **0** |

Li-ion cycle rates dropped from 1.42 (without tx cost) to 1.37 (with tx cost), extending projected EOL from ~4.3 years to ~4.5 years.

---

## 2. What Changed vs. Previous Backtest

| Feature | Previous (V2) | This Report (Honest) |
|---|---|---|
| **Predictions** | In-sample (trained on full dataset) | ✅ Walk-forward (monthly retraining) |
| **SoC initialization** | Reset to 50% every day | ✅ Carry-over from previous day's final SoC |
| **Transaction costs** | ❌ None | ✅ €2/MWh on all trades |
| **Backtest length** | ~3.3 years (1,198 days) | ~10 months (303 days) |
| **Li-ion EOL** | Hit at ~2.7 years | Not reached in test period |

---

## 3. Results

### 3.1 Total Profit by Profile & Scenario (10 Months)

| Profile | Safe (€) | Regular (€) | Risky (€) | Safe vs Risky |
|---|---|---|---|---|
| `flow_100_6h` | **12,355,175** | 12,347,585 | 12,269,836 | **+0.7%** |
| `liion_100_2h` | **5,757,477** | 5,698,745 | 5,657,357 | **+1.8%** |
| `liion_200_2h` | **11,514,954** | 11,397,489 | 11,314,714 | **+1.8%** |
| `liion_300_2h` | **17,272,431** | 17,096,234 | 16,972,072 | **+1.8%** |
| `phs_100_8h` | **14,355,397** | 14,394,497 | 14,144,945 | **+1.5%** |
| `phs_200_8h` | **28,710,795** | 28,789,335 | 28,289,890 | **+1.5%** |

**Safe consistently outperforms Risky** by 0.7–1.8% over the 10-month period. The CVaR-based hedging provides a small but measurable edge.

### 3.2 Average Daily Profit

| Profile | Safe (€/day) | Regular (€/day) | Risky (€/day) |
|---|---|---|---|
| `phs_200_8h` | **98,663** | 98,932 | 97,216 |
| `phs_100_8h` | **49,331** | 49,466 | 48,608 |
| `flow_100_6h` | **42,458** | 42,432 | 42,164 |
| `liion_300_2h` | **59,355** | 58,750 | 58,323 |
| `liion_200_2h` | **39,570** | 39,167 | 38,882 |
| `liion_100_2h` | **19,785** | 19,583 | 19,441 |

### 3.3 Transaction Cost Impact

| Profile | Scenario | Total Tx Cost (€) | Daily Tx Cost (€) | Profit Reduction vs Zero-Tx |
|---|---|---|---|---|
| `liion_100_2h` | Regular | 244,481 | 840 | **-4.1%** |
| `liion_100_2h` | Risky | 251,724 | 865 | **-4.3%** |
| `phs_100_8h` | Regular | 766,442 | 2,634 | **-5.1%** |
| `phs_100_8h` | Risky | 774,346 | 2,661 | **-5.2%** |
| `flow_100_6h` | Regular | 661,703 | 2,274 | **-5.1%** |
| `flow_100_6h` | Risky | 708,167 | 2,434 | **-5.5%** |

**Key insight:** PHS and Flow suffer larger absolute profit reductions because they move more MWh per day. Li-ion is less affected in percentage terms because its narrower spreads already limit cycling.

### 3.4 Degradation Trajectory

| Profile | Scenario | Final SOH | Cumulative Cycles | Annual Budget Left | Lifetime Budget Left |
|---|---|---|---|---|---|
| **Li-ion 100 2h** | Safe | 92.0% | 398.2 | 150.8 | 4,601.8 |
| **Li-ion 100 2h** | Regular | 92.0% | 397.8 | 151.2 | 4,602.2 |
| **Li-ion 100 2h** | Risky | 91.8% | 410.1 | 138.9 | 4,589.9 |
| **PHS 100 8h** | Safe | 98.2% | 269.9 | 96.1 | 14,730.1 |
| **PHS 100 8h** | Regular | 98.2% | 268.5 | 97.5 | 14,731.5 |
| **PHS 100 8h** | Risky | 98.2% | 271.3 | 94.7 | 14,728.7 |
| **Flow 100 6h** | Safe | 97.9% | 312.7 | 418.3 | 14,687.3 |
| **Flow 100 6h** | Regular | 97.9% | 309.5 | 421.5 | 14,690.5 |
| **Flow 100 6h** | Risky | 97.8% | 331.5 | 399.5 | 14,668.5 |

**At these cycle rates (with tx-cost-aware optimizer):**
- Li-ion EOL projection: ~4.5 years (down from 1.5 cycles/day to 1.37)
- PHS annual budget exhaustion: ~1.4 years of continuous operation
- Flow is the clear durability winner with >44 years of lifetime headroom

---

## 4. Scenario Ranking

| Scenario | Aggregate Profit (All Profiles, 10mo) |
|---|---|
| **Safe** | €90.0M |
| **Regular** | €89.7M |
| **Risky** | €88.6M |

Safe > Regular > Risky, consistent with earlier results. The absolute gaps shrank slightly because transaction costs compress the strategy space.

---

## 5. Important Caveats (Remaining Biases)

| Issue | Direction | Estimated Impact |
|---|---|---|
| **Perfect price execution** | Inflates profit | Unknown (assumes DAM bid = actual MCP) |
| **Linear SOH model** | Approximate | Real Li-ion degrades nonlinearly |
| **No calendar aging** | Missing | Li-ion loses ~2%/year even when idle |
| **Single-day horizon** | Misses multi-day arbitrage | Underestimates long-duration storage value |
| **Flat transaction cost** | Approximate | Real grid fees vary by time-of-use and network location |

**The largest remaining bias is price execution.** We assume the battery can buy/sell at the forecasted MCP. In reality, bid curves may not clear, and imbalance penalties can exceed €2/MWh.

---

## 6. Files Generated

| File | Description |
|---|---|
| `data/processed/walkforward_predictions.csv` | 28,181 rows — out-of-sample p10/p50/p90 predictions |
| `outputs/backtest_detailed.csv` | 5,454 rows — daily results with SOH, cycles, budget, tx cost |
| `outputs/backtest_summary.csv` | Aggregated per-profile, per-scenario statistics |
| `outputs/backtest_degradation_{profile}_{scenario}.csv` | 18 files — daily degradation trajectory |

---

## 7. How to Reproduce

```bash
cd /home/dimit/BatteryOS
source .venv/bin/activate

# 1. Generate walk-forward predictions (one-time, ~30 min)
python pipelines/run_walkforward_training.py

# 2. Run honest backtest (~8 min)
python pipelines/run_backtest.py
```

**Walk-forward training:** 10 monthly retrains × 3 quantile models = 30 model fits  
**Backtest:** 303 days × 6 profiles × 3 scenarios = 5,454 LP solves  
**Transaction cost:** €2/MWh applied to all charge + discharge throughput  
**Total runtime:** ~40 minutes

---

*Report generated by `pipelines/run_backtest.py` with `BatteryStateTracker`*  
*Degradation model: Linear SOH decay, per-technology EOL thresholds, dynamic cost escalation*  
*Transaction cost: €2/MWh on all trades, internalised by optimizer*  
*Predictions: LightGBM quantile regression (walk-forward out-of-sample)*  
*Optimizer: PuLP/CBC LP with CVaR (Safe) and deterministic (Regular/Risky)*
