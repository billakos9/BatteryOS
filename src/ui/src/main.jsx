import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  BatteryCharging,
  CheckCircle2,
  CircleDollarSign,
  Database,
  Gauge,
  GitBranch,
  LineChart as LineChartIcon,
  Menu,
  Radar,
  ShieldAlert,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
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

function formatEUR(value) {
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(value).replace(/\s/g, "\u202F") + " EUR";
}

function formatDate(isoDate) {
  if (!isoDate) return "from artifact";
  const d = new Date(isoDate + "T00:00:00");
  if (isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function optimizerDisplayName(metadata) {
  return metadata.optimizer_display_name ?? metadata.optimizer_name ?? "Optimizer V1";
}

function emptyDataset() {
  return {
    schedule: [],
    scenarioPanel: [],
    robustness: [],
    metadata: {
      battery_profile: {},
      optimizer: "optimize_dispatch",
      optimizer_display_name: "Optimizer V1",
      solver_status: "Loading",
      expected_profit_eur: 0,
      realized_profit_eur: 0,
      worst_profit_eur: 0,
      rainflow_net_profit_eur: 0,
      rainflow_aging_cost_eur: 0,
      cycles_used: 0,
      scenario_profits_eur: [],
      feasibility: { feasible: true },
    },
  };
}

function withChartFields(schedule, scenarioPanel) {
  let cumulative = 0;
  return schedule.map((row, idx) => {
    const timestamp = row.timestamp ?? "";
    const time = timestamp.includes("T")
      ? timestamp.slice(11, 16)
      : timestamp.split(" ").at(-1)?.slice(0, 5) ?? String(idx);
    const scenariosAtTime = scenarioPanel.filter((item) => item.timestamp === row.timestamp);
    const scenarioPrices = scenariosAtTime.map((item) => Number(item.price_eur_per_mwh)).filter(Number.isFinite);
    const bandLow = scenarioPrices.length ? Math.min(...scenarioPrices) : row.forecast_price_eur_per_mwh;
    const bandHigh = scenarioPrices.length ? Math.max(...scenarioPrices) : row.forecast_price_eur_per_mwh;
    cumulative += Number(row.period_profit_eur ?? 0);
    return {
      ...row,
      idx,
      time,
      bandLow,
      bandHigh,
      realized_price_eur_per_mwh: row.realized_price_eur_per_mwh ?? row.forecast_price_eur_per_mwh,
      dispatchBar: Number(row.discharge_mw ?? 0) > 0 ? row.discharge_mw : -Number(row.charge_mw ?? 0),
      actionLabel: row.action === "CHARGE" ? "C" : row.action === "DISCHARGE" ? "D" : "",
      cumulative_profit_eur: cumulative,
    };
  });
}

function buildScenarioChartData(scenarioPanel) {
  const byTimestamp = new Map();
  for (const row of scenarioPanel) {
    const timestamp = row.timestamp ?? "";
    if (!byTimestamp.has(timestamp)) {
      byTimestamp.set(timestamp, {
        timestamp,
        time: timestamp.includes("T") ? timestamp.slice(11, 16) : timestamp.split(" ").at(-1)?.slice(0, 5) ?? "",
      });
    }
    byTimestamp.get(timestamp)[row.scenario_label] = row.price_eur_per_mwh;
  }
  return Array.from(byTimestamp.values());
}

async function fetchJson(path, fallback) {
  const response = await fetch(path);
  if (!response.ok) return fallback;
  return response.json();
}

async function loadRunArtifacts() {
  const [scheduleRaw, metadata, scenarioPanel, robustness] = await Promise.all([
    fetchJson("/data/schedule.json", []),
    fetchJson("/data/run_metadata.json", {}),
    fetchJson("/data/scenario_panel.json", []),
    fetchJson("/data/robustness_sweep.json", []),
  ]);
  return {
    schedule: withChartFields(scheduleRaw, scenarioPanel),
    scenarioChart: buildScenarioChartData(scenarioPanel),
    scenarioPanel,
    robustness,
    metadata: {
      ...emptyDataset().metadata,
      ...metadata,
      battery_profile: metadata.battery_profile ?? {},
      scenario_profits_eur: metadata.scenario_profits_eur ?? [],
      feasibility: metadata.feasibility ?? { feasible: true },
    },
  };
}

function App() {
  const path = window.location.pathname;
  const initialRoute = path.startsWith("/analytics") ? "analytics" : "dashboard";
  const initialAnalyticsTab = path === "/analytics/forecaster" ? "forecaster" : "optimizer";
  const [route, setRoute] = useState(initialRoute);
  const [analyticsTab, setAnalyticsTab] = useState(initialAnalyticsTab);
  const [profitMode, setProfitMode] = useState("period");
  const [selectedPeriod, setSelectedPeriod] = useState(0);
  const [dataset, setDataset] = useState(emptyDataset);
  const [pendingBatteryProfile, setPendingBatteryProfile] = useState(null);
  const [pendingRiskProfile, setPendingRiskProfile] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    function onKeyDown(event) {
      if (["INPUT", "SELECT", "TEXTAREA"].includes(event.target?.tagName)) return;
      if (event.key === "ArrowRight") setSelectedPeriod((value) => Math.min(95, value + 1));
      if (event.key === "ArrowLeft") setSelectedPeriod((value) => Math.max(0, value - 1));
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadRunArtifacts()
      .then((nextDataset) => {
        if (!cancelled) {
          setDataset(nextDataset);
          setPendingBatteryProfile(null);
          setPendingRiskProfile(null);
        }
      })
      .catch(() => {
        if (!cancelled) setDataset(emptyDataset());
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function rerunOptimizer(batteryProfileName, riskLambda, riskAlpha) {
    setIsRunning(true);
    try {
      const res = await fetch("/api/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          battery_profile_name: batteryProfileName,
          risk_lambda: riskLambda,
          risk_alpha: riskAlpha,
          build_bid_curves: false,
          run_robustness_sweep: true,
        }),
      });
      if (!res.ok) throw new Error("Optimize request failed");
      const next = await loadRunArtifacts();
      setDataset(next);
      setPendingBatteryProfile(null);
      setPendingRiskProfile(null);
    } catch (err) {
      console.error(err);
      alert("Re-run failed. Is the backend server running? (python api/server.py)");
    } finally {
      setIsRunning(false);
    }
  }

  function navigate(next) {
    setRoute(next);
    const pathByRoute = {
      dashboard: "/",
      analytics: analyticsTab === "forecaster" ? "/analytics/forecaster" : "/analytics/optimizer",
    };
    window.history.pushState({}, "", pathByRoute[next] ?? "/");
  }

  function setAnalyticsSubpage(next) {
    setAnalyticsTab(next);
    window.history.pushState({}, "", next === "forecaster" ? "/analytics/forecaster" : "/analytics/optimizer");
  }

  const displayBattery = pendingBatteryProfile ?? dataset.metadata.battery_profile;
  const displayRisk = pendingRiskProfile;

  return (
    <div className={`app ${sidebarOpen ? "" : "sidebar-closed"}`}>
      <Sidebar route={route} navigate={navigate} isOpen={sidebarOpen} onToggle={() => setSidebarOpen((v) => !v)} />
      <main className="shell">
        <TopBar metadata={dataset.metadata} displayBattery={displayBattery} displayRisk={displayRisk} onToggleSidebar={() => setSidebarOpen((v) => !v)} />
        {route === "dashboard" && <Dashboard data={dataset} profitMode={profitMode} setProfitMode={setProfitMode} selectedPeriod={selectedPeriod} />}
        {route === "analytics" && (
          <Analytics
            data={dataset}
            activeTab={analyticsTab}
            setActiveTab={setAnalyticsSubpage}
            onBatteryProfileChange={setPendingBatteryProfile}
            onRiskProfileChange={setPendingRiskProfile}
            onRerun={rerunOptimizer}
            isRunning={isRunning}
          />
        )}
      </main>
    </div>
  );
}

function Sidebar({ route, navigate, isOpen, onToggle }) {
  const items = [
    ["dashboard", "Dashboard", LineChartIcon],
    ["analytics", "Analytics", Database],
  ];
  return (
    <aside className={`sidebar ${isOpen ? "" : "collapsed"}`}>
      <div className="sidebar-header">
        <div className="brand"><BatteryCharging size={22} /><span>BatteryOS</span></div>
        <button className="sidebar-toggle" onClick={onToggle} title={isOpen ? "Collapse sidebar" : "Expand sidebar"}>
          {isOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>
      <nav>
        {items.map(([key, label, Icon]) => (
          <button key={key} onClick={() => navigate(key)} className={`nav-item ${route === key ? "active" : ""}`}>
            <Icon size={17} /> {isOpen && <span>{label}</span>}
          </button>
        ))}
      </nav>
      {isOpen && (
        <div className="sidebar-foot">
          <span>Implemented backend</span>
          <strong>HEnEx DAM optimizer</strong>
        </div>
      )}
    </aside>
  );
}

function TopBar({ metadata, displayBattery, displayRisk, onToggleSidebar }) {
  const metaBattery = metadata.battery_profile ?? {};
  const battery = displayBattery ?? metaBattery;

  // Look up friendly label for the battery profile
  const batteryEntry = BATTERY_PROFILES.find((p) => p.name === battery.name);
  const batteryLabel = batteryEntry?.label ?? battery.name ?? metaBattery.name ?? "from backend";
  const isBatteryPending = displayBattery && displayBattery.name !== metaBattery.name;

  // Look up friendly risk label
  const riskEntry = displayRisk
    ? RISK_PROFILES.find((p) => p.name === displayRisk.name)
    : null;
  const riskLabel = riskEntry ? ` · ${riskEntry.name}` : "";

  return (
    <header className="topbar">
      <button className="topbar-menu-btn" onClick={onToggleSidebar} title="Toggle sidebar">
        <Menu size={18} />
      </button>
      <div className="market-pill">
        <span>Market</span>
        <strong>Greek HEnEx DAM</strong>
      </div>
      <div className={`market-pill ${isBatteryPending ? "pending" : ""}`}>
        <span>Battery profile</span>
        <strong>{batteryLabel}</strong>
      </div>
      <div className="control readonly">
        <span>Delivery day</span>
        <strong>{formatDate(metadata.delivery_day)}</strong>
      </div>
      <div className="optimizer-pill">
        <span>Optimizer</span>
        <strong>{optimizerDisplayName(metadata)}{riskLabel}</strong>
      </div>
    </header>
  );
}

function Dashboard({ data, profitMode, setProfitMode, selectedPeriod }) {
  const { schedule, metadata } = data;
  if (!schedule.length) {
    return <div className="page"><Panel title="Loading run artifacts"><p className="caption">Fetching schedule, metadata, scenarios and robustness from /data.</p></Panel></div>;
  }
  return (
    <div className="page dashboard-grid">
      <section className="content">
        <div className="kpis">
          <Kpi title="Expected profit" value={formatEUR(metadata.expected_profit_eur)} sub="objective schedule value" icon={CircleDollarSign} />
          <Kpi title="Realized evaluation" value={formatEUR(metadata.realized_profit_eur)} sub="using realized DAM prices when available" icon={Gauge} />
          <Kpi title="Worst-case profit" value={formatEUR(metadata.worst_profit_eur)} sub="scenario / robustness lower bound" icon={ShieldAlert} />
          <Kpi title="Cycles used" value={`${metadata.cycles_used} / ${metadata.battery_profile.max_cycles_per_day}`} sub={<Progress value={metadata.cycles_used / metadata.battery_profile.max_cycles_per_day} />} icon={Activity} />
          <Kpi title="Rainflow net profit" value={formatEUR(metadata.rainflow_net_profit_eur)} sub={`${formatEUR(metadata.rainflow_aging_cost_eur)} algorithmic aging cost`} icon={GitBranch} />
        </div>
        <Panel title="Live dispatch" action={<span className="caption">Selected {schedule[selectedPeriod]?.time} · 96 quarter-hour MTUs</span>}>
          <div className="chart-large">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={schedule} margin={{ top: 20, right: 40, left: 0, bottom: 20 }}>
                <CartesianGrid stroke="#1F2937" vertical={false} />
                <XAxis dataKey="time" tick={{ fill: COLORS.faint, fontSize: 11 }} interval={7} axisLine={false} tickLine={false} />
                <YAxis yAxisId="price" tick={{ fill: COLORS.faint, fontSize: 11 }} axisLine={false} tickLine={false} label={{ value: "EUR/MWh", angle: -90, fill: COLORS.faint, position: "insideLeft" }} />
                <YAxis yAxisId="mw" orientation="right" tick={{ fill: COLORS.faint, fontSize: 11 }} axisLine={false} tickLine={false} label={{ value: "MW", angle: 90, fill: COLORS.faint, position: "insideRight" }} />
                <Tooltip content={<DispatchTooltip />} />
                <Area yAxisId="price" type="monotone" dataKey="bandHigh" stroke="none" fill="#6B7280" fillOpacity={0.13} />
                <Area yAxisId="price" type="monotone" dataKey="bandLow" stroke="none" fill={COLORS.bg} fillOpacity={1} />
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
      </section>
      <RunSummary data={data} />
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

function RunSummary({ data }) {
  const { metadata } = data;
  const profits = metadata.scenario_profits_eur ?? [];
  const worstProfit = Math.min(...profits);
  const rows = profits.slice(0, 5).map((profit, i) => ({
    label: metadata.scenario_labels?.[i] ?? `s${i}`,
    weight: metadata.scenario_weights?.[i] ?? 0,
    profit,
  }));
  return <aside className="rail"><h2>Run summary</h2><Info label="Optimizer" value={optimizerDisplayName(metadata)} /><Info label="Backend entrypoint" value={metadata.optimizer} /><Info label="Risk setting" value={`${metadata.risk_setting} · λ ${metadata.cvar_lambda}`} /><Info label="Battery" value={metadata.battery_profile.name} /><Info label="Power / energy" value={`${metadata.battery_profile.power_mw} MW / ${metadata.battery_profile.energy_mwh} MWh`} /><Info label="η round-trip" value={`${Math.round(metadata.battery_profile.eta_rt * 100)}%`} /><Info label="Solver" value={`${metadata.solver_status} · ${metadata.runtime_ms} ms`} /><Info label="Scenarios" value={metadata.scenarios_used} /><Info label="Objective" value={formatEUR(metadata.objective_value_eur)} /><div className="feasible"><CheckCircle2 size={16} /> Feasible</div><div className="scenario-table"><h3>Scenario profits sample</h3>{rows.map((r) => <div key={r.label} className={r.profit === worstProfit ? "tail" : ""}><span>{r.label}</span><span>{Math.round(r.weight * 100)}%</span><strong>{formatEUR(r.profit)}</strong></div>)}</div><button className="rerun"><SlidersHorizontal size={15} /> Re-run with different parameters</button></aside>;
}

function Info({ label, value }) {
  return <div className="info"><span>{label}</span><strong>{value}</strong></div>;
}

function DispatchTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return <div className="tooltip"><strong>{r.timestamp}</strong><span>expected {Number(r.forecast_price_eur_per_mwh).toFixed(2)} EUR/MWh</span><span>scenario range {Number(r.bandLow).toFixed(2)} / {Number(r.bandHigh).toFixed(2)}</span><span>realized {Number(r.realized_price_eur_per_mwh).toFixed(2)}</span><span>charge/discharge {r.charge_mw} / {r.discharge_mw} MW</span><span>SoC {r.state_of_charge_mwh} MWh</span><span>profit {formatEUR(r.period_profit_eur)}</span></div>;
}
function SimpleTooltip({ active, payload }) { if (!active || !payload?.length) return null; const r = payload[0].payload; return <div className="tooltip"><strong>{r.time}</strong><span>SoC {r.state_of_charge_mwh} MWh</span></div>; }
function ProfitTooltip({ active, payload }) { if (!active || !payload?.length) return null; const r = payload[0].payload; return <div className="tooltip"><strong>{r.time}</strong><span>period {formatEUR(r.period_profit_eur)}</span><span>cumulative {formatEUR(r.cumulative_profit_eur)}</span></div>; }

function Analytics({ data, activeTab, setActiveTab, onBatteryProfileChange, onRiskProfileChange, onRerun, isRunning }) {
  return (
    <div className="page content">
      <Panel title="Analytics" action={<span className="caption">Framework subsystems</span>}>
        <div className="subpage-tabs">
          <button className={activeTab === "forecaster" ? "active" : ""} onClick={() => setActiveTab("forecaster")}>
            <LineChartIcon size={16} /> Forecaster
          </button>
          <button className={activeTab === "optimizer" ? "active" : ""} onClick={() => setActiveTab("optimizer")}>
            <BatteryCharging size={16} /> Optimizer V1
          </button>
        </div>
      </Panel>
      {activeTab === "forecaster" ? (
        <ForecasterPlaceholder />
      ) : (
        <OptimizerAnalytics
          data={data}
          embedded
          onBatteryProfileChange={onBatteryProfileChange}
          onRiskProfileChange={onRiskProfileChange}
          onRerun={onRerun}
          isRunning={isRunning}
        />
      )}
    </div>
  );
}

function ForecasterPlaceholder() {
  return (
    <div className="analytics-grid">
      <section className="content">
        <Panel title="Forecaster">
          <div className="artifact-note">
            <LineChartIcon size={18} />
            <div>
              <strong>Not implemented yet</strong>
              <p>The forecaster will later own raw market data, feature engineering, model training, and price scenario generation. This page intentionally shows no fake curves or fake metrics.</p>
            </div>
          </div>
        </Panel>
      </section>
      <aside className="rail">
        <h2>Forecaster contract</h2>
        <ul className="judge-list">
          <li>Forecasting is separate from Optimizer V1.</li>
          <li>When implemented, it should export `PriceScenarios`.</li>
          <li>Optimizer V1 can already consume externally provided scenarios.</li>
        </ul>
        <Info label="Status" value="Not implemented" />
        <Info label="Future output" value="PriceScenarios" />
      </aside>
    </div>
  );
}

const BATTERY_PROFILES = [
  {
    name: "liion_100_2h",
    label: "Li-Ion 100 MW / 2 h",
    tech: "Lithium-Ion",
    description: "100 MW / 200 MWh lithium-ion system. Typical 2-hour BESS with 90% round-trip efficiency.",
  },
  {
    name: "liion_200_2h",
    label: "Li-Ion 200 MW / 2 h",
    tech: "Lithium-Ion",
    description: "200 MW / 400 MWh lithium-ion system. Large-scale 2-hour BESS.",
  },
  {
    name: "liion_300_2h",
    label: "Li-Ion 300 MW / 2 h",
    tech: "Lithium-Ion",
    description: "300 MW / 600 MWh lithium-ion system. Utility-scale 2-hour BESS.",
  },
  {
    name: "phs_100_8h",
    label: "Pumped Hydro 100 MW / 8 h",
    tech: "Pumped Hydro",
    description: "100 MW / 800 MWh pumped-hydro storage. Long-duration, lower efficiency, very low degradation cost.",
  },
  {
    name: "phs_200_8h",
    label: "Pumped Hydro 200 MW / 8 h",
    tech: "Pumped Hydro",
    description: "200 MW / 1,600 MWh pumped-hydro storage. Large long-duration asset.",
  },
  {
    name: "flow_100_6h",
    label: "Flow 100 MW / 6 h",
    tech: "Vanadium Flow",
    description: "100 MW / 600 MWh vanadium flow battery. 6-hour duration with high cycle tolerance.",
  },
  {
    name: "custom",
    label: "Custom battery",
    tech: "User-defined",
    description: "Define your own power, energy, efficiency and SoC limits via the backend API.",
  },
];

const RISK_PROFILES = [
  {
    name: "Risk Neutral",
    lambda: 0.0,
    alpha: 0.10,
    description:
      "Maximises expected profit only. Best when you have high risk tolerance and can absorb occasional bad days.",
  },
  {
    name: "Balanced",
    lambda: 0.5,
    alpha: 0.10,
    description:
      "Equal weight on expected profit and tail protection. A good default for most battery operators.",
  },
  {
    name: "Tail Defensive",
    lambda: 0.7,
    alpha: 0.10,
    description:
      "Prioritises protecting against worst-case scenarios. Useful when a single bad day hurts your P&L badly.",
  },
  {
    name: "Worst-Case",
    lambda: 1.0,
    alpha: 0.10,
    description:
      "Pure CVaR optimisation. Maximises the profit you make in the worst tail of the scenario set.",
  },
];

function OptimizerAnalytics({ data }) {
  const { schedule, metadata, robustness, scenarioChart, scenarioPanel } = data;
  const [selectedBatteryProfile, setSelectedBatteryProfile] = useState(
    BATTERY_PROFILES.find((p) => p.name === (metadata.battery_profile?.name ?? "liion_100_2h")) ?? BATTERY_PROFILES[0]
  );
  const [selectedProfile, setSelectedProfile] = useState(
    RISK_PROFILES.find((p) => Math.abs(p.lambda - (metadata.cvar_lambda ?? 0.5)) < 0.15) ?? RISK_PROFILES[1]
  );

  if (!schedule.length) {
    return <div className="page"><Panel title="Loading optimizer artifacts"><p className="caption">Fetching backend output artifacts from /data.</p></Panel></div>;
  }
  const scenarioRows = scenarioPanel.slice(0, 10).map((r) => ({
    time: r.timestamp?.slice(11, 16) ?? "",
    scenario: r.scenario_label,
    weight: `${Math.round(r.scenario_weight * 100)}%`,
    price: Number(r.price_eur_per_mwh).toFixed(2),
  }));
  const outputRows = schedule.filter((_, i) => i % 8 === 0).slice(0, 8).map((r) => ({
    time: r.time,
    price: Number(r.forecast_price_eur_per_mwh).toFixed(2),
    charge: Number(r.charge_mw).toFixed(1),
    discharge: Number(r.discharge_mw).toFixed(1),
    soc: Number(r.state_of_charge_mwh).toFixed(1),
    action: r.action,
  }));
  const waterfall = [
    { name: "Expected profit", value: metadata.expected_profit_eur, fill: COLORS.green },
    { name: "Rainflow aging", value: -metadata.rainflow_aging_cost_eur, fill: COLORS.red },
    { name: "Net profit", value: metadata.rainflow_net_profit_eur, fill: COLORS.amber },
  ];

  return (
    <div className="page workflow-page">
      <section className="workflow-main">
        <Panel title="Optimizer V1 workflow" action={<span className="caption">Scroll through the backend process from input to result</span>}>
          <div className="workflow-intro">
            <BatteryCharging size={22} />
            <div>
              <strong>What this page shows</strong>
              <p>Optimizer V1 does not forecast prices. It receives external `PriceScenarios` plus a `BatteryProfile`, solves a constrained dispatch problem, then reports schedule, economics, degradation, feasibility and robustness artifacts.</p>
            </div>
          </div>
        </Panel>

        <WorkflowStepSection
          number="01"
          icon={LineChartIcon}
          title="External PriceScenarios input"
          description="The optimizer starts from a scenario bundle produced outside this module. This demo artifact uses the validated 20-scenario input draft: each line is one full 96-period price path with its own probability weight."
          consumes="PriceScenarios: timestamps, prices[S,T], weights[S], labels[S]"
          produces="Expected price curve used by Optimizer V1"
        >
          <div className="stacked-visual">
            <ScenarioChart scenarioChart={scenarioChart} labels={metadata.scenario_labels ?? []} />
            <ScenarioInputTable rows={scenarioRows} />
          </div>
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="02"
          icon={BatteryCharging}
          title="Battery profile and constraints"
          description="The optimizer combines the scenario prices with the selected asset limits: power, energy, state-of-charge bounds, efficiency and maximum daily cycles. These constraints define what actions are physically possible."
          consumes="BatteryProfile"
          produces="Feasible action space"
        >
          <div className="profile-controls">
            <label className="profile-label">Select battery profile</label>
            <select
              className="profile-select"
              value={selectedBatteryProfile.name}
              onChange={(e) => {
                const p = BATTERY_PROFILES.find((x) => x.name === e.target.value) ?? BATTERY_PROFILES[0];
                setSelectedBatteryProfile(p);
              }}
            >
              {BATTERY_PROFILES.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.label}
                </option>
              ))}
            </select>
            <p className="profile-caption">{selectedBatteryProfile.description}</p>
          </div>
          <div className="spec-grid">
            <Info label="Battery" value={metadata.battery_profile.name} />
            <Info label="Power" value={`${metadata.battery_profile.power_mw} MW`} />
            <Info label="Energy" value={`${metadata.battery_profile.energy_mwh} MWh`} />
            <Info label="SoC band" value={`${metadata.battery_profile.soc_min_mwh} - ${metadata.battery_profile.soc_max_mwh} MWh`} />
            <Info label="Round-trip efficiency" value={`${Math.round(metadata.battery_profile.eta_rt * 100)}%`} />
            <Info label="Max cycles/day" value={metadata.battery_profile.max_cycles_per_day} />
          </div>
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="03"
          icon={ShieldAlert}
          title="Mean-CVaR objective"
          description="Optimizer V1 balances expected profit against downside risk. The CVaR term penalizes schedules that make weak profit in the bad tail of the scenario set."
          consumes="Scenario profits across all weighted scenarios"
          produces="Risk-aware objective value"
        >
          <div className="profile-controls">
            <label className="profile-label">Select risk profile (λ)</label>
            <select
              className="profile-select"
              value={selectedProfile.name}
              onChange={(e) => {
                const p = RISK_PROFILES.find((x) => x.name === e.target.value) ?? RISK_PROFILES[1];
                setSelectedProfile(p);
              }}
            >
              {RISK_PROFILES.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} (λ = {p.lambda})
                </option>
              ))}
            </select>
            <p className="profile-caption">{selectedProfile.description}</p>
          </div>

          <div className="spec-grid">
            <Info label="Expected profit" value={formatEUR(metadata.expected_profit_eur)} />
            <Info label={`CVaR_${metadata.cvar_alpha}`} value={formatEUR(metadata.cvar_eur)} />
            <Info label="Risk lambda" value={metadata.cvar_lambda} />
            <Info label="Worst scenario profit" value={formatEUR(metadata.worst_profit_eur)} />
          </div>

          <div className="metric-explanations">
            <h4>What these metrics mean</h4>
            <div className="explanation-grid">
              <div className="explanation-item">
                <strong>Expected Profit</strong>
                <p>
                  The weighted-average profit across all scenario price paths. This is the profit you would earn on a statistically typical day.
                </p>
              </div>
              <div className="explanation-item">
                <strong>CVaR (Conditional Value at Risk)</strong>
                <p>
                  The average profit in the worst α-fraction of scenarios. Here α = 0.1 means it measures the average of the worst 10% of days. It tells you how bad things get when prices move against you.
                </p>
              </div>
              <div className="explanation-item">
                <strong>Risk Lambda (λ)</strong>
                <p>
                  The convex weight blending expected profit and CVaR. λ = 0 is purely risk-neutral (only average profit matters). λ = 1 is purely tail-defensive (only the worst-case tail matters). λ = 0.5 gives equal weight to both.
                </p>
              </div>
              <div className="explanation-item">
                <strong>Worst Scenario Profit</strong>
                <p>
                  The single lowest profit across all scenarios. This is the absolute worst day in the entire scenario set.
                </p>
              </div>
            </div>
          </div>
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="04"
          icon={BatteryCharging}
          title="Dispatch schedule"
          description="The solver decides charge, discharge or idle for every 15-minute market time unit. Charge bars go below zero, discharge bars go above zero, and the SoC line shows the physical battery state through time."
          consumes="PriceScenarios + BatteryProfile + risk objective"
          produces="schedule: charge_mw, discharge_mw, state_of_charge_mwh, action"
        >
          <OptimizerDispatchChart schedule={schedule} />
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="05"
          icon={CheckCircle2}
          title="Feasibility check"
          description="After optimization, the schedule is checked against battery dynamics and hard limits. This confirms that the result is not only profitable, but physically executable."
          consumes="Schedule + BatteryProfile"
          produces="FeasibilityReport"
        >
          <div className="spec-grid">
            <Info label="Feasible" value={metadata.feasibility?.feasible ? "True" : "False"} />
            <Info label="Solver status" value={metadata.solver_status} />
            <Info label="Runtime" value={`${metadata.runtime_ms} ms`} />
            <Info label="Cycles used" value={`${metadata.cycles_used} / ${metadata.battery_profile.max_cycles_per_day}`} />
          </div>
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="06"
          icon={CircleDollarSign}
          title="Economic scoring"
          description="The resulting actions are converted into money: discharge earns revenue, charge pays market cost, and the run reports expected and realized economic performance."
          consumes="Schedule + price curve"
          produces="period_profit_eur and realized_profit_eur"
        >
          <div className="chart-mid analytics-focus">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={schedule} margin={{ top: 14, right: 16, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="#1F2937" vertical={false} />
                <XAxis dataKey="time" interval={15} tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ProfitTooltip />} />
                <Bar dataKey="period_profit_eur" barSize={5}>{schedule.map((r) => <Cell key={r.idx} fill={r.period_profit_eur >= 0 ? "#16A34A" : COLORS.red} fillOpacity={0.72} />)}</Bar>
                <Line dataKey="cumulative_profit_eur" stroke={COLORS.text} dot={false} strokeWidth={1.8} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="07"
          icon={Activity}
          title="Rainflow degradation"
          description="The optimizer output is then scored with a cycle-depth-aware degradation algorithm. This uses the SoC trajectory to estimate aging cost instead of pretending degradation is only a static input."
          consumes="Schedule SoC trajectory"
          produces="RainflowScore"
        >
          <DegradationView waterfall={waterfall} />
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="08"
          icon={ShieldAlert}
          title="Robustness sweep"
          description="The fixed schedule is replayed under different battery assumptions. This answers: how bad is the profit if efficiency or degradation assumptions are wrong?"
          consumes="Schedule + perturbed BatteryProfile assumptions"
          produces="ParameterSweepResult"
        >
          <RobustnessChart robustness={robustness} />
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="09"
          icon={GitBranch}
          title="Bid curves"
          description="When bid output is enabled, the backend can re-solve across candidate clearing prices to produce a HEnEx-style price-quantity ladder."
          consumes="Expected price curve + BatteryProfile"
          produces="bid_curves artifact"
        >
          <div className="artifact-note">
            <GitBranch size={18} />
            <div>
              <strong>Bid curves artifact</strong>
              <p>The backend can export `bid_curves.parquet/json` when bid output is enabled. This viewer does not invent bid quantities; it waits for that artifact.</p>
            </div>
          </div>
        </WorkflowStepSection>

        <div className="step-connector"><ArrowDownToLine size={18} /></div>

        <WorkflowStepSection
          number="10"
          icon={Radar}
          title="DispatchResult output"
          description="The final result bundle is what the dashboard visualizes: schedule, scenarios, bid curves, rainflow score, feasibility, robustness and metadata."
          consumes="All optimizer sub-results"
          produces="DispatchResult"
        >
          <OptimizerOutputTable rows={outputRows} />
        </WorkflowStepSection>
      </section>

      <aside className="rail workflow-rail">
        <h2>Reading guide</h2>
        <ul className="judge-list">
          <li>Scroll top to bottom.</li>
          <li>Each section shows one backend responsibility.</li>
          <li>No forecasting model is shown here.</li>
          <li>Everything visualized is an Optimizer V1 input or output artifact.</li>
        </ul>
        <Info label="Backend entrypoint" value={metadata.optimizer} />
        <Info label="Result object" value="DispatchResult" />
        <Info label="Scenario count" value={metadata.scenarios_used} />
      </aside>
    </div>
  );
}

function WorkflowStepSection({ number, icon: Icon, title, description, consumes, produces, children }) {
  return (
    <section className="workflow-section">
      <div className="workflow-copy">
        <span className="workflow-number">{number}</span>
        <Icon size={18} />
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
          <div className="io-grid">
            <Info label="Consumes" value={consumes} />
            <Info label="Produces" value={produces} />
          </div>
        </div>
      </div>
      <div className="workflow-visual">{children}</div>
    </section>
  );
}

function ScenarioChart({ scenarioChart, labels }) {
  const colorFor = (idx) => [
    COLORS.blue,
    COLORS.amber,
    COLORS.green,
    COLORS.teal,
    COLORS.purple,
    COLORS.cyan,
    "#94A3B8",
    "#F97316",
  ][idx % 8];
  return (
    <div className="chart-mid analytics-focus">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={scenarioChart} margin={{ top: 14, right: 16, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="#1F2937" vertical={false} />
          <XAxis dataKey="time" interval={15} tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={{ background: COLORS.panel, border: `1px solid ${COLORS.border}` }} />
          {labels.map((label, idx) => (
            <Line key={label} dataKey={label} stroke={colorFor(idx)} strokeOpacity={0.38} strokeWidth={1.2} dot={false} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function OptimizerDispatchChart({ schedule }) {
  return (
    <div className="chart-mid analytics-focus">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={schedule} margin={{ top: 14, right: 16, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="#1F2937" vertical={false} />
          <XAxis dataKey="time" interval={15} tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis yAxisId="mw" tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis yAxisId="soc" orientation="right" tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
          <Tooltip content={<DispatchTooltip />} />
          <Bar yAxisId="mw" dataKey="dispatchBar" barSize={5}>{schedule.map((r) => <Cell key={r.idx} fill={r.dispatchBar < 0 ? COLORS.blue : COLORS.amber} fillOpacity={0.75} />)}</Bar>
          <Line yAxisId="soc" dataKey="state_of_charge_mwh" stroke={COLORS.text} strokeWidth={1.8} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function DegradationView({ waterfall }) {
  return (
    <div className="value-grid">
      <div className="value-flow">
        {["Schedule SoC", "rainflow_count", "aging cost", "net profit"].map((label, i) => (
          <React.Fragment key={label}>
            <span className={i === 1 ? "blue" : i === 3 ? "amber" : ""}>{label}</span>
            {i < 3 && <ArrowDownToLine size={15} />}
          </React.Fragment>
        ))}
      </div>
      <div className="chart-mid compact">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={waterfall} margin={{ top: 12, right: 12, left: -18, bottom: 0 }}>
            <CartesianGrid stroke="#1F2937" vertical={false} />
            <XAxis dataKey="name" tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip formatter={(value) => formatEUR(value)} contentStyle={{ background: COLORS.panel, border: `1px solid ${COLORS.border}` }} />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>{waterfall.map((r) => <Cell key={r.name} fill={r.fill} fillOpacity={0.82} />)}</Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function RobustnessChart({ robustness }) {
  return (
    <div className="chart-mid analytics-focus">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={robustness.slice(0, 16)} margin={{ top: 14, right: 16, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="#1F2937" vertical={false} />
          <XAxis dataKey="round_trip_efficiency" tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: COLORS.faint, fontSize: 10 }} axisLine={false} tickLine={false} />
          <Tooltip formatter={(value) => formatEUR(value)} contentStyle={{ background: COLORS.panel, border: `1px solid ${COLORS.border}` }} />
          <Bar dataKey="realized_profit_eur" fill={COLORS.amber} fillOpacity={0.78} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ScenarioInputTable({ rows }) {
  return (
    <div className="feature-matrix scenario-input-table">
      <div className="matrix-head"><span>MTU</span><span>Scenario</span><span>Weight</span><span>Price</span></div>
      {rows.map((r) => (
        <div key={`${r.time}-${r.scenario}`} className="matrix-row">
          <span>{r.time}</span><span>{r.scenario}</span><span>{r.weight}</span><span>{r.price}</span>
        </div>
      ))}
    </div>
  );
}

function OptimizerOutputTable({ rows }) {
  return (
    <div className="feature-matrix optimizer-output-table">
      <div className="matrix-head"><span>MTU</span><span>Expected price</span><span>Charge</span><span>Discharge</span><span>SoC</span><span>Action</span></div>
      {rows.map((r) => (
        <div key={r.time} className="matrix-row">
          <span>{r.time}</span><span>{r.price}</span><span>{r.charge}</span><span>{r.discharge}</span><span>{r.soc}</span><span>{r.action}</span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
