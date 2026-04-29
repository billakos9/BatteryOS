// Domain types for BatteryOS
export type AssetTech = "Li-Ion" | "Pumped Hydro" | "Vanadium Flow" | "NaS" | "Custom";
export type AssetStatus = "active" | "paused" | "maintenance";
export type RiskProfileId = "risk_neutral" | "balanced" | "defensive" | "tail_hedged" | "custom";

export interface BatteryAsset {
  id: string;
  tech: AssetTech;
  power: number;        // MW
  energy: number;       // MWh
  eff: number;          // one-way efficiency (round-trip = eff^2)
  socMinPct: number;    // 0..1
  socMaxPct: number;    // 0..1
  cyclesPerDay: number; // cap
  agingCost: number;    // €/MWh throughput
  status: AssetStatus;
  utilization: number;  // 0..1, observed
  notes?: string;
}

export interface OptimizerParams {
  assetId: string;
  riskProfile: RiskProfileId;
  lambda: number;          // 0..1 mean-CVaR mix
  alpha: number;           // 0.05..0.5 CVaR tail
  cyclesCap: number;       // override cycles/day
  eff: number;             // override one-way efficiency
  agingCost: number;       // override aging €/MWh
  terminalSoc: "free" | "start" | "50";
  robust: boolean;
  scenarios: number;       // 5..50
  solver: "HiGHS" | "GLPK" | "CBC";
  socStartPct: number;     // 0..1 initial SoC fraction
  gateCloseHour: number;   // 0..23
}

export type RunStatus = "Optimal" | "Suboptimal" | "Failed";

export interface OptimizerRun {
  id: string;
  time: string;
  day: string;
  assetId: string;
  lambda: number;
  profit: number;
  status: RunStatus;
  capture: number;
}
