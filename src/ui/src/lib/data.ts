// Deterministic synthetic data for the Greek DAM (mirrors original BatteryOS demo)
import type { BatteryAsset } from "./types";

export const N_PERIODS = 96; // 15-min MTU

export function tsLabel(i: number) {
  const h = Math.floor(i / 4);
  const m = (i % 4) * 15;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function priceAt(i: number) {
  const h = i / 4;
  let p = 80;
  p += -10 * Math.exp(-Math.pow((h - 3.5) / 2.4, 2));
  p += 60 * Math.exp(-Math.pow((h - 7.8) / 1.4, 2));
  p += -42 * Math.exp(-Math.pow((h - 13) / 1.6, 2));
  p += 18 * Math.exp(-Math.pow((h - 16) / 2.4, 2));
  p += 95 * Math.exp(-Math.pow((h - 19.5) / 1.5, 2));
  p += -8 * Math.exp(-Math.pow((h - 23) / 2.0, 2));
  p += Math.sin(i * 0.71) * 2.4 + Math.cos(i * 0.31) * 1.7;
  return Math.max(28, p);
}

export const realized: number[] = Array.from({ length: N_PERIODS }, (_, i) => priceAt(i));
export const forecast: number[] = realized.map(
  (v, i) => v * (0.96 + 0.04 * Math.cos(i * 0.21)) + Math.sin(i * 0.5) * 1.5
);
export const p10: number[] = forecast.map((v, i) => v - 8 - 6 * Math.abs(Math.sin(i * 0.18)));
export const p90: number[] = forecast.map((v, i) => v + 9 + 7 * Math.abs(Math.cos(i * 0.22)));

function rng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

export function buildScenarios(n = 20): number[][] {
  const out: number[][] = [];
  for (let k = 0; k < n; k++) {
    const r = rng(7 * (k + 1) + 13);
    const path: number[] = [];
    const bias = (r() - 0.5) * 16;
    for (let i = 0; i < N_PERIODS; i++) {
      const drift = Math.sin(i * 0.1 + k * 0.3) * 6;
      path.push(forecast[i] + bias + drift + (r() - 0.5) * 12);
    }
    out.push(path);
  }
  return out;
}

export const scenarios20 = buildScenarios(20);

// Backtest equity (90 days)
export const equityCurve = (() => {
  const days = 90;
  const equity = { batteryOS: [] as number[], naive: [] as number[], perfect: [] as number[] };
  const acc = { b: 0, n: 0, p: 0 };
  const dayProfits: { d: number; bos: number; naive: number; perfect: number; capture: number }[] = [];
  for (let d = 0; d < days; d++) {
    const r = rng(d * 11 + 5);
    const baseline = 22000 + Math.sin(d * 0.21) * 3000 + (r() - 0.5) * 4000;
    const perfect = baseline * 1.45 + (r() - 0.5) * 1500;
    const bos = baseline * 1.05 + (r() - 0.5) * 2200;
    const naive = baseline * 0.65 + (r() - 0.5) * 2500;
    acc.b += bos; acc.n += naive; acc.p += perfect;
    equity.batteryOS.push(acc.b);
    equity.naive.push(acc.n);
    equity.perfect.push(acc.p);
    dayProfits.push({ d, bos, naive, perfect, capture: bos / perfect });
  }
  return { equity, dayProfits };
})();

// Heatmap 30 × 24
export const heatmap = (() => {
  const heat: number[][] = [];
  for (let day = 0; day < 30; day++) {
    const row: number[] = [];
    const r = rng(day * 31 + 17);
    for (let h = 0; h < 24; h++) {
      const peak = Math.exp(-Math.pow((h - 8) / 2, 2)) + 1.4 * Math.exp(-Math.pow((h - 19) / 1.6, 2));
      const trough = -0.7 * Math.exp(-Math.pow((h - 13) / 1.7, 2));
      row.push(peak + trough + 0.4 + (r() - 0.5) * 0.5);
    }
    heat.push(row);
  }
  return heat;
})();

export const defaultAssets: BatteryAsset[] = [
  { id: "liion_100_2h", tech: "Li-Ion", power: 100, energy: 200, eff: 0.949, socMinPct: 0.10, socMaxPct: 0.90, cyclesPerDay: 1.5, agingCost: 2.0, status: "active", utilization: 0.62 },
  { id: "liion_200_2h", tech: "Li-Ion", power: 200, energy: 400, eff: 0.949, socMinPct: 0.10, socMaxPct: 0.90, cyclesPerDay: 1.5, agingCost: 2.0, status: "active", utilization: 0.71 },
  { id: "liion_300_2h", tech: "Li-Ion", power: 300, energy: 600, eff: 0.949, socMinPct: 0.10, socMaxPct: 0.90, cyclesPerDay: 1.5, agingCost: 2.0, status: "active", utilization: 0.58 },
  { id: "phs_100_8h",   tech: "Pumped Hydro", power: 100, energy: 800, eff: 0.886, socMinPct: 0.05, socMaxPct: 0.95, cyclesPerDay: 1.0, agingCost: 0.5, status: "active", utilization: 0.44 },
  { id: "phs_200_8h",   tech: "Pumped Hydro", power: 200, energy: 1600, eff: 0.886, socMinPct: 0.05, socMaxPct: 0.95, cyclesPerDay: 1.0, agingCost: 0.5, status: "paused", utilization: 0.0 },
  { id: "flow_100_6h",  tech: "Vanadium Flow", power: 100, energy: 600, eff: 0.866, socMinPct: 0.10, socMaxPct: 0.95, cyclesPerDay: 2.0, agingCost: 1.0, status: "active", utilization: 0.39 },
];

export const sources = [
  { id: "henex",   name: "HEnEx DAM",       desc: "Day-ahead clearing prices, market curves", status: "ok",   latency: "8 min",  rows: "2.4M", lastSync: "12:42" },
  { id: "ipto",    name: "IPTO / ADMIE",    desc: "Greek load + RES forecasts, ATC, system data", status: "ok",   latency: "21 min", rows: "1.1M", lastSync: "12:42" },
  { id: "openmeteo", name: "Open-Meteo",    desc: "Weather: temp, wind, irradiance, clouds", status: "ok",   latency: "4 min",  rows: "640k", lastSync: "12:43" },
  { id: "entsoe",  name: "ENTSO-E",         desc: "Pan-European load, generation, cross-border", status: "ok",   latency: "33 min", rows: "8.2M", lastSync: "12:34" },
  { id: "ttf",     name: "TTF Gas",         desc: "Dutch TTF gas benchmark", status: "warn", latency: "2 h 04m", rows: "12k",  lastSync: "10:42" },
  { id: "eua",     name: "EEX EUA Carbon",  desc: "EU carbon allowance prices", status: "ok",   latency: "55 min", rows: "9.8k", lastSync: "12:00" },
  { id: "remit",   name: "REMIT Outages",   desc: "Plant outage notifications", status: "err",  latency: "—",      rows: "—",    lastSync: "yest. 18:11" },
] as const;

export const features = [
  { name: "residual_load_forecast", group: "Fundamentals", imp: 0.184 },
  { name: "price_lag_1d_same_hour", group: "Market Memory", imp: 0.142 },
  { name: "gas_price",              group: "Fuel & Carbon", imp: 0.108 },
  { name: "DE_residual_load",       group: "Cross-border", imp: 0.094 },
  { name: "rolling_volatility_7d",  group: "Market Memory", imp: 0.078 },
  { name: "solar_irradiance_fc",    group: "Weather",       imp: 0.072 },
  { name: "carbon_price",           group: "Fuel & Carbon", imp: 0.061 },
  { name: "hour_of_day",            group: "Calendar",      imp: 0.058 },
  { name: "wind_speed_fc",          group: "Weather",       imp: 0.044 },
  { name: "GR_IT_atc",              group: "Cross-border", imp: 0.041 },
  { name: "weekend_flag",           group: "Calendar",      imp: 0.034 },
  { name: "price_lag_7d",           group: "Market Memory", imp: 0.029 },
  { name: "BG_residual_load",       group: "Cross-border", imp: 0.024 },
  { name: "temperature_fc",         group: "Weather",       imp: 0.021 },
  { name: "holiday_flag",           group: "Calendar",      imp: 0.012 },
];

export const models = [
  { id: "naive_1d",   name: "Naive 1d",          kind: "Baseline",      mae: 22.4, rmse: 31.1, smape: 24.2, profit: 0.41 },
  { id: "naive_7d",   name: "Naive 7d",          kind: "Baseline",      mae: 18.9, rmse: 27.3, smape: 21.6, profit: 0.48 },
  { id: "sarimax",    name: "SARIMAX",           kind: "Statistical",   mae: 14.3, rmse: 21.8, smape: 16.4, profit: 0.61 },
  { id: "lgbm",       name: "LightGBM-q50",      kind: "ML",            mae: 9.8,  rmse: 15.2, smape: 11.7, profit: 0.72 },
  { id: "lgbm_q",     name: "LightGBM Quantile", kind: "ML+Quantile",   mae: 9.6,  rmse: 15.0, smape: 11.5, profit: 0.74 },
];

export const ticker = [
  { l: "EL DAM", v: "€84.2/MWh", d: "+2.1%", up: true },
  { l: "TTF gas", v: "€31.4", d: "−0.4%", up: false },
  { l: "EUA", v: "€72.8", d: "+0.8%", up: true },
  { l: "GR load fc", v: "6.4 GW", d: "+1.2%", up: true },
  { l: "RES share", v: "38%", d: "+3.0%", up: true },
  { l: "DE residual", v: "42 GW", d: "−1.1%", up: false },
  { l: "GR-IT ATC", v: "500 MW", d: "—", up: null as boolean | null },
];
