import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  BatteryCharging,
  BriefcaseBusiness,
  CheckCircle2,
  CircleDollarSign,
  Database,
  Gauge,
  GitBranch,
  LineChart as LineChartIcon,
  Map,
  Radar,
  ShieldAlert,
  SlidersHorizontal,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./styles.css";

const COLORS = {
  bg: "#0B0F19",
  panel: "#111827",
  panel2: "#0F1624",
  border: "#253044",
  text: "#FAFAFA",
  muted: "#9CA3AF",
  faint: "#6B7280",
  blue: "#3B82F6",
  amber: "#F59E0B",
  red: "#EF4444",
  green: "#22C55E",
  teal: "#14B8A6",
  purple: "#A855F7",
  cyan: "#06B6D4",
};

const profiles = {
  liion_100_2h: {
    name: "Li-ion 100 MW / 2h",
    power_mw: 100,
    energy_mwh: 200,
    eta_rt: 0.9,
    soc_min_mwh: 20,
    soc_max_mwh: 180,
    max_cycles_per_day: 1.5,
  },
  liion_200_2h: {
    name: "Li-ion 200 MW / 2h",
    power_mw: 200,
    energy_mwh: 400,
    eta_rt: 0.9,
    soc_min_mwh: 40,
    soc_max_mwh: 360,
    max_cycles_per_day: 1.5,
  },
  phs_100_8h: {
    name: "Pumped hydro 100 MW / 8h",
    power_mw: 100,
    energy_mwh: 800,
    eta_rt: 0.78,
    soc_min_mwh: 40,
    soc_max_mwh: 760,
    max_cycles_per_day: 1,
  },
};

const countries = {
  GR: "Greece",
  IT_S: "Italy South",
  BG: "Bulgaria",
};

const featurePresets = {
  greek: ["Greek-only"],
  multi: ["Greek-only", "+Multi-country"],
  domino: ["Greek-only", "+Multi-country", "+German-domino"],
  remit: ["Greek-only", "+Multi-country", "+German-domino", "+REMIT outages"],
};

const zoneData = [
  { code: "GR", name: "Greece", tier: 2, x: 62, y: 68, mtu: 15, bess: 3200, sources: 6, neighbors: "IT-S, BG" },
  { code: "IT-S", name: "Italy South", tier: 2, x: 48, y: 63, mtu: 15, bess: 5400, sources: 5, neighbors: "GR, IT-N" },
  { code: "BG", name: "Bulgaria", tier: 2, x: 66, y: 58, mtu: 15, bess: 1600, sources: 4, neighbors: "GR, RO" },
  { code: "RO", name: "Romania", tier: 1, x: 68, y: 50, mtu: 15, bess: 2100, sources: 3, neighbors: "BG, HU" },
  { code: "HU", name: "Hungary", tier: 1, x: 58, y: 48, mtu: 15, bess: 1800, sources: 3, neighbors: "RO, SK" },
  { code: "SK", name: "Slovakia", tier: 1, x: 56, y: 42, mtu: 15, bess: 900, sources: 3, neighbors: "HU, CZ" },
  { code: "CZ", name: "Czechia", tier: 1, x: 50, y: 40, mtu: 15, bess: 1300, sources: 3, neighbors: "SK, DE" },
  { code: "DE", name: "Germany/Lux", tier: 2, x: 46, y: 34, mtu: 15, bess: 11200, sources: 5, neighbors: "AT, CZ, NL" },
  { code: "AT", name: "Austria", tier: 1, x: 50, y: 48, mtu: 15, bess: 1600, sources: 3, neighbors: "DE, IT-N" },
  { code: "CH", name: "Switzerland", tier: 1, x: 43, y: 50, mtu: 15, bess: 1200, sources: 3, neighbors: "DE, IT-N" },
  { code: "FR", name: "France", tier: 1, x: 34, y: 45, mtu: 15, bess: 7800, sources: 3, neighbors: "DE, ES" },
  { code: "ES", name: "Spain", tier: 1, x: 22, y: 62, mtu: 15, bess: 6200, sources: 3, neighbors: "FR, PT" },
];

const familyColors = {
  Calendar: "#94A3B8",
  "Lag/rolling": "#64748B",
  "Residual load": COLORS.blue,
  RES: "#22C55E",
  "Fuels/EUA": COLORS.amber,
  "Greek supply curve": COLORS.purple,
  "Multi-country direct neighbor": COLORS.teal,
  "German domino": COLORS.red,
  "REMIT outage": "#F97316",
  Hydro: COLORS.cyan,
};

const sourceFreshness = [
  ["HEnEx", "2026-04-28 14:15", "green", "1,617"],
  ["IPTO", "2026-04-28 11:52", "green", "384"],
  ["ENTSO-E GR/IT/BG/DE", "2026-04-28 12:05", "green", "2,304"],
  ["Open-Meteo", "2026-04-28 10:30", "green", "1,152"],
  ["ICE TTF", "2026-04-28 18:00", "amber", "1"],
  ["EEX EUA", "2026-04-28 18:10", "amber", "1"],
  ["REMIT UMM", "2026-04-28 09:45", "green", "42"],
  ["Hydro reservoirs", "2026-04-27 23:00", "amber", "18"],
];

function generateData(profileKey, runMode, presetKey, country) {
  const profile = profiles[profileKey];
  const featureBoost = { greek: 0, multi: 0.08, domino: 0.15, remit: 0.2 }[presetKey];
  const countryShift = { GR: 0, IT_S: -7, BG: -12 }[country] || 0;
  const powerScale = profile.power_mw / 100;
  let soc = profile.energy_mwh * 0.5;
  const schedule = [];
  const scenarioPanel = [];
  let cumulative = 0;
  for (let i = 0; i < 96; i++) {
    const hour = i / 4;
    const label = `${String(Math.floor(hour)).padStart(2, "0")}:${String((i % 4) * 15).padStart(2, "0")}`;
    const solarDip = -55 * Math.exp(-Math.pow((hour - 13) / 3.8, 2));
    const eveningSpike = 82 * Math.exp(-Math.pow((hour - 20) / 2.5, 2));
    const morningSpike = 30 * Math.exp(-Math.pow((hour - 7.5) / 1.8, 2));
    const noise = 8 * Math.sin(i * 0.72) + 5 * Math.cos(i * 0.21);
    const p50 = 112 + countryShift + solarDip + eveningSpike + morningSpike + noise;
    const band = runMode === "Deterministic" ? 0 : 18 + 18 * Math.exp(-Math.pow((hour - 20) / 3, 2));
    const p10 = p50 - band;
    const p90 = p50 + band * 1.25;
    const realized = p50 + (1 - featureBoost) * (12 * Math.sin(i * 0.5) + 8 * Math.cos(i * 0.13));
    let charge = 0;
    let discharge = 0;
    if (p50 < 78 && soc < profile.soc_max_mwh - 2) charge = Math.min(profile.power_mw, (profile.soc_max_mwh - soc) / (0.25 * 0.949));
    if (p50 > 145 && soc > profile.soc_min_mwh + 2) discharge = Math.min(profile.power_mw, (soc - profile.soc_min_mwh) * 0.949 / 0.25);
    if (charge > 0) soc += charge * 0.949 * 0.25;
    if (discharge > 0) soc -= (discharge / 0.949) * 0.25;
    const periodProfit = p50 * (discharge - charge) * 0.25 - 2 * (charge + discharge) * 0.25;
    cumulative += periodProfit;
    schedule.push({
      idx: i,
      timestamp: `2026-04-29 ${label}`,
      time: label,
      forecast_price_eur_per_mwh: Math.round(p50 * 100) / 100,
      p10: Math.round(p10 * 100) / 100,
      p90: Math.round(p90 * 100) / 100,
      bandLow: Math.round(p10 * 100) / 100,
      bandHigh: Math.round(p90 * 100) / 100,
      realized_price_eur_per_mwh: Math.round(realized * 100) / 100,
      charge_mw: Math.round(charge * 10) / 10,
      discharge_mw: Math.round(discharge * 10) / 10,
      dispatchBar: discharge > 0 ? discharge : charge > 0 ? -charge : 0,
      state_of_charge_mwh: Math.round(soc * 10) / 10,
      action: charge > 0.1 ? "CHARGE" : discharge > 0.1 ? "DISCHARGE" : "IDLE",
      actionLabel: charge > 0.1 ? "C" : discharge > 0.1 ? "D" : "",
      period_profit_eur: Math.round(periodProfit),
      cumulative_profit_eur: Math.round(cumulative),
    });
    scenarioPanel.push(
      { timestamp: `2026-04-29 ${label}`, scenario_label: "p10", scenario_weight: 0.2, price_eur_per_mwh: p10 },
      { timestamp: `2026-04-29 ${label}`, scenario_label: "p50", scenario_weight: 0.6, price_eur_per_mwh: p50 },
      { timestamp: `2026-04-29 ${label}`, scenario_label: "p90", scenario_weight: 0.2, price_eur_per_mwh: p90 },
    );
  }
  const throughput = schedule.reduce((s, r) => s + (r.charge_mw + r.discharge_mw) * 0.25, 0);
  const cycles = throughput / (2 * profile.energy_mwh);
  const realizedProfit = schedule.reduce((sum, r) => sum + r.realized_price_eur_per_mwh * (r.discharge_mw - r.charge_mw) * 0.25 - 2 * (r.charge_mw + r.discharge_mw) * 0.25, 0);
  const perfectPct = Math.min(91, 62 + featureBoost * 120 + (runMode === "CVaR" ? 2 : 0));
  const naiveDelta = realizedProfit * (0.18 + featureBoost);
  const scenarioProfits = [
    realizedProfit * 0.62,
    realizedProfit * 0.94,
    realizedProfit * 1.22,
  ].map((v) => Math.round(v));
  const robustness = [];
  for (const eta of [0.85, 0.9, 0.95, 1]) {
    for (const deg of [1, 2, 3, 5]) {
      const penalty = (1 - eta) * 90000 * powerScale + deg * 1250 * powerScale;
      robustness.push({
        round_trip_efficiency: eta,
        degradation_cost_eur_per_mwh: deg,
        realized_profit_eur: Math.round(realizedProfit - penalty),
        cycles_used: Math.round((cycles + (1 - eta) * 0.2) * 100) / 100,
        cycle_violation: Math.max(0, Math.round((cycles - profile.max_cycles_per_day) * 100) / 100),
      });
    }
  }
  return {
    schedule,
    scenarioPanel,
    robustness,
    metadata: {
      battery_profile: profile,
      optimizer: runMode.toLowerCase(),
      objective_value_eur: Math.round(realizedProfit * 0.96),
      solver_status: "Optimal",
      expected_profit_eur: Math.round(realizedProfit),
      worst_profit_eur: Math.min(...robustness.map((r) => r.realized_profit_eur)),
      cvar_eur: runMode === "CVaR" ? Math.round(scenarioProfits[0] * 0.92) : null,
      cvar_alpha: runMode === "CVaR" ? 0.1 : null,
      cvar_lambda: runMode === "CVaR" ? 0.7 : null,
      scenario_profits_eur: scenarioProfits,
      feasibility: { feasible: true },
      feature_families_enabled: featurePresets[presetKey],
      realized_profit_vs_perfect_pct: Math.round(perfectPct * 10) / 10,
      realized_profit_vs_naive_pct: Math.round((18 + featureBoost * 100) * 10) / 10,
      cycles_used: Math.round(cycles * 100) / 100,
      naive_delta_eur: Math.round(naiveDelta),
      perfect_delta_eur: Math.round(realizedProfit * (100 / perfectPct - 1)),
      runtime_ms: 184,
      scenarios_used: runMode === "Deterministic" ? 1 : 3,
    },
  };
}

function formatEUR(value) {
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(value).replace(/\s/g, "\u202F") + " EUR";
}

function formatPct(value) {
  return `${Number(value).toFixed(1)}%`;
}

function App() {
  const [route, setRoute] = useState(window.location.pathname === "/moat" ? "moat" : window.location.pathname === "/business" ? "business" : "dashboard");
  const [country, setCountry] = useState("GR");
  const [profile, setProfile] = useState("liion_100_2h");
  const [runMode, setRunMode] = useState("Stochastic");
  const [preset, setPreset] = useState("domino");
  const [profitMode, setProfitMode] = useState("period");
  const [selectedPeriod, setSelectedPeriod] = useState(0);
  const dataset = useMemo(() => generateData(profile, runMode, preset, country), [profile, runMode, preset, country]);

  useEffect(() => {
    const runModes = ["Deterministic", "Stochastic", "CVaR"];
    const presets = Object.keys(featurePresets);
    function onKeyDown(event) {
      if (["INPUT", "SELECT", "TEXTAREA"].includes(event.target?.tagName)) return;
      if (event.key === "ArrowRight") setSelectedPeriod((value) => Math.min(95, value + 1));
      if (event.key === "ArrowLeft") setSelectedPeriod((value) => Math.max(0, value - 1));
      if (event.key.toLowerCase() === "r") {
        setRunMode((value) => runModes[(runModes.indexOf(value) + 1) % runModes.length]);
      }
      if (event.key.toLowerCase() === "f") {
        setPreset((value) => presets[(presets.indexOf(value) + 1) % presets.length]);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function navigate(next) {
    setRoute(next);
    window.history.pushState({}, "", next === "dashboard" ? "/" : `/${next}`);
  }

  return (
    <div className="app">
      <Sidebar route={route} navigate={navigate} />
      <main className="shell">
        <TopBar country={country} setCountry={setCountry} profile={profile} setProfile={setProfile} runMode={runMode} setRunMode={setRunMode} />
        {route === "dashboard" && <Dashboard data={dataset} runMode={runMode} preset={preset} setPreset={setPreset} profitMode={profitMode} setProfitMode={setProfitMode} selectedPeriod={selectedPeriod} />}
        {route === "moat" && <Moat preset={preset} setPreset={setPreset} />}
        {route === "business" && <Business />}
      </main>
    </div>
  );
}

function Sidebar({ route, navigate }) {
  const items = [
    ["dashboard", "Dashboard", LineChartIcon],
    ["moat", "Moat", Radar],
    ["business", "Business", BriefcaseBusiness],
  ];
  return (
    <aside className="sidebar">
      <div className="brand"><BatteryCharging size={22} /><span>BatteryOS</span></div>
      <nav>
        {items.map(([key, label, Icon]) => (
          <button key={key} onClick={() => navigate(key)} className={`nav-item ${route === key ? "active" : ""}`}>
            <Icon size={17} /> {label}
          </button>
        ))}
      </nav>
      <div className="sidebar-foot">
        <span>HEnEx anchor</span>
        <strong>SDAC roadmap</strong>
      </div>
    </aside>
  );
}

function TopBar({ country, setCountry, profile, setProfile, runMode, setRunMode }) {
  return (
    <header className="topbar">
      <div className="control">
        <span>Country</span>
        <select value={country} onChange={(e) => setCountry(e.target.value)}>{Object.entries(countries).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      </div>
      <div className="control wide">
        <span>Storage profile</span>
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>{Object.entries(profiles).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}</select>
      </div>
      <div className="control">
        <span>Delivery day</span>
        <input type="date" defaultValue="2026-04-29" />
      </div>
      <div className="segmented">
        {["Deterministic", "Stochastic", "CVaR"].map((mode) => <button key={mode} onClick={() => setRunMode(mode)} className={runMode === mode ? "active" : ""}>{mode}</button>)}
      </div>
    </header>
  );
}

function Dashboard({ data, runMode, preset, setPreset, profitMode, setProfitMode, selectedPeriod }) {
  const { schedule, metadata } = data;
  const cvarVisible = runMode === "CVaR";
  return (
    <div className="page dashboard-grid">
      <section className="content">
        <div className="kpis">
          <Kpi title="Realized profit" value={formatEUR(metadata.expected_profit_eur)} sub={`+${formatEUR(metadata.naive_delta_eur)} vs naive · -${formatEUR(metadata.perfect_delta_eur)} vs perfect`} icon={CircleDollarSign} />
          <Kpi title="Perfect foresight captured" value={formatPct(metadata.realized_profit_vs_perfect_pct)} sub="the headline number" icon={Gauge} />
          <Kpi title="Worst-case profit" value={formatEUR(metadata.worst_profit_eur)} sub="if the battery underperforms its spec sheet" icon={ShieldAlert} />
          <Kpi title="Cycles used" value={`${metadata.cycles_used} / ${metadata.battery_profile.max_cycles_per_day}`} sub={<Progress value={metadata.cycles_used / metadata.battery_profile.max_cycles_per_day} />} icon={Activity} />
          <Kpi title={`CVaR${metadata.cvar_alpha ? `_${metadata.cvar_alpha}` : ""} profit`} value={cvarVisible ? formatEUR(metadata.cvar_eur) : "Hidden"} sub={cvarVisible ? "tail-risk adjusted" : "shown only in CVaR mode"} icon={GitBranch} muted={!cvarVisible} />
        </div>
        <Panel title="Live dispatch" action={<span className="caption">Selected {schedule[selectedPeriod]?.time} · 96 quarter-hour MTUs</span>}>
          <div className="chart-large">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={schedule} margin={{ top: 20, right: 40, left: 0, bottom: 20 }}>
                <CartesianGrid stroke="#1F2937" vertical={false} />
                <XAxis dataKey="time" tick={{ fill: COLORS.faint, fontSize: 11 }} interval={7} axisLine={false} tickLine={false} />
                <YAxis yAxisId="price" tick={{ fill: COLORS.faint, fontSize: 11 }} axisLine={false} tickLine={false} label={{ value: "EUR/MWh", angle: -90, fill: COLORS.faint, position: "insideLeft" }} />
                <YAxis yAxisId="mw" orientation="right" tick={{ fill: COLORS.faint, fontSize: 11 }} axisLine={false} tickLine={false} label={{ value: "MW", angle: 90, fill: COLORS.faint, position: "insideRight" }} />
                <Tooltip content={<DispatchTooltip runMode={runMode} />} />
                {runMode !== "Deterministic" && <Area yAxisId="price" type="monotone" dataKey="bandHigh" stroke="none" fill="#6B7280" fillOpacity={0.13} />}
                {runMode !== "Deterministic" && <Area yAxisId="price" type="monotone" dataKey="bandLow" stroke="none" fill={COLORS.bg} fillOpacity={1} />}
                <Bar yAxisId="mw" dataKey="dispatchBar" barSize={4}>{schedule.map((r) => <Cell key={r.idx} fill={r.dispatchBar < 0 ? COLORS.blue : COLORS.amber} fillOpacity={0.72} />)}</Bar>
                <Line yAxisId="price" type="monotone" dataKey="forecast_price_eur_per_mwh" stroke="#9CA3AF" strokeWidth={2} dot={false} />
                <Line yAxisId="price" type="monotone" dataKey="realized_price_eur_per_mwh" stroke={COLORS.text} strokeWidth={2.4} strokeDasharray="5 5" dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="action-strip">{schedule.map((r) => <span key={r.idx} className={`action-tag ${r.action.toLowerCase()} ${r.idx === selectedPeriod ? "selected" : ""}`}>{r.actionLabel}</span>)}</div>
        </Panel>
        <div className="split">
          <Panel title="State of charge">
            <div className="chart-mid">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={schedule} margin={{ top: 14, right: 16, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke="#1F2937" vertical={false} />
                  <XAxis dataKey="time" interval={15} tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<SimpleTooltip />} />
                  <Area dataKey="state_of_charge_mwh" type="monotone" stroke={COLORS.blue} fill={COLORS.blue} fillOpacity={0.16} strokeWidth={2.2} />
                  <Line dataKey={() => metadata?.battery_profile?.soc_min_mwh || 20} stroke={COLORS.red} strokeDasharray="4 4" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Panel>
          <Panel title="Period profit" action={<button className="micro-button" onClick={() => setProfitMode(profitMode === "period" ? "cumulative" : "period")}>{profitMode}</button>}>
            <div className="chart-mid">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={schedule} margin={{ top: 14, right: 16, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke="#1F2937" vertical={false} />
                  <XAxis dataKey="time" interval={15} tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ProfitTooltip />} />
                  <Bar dataKey={profitMode === "period" ? "period_profit_eur" : "cumulative_profit_eur"} barSize={5}>{schedule.map((r) => <Cell key={r.idx} fill={(profitMode === "period" ? r.period_profit_eur : r.cumulative_profit_eur) >= 0 ? "#16A34A" : COLORS.red} fillOpacity={0.72} />)}</Bar>
                  <Line dataKey="cumulative_profit_eur" stroke={COLORS.text} dot={false} strokeWidth={1.8} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>
        <FeaturePills preset={preset} setPreset={setPreset} />
      </section>
      <RunSummary data={data} runMode={runMode} />
    </div>
  );
}

function Kpi({ title, value, sub, icon: Icon, muted }) {
  return <div className={`kpi ${muted ? "muted" : ""}`}><div className="kpi-head"><span>{title}</span><Icon size={16} /></div><strong>{value}</strong><div className="kpi-sub">{sub}</div></div>;
}

function Panel({ title, children, action }) {
  return <section className="panel"><div className="panel-head"><h2>{title}</h2>{action}</div>{children}</section>;
}

function Progress({ value }) {
  return <span className="progress"><i style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} /></span>;
}

function FeaturePills({ preset, setPreset }) {
  return <div className="feature-row">{Object.entries(featurePresets).map(([key, labels]) => <button key={key} onClick={() => setPreset(key)} className={preset === key ? "active" : ""}>{labels[labels.length - 1]}</button>)}</div>;
}

function RunSummary({ data, runMode }) {
  const { metadata } = data;
  const rows = ["p10", "p50", "p90"].map((label, i) => ({ label, weight: [0.2, 0.6, 0.2][i], profit: metadata.scenario_profits_eur[i] }));
  return <aside className="rail"><h2>Run summary</h2><Info label="Battery" value={metadata.battery_profile.name} /><Info label="Power / energy" value={`${metadata.battery_profile.power_mw} MW / ${metadata.battery_profile.energy_mwh} MWh`} /><Info label="η round-trip" value={`${Math.round(metadata.battery_profile.eta_rt * 100)}%`} /><Info label="Solver" value={`${metadata.solver_status} · ${metadata.runtime_ms} ms`} /><Info label="Scenarios" value={metadata.scenarios_used} /><Info label="Objective" value={formatEUR(metadata.objective_value_eur)} /><div className="feasible"><CheckCircle2 size={16} /> Feasible</div>{runMode !== "Deterministic" && <div className="scenario-table"><h3>Scenario profits</h3>{rows.map((r, idx) => <div key={r.label} className={runMode === "CVaR" && idx === 0 ? "tail" : ""}><span>{r.label}</span><span>{Math.round(r.weight * 100)}%</span><strong>{formatEUR(r.profit)}</strong></div>)}</div>}<button className="rerun"><SlidersHorizontal size={15} /> Re-run with different parameters</button></aside>;
}

function Info({ label, value }) {
  return <div className="info"><span>{label}</span><strong>{value}</strong></div>;
}

function DispatchTooltip({ active, payload, runMode }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return <div className="tooltip"><strong>{r.timestamp}</strong><span>p50 {r.forecast_price_eur_per_mwh} EUR/MWh</span>{runMode !== "Deterministic" && <span>p10/p90 {r.p10} / {r.p90}</span>}<span>realized {r.realized_price_eur_per_mwh}</span><span>charge/discharge {r.charge_mw} / {r.discharge_mw} MW</span><span>SoC {r.state_of_charge_mwh} MWh</span><span>profit {formatEUR(r.period_profit_eur)}</span></div>;
}
function SimpleTooltip({ active, payload }) { if (!active || !payload?.length) return null; const r = payload[0].payload; return <div className="tooltip"><strong>{r.time}</strong><span>SoC {r.state_of_charge_mwh} MWh</span></div>; }
function ProfitTooltip({ active, payload }) { if (!active || !payload?.length) return null; const r = payload[0].payload; return <div className="tooltip"><strong>{r.time}</strong><span>period {formatEUR(r.period_profit_eur)}</span><span>cumulative {formatEUR(r.cumulative_profit_eur)}</span></div>; }

function Moat({ preset, setPreset }) {
  const features = makeFeatures(preset);
  return <div className="page moat-grid"><section className="content"><Panel title="SDAC zone coverage"><EuropeMap mode="tier" /></Panel><Panel title="Feature importance" action={<FeaturePills preset={preset} setPreset={setPreset} />}><div className="chart-mid"><ResponsiveContainer width="100%" height="100%"><BarChart data={features} layout="vertical" margin={{ left: 120, right: 20, top: 10, bottom: 10 }}><CartesianGrid stroke="#1F2937" horizontal={false} /><XAxis type="number" tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis type="category" dataKey="name" tick={{ fill: COLORS.muted, fontSize: 10 }} width={118} axisLine={false} tickLine={false} /><Tooltip content={<FeatureTooltip />} /><Bar dataKey="gain" radius={[0, 4, 4, 0]}>{features.map((f) => <Cell key={f.name} fill={familyColors[f.family]} />)}<LabelList dataKey="gain" position="right" fill={COLORS.muted} fontSize={10} /></Bar></BarChart></ResponsiveContainer></div></Panel><Panel title="Coupling chain"><CouplingChain /></Panel></section><aside className="rail"><h2>Pipeline freshness</h2>{sourceFreshness.map(([name, time, status, count]) => <div className="source" key={name}><span className={`dot ${status}`} /><div><strong>{name}</strong><small>{time}</small></div><em>{count}</em></div>)}</aside></div>;
}

function makeFeatures(preset) {
  const base = [
    ["GR residual load forecast", "Residual load", 96],
    ["price lag 1d same MTU", "Lag/rolling", 84],
    ["hour x weekend", "Calendar", 62],
    ["solar forecast", "RES", 58],
    ["TTF implied CCGT cost", "Fuels/EUA", 55],
    ["HEnEx supply slope", "Greek supply curve", 50],
    ["IT-S residual load", "Multi-country direct neighbor", 44],
    ["BG residual load", "Multi-country direct neighbor", 38],
    ["DE wind surplus", "German domino", preset === "greek" ? 8 : preset === "multi" ? 28 : 68],
    ["central corridor surplus", "German domino", preset === "greek" ? 6 : preset === "multi" ? 24 : 64],
    ["REMIT gas outage MW", "REMIT outage", preset === "remit" ? 57 : 14],
    ["Alpine reservoir index", "Hydro", 31],
  ];
  return base.map(([name, family, gain]) => ({ name, family, gain })).sort((a, b) => b.gain - a.gain).slice(0, 20);
}

function FeatureTooltip({ active, payload }) { if (!active || !payload?.length) return null; const f = payload[0].payload; return <div className="tooltip"><strong>{f.name}</strong><span>{f.family}</span><span>SHAP gain {f.gain}</span></div>; }

function EuropeMap({ mode = "tier" }) {
  return <div className="mapbox">{zoneData.map((z) => <div key={z.code} className={`zone tier-${z.tier} ${z.code === "GR" ? "anchor" : ""}`} style={{ left: `${z.x}%`, top: `${z.y}%`, transform: `scale(${mode === "tam" ? 0.8 + z.bess / 14000 : 1})` }} title={`${z.name}: ${z.mtu} min MTU, neighbors ${z.neighbors}`}><span>{z.code}</span></div>)}<div className="map-caption">{mode === "tam" ? "Shaded by addressable BESS pipeline" : "Tier coverage by connected sources"}</div></div>;
}

function CouplingChain() {
  const nodes = ["DE", "AT/CH", "IT-N", "IT-S", "GR", "CZ", "SK", "HU", "RO", "BG"];
  return <div className="chain">{nodes.map((n) => <span key={n}>{n}</span>)}<svg viewBox="0 0 900 180" preserveAspectRatio="none"><path d="M70 45 C190 20 240 30 330 55 S500 70 590 85 S720 95 830 120" /><path d="M70 45 C210 100 260 120 350 120 S520 120 610 122 S730 128 830 120" /></svg></div>;
}

function Business() {
  return <div className="page moat-grid"><section className="content"><Panel title="Addressable SDAC market"><EuropeMap mode="tam" /><div className="tam-stats"><strong>46,300 MW</strong><span>addressable BESS pipeline</span><strong>38%</strong><span>Europe ingested in MVP roadmap</span></div></Panel><div className="pricing">{["Per-MW SaaS", "Performance kicker", "Tier-4 network effect"].map((title, i) => <div className="price-card" key={title}><h3>{title}</h3><strong>{["€2k-€6k / MW-year", "5-12% uplift share", "Telemetry premium"][i]}</strong><p>{["Asset owners and operators", "Trading desks and IPPs", "Fleet customers after pilot"][i]}</p><ul><li>Dispatch dashboard</li><li>Backtested value reporting</li><li>Robustness and risk controls</li></ul></div>)}</div><Panel title="Roadmap"><div className="roadmap">{[["30-day", "Live Greek pilot", "Deployed dashboard", "Operator feedback loop"], ["90-day", "Italy + Bulgaria + Romania", "REMIT outage features", "Rolling-horizon MPC"], ["365-day", "Continental coverage", "DAM + intraday + ancillary co-optimization", "Learned terminal-SoC value function"]].map((col) => <div key={col[0]}><h3>{col[0]}</h3>{col.slice(1).map((m) => <p key={m}><Zap size={13} /> {m}</p>)}</div>)}</div></Panel></section><aside className="rail"><h2>Network effect</h2><div className="chart-mid small"><ResponsiveContainer width="100%" height="100%"><LineChart data={[0, 1, 3, 5, 8, 13].map((c, i) => ({ c, public: 58 + i, tier2: 64 + i * 2.2, tier4: 64 + i * i * 1.2 }))}><CartesianGrid stroke="#1F2937" vertical={false} /><XAxis dataKey="c" tick={{ fill: COLORS.faint, fontSize: 10 }} /><YAxis tick={{ fill: COLORS.faint, fontSize: 10 }} /><Tooltip contentStyle={{ background: COLORS.panel, border: `1px solid ${COLORS.border}` }} /><Line dataKey="public" stroke="#64748B" dot={false} /><Line dataKey="tier2" stroke={COLORS.blue} dot={false} /><Line dataKey="tier4" stroke={COLORS.amber} strokeWidth={2.4} dot={false} /></LineChart></ResponsiveContainer></div><Info label="Public data only" value="flat accuracy" /><Info label="Tier-2 multi-country" value="engineering moat" /><Info label="Tier-4 telemetry" value="compounds after customer #1" /></aside></div>;
}

createRoot(document.getElementById("root")).render(<App />);
