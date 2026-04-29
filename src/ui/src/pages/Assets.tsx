import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, KPI, Tag, Icon } from "@/components/bos/Primitives";
import { AssetEditor } from "@/components/bos/AssetEditor";
import { useBosStore } from "@/lib/store";
import { fmtEur } from "@/lib/dispatch";
import type { BatteryAsset } from "@/lib/types";

export default function PageAssets() {
  const navigate = useNavigate();
  const { assets, upsertAsset, removeAsset, toggleAssetStatus, setSelectedAsset, resetAssets } = useBosStore();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<BatteryAsset | undefined>(undefined);

  const startAdd = () => { setEditing(undefined); setEditorOpen(true); };
  const startEdit = (a: BatteryAsset) => { setEditing(a); setEditorOpen(true); };

  const dispatchAsset = (id: string) => { setSelectedAsset(id); navigate("/optimizer"); };

  return (
    <div>
      <div className="mb-6 flex items-end gap-6 border-b border-line pb-5">
        <div>
          <div className="eyebrow mb-2">Fleet</div>
          <h1 className="h-display">Storage <em>assets</em></h1>
          <div className="mt-2 max-w-[72ch] text-[13px] text-fg-2">
            Battery profiles for the Greek DAM. Review and edit asset assumptions, cycle limits, and degradation settings.
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button className="bos-btn ghost" onClick={resetAssets} title="Reset to defaults"><Icon name="refresh" size={12} />Reset</button>
          <button className="bos-btn"><Icon name="download" size={12} />Export YAML</button>
          <button className="bos-btn primary" onClick={startAdd}><Icon name="plus" size={12} />Add asset</button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-4 gap-4">
        <KPI featured label="Active assets" value={assets.filter((a) => a.status === "active").length} unit={`of ${assets.length}`}
          delta={{ tone: "up", text: "all reporting" }} />
        <KPI label="Fleet power" value={assets.reduce((s, a) => s + (a.status === "active" ? a.power : 0), 0)} unit="MW"
          delta={{ tone: "neu", text: "active only" }} />
        <KPI label="Fleet energy" value={assets.reduce((s, a) => s + (a.status === "active" ? a.energy : 0), 0)} unit="MWh"
          delta={{ tone: "neu", text: "nameplate" }} />
        <KPI label="Avg utilization" value={`${(assets.filter((a) => a.status === "active").reduce((s, a) => s + a.utilization, 0) / Math.max(1, assets.filter((a) => a.status === "active").length) * 100).toFixed(0)}%`}
          delta={{ tone: "up", text: "trailing 30d" }} />
      </div>

      <div className="mb-4 grid grid-cols-3 gap-4">
        {assets.map((p) => (
          <div key={p.id} className="asset-card">
            <div className="flex items-center gap-2.5 border-b border-line p-4">
              <div className="grid h-7 w-7 place-items-center rounded" style={{ background: "hsl(var(--bg-3))", color: p.status === "active" ? "hsl(var(--acc))" : "hsl(var(--fg-3))" }}>
                <Icon name={p.tech === "Pumped Hydro" || p.tech === "Vanadium Flow" ? "flow" : "battery"} size={14} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-mono-tnum text-[12px] font-medium text-fg-0">{p.id}</div>
                <div className="mt-0.5 font-mono-tnum text-[10px] text-fg-3">{p.tech} · {(p.energy / p.power).toFixed(1)}h</div>
              </div>
              <Tag tone={p.status === "active" ? "acc" : p.status === "paused" ? "amber" : "red"} dot>{p.status}</Tag>
            </div>
            <div className="asset-stats">
              <div className="s"><div className="l">Power</div><div className="v">{p.power}<span className="u">MW</span></div></div>
              <div className="s"><div className="l">Energy</div><div className="v">{p.energy}<span className="u">MWh</span></div></div>
              <div className="s"><div className="l">η RT</div><div className="v">{(p.eff * p.eff * 100).toFixed(0)}<span className="u">%</span></div></div>
            </div>
            <div className="flex flex-col gap-2 px-4 py-3">
              <div className="param-row" style={{ padding: "4px 0", gridTemplateColumns: "1fr auto" }}>
                <span className="lbl">Cycles/day cap</span>
                <span className="val">{p.cyclesPerDay.toFixed(1)}</span>
              </div>
              <div className="param-row" style={{ padding: "4px 0", gridTemplateColumns: "1fr auto" }}>
                <span className="lbl">Aging cost</span>
                <span className="val">€{p.agingCost.toFixed(1)}<span className="unit">/MWh</span></span>
              </div>
              <div className="param-row" style={{ padding: "4px 0", gridTemplateColumns: "1fr auto", borderBottom: "none" }}>
                <span className="lbl">SoC band</span>
                <span className="val">{Math.round(p.socMinPct * 100)}–{Math.round(p.socMaxPct * 100)}<span className="unit">%</span></span>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <span className="eyebrow">Utilization</span>
                <div className="flex-1"><div className="bar-track"><div className="bar-fill" style={{ width: p.utilization * 100 + "%" }} /></div></div>
                <span className="font-mono-tnum text-[10px] text-fg-3">{(p.utilization * 100).toFixed(0)}%</span>
              </div>
            </div>
            <div className="flex gap-1.5 border-t border-line p-2.5">
              <button className="bos-btn sm ghost flex-1" onClick={() => dispatchAsset(p.id)}><Icon name="play" size={11} />Dispatch</button>
              <button className="bos-btn sm ghost flex-1" onClick={() => startEdit(p)}><Icon name="edit" size={11} />Edit</button>
              <button className="bos-btn sm ghost" onClick={() => toggleAssetStatus(p.id)} title={p.status === "active" ? "Pause" : "Activate"}>
                <Icon name={p.status === "active" ? "pause" : "play"} size={11} />
              </button>
            </div>
          </div>
        ))}

        {/* Add card */}
        <button onClick={startAdd}
          className="asset-card flex min-h-[260px] flex-col items-center justify-center gap-3 border-dashed text-fg-3 transition-colors hover:border-acc-dim hover:text-acc">
          <Icon name="plus" size={20} />
          <span className="font-mono-tnum text-[11px] uppercase tracking-[0.12em]">Add asset</span>
        </button>
      </div>

      <Card title="Profile comparison" meta="head-to-head dispatch economics" flush>
        <table className="bos-tbl">
          <thead><tr>
            <th>Profile</th><th>Tech</th><th className="num">P</th><th className="num">E</th><th className="num">Duration</th>
            <th className="num">η RT</th><th className="num">Cycles/d</th><th className="num">Aging</th><th className="num">Util</th>
            <th className="num">Daily ~</th><th></th>
          </tr></thead>
          <tbody>
            {assets.map((p) => (
              <tr key={p.id}>
                <td className="font-mono-tnum text-fg-0">{p.id}</td>
                <td>{p.tech}</td>
                <td className="num">{p.power} MW</td>
                <td className="num">{p.energy} MWh</td>
                <td className="num">{(p.energy / p.power).toFixed(1)}h</td>
                <td className="num">{(p.eff * p.eff * 100).toFixed(1)}%</td>
                <td className="num">{p.cyclesPerDay.toFixed(1)}</td>
                <td className="num">€{p.agingCost.toFixed(1)}</td>
                <td className="num">{(p.utilization * 100).toFixed(0)}%</td>
                <td className="num text-fg-0">{fmtEur(Math.round(p.power * 290 * p.utilization))}</td>
                <td><button className="bos-btn sm ghost" onClick={() => startEdit(p)}><Icon name="edit" size={11} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <AssetEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        initial={editing}
        onSave={upsertAsset}
        onDelete={editing ? removeAsset : undefined}
      />
    </div>
  );
}
