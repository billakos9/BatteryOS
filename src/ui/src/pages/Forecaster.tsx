import { useEffect, useState } from "react";
import { Card, KPI, Tag, Seg, Toggle, Icon, Legend } from "@/components/bos/Primitives";
import { FanChart, Histogram, BulletBar } from "@/components/bos/Charts";
import { useSize } from "@/components/bos/Primitives";

const groupColors: Record<string, string> = {
  Fundamentals: "hsl(var(--acc))",
  "Market Memory": "hsl(var(--blue))",
  "Fuel & Carbon": "hsl(var(--amber))",
  "Cross-border": "hsl(var(--magenta))",
  Weather: "hsl(var(--blue))",
  Calendar: "hsl(var(--fg-2))",
};

type ForecastOverview = {
  source: string;
  market: string;
  unit: string;
  resolution_minutes: number;
  generated_at: string;
  quantiles: {
    timestamps: string[];
    p10: number[];
    p50: number[];
    p90: number[];
    realized: number[];
  };
  diagnostics: {
    mae_eur_per_mwh: number;
    rmse_eur_per_mwh: number;
    profit_capture_pct: number;
    pinball_q90_eur_per_mwh: number;
    bias_eur_per_mwh: number;
    sigma_eur_per_mwh: number;
    p95_abs_error_eur_per_mwh: number;
    skew: number;
  };
  models: {
    id: string;
    name: string;
    kind: string;
    mae: number;
    rmse: number;
    smape: number;
    profit_capture_pct: number;
    pinball_q90: number;
  }[];
  features: {
    name: string;
    group: string;
    imp: number;
  }[];
  residuals: number[];
  calibration: {
    nominal: number[];
    empirical: number[];
  };
};

export default function PageForecaster() {
  const [activeModel, setActiveModel] = useState("lgbm_q");
  const [showRealized, setShowRealized] = useState(true);
  const [horizon, setHorizon] = useState<"24" | "48">("24");
  const [overview, setOverview] = useState<ForecastOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const fetchOverview = async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch(`/api/forecast/overview?horizon_h=${horizon}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ForecastOverview;
      setOverview(data);
      if (!data.models.some((model) => model.id === activeModel)) {
        setActiveModel(data.models[0]?.id ?? "lgbm_q");
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load forecast overview");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [horizon]);

  const active = overview?.models.find((model) => model.id === activeModel) ?? overview?.models[0];
  const diagnostics = overview?.diagnostics;

  return (
    <div>
      <div className="mb-6 flex items-end gap-6 border-b border-line pb-5">
        <div>
          <div className="eyebrow mb-2">Analytics · Forecaster</div>
          <h1 className="h-display">Price <em>forecasting</em> for the Greek DAM</h1>
          <div className="mt-2 max-w-[72ch] text-[13px] text-fg-2">
            Local backend forecast diagnostics, quantile curves and model context. This page now reads from the BatteryOS API instead of the external Supabase demo.
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button className="bos-btn"><Icon name="download" size={12} />Export forecast</button>
          <button className="bos-btn primary" onClick={fetchOverview} disabled={loading}>
            <Icon name="refresh" size={12} />{loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {err && (
        <div className="bos-callout mb-4 border-red/40 text-red">
          Forecast backend request failed: {err}
        </div>
      )}

      <div className="mb-4 grid grid-cols-4 gap-4">
        <KPI featured label="Forecast MAE" value={diagnostics?.mae_eur_per_mwh.toFixed(1) ?? "0.0"} unit="€/MWh"
          delta={{ tone: "up", text: `${active?.name ?? "Model"} · average absolute error` }} />
        <KPI label="Forecast RMSE" value={diagnostics?.rmse_eur_per_mwh.toFixed(1) ?? "0.0"} unit="€/MWh"
          delta={{ tone: "neu", text: "penalizes larger misses more heavily" }} />
        <KPI label="Profit capture" value={diagnostics ? diagnostics.profit_capture_pct.toFixed(0) : "0"} unit="% of perfect"
          delta={{ tone: "up", text: "forecast-driven dispatch vs perfect foresight" }} />
        <KPI label="Pinball loss · q90" value={diagnostics?.pinball_q90_eur_per_mwh.toFixed(2) ?? "0.00"} unit="€/MWh"
          delta={{ tone: "neu", text: "upper-tail quantile accuracy" }} />
      </div>

      <Card title="Forecasting workflow" meta="data → features → model → forecast"
        actions={<Seg value="active" onChange={() => {}} options={[{ v: "active", l: "Pipeline" }, { v: "history", l: "Runs" }]} />}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(6, minmax(0, 1fr))" }}>
          {[
            { n: 1, t: "Ingest", d: "7 sources, point-in-time joined", x: "asof_ts ≤ gate_close(D−1)" },
            { n: 2, t: "Features", d: "Calendar + lags + residual load + fuel + cross-border", x: "184 features · leakage-safe" },
            { n: 3, t: "Validate", d: "Time-series CV, no shuffle", x: "5 folds · 30-day window" },
            { n: 4, t: "Train", d: "LightGBM, quantile loss", x: "q10 / q50 / q90 · backend contract" },
            { n: 5, t: "Predict", d: "96 or 192 quarter-hourly prices", x: "point + uncertainty" },
            { n: 6, t: "Score", d: "MAE / RMSE / pinball + decision-aware", x: "profit vs perfect foresight" },
          ].map((s, i) => (
            <div key={i} className="p-3.5" style={{ borderRight: i < 5 ? "1px solid hsl(var(--line))" : undefined }}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="grid h-[22px] w-[22px] place-items-center rounded-full font-mono-tnum text-[10px] font-semibold"
                  style={{ background: i < 4 ? "hsl(var(--acc))" : "hsl(var(--bg-3))", color: i < 4 ? "hsl(var(--bg-0))" : "hsl(var(--fg-2))" }}>
                  {s.n}
                </span>
                <span className="text-[12px] font-medium text-fg-0">{s.t}</span>
              </div>
              <div className="text-[11px] text-fg-2">{s.d}</div>
              <div className="mt-1.5 font-mono-tnum text-[10px] text-fg-3">{s.x}</div>
            </div>
          ))}
        </div>
      </Card>

      <div className="mb-4 mt-4 grid grid-cols-12 gap-4">
        <div className="col-span-8">
          <Card
            title="Day-ahead price · P10 / P50 / P90"
            meta={overview ? `${overview.market} · ${overview.unit} · res ${overview.resolution_minutes}min · ${new Date(overview.generated_at).toLocaleTimeString()} · ${overview.source}` : "fetching from local backend…"}
            actions={
              <>
                <Seg<"24" | "48">
                  value={horizon}
                  onChange={(v) => setHorizon(v)}
                  options={[{ v: "24", l: "24h" }, { v: "48", l: "48h" }]}
                />
                <span className="font-mono-tnum text-[10px] text-fg-3">overlay realized</span>
                <Toggle on={showRealized} onChange={setShowRealized} />
                <button className="bos-btn" onClick={fetchOverview} disabled={loading}>
                  <Icon name="refresh" size={12} />{loading ? "Loading…" : "Refresh"}
                </button>
              </>
            }
          >
            {overview ? (
              <FanChart
                timestamps={overview.quantiles.timestamps}
                p10={overview.quantiles.p10}
                p50={overview.quantiles.p50}
                p90={overview.quantiles.p90}
                realized={showRealized ? overview.quantiles.realized : undefined}
                height={300}
              />
            ) : (
              <div style={{ height: 300 }} className="flex items-center justify-center text-[11px] text-fg-3">
                {loading ? "Loading forecast overview…" : "No data"}
              </div>
            )}
            <div className="mt-3 flex border-t border-line pt-3">
              <Legend items={[
                { color: "hsl(var(--magenta))", label: "P50 (median)" },
                { color: "hsl(var(--magenta))", label: "P10 – P90 band" },
                { color: "hsl(var(--blue))", label: "Realized DAM" },
              ]} />
              <div className="ml-auto font-mono-tnum text-[10px] text-fg-3">
                source: <span className="text-fg-0">/api/forecast/overview</span>
              </div>
            </div>
          </Card>
        </div>

        <div className="col-span-4">
          <Card title="Model ladder" meta="select active" flush>
            <div className="flex flex-col">
              {(overview?.models ?? []).map((model) => (
                <div
                  key={model.id}
                  className="flex cursor-pointer items-center gap-3.5 border-b border-line px-4 py-3 last:border-b-0"
                  style={{ background: activeModel === model.id ? "hsla(152,100%,71%,0.04)" : undefined }}
                  onClick={() => setActiveModel(model.id)}
                >
                  <span className="h-2 w-2 rounded-full"
                    style={{ background: activeModel === model.id ? "hsl(var(--acc))" : "hsl(var(--bg-4))", boxShadow: activeModel === model.id ? "0 0 8px hsl(var(--acc))" : undefined }} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[12px] font-medium text-fg-0">{model.name}</div>
                    <div className="mt-0.5 font-mono-tnum text-[10px] text-fg-3">{model.kind}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono-tnum text-[12px] text-fg-0">MAE {model.mae}</div>
                    <div className="font-mono-tnum text-[10px] text-fg-3">capture {model.profit_capture_pct}%</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-7">
          <Card title="Feature importance" meta="backend overview · gain" flush>
            <table className="bos-tbl">
              <thead><tr><th>Feature</th><th>Group</th><th className="num">Gain</th><th style={{ width: "38%" }}>Importance</th></tr></thead>
              <tbody>
                {(overview?.features ?? []).map((feature) => (
                  <tr key={feature.name}>
                    <td className="font-mono-tnum text-fg-0">{feature.name}</td>
                    <td><Tag tone={feature.group === "Cross-border" ? "mag" : feature.group === "Weather" ? "blue" : feature.group === "Fuel & Carbon" ? "amber" : undefined}>{feature.group}</Tag></td>
                    <td className="num">{feature.imp.toFixed(3)}</td>
                    <td><BulletBar value={feature.imp} max={overview?.features?.[0]?.imp ?? 1} color={groupColors[feature.group] ?? "hsl(var(--acc))"} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <div className="col-span-5 grid gap-4" style={{ gridTemplateRows: "auto 1fr" }}>
          <Card title="Residuals · forecast − realized" meta="distribution">
            <Histogram values={overview?.residuals ?? []} bins={20} height={160} color="hsl(var(--magenta))" />
            <div className="mt-2 flex gap-4 border-t border-line pt-2">
              {[
                ["Bias", diagnostics ? diagnostics.bias_eur_per_mwh.toFixed(2) : "0.00"],
                ["σ", diagnostics ? diagnostics.sigma_eur_per_mwh.toFixed(1) : "0.0"],
                ["P95", diagnostics ? `±${diagnostics.p95_abs_error_eur_per_mwh.toFixed(1)}` : "±0.0"],
                ["Skew", diagnostics ? diagnostics.skew.toFixed(2) : "0.00"],
              ].map(([k, v]) => (
                <div key={k}><div className="eyebrow">{k}</div><div className="font-mono-tnum text-fg-0">{v}</div></div>
              ))}
            </div>
          </Card>
          <Card title="Calibration" meta="empirical vs nominal">
            <CalibrationChart nominal={overview?.calibration.nominal ?? []} empirical={overview?.calibration.empirical ?? []} />
          </Card>
        </div>
      </div>
    </div>
  );
}

function CalibrationChart({ nominal, empirical }: { nominal: number[]; empirical: number[] }) {
  const { ref, w } = useSize<HTMLDivElement>();
  const h = 140;
  const pad = { l: 30, r: 10, t: 10, b: 22 };
  const sx = (v: number) => pad.l + v * (w - pad.l - pad.r);
  const sy = (v: number) => h - pad.b - v * (h - pad.t - pad.b);
  return (
    <div ref={ref} style={{ width: "100%", height: h }}>
      {w > 0 && nominal.length > 0 && empirical.length > 0 && (
        <svg width={w} height={h}>
          <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="hsl(var(--fg-3))" strokeDasharray="2 3" />
          <path d={nominal.map((n, i) => (i === 0 ? "M" : "L") + sx(n) + "," + sy(empirical[i])).join(" ")} stroke="hsl(var(--acc))" strokeWidth="1.5" fill="none" />
          {nominal.map((n, i) => <circle key={i} cx={sx(n)} cy={sy(empirical[i])} r="2.5" fill="hsl(var(--acc))" />)}
          {[0, 0.5, 1].map((t) => <text key={t} x={sx(t)} y={h - pad.b + 12} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="middle">{t}</text>)}
          {[0, 0.5, 1].map((t) => <text key={t} x={pad.l - 4} y={sy(t) + 3} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">{t}</text>)}
        </svg>
      )}
    </div>
  );
}
