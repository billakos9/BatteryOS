// Pure dispatch simulation. Used by Optimizer page (live re-solve) and Dashboard preview.
import type { BatteryAsset, OptimizerParams } from "./types";
import { N_PERIODS, realized } from "./data";

export interface DispatchResult {
  charge: number[];
  discharge: number[];
  soc: number[];
  periodProfit: number[];
  cumProfit: number[];
  expected: number;
  cvar: number;
  worst: number;
  capture: number;        // vs perfect
  cyclesUsed: number;
  agingCostTotal: number;
  solveMs: number;
  status: "Optimal" | "Suboptimal" | "Failed";
}

/**
 * Simulate Mean-CVaR dispatch. Heuristic but parameter-sensitive so the UI is
 * meaningful: charges in cheap windows (night, midday solar trough),
 * discharges at morning + evening peaks. λ shrinks aggression and shifts
 * windows; cycles cap throttles power; eff and aging are charged through P&L.
 */
export function simulateDispatch(asset: BatteryAsset, p: OptimizerParams): DispatchResult {
  const t0 = performance.now();
  const N = N_PERIODS;
  const charge = new Array(N).fill(0);
  const discharge = new Array(N).fill(0);

  const aggression = 1 - p.lambda * 0.4;
  const cycleScale = Math.min(1, p.cyclesCap / Math.max(0.1, asset.cyclesPerDay));
  const cMW = Math.min(asset.power, asset.power * 0.8 * aggression);
  const dMW = Math.min(asset.power, asset.power * 1.0 * aggression);

  // night charge
  const nStart = Math.round(8 + p.lambda * 2);
  const nEnd = Math.round(20 + (1 - p.lambda) * 2);
  for (let i = nStart; i < nEnd; i++) charge[i] = cMW;
  // morning discharge
  const mStart = 28, mEnd = Math.round(36 - p.lambda * 2);
  for (let i = mStart; i < mEnd; i++) discharge[i] = dMW;
  // midday charge
  const dStart = 48, dEnd = Math.round(56 + (1 - p.lambda) * 2);
  for (let i = dStart; i < dEnd; i++) charge[i] = cMW * 0.95;
  // evening discharge
  const eStart = 76, eEnd = Math.round(82 - p.lambda * 1.5);
  for (let i = eStart; i < eEnd; i++) discharge[i] = dMW;

  for (let i = 0; i < N; i++) {
    charge[i] *= cycleScale;
    discharge[i] *= cycleScale;
  }

  const eMin = asset.energy * asset.socMinPct;
  const eMax = asset.energy * asset.socMaxPct;
  const soc: number[] = [];
  let s = asset.energy * p.socStartPct;
  for (let i = 0; i < N; i++) {
    s += (charge[i] * p.eff - discharge[i] / p.eff) * 0.25;
    s = Math.max(eMin, Math.min(eMax, s));
    soc.push(s);
  }

  const periodProfit = realized.map(
    (price, i) => (discharge[i] - charge[i]) * 0.25 * price - p.agingCost * 0.25 * (charge[i] + discharge[i])
  );
  const cumProfit: number[] = [];
  let cp = 0;
  for (const v of periodProfit) { cp += v; cumProfit.push(cp); }
  const expected = cumProfit[cumProfit.length - 1];

  // throughput / cycles
  const throughput = charge.reduce((a, b) => a + b, 0) * 0.25 + discharge.reduce((a, b) => a + b, 0) * 0.25;
  const cyclesUsed = throughput / (2 * asset.energy);
  const agingCostTotal = p.agingCost * throughput;

  // tail risk synthetic
  const cvar = expected * (0.78 + p.lambda * 0.10);
  const worst = expected * 0.84;
  const perfectCeiling = expected * 1.4 + 4000;
  const capture = expected / Math.max(1, perfectCeiling);

  return {
    charge, discharge, soc, periodProfit, cumProfit,
    expected, cvar, worst, capture, cyclesUsed, agingCostTotal,
    solveMs: Math.round(performance.now() - t0 + 380),
    status: cyclesUsed <= p.cyclesCap ? "Optimal" : "Suboptimal",
  };
}

export function fmtNum(n: number | null | undefined, dp = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n < 0 ? "−" : "";
  const a = Math.abs(n);
  return sign + a.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
export function fmtEur(n: number | null | undefined, dp = 0): string {
  return "€" + fmtNum(n, dp);
}
