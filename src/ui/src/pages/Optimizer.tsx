import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, KPI, Slider, Icon, ParamRow } from "@/components/bos/Primitives";
import { DispatchChart, ProfitChart } from "@/components/bos/Charts";
import { fmtEur } from "@/lib/dispatch";
import { useBosStore } from "@/lib/store";
import { getRiskProfile, riskProfiles } from "@/lib/riskProfiles";
import { downloadCsv } from "@/lib/export";
import {
  artifactsToDispatchView,
  fetchBackendArtifacts,
  runBackendOptimizer,
  type BackendArtifacts,
} from "@/lib/backend";
import { toast } from "sonner";

const emptyArtifacts: BackendArtifacts = {
  schedule: [],
  scenario_panel: [],
  run_metadata: {},
  robustness_sweep: [],
};

export default function PageOptimizer() {
  const navigate = useNavigate();
  const { assets, selectedAssetId, optimizer, setOptimizer, setSelectedAsset, resetOptimizer, recordRun } = useBosStore();
  const asset =
    assets.find((a) => a.id === selectedAssetId) ?? assets[0] ?? {
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
  const [solving, setSolving] = useState(false);
  const [artifacts, setArtifacts] = useState<BackendArtifacts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedRiskProfile = getRiskProfile(optimizer.riskProfile);

  useEffect(() => {
    let cancelled = false;
    fetchBackendArtifacts()
      .then((next) => {
        if (!cancelled) {
          setArtifacts(next);
          setOptimizer({
            riskProfile: (next.run_metadata.risk_profile as typeof optimizer.riskProfile | undefined) ?? optimizer.riskProfile,
            lambda: Number(next.run_metadata.cvar_lambda ?? optimizer.lambda),
            alpha: Number(next.run_metadata.cvar_alpha ?? optimizer.alpha),
          });
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
        risk_profile: optimizer.riskProfile,
        risk_lambda: optimizer.riskProfile === "custom" ? optimizer.lambda : undefined,
        risk_alpha: optimizer.riskProfile === "custom" ? optimizer.alpha : undefined,
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
      toast.success(`Optimizer run completed for ${asset.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSolving(false);
    }
  };

  return (
    <div>
      <div className="mb-6 flex items-end gap-6 border-b border-line pb-5">
        <div>
          <div className="eyebrow mb-2">Analytics · Optimizer</div>
          <h1 className="h-display">Mean-CVaR optimizer</h1>
          <div className="mt-2 max-w-[72ch] text-[13px] text-fg-2">
             Choose a battery profile and a risk preset, then solve to see the dispatch schedule, profit
             waterfall and rainflow aging for the next delivery day.
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            className="bos-btn"
            onClick={() => {
              const rows = artifacts?.schedule ?? [];
              if (!rows.length) {
                toast.error("No schedule available to export");
                return;
              }
              downloadCsv(`schedule_${asset.id}.csv`, rows as Array<Record<string, unknown>>);
              toast.success("Schedule exported");
            }}
          >
            <Icon name="download" size={12} />Export schedule
          </button>
          <button className="bos-btn primary" onClick={onSolve}>
            {solving ? <><span className="sdot ok" />Solving…</> : <><Icon name="play" size={12} />Solve</>}
          </button>
        </div>
      </div>

      {error && (
        <div className="bos-callout mb-4 border-red/40 text-red">
          Optimizer request failed: {error}
        </div>
      )}

      <div className="mb-4 grid grid-cols-4 gap-4">
        <KPI featured label="Expected profit" value={fmtEur(result.expected)} unit="EUR"
          delta={{ tone: "up", text: `${result.riskProfileLabel} · ${(result.capture * 100).toFixed(0)}% of perfect` }} />
        <KPI label="Risk profile" value={result.riskProfileLabel}
          delta={{ tone: "neu", text: `λ=${result.riskLambda.toFixed(2)} · α=${result.riskAlpha.toFixed(2)}` }} />
        <KPI label="Cycles used" value={result.cyclesUsed.toFixed(2)} unit={`/ ${result.cyclesCap.toFixed(1)} cap`}
          delta={{ tone: "up", text: `aging ${fmtEur(result.agingCostTotal)}` }} />
      </div>

      <div className="mb-4 grid grid-cols-12 gap-4">
        <div className="col-span-4">
          <Card title="Parameters" meta="risk · battery"
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
            <div className="bos-opts mb-3">
              {riskProfiles.map((profile) => (
                <span
                  key={profile.id}
                  className={`o ${optimizer.riskProfile === profile.id ? "on" : ""}`}
                  onClick={() => setOptimizer({
                    riskProfile: profile.id,
                    lambda: profile.id === "custom" ? optimizer.lambda : profile.lambda,
                    alpha: profile.id === "custom" ? optimizer.alpha : profile.alpha,
                  })}
                >
                  {profile.label}
                </span>
              ))}
            </div>

            <ReadOnlyRow label="Preset" value={selectedRiskProfile.label} />
            <ReadOnlyRow label="Description" value={selectedRiskProfile.description} />

            <ParamRow label="λ" hint="mean-CVaR mix" value={optimizer.lambda.toFixed(2)}>
              <Slider min={0} max={1} step={0.05} value={optimizer.lambda} onChange={(v) => setOptimizer({ lambda: v, riskProfile: "custom" })} />
            </ParamRow>
            <ParamRow label="α" hint="CVaR tail" value={optimizer.alpha.toFixed(2)}>
              <Slider min={0.05} max={0.5} step={0.05} value={optimizer.alpha} onChange={(v) => setOptimizer({ alpha: v, riskProfile: "custom" })} />
            </ParamRow>
            <div className="mt-2 font-mono-tnum text-[10px] text-fg-3">
              {optimizer.riskProfile === "custom" ? "Custom mode: sliders define the risk tuple." : "Preset mode: risk tuple is fixed by the selected category."}
            </div>

            <div className="eyebrow mb-1 mt-3">Battery profile</div>
            <ReadOnlyRow label="Power" value={`${(artifacts?.run_metadata.battery_profile?.power_mw ?? asset.power).toFixed(0)} MW`} />
            <ReadOnlyRow label="Energy" value={`${(artifacts?.run_metadata.battery_profile?.energy_mwh ?? asset.energy).toFixed(0)} MWh`} />
            <ReadOnlyRow label="Round-trip η" value={`${((artifacts?.run_metadata.battery_profile?.eta_rt ?? asset.eff * asset.eff) * 100).toFixed(1)}%`} />
            <ReadOnlyRow label="Degradation" value={artifacts?.run_metadata.degradation_model ?? "constant + SoC-banded"} />
          </Card>
        </div>

        <div className="col-span-8 space-y-4">
          <Card title="Optimized dispatch · live" meta={`${asset.power} MW / ${asset.energy} MWh`}>
            <DispatchChart data={data} height={300} showSoc />
            <div className="mt-3 flex items-center gap-4 border-t border-line pt-3 font-mono-tnum text-[10px] text-fg-3">
              <span>{artifacts?.run_metadata.optimizer_display_name ?? "Mean-CVaR optimizer"} · {result.solveMs}ms · {result.status}</span>
              <span className="ml-auto">{artifacts?.run_metadata.scenarios_used ?? result.scenarios.length} scenarios · {result.riskProfileLabel}</span>
            </div>
          </Card>

          <Card title="Profit waterfall" meta="period + cumulative">
            <ProfitChart periodProfit={result.periodProfit} cumProfit={result.cumProfit} height={200} />
          </Card>
        </div>
      </div>

      <div className="bos-callout">
        <div className="eyebrow mb-1 text-acc">Decision-aware insight</div>
        Under the {result.riskProfileLabel} profile, the optimizer chooses one feasible schedule from the scenario bundle.
        Schedule, profit and rainflow aging are shown above. The same logic can be replayed on{" "}
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


