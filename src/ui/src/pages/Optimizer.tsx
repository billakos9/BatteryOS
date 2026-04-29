import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, KPI, Tag, Slider, Toggle, Icon, ParamRow } from "@/components/bos/Primitives";
import { DispatchChart, ProfitChart, ScenarioChart } from "@/components/bos/Charts";
import { fmtEur } from "@/lib/dispatch";
import { useBosStore } from "@/lib/store";
import {
  artifactsToDispatchView,
  fetchBackendArtifacts,
  robustRowsForGrid,
  runBackendOptimizer,
  type BackendArtifacts,
} from "@/lib/backend";

const emptyArtifacts: BackendArtifacts = {
  schedule: [],
  scenario_panel: [],
  run_metadata: {},
  robustness_sweep: [],
};

export default function PageOptimizer() {
  const navigate = useNavigate();
  const { assets, selectedAssetId, optimizer, setOptimizer, setSelectedAsset, resetOptimizer, recordRun } = useBosStore();
  const asset = assets.find((a) => a.id === selectedAssetId) ?? assets[0];
  const [solving, setSolving] = useState(false);
  const [artifacts, setArtifacts] = useState<BackendArtifacts | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const result = useMemo(() => artifactsToDispatchView(artifacts ?? emptyArtifacts), [artifacts]);
  const data = {
    realized: result.realized,
    forecast: result.forecast,
    p10: result.p10,
    p90: result.p90,
    charge: result.charge,
    discharge: result.discharge,
    soc: result.soc,
  };

  const onSolve = async () => {
    setSolving(true);
    setError(null);
    try {
      const next = await runBackendOptimizer({
        battery_profile_name: asset.id,
        risk_lambda: optimizer.lambda,
        risk_alpha: optimizer.alpha,
        build_bid_curves: true,
        run_robustness_sweep: optimizer.robust,
      });
      setArtifacts(next);
      const nextResult = artifactsToDispatchView(next);
      const now = new Date();
      recordRun({
        id: "run-" + Math.floor(Math.random() * 9000 + 1000),
        time: now.toTimeString().slice(0, 5),
        day: next.run_metadata.delivery_day ?? now.toISOString().slice(0, 10),
        assetId: asset.id,
        lambda: optimizer.lambda,
        profit: Math.round(nextResult.expected),
        status: nextResult.status,
        capture: nextResult.capture,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSolving(false);
    }
  };

  const sweepRows = useMemo(() => robustRowsForGrid(artifacts?.robustness_sweep ?? []), [artifacts]);

  return (
    <div>
      <div className="mb-6 flex items-end gap-6 border-b border-line pb-5">
        <div>
          <div className="eyebrow mb-2">Analytics · Optimizer</div>
          <h1 className="h-display">Mean-CVaR <em>dispatch</em> with rainflow aging</h1>
          <div className="mt-2 max-w-[72ch] text-[13px] text-fg-2">
            This page calls the backend Optimizer V1. The React UI only sends the selected profile, λ, α and robustness flag,
            then visualizes the artifacts returned by FastAPI.
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button className="bos-btn"><Icon name="download" size={12} />Export schedule</button>
          <button className="bos-btn primary" onClick={onSolve}>
            {solving ? <><span className="sdot ok" />Solving…</> : <><Icon name="play" size={12} />Solve</>}
          </button>
        </div>
      </div>

      {error && (
        <div className="bos-callout mb-4 border-red/40 text-red">
          Backend request failed: {error}
        </div>
      )}

      <div className="mb-4 grid grid-cols-4 gap-4">
        <KPI featured label="Expected profit" value={fmtEur(result.expected)} unit="EUR"
          delta={{ tone: "up", text: `λ=${optimizer.lambda.toFixed(2)} · ${(result.capture * 100).toFixed(0)}% of perfect` }} />
        <KPI label={`CVaR α=${optimizer.alpha.toFixed(2)}`} value={fmtEur(result.cvar)} unit="EUR"
          delta={{ tone: "neu", text: "tail-protected" }} />
        <KPI label="Worst case · robust" value={fmtEur(result.worst)} unit="EUR"
          delta={{ tone: "neu", text: optimizer.robust ? "verified across grid" : "robust mode off" }} />
        <KPI label="Cycles used" value={result.cyclesUsed.toFixed(2)} unit={`/ ${result.cyclesCap.toFixed(1)} cap`}
          delta={{ tone: "up", text: `aging ${fmtEur(result.agingCostTotal)}` }} />
      </div>

      <div className="mb-4 grid grid-cols-12 gap-4">
        <div className="col-span-4">
          <Card title="Parameters" meta="backend solve"
            actions={<button className="bos-btn sm ghost" onClick={resetOptimizer}>Reset</button>}>

            <div className="eyebrow mb-2">Battery asset</div>
            <div className="bos-opts mb-4">
              {assets.map((p) => (
                <span key={p.id} className={`o ${selectedAssetId === p.id ? "on" : ""}`} onClick={() => setSelectedAsset(p.id)}>
                  {p.id}
                </span>
              ))}
            </div>

            <div className="eyebrow mb-2">Risk profile</div>
            <ParamRow label="λ" hint="mean-CVaR mix" value={optimizer.lambda.toFixed(2)}>
              <Slider min={0} max={1} step={0.05} value={optimizer.lambda} onChange={(v) => setOptimizer({ lambda: v })} />
            </ParamRow>
            <ParamRow label="α" hint="CVaR tail" value={optimizer.alpha.toFixed(2)}>
              <Slider min={0.05} max={0.5} step={0.05} value={optimizer.alpha} onChange={(v) => setOptimizer({ alpha: v })} />
            </ParamRow>

            <div className="my-2 flex flex-wrap gap-2">
              {[
                { v: 0.0, l: "Risk Neutral" },
                { v: 0.5, l: "Balanced" },
                { v: 0.7, l: "Defensive" },
                { v: 1.0, l: "Worst Case" },
              ].map((o) => (
                <span key={o.v} className={`bos-tag ${Math.abs(optimizer.lambda - o.v) < 0.03 ? "acc" : ""} cursor-pointer`}
                  onClick={() => setOptimizer({ lambda: o.v })}>
                  {Math.abs(optimizer.lambda - o.v) < 0.03 && <span className="dot" />}{o.l}
                </span>
              ))}
            </div>

            <div className="eyebrow mb-1 mt-3">Backend profile values</div>
            <ReadOnlyRow label="Power" value={`${(artifacts?.run_metadata.battery_profile?.power_mw ?? asset.power).toFixed(0)} MW`} />
            <ReadOnlyRow label="Energy" value={`${(artifacts?.run_metadata.battery_profile?.energy_mwh ?? asset.energy).toFixed(0)} MWh`} />
            <ReadOnlyRow label="Round-trip η" value={`${((artifacts?.run_metadata.battery_profile?.eta_rt ?? asset.eff * asset.eff) * 100).toFixed(1)}%`} />
            <ReadOnlyRow label="Degradation" value={artifacts?.run_metadata.degradation_model ?? "constant + SoC-banded"} />

            <div className="param-row" style={{ gridTemplateColumns: "1fr auto", borderBottom: "none" }}>
              <span className="lbl">Robust sweep<span className="hint">verify under perturbations</span></span>
              <Toggle on={optimizer.robust} onChange={(v) => setOptimizer({ robust: v })} />
            </div>
          </Card>
        </div>

        <div className="col-span-8 space-y-4">
          <Card title="Optimized dispatch · live" meta={`${asset.power} MW / ${asset.energy} MWh`}>
            <DispatchChart data={data} height={300} showSoc />
            <div className="mt-3 flex items-center gap-4 border-t border-line pt-3 font-mono-tnum text-[10px] text-fg-3">
              <span>optimizer: {artifacts?.run_metadata.optimizer_display_name ?? "Optimizer V1"} · {result.solveMs}ms · status: {result.status}</span>
              <span className="ml-auto">{artifacts?.run_metadata.scenarios_used ?? result.scenarios.length} scenarios · α={optimizer.alpha.toFixed(2)}</span>
            </div>
          </Card>

          <Card title="Profit waterfall" meta="period + cumulative">
            <ProfitChart periodProfit={result.periodProfit} cumProfit={result.cumProfit} height={200} />
          </Card>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-12 gap-4">
        <div className="col-span-5">
          <Card title="Solver workflow" meta="10 steps · auditable">
            <div className="bos-steps">
              {[
                { t: "External scenarios", d: `${artifacts?.run_metadata.scenarios_used ?? result.scenarios.length} price paths loaded from backend artifact`, x: "forecaster contract" },
                { t: "Battery constraints", d: "power, energy, η, SoC bounds", x: `P≤${asset.power} · E≤${asset.energy}` },
                { t: "Cycle envelope", d: "daily cycle cap from selected storage profile", x: `max ${result.cyclesCap.toFixed(1)} eq. cycles` },
                { t: "Mean-CVaR objective", d: "(1−λ)·E[π] + λ·CVaR_α[π]", x: `λ=${optimizer.lambda.toFixed(2)} · α=${optimizer.alpha.toFixed(2)}` },
                { t: "LP / MILP solve", d: "backend optimizer call", x: `${result.solveMs} ms · ${result.status}` },
                { t: "Feasibility check", d: "SoC, power, simultaneity, cycles", x: artifacts?.run_metadata.feasibility?.feasible === false ? "violations reported" : "feasible" },
                { t: "Period economics", d: "profit per MTU at realized price", x: `Σ = ${fmtEur(result.expected)}` },
                { t: "Rainflow aging", d: "ASTM E1049 + Wöhler", x: `${fmtEur(result.agingCostTotal)} cost` },
                { t: "Robust sweep", d: "η × aging × cycles grid", x: optimizer.robust ? `${sweepRows.length} cells verified` : "off" },
                { t: "Bid curves", d: "HEnEx ladder per MTU", x: "96 bid blocks" },
              ].map((s, i) => (
                <div key={i} className="bos-step done">
                  <div className="num">{i + 1}</div>
                  <div>
                    <div className="ttl">{s.t}</div>
                    <div className="desc">{s.d}</div>
                    <div className="extra">{s.x}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div className="col-span-7 space-y-4">
          <Card title="Scenario fan · optimizer input" meta={`${result.scenarios.length} paths × ${result.forecast.length} periods`}
            actions={<span className="font-mono-tnum text-[10px] text-fg-3">CVaR={fmtEur(result.cvar)}</span>}>
            <ScenarioChart scenarios={result.scenarios} forecast={result.forecast} realized={result.realized} height={200} />
          </Card>

          <Card title="Robustness sweep" meta="η × aging cost · realized profit"
            actions={<span className="font-mono-tnum text-[10px] text-fg-3">worst {sweepRows.length ? fmtEur(Math.min(...sweepRows.map((r) => r.p))) : "n/a"}</span>}>
            {sweepRows.length ? <RobustGrid rows={sweepRows} /> : <div className="py-8 text-center font-mono-tnum text-[11px] text-fg-3">Run with robust sweep enabled to populate this table.</div>}
          </Card>
        </div>
      </div>

      <div className="bos-callout">
        <div className="eyebrow mb-1 text-acc">Decision-aware insight</div>
        At λ={optimizer.lambda.toFixed(2)} the backend optimizer chooses one feasible schedule from the scenario bundle.
        The UI is displaying schedule, profit, rainflow aging and robustness artifacts returned by that solve. Same code path can be backtested on{" "}
        <button className="bos-btn sm ghost inline-flex" onClick={() => navigate("/backtest")}>90 historical days <Icon name="chevR" size={11} /></button>.
      </div>
    </div>
  );
}

function ReadOnlyRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid items-center gap-3 border-b border-line py-2 last:border-b-0" style={{ gridTemplateColumns: "1fr auto" }}>
      <span className="font-mono-tnum text-[11px] text-fg-2">{label}</span>
      <span className="font-mono-tnum text-[11px] text-fg-0">{value}</span>
    </div>
  );
}

function RobustGrid({ rows }: { rows: { e: number; d: number; p: number }[] }) {
  const effs = [...new Set(rows.map((r) => r.e))];
  const degs = [...new Set(rows.map((r) => r.d))];
  const min = Math.min(...rows.map((r) => r.p));
  const max = Math.max(...rows.map((r) => r.p));
  const colorFor = (p: number) => {
    const t = (p - min) / Math.max(1, max - min);
    if (t < 0.33) return `hsla(0,100%,71%,${0.25 + t})`;
    if (t < 0.66) return `hsla(35,100%,64%,${0.2 + t})`;
    return `hsla(152,100%,71%,${0.2 + t * 0.6})`;
  };
  return (
    <div>
      <div className="grid gap-px" style={{ gridTemplateColumns: `60px repeat(${degs.length}, 1fr)` }}>
        <div className="eyebrow py-1">η ↓ / €/MWh →</div>
        {degs.map((d) => <div key={d} className="eyebrow text-center">€{d.toFixed(1)}</div>)}
      </div>
      {effs.map((e) => (
        <div key={e} className="mb-px grid gap-px" style={{ gridTemplateColumns: `60px repeat(${degs.length}, 1fr)` }}>
          <div className="font-mono-tnum text-[10px] text-fg-3 px-1 py-2">{(e * 100).toFixed(0)}%</div>
          {degs.map((d) => {
            const r = rows.find((x) => x.e === e && x.d === d)!;
            return (
              <div key={d} className="rounded-sm py-2.5 text-center" style={{ background: colorFor(r.p) }}>
                <div className="font-mono-tnum text-[11px] font-medium text-fg-0">{fmtEur(r.p)}</div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
