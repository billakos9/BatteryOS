export interface BackendScheduleRow {
  timestamp: string;
  forecast_price_eur_per_mwh: number;
  realized_price_eur_per_mwh?: number;
  charge_mw: number;
  discharge_mw: number;
  state_of_charge_mwh: number;
  action: "CHARGE" | "DISCHARGE" | "IDLE";
  period_profit_eur: number;
}

export interface BackendScenarioRow {
  timestamp: string;
  scenario_label: string;
  scenario_weight: number;
  price_eur_per_mwh: number;
}

export interface BackendRunMetadata {
  delivery_day?: string;
  optimizer_display_name?: string;
  risk_profile?: string;
  risk_profile_label?: string;
  risk_profile_description?: string;
  solver_status?: string;
  expected_profit_eur?: number;
  realized_profit_eur?: number;
  worst_profit_eur?: number;
  best_profit_eur?: number;
  cvar_eur?: number;
  cvar_alpha?: number;
  cvar_lambda?: number;
  scenario_labels?: string[];
  scenario_weights?: number[];
  scenario_profits_eur?: number[];
  runtime_ms?: number;
  scenarios_used?: number;
  rainflow_aging_cost_eur?: number;
  rainflow_net_profit_eur?: number;
  equivalent_full_cycles?: number;
  cycles_used?: number;
  degradation_model?: string;
  battery_profile?: {
    name: string;
    technology?: string;
    power_mw: number;
    energy_mwh: number;
    eta_rt?: number;
    max_cycles_per_day?: number;
  };
  feasibility?: {
    feasible?: boolean;
    cycles_used?: number;
    cycle_violation?: number;
  };
}

export interface BackendRobustnessRow {
  round_trip_efficiency: number;
  degradation_cost_eur_per_mwh: number;
  realized_profit_eur: number;
  cycles_used?: number;
  cycle_violation?: number;
}

export interface BackendArtifacts {
  schedule: BackendScheduleRow[];
  scenario_panel: BackendScenarioRow[];
  run_metadata: BackendRunMetadata;
  robustness_sweep: BackendRobustnessRow[];
}

export interface BackendDispatchView {
  timestamps: string[];
  realized: number[];
  forecast: number[];
  p10: number[];
  p90: number[];
  charge: number[];
  discharge: number[];
  soc: number[];
  periodProfit: number[];
  cumProfit: number[];
  scenarios: number[][];
  expected: number;
  riskProfile: string;
  riskProfileLabel: string;
  riskLambda: number;
  riskAlpha: number;
  cvar: number;
  worst: number;
  capture: number;
  cyclesUsed: number;
  cyclesCap: number;
  agingCostTotal: number;
  solveMs: number;
  status: "Optimal" | "Suboptimal" | "Failed";
}

export interface OptimizePayload {
  battery_profile_name: string;
  risk_profile?: string;
  risk_lambda?: number;
  risk_alpha?: number;
  build_bid_curves?: boolean;
  run_robustness_sweep?: boolean;
}

function unwrapArtifacts(payload: unknown): BackendArtifacts {
  const data = payload as { artifacts?: BackendArtifacts } | BackendArtifacts;
  if ("artifacts" in data && data.artifacts) return data.artifacts;
  return data as BackendArtifacts;
}

async function readJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return res.json() as Promise<T>;
}

export async function fetchBackendArtifacts(): Promise<BackendArtifacts> {
  const res = await fetch("/api/artifacts");
  if (res.ok) return unwrapArtifacts(await res.json());

  return {
    schedule: await readJson<BackendScheduleRow[]>("/data/schedule.json"),
    scenario_panel: await readJson<BackendScenarioRow[]>("/data/scenario_panel.json"),
    run_metadata: await readJson<BackendRunMetadata>("/data/run_metadata.json"),
    robustness_sweep: await readJson<BackendRobustnessRow[]>("/data/robustness_sweep.json"),
  };
}

export async function runBackendOptimizer(payload: OptimizePayload): Promise<BackendArtifacts> {
  const res = await fetch("/api/optimize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`/api/optimize returned ${res.status}`);
  return unwrapArtifacts(await res.json());
}

export function artifactsToDispatchView(artifacts: BackendArtifacts): BackendDispatchView {
  const schedule = artifacts.schedule ?? [];
  const timestamps = schedule.map((r) => r.timestamp);
  const fallback = Array.from({ length: 96 }, () => 0);
  const forecast = schedule.length ? schedule.map((r) => Number(r.forecast_price_eur_per_mwh ?? 0)) : fallback;
  const realized = schedule.length ? schedule.map((r) => Number(r.realized_price_eur_per_mwh ?? r.forecast_price_eur_per_mwh ?? 0)) : fallback;
  const charge = schedule.length ? schedule.map((r) => Number(r.charge_mw ?? 0)) : fallback;
  const discharge = schedule.length ? schedule.map((r) => Number(r.discharge_mw ?? 0)) : fallback;
  const soc = schedule.length ? schedule.map((r) => Number(r.state_of_charge_mwh ?? 0)) : fallback;
  const periodProfit = schedule.length ? schedule.map((r) => Number(r.period_profit_eur ?? 0)) : fallback;
  const cumProfit = periodProfit.reduce<number[]>((acc, v) => {
    acc.push((acc[acc.length - 1] ?? 0) + v);
    return acc;
  }, []);

  const scenarioMatrix = buildScenarioMatrix(artifacts.scenario_panel ?? [], timestamps);
  const p10 = scenarioMatrix.length ? quantileByPeriod(scenarioMatrix, 0.1) : forecast;
  const p90 = scenarioMatrix.length ? quantileByPeriod(scenarioMatrix, 0.9) : forecast;
  const meta = artifacts.run_metadata ?? {};
  const best = Number(meta.best_profit_eur ?? meta.expected_profit_eur ?? 0);
  const expected = Number(meta.expected_profit_eur ?? cumProfit[cumProfit.length - 1] ?? 0);

  return {
    timestamps,
    realized,
    forecast,
    p10,
    p90,
    charge,
    discharge,
    soc,
    periodProfit,
    cumProfit,
    scenarios: scenarioMatrix,
    expected,
    riskProfile: String(meta.risk_profile ?? "custom"),
    riskProfileLabel: String(meta.risk_profile_label ?? "Custom"),
    riskLambda: Number(meta.cvar_lambda ?? 0.5),
    riskAlpha: Number(meta.cvar_alpha ?? 0.10),
    cvar: Number(meta.cvar_eur ?? expected),
    worst: Number(meta.worst_profit_eur ?? expected),
    capture: best > 0 ? expected / best : 0,
    cyclesUsed: Number(meta.cycles_used ?? meta.feasibility?.cycles_used ?? meta.equivalent_full_cycles ?? 0),
    cyclesCap: Number(meta.battery_profile?.max_cycles_per_day ?? 0),
    agingCostTotal: Number(meta.rainflow_aging_cost_eur ?? 0),
    solveMs: Number(meta.runtime_ms ?? 0),
    status: normalizeStatus(meta.solver_status),
  };
}

export function robustRowsForGrid(rows: BackendRobustnessRow[]): { e: number; d: number; p: number }[] {
  return rows.map((r) => ({
    e: Number(r.round_trip_efficiency),
    d: Number(r.degradation_cost_eur_per_mwh),
    p: Number(r.realized_profit_eur),
  }));
}

function buildScenarioMatrix(rows: BackendScenarioRow[], timestamps: string[]): number[][] {
  if (!rows.length) return [];
  const labels = [...new Set(rows.map((r) => r.scenario_label))];
  const timeOrder = timestamps.length ? timestamps : [...new Set(rows.map((r) => r.timestamp))];
  const byLabel = new Map<string, Map<string, number>>();
  for (const row of rows) {
    if (!byLabel.has(row.scenario_label)) byLabel.set(row.scenario_label, new Map());
    byLabel.get(row.scenario_label)!.set(row.timestamp, Number(row.price_eur_per_mwh));
  }
  return labels.map((label) => {
    const byTime = byLabel.get(label)!;
    return timeOrder.map((ts) => byTime.get(ts) ?? 0);
  });
}

function quantileByPeriod(matrix: number[][], q: number): number[] {
  const width = matrix[0]?.length ?? 0;
  return Array.from({ length: width }, (_, i) => {
    const values = matrix.map((row) => row[i]).sort((a, b) => a - b);
    const idx = Math.min(values.length - 1, Math.max(0, Math.round(q * (values.length - 1))));
    return values[idx] ?? 0;
  });
}

function normalizeStatus(status?: string): "Optimal" | "Suboptimal" | "Failed" {
  const s = (status ?? "").toLowerCase();
  if (s.includes("optimal")) return "Optimal";
  if (s.includes("sub") || s.includes("feasible")) return "Suboptimal";
  return s ? "Failed" : "Suboptimal";
}
