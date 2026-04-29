import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Icon } from "@/components/bos/Primitives";
import type { BatteryAsset, AssetTech, AssetStatus } from "@/lib/types";

const TECHS: AssetTech[] = ["Li-Ion", "Pumped Hydro", "Vanadium Flow", "NaS", "Custom"];
const STATUSES: AssetStatus[] = ["active", "paused", "maintenance"];

const empty = (): BatteryAsset => ({
  id: "new_asset_" + Math.random().toString(36).slice(2, 6),
  tech: "Li-Ion",
  power: 100,
  energy: 200,
  eff: 0.949,
  socMinPct: 0.10,
  socMaxPct: 0.90,
  cyclesPerDay: 1.5,
  agingCost: 2.0,
  status: "active",
  utilization: 0.0,
  notes: "",
});

export function AssetEditor({
  open, onOpenChange, initial, onSave, onDelete,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initial?: BatteryAsset;
  onSave: (a: BatteryAsset) => void;
  onDelete?: (id: string) => void;
}) {
  const [a, setA] = useState<BatteryAsset>(initial ?? empty());
  const isEdit = !!initial;

  useEffect(() => {
    if (open) setA(initial ?? empty());
  }, [open, initial]);

  const update = <K extends keyof BatteryAsset>(k: K, v: BatteryAsset[K]) =>
    setA((prev) => ({ ...prev, [k]: v }));

  const valid = a.id.trim().length > 0 && a.power > 0 && a.energy > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[640px] border-line-strong bg-bg-1 text-fg-1">
        <DialogHeader>
          <DialogTitle className="font-mono-tnum text-[12px] uppercase tracking-[0.12em] text-fg-3">
            {isEdit ? "Edit asset" : "Add asset"}
          </DialogTitle>
          <DialogDescription className="text-[12px] text-fg-2">
            Edit the asset profile used across the BatteryOS interface.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-x-4 gap-y-3 py-2">
          <Field label="Asset ID" hint="lowercase_underscore">
            <input
              className="bos-input"
              value={a.id}
              disabled={isEdit}
              onChange={(e) => update("id", e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))}
            />
          </Field>
          <Field label="Technology">
            <select className="bos-input" value={a.tech} onChange={(e) => update("tech", e.target.value as AssetTech)}>
              {TECHS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>

          <Field label="Power" suffix="MW">
            <input className="bos-input" type="number" min={1} max={2000} step={1} value={a.power}
              onChange={(e) => update("power", +e.target.value)} />
          </Field>
          <Field label="Energy" suffix="MWh">
            <input className="bos-input" type="number" min={1} max={20000} step={1} value={a.energy}
              onChange={(e) => update("energy", +e.target.value)} />
          </Field>

          <Field label="One-way η" hint={`round-trip ≈ ${(a.eff * a.eff * 100).toFixed(1)}%`}>
            <input className="bos-input" type="number" min={0.5} max={1} step={0.001} value={a.eff}
              onChange={(e) => update("eff", +e.target.value)} />
          </Field>
          <Field label="Cycles / day cap">
            <input className="bos-input" type="number" min={0.1} max={10} step={0.1} value={a.cyclesPerDay}
              onChange={(e) => update("cyclesPerDay", +e.target.value)} />
          </Field>

          <Field label="SoC min" suffix="% of E">
            <input className="bos-input" type="number" min={0} max={0.5} step={0.01} value={a.socMinPct}
              onChange={(e) => update("socMinPct", +e.target.value)} />
          </Field>
          <Field label="SoC max" suffix="% of E">
            <input className="bos-input" type="number" min={0.5} max={1} step={0.01} value={a.socMaxPct}
              onChange={(e) => update("socMaxPct", +e.target.value)} />
          </Field>

          <Field label="Aging cost" suffix="€/MWh">
            <input className="bos-input" type="number" min={0} max={50} step={0.1} value={a.agingCost}
              onChange={(e) => update("agingCost", +e.target.value)} />
          </Field>
          <Field label="Status">
            <select className="bos-input" value={a.status} onChange={(e) => update("status", e.target.value as AssetStatus)}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>

          <div className="col-span-2">
            <Field label="Notes" hint="optional">
              <input className="bos-input" value={a.notes ?? ""} onChange={(e) => update("notes", e.target.value)} />
            </Field>
          </div>
        </div>

        <DialogFooter className="!justify-between">
          <div>
            {isEdit && onDelete && (
              <button className="bos-btn danger" onClick={() => { onDelete(a.id); onOpenChange(false); }}>
                <Icon name="trash" size={12} /> Delete
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button className="bos-btn ghost" onClick={() => onOpenChange(false)}>Cancel</button>
            <button
              className="bos-btn primary"
              disabled={!valid}
              onClick={() => { onSave(a); onOpenChange(false); }}
              style={!valid ? { opacity: 0.5, cursor: "not-allowed" } : undefined}
            >
              <Icon name="save" size={12} /> Save asset
            </button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, hint, suffix, children }: { label: string; hint?: string; suffix?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1 flex items-center gap-2 font-mono-tnum text-[10px] uppercase tracking-[0.1em] text-fg-3">
        <span>{label}</span>
        {suffix && <span className="text-fg-3">· {suffix}</span>}
        {hint && <span className="ml-auto normal-case tracking-normal text-fg-3">{hint}</span>}
      </div>
      {children}
    </label>
  );
}
