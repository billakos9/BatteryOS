import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, KPI, Tag, Icon, Legend } from "@/components/bos/Primitives";
import { Spark, DispatchChart, ProfitChart, BatteryGauge } from "@/components/bos/Charts";
import { fmtEur } from "@/lib/dispatch";
import { useBosStore } from "@/lib/store";
import { artifactsToDispatchView, fetchBackendArtifacts, type BackendArtifacts } from "@/lib/backend";

const emptyArtifacts: BackendArtifacts = {
  schedule: [],
  scenario_panel: [],
  run_metadata: {},
  robustness_sweep: [],
};

const ATHENS_TZ = "Europe/Athens";

export default function PageDashboard() {
  const navigate = useNavigate();
  const { assets, selectedAssetId, optimizer, runs } = useBosStore();
  const asset = assets.find((a) => a.id === selectedAssetId) ?? assets[0];
  const [artifacts, setArtifacts] = useState<BackendArtifacts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
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
    let cancelled = false;
    fetchBackendArtifacts()
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
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

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

      {error && (
        <div className="bos-callout mb-4 border-red/40 text-red">
          Backend artifact fetch failed: {error}
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
              <div className="ml-auto font-mono-tnum text-[10px] text-fg-3">96 quarter-hourly periods · MTU=15min</div>
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

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-8">
          <Card title="Recent optimizer runs" meta="last 24h" flush
            actions={<button className="bos-btn sm ghost" onClick={() => navigate("/optimizer")}>New run <Icon name="plus" size={11} /></button>}>
            <table className="bos-tbl">
              <thead><tr><th>Run</th><th>Time</th><th>Day</th><th>Asset</th><th className="num">λ</th><th>Status</th><th className="num">Capture</th><th className="num">Profit</th></tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td className="font-mono-tnum">{r.id}</td>
                    <td className="font-mono-tnum">{r.time}</td>
                    <td className="font-mono-tnum">{r.day}</td>
                    <td className="font-mono-tnum">{r.assetId}</td>
                    <td className="num">{r.lambda.toFixed(2)}</td>
                    <td><Tag tone={r.status === "Optimal" ? "acc" : "amber"} dot>{r.status}</Tag></td>
                    <td className="num">{(r.capture * 100).toFixed(0)}%</td>
                    <td className="num text-fg-0">{fmtEur(r.profit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <div className="col-span-4">
          <Card title="Pipeline" meta="last hour">
            <div className="bos-steps pt-1">
              {[
                { l: "Ingest", t: "7 sources", n: "08m" },
                { l: "Features", t: "184 features", n: "11m" },
                { l: "Forecast", t: "LightGBM-q50", n: "21m" },
                { l: "Optimize", t: "Mean-CVaR · 20s", n: "18m" },
                { l: "Backtest", t: "queued", n: "—" },
              ].map((s, i) => (
                <div key={i} className={`bos-step ${i < 4 ? "done" : "active"}`}>
                  <div className="num">{i + 1}</div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="ttl">{s.l}</span>
                      <span className={`sdot ${i < 4 ? "ok" : "warn"}`} />
                      <span className="ml-auto font-mono-tnum text-[10px] text-fg-3">{s.n} ago</span>
                    </div>
                    <div className="desc">{s.t}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
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
