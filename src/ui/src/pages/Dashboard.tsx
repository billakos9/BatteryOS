import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, KPI, Tag, Icon, Legend } from "@/components/bos/Primitives";
import { Spark, DispatchChart, ProfitChart, BatteryGauge } from "@/components/bos/Charts";
import { fmtEur } from "@/lib/dispatch";
import { useBosStore } from "@/lib/store";
import { artifactsToDispatchView, fetchBackendArtifacts, type BackendArtifacts } from "@/lib/backend";
import WorkflowDiagram from "@/components/bos/WorkflowDiagram";

const emptyArtifacts: BackendArtifacts = {
  schedule: [],
  scenario_panel: [],
  run_metadata: {},
  robustness_sweep: [],
};

const ATHENS_TZ = "Europe/Athens";

// Placeholder asset used only while /api/batteries is in flight.
// All real numbers come from the backend; this just keeps the early
// render from dereferencing `undefined`.
const PLACEHOLDER_ASSET = {
  id: "—",
  tech: "Li-Ion" as const,
  power: 0,
  energy: 0,
  eff: 1,
  socMinPct: 0,
  socMaxPct: 1,
  cyclesPerDay: 0,
  agingCost: 0,
  status: "active" as const,
  utilization: 0,
};

export default function PageDashboard() {
  const navigate = useNavigate();
  const { assets, selectedAssetId, optimizer, setSelectedAsset } = useBosStore();
  const asset =
    assets.find((a) => a.id === selectedAssetId) ?? assets[0] ?? PLACEHOLDER_ASSET;
  const [artifacts, setArtifacts] = useState<BackendArtifacts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const result = useMemo(() => artifactsToDispatchView(artifacts ?? emptyArtifacts), [artifacts]);
  const realizedProfit = Number(artifacts?.run_metadata.realized_profit_eur ?? result.expected);
  const realizedVsExpectedPct = result.expected !== 0 ? (realizedProfit / result.expected) * 100 : 0;
  const lastDeliveryDay = artifacts?.run_metadata.delivery_day ?? "latest settled day";
  const data = {
    realized: result.realized,
    forecast: result.forecast,
    p10: result.p10,
    p90: result.p90,
    charge: result.charge,
    discharge: result.discharge,
    soc: result.soc,
  };
  const athensNow = useMemo(() => getAthensDate(now), [now]);
  const headerTimestamp = useMemo(() => formatAthensHeader(athensNow), [athensNow]);
  const gateCloseCountdown = useMemo(() => formatGateCloseCountdown(athensNow, optimizer.gateCloseHour), [athensNow, optimizer.gateCloseHour]);

  useEffect(() => {
    if (!asset.id || asset.id === "—") return;
    let cancelled = false;
    setArtifacts(null);
    fetchBackendArtifacts(asset.id)
      .then((next) => {
        if (!cancelled) {
          setArtifacts(next);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [asset.id]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!pickerOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setPickerOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [pickerOpen]);

  return (
    <div>
      <div className="mb-6 flex items-end gap-6 border-b border-line pb-5">
        <div>
          <div className="eyebrow mb-2">Operations · {headerTimestamp}</div>
          <h1 className="h-display">Dispatch <em>at a glance</em></h1>
          <div className="mt-2 max-w-[64ch] text-[13px] text-fg-2">
            Review of the last settled delivery day: realized prices, submitted schedule, battery state and realized economics.
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="bos-pill"><span className="dot" />LIVE · gate close {gateCloseCountdown}</div>
          <button className="bos-btn"><Icon name="refresh" size={12} />Refresh</button>
          <button className="bos-btn primary" onClick={() => navigate("/optimizer")}><Icon name="play" size={12} />Run optimizer</button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2 rounded border border-line bg-bg-2 px-3 py-2">
        <span className="eyebrow">Asset</span>
        <div ref={pickerRef} className="relative">
          <button
            type="button"
            className="bos-btn sm primary"
            onClick={() => setPickerOpen((v) => !v)}
            title={`${asset.tech} · ${asset.power} MW / ${asset.energy} MWh`}
          >
            <Icon name={asset.tech === "Pumped Hydro" || asset.tech === "Vanadium Flow" ? "flow" : "battery"} size={11} />
            <span className="font-mono-tnum text-[10px]">{asset.id}</span>
            <Icon name="chevD" size={10} />
          </button>
          {pickerOpen && (
            <div
              className="absolute left-0 top-full z-20 mt-1 min-w-[260px] rounded border border-line bg-bg-1 py-1 shadow-lg"
              role="listbox"
            >
              {assets.length === 0 && (
                <div className="px-3 py-2 font-mono-tnum text-[10px] text-fg-3">No assets loaded</div>
              )}
              {assets.map((a) => {
                const active = a.id === asset.id;
                return (
                  <button
                    key={a.id}
                    type="button"
                    role="option"
                    aria-selected={active}
                    onClick={() => {
                      setSelectedAsset(a.id);
                      setPickerOpen(false);
                    }}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-bg-2 ${active ? "bg-bg-2" : ""}`}
                  >
                    <Icon name={a.tech === "Pumped Hydro" || a.tech === "Vanadium Flow" ? "flow" : "battery"} size={11} />
                    <span className="font-mono-tnum text-[11px] text-fg-0">{a.id}</span>
                    <span className="ml-auto font-mono-tnum text-[10px] text-fg-3">
                      {a.tech} · {a.power} MW / {a.energy} MWh
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {!artifacts && !error && asset.id !== "—" && (
        <div className="mb-4 font-mono-tnum text-[11px] text-fg-3">
          Loading dispatch for {asset.id}…
        </div>
      )}

      {error && (
        <div className="bos-callout mb-4 border-red/40 text-red">
          Could not load dispatch results: {error}
        </div>
      )}

      <div className="mb-4 grid grid-cols-4 gap-4">
        <KPI featured label="Next delivery day expected" value={fmtEur(result.expected)} unit="EUR"
          delta={{ tone: "up", text: "ex-ante DAM schedule profit" }}
          spark={<Spark values={result.cumProfit} color="hsl(var(--acc))" fill />} />
        <KPI label="Previous day realization" value={realizedVsExpectedPct.toFixed(1)} unit="%"
          delta={{ tone: realizedVsExpectedPct >= 100 ? "up" : "neu", text: `${fmtEur(realizedProfit)} realized vs previous expected` }}
          spark={<Spark values={result.cumProfit.slice(0, 52)} color="hsl(var(--amber))" />} />
        <KPI label="Risk profile" value={result.riskProfileLabel}
          delta={{ tone: "neu", text: `λ=${result.riskLambda.toFixed(2)} · α=${result.riskAlpha.toFixed(2)}` }} />
        <KPI label="Cycles used" value={result.cyclesUsed.toFixed(2)} unit={`/ ${result.cyclesCap.toFixed(1)} cap`}
          delta={{ tone: "up", text: `aging ${fmtEur(result.agingCostTotal)}` }}
          spark={<Spark values={result.soc} color="hsl(var(--blue))" />} />
      </div>

      <div className="mb-4 grid grid-cols-12 gap-4">
        <div className="col-span-8">
          <Card
            title="Last day diagram"
            meta={`${lastDeliveryDay} · ${asset.id} · ${asset.power} MW / ${asset.energy} MWh · η ${(asset.eff * asset.eff * 100).toFixed(1)}%`}
          >
            <DispatchChart data={data} height={300} showSoc showForecast />
            <div className="mt-3 flex flex-wrap gap-4 border-t border-line pt-3">
              <Legend items={[
                { color: "hsl(var(--blue))", label: "Realized price" },
                { color: "hsl(var(--magenta))", label: "Forecast (p50)", dashed: true },
                { color: "hsl(var(--acc))", label: "Charge", bar: true },
                { color: "hsl(var(--amber))", label: "Discharge", bar: true },
                { color: "hsl(var(--acc))", label: "State of charge" },
              ]} />
              <div className="ml-auto font-mono-tnum text-[10px] text-fg-3">96 quarter-hourly periods</div>
            </div>
          </Card>
        </div>

        <div className="col-span-4 grid gap-4" style={{ gridTemplateRows: "auto auto" }}>
          <Card title="Last day battery state" meta={lastDeliveryDay}>
            <div className="flex items-center gap-4">
              <BatteryGauge socMWh={result.soc[28]} energyMWh={asset.energy} />
              <div className="flex-1">
                <Row k="SoC" v={<>{result.soc[28].toFixed(1)} <span className="text-[10px] text-fg-3">MWh</span></>} />
                <Row k="Action" v={<Tag tone="amber" dot>DISCHARGE</Tag>} />
                <Row k="Power" v={<>{asset.power.toFixed(1)} <span className="text-[10px] text-fg-3">MW</span></>} />
                <Row k="Period" v="07:30–07:45" last />
              </div>
            </div>
          </Card>
          <Card title="Last day profit path" meta="cumulative + per-period">
            <ProfitChart periodProfit={result.periodProfit} cumProfit={result.cumProfit} height={200} />
          </Card>
        </div>
      </div>

      <div className="mt-4">
        <WorkflowDiagram />
      </div>

    </div>
  );
}

function Row({ k, v, last }: { k: string; v: React.ReactNode; last?: boolean }) {
  return (
    <div className="grid items-center gap-4 py-1.5" style={{ gridTemplateColumns: "1fr auto", borderBottom: last ? "none" : "1px dashed hsl(var(--line))" }}>
      <span className="font-mono-tnum text-[11px] text-fg-2">{k}</span>
      <span className="font-mono-tnum text-[13px] text-fg-0">{v}</span>
    </div>
  );
}

function getAthensDate(now: Date): Date {
  return new Date(now.toLocaleString("en-US", { timeZone: ATHENS_TZ }));
}

function formatAthensHeader(date: Date): string {
  const day = date.toLocaleDateString("en-GB", {
    timeZone: ATHENS_TZ,
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const time = date.toLocaleTimeString("en-GB", {
    timeZone: ATHENS_TZ,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  return `${day} · ${time} EEST`;
}

function formatGateCloseCountdown(date: Date, gateCloseHour: number): string {
  const gateClose = new Date(date);
  gateClose.setHours(gateCloseHour, 0, 0, 0);
  if (gateClose <= date) gateClose.setDate(gateClose.getDate() + 1);

  const diffMs = gateClose.getTime() - date.getTime();
  const totalMinutes = Math.max(0, Math.floor(diffMs / 60000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `in ${hours}h ${String(minutes).padStart(2, "0")}m`;
}
