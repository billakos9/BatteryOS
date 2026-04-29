import type { BatteryAsset } from "./types";

export function downloadJson(filename: string, value: unknown) {
  downloadText(filename, JSON.stringify(value, null, 2), "application/json");
}

export function downloadText(filename: string, text: string, mimeType = "text/plain;charset=utf-8") {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function downloadCsv(filename: string, rows: Array<Record<string, unknown>>) {
  const csv = rowsToCsv(rows);
  downloadText(filename, csv, "text/csv;charset=utf-8");
}

export function rowsToCsv(rows: Array<Record<string, unknown>>): string {
  if (!rows.length) return "";
  const headers = Array.from(
    rows.reduce((acc, row) => {
      Object.keys(row).forEach((key) => acc.add(key));
      return acc;
    }, new Set<string>())
  );
  const lines = [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ];
  return lines.join("\n");
}

function csvCell(value: unknown): string {
  const raw = value == null ? "" : String(value);
  if (!/[",\n]/.test(raw)) return raw;
  return `"${raw.replace(/"/g, "\"\"")}"`;
}

export function batteryAssetsToYaml(assets: BatteryAsset[]): string {
  const lines = ["profiles:"];
  for (const asset of assets) {
    lines.push(`  ${asset.id}:`);
    lines.push(`    technology: ${assetTechToYaml(asset.tech)}`);
    lines.push(`    power_mw: ${asset.power}`);
    lines.push(`    energy_mwh: ${asset.energy}`);
    lines.push(`    soc_min_frac: ${asset.socMinPct}`);
    lines.push(`    soc_max_frac: ${asset.socMaxPct}`);
    lines.push(`    initial_soc_frac: ${clamp((asset.socMinPct + asset.socMaxPct) / 2, 0, 1)}`);
    lines.push(`    charge_efficiency: ${asset.eff}`);
    lines.push(`    discharge_efficiency: ${asset.eff}`);
    lines.push(`    max_cycles_per_day: ${asset.cyclesPerDay}`);
    lines.push(`    degradation_cost_eur_per_mwh: ${asset.agingCost}`);
    if (asset.notes?.trim()) {
      lines.push(`    notes: "${asset.notes.replace(/"/g, '\\"')}"`);
    }
  }
  return lines.join("\n") + "\n";
}

function assetTechToYaml(tech: BatteryAsset["tech"]): string {
  switch (tech) {
    case "Li-Ion":
      return "lithium_ion";
    case "Pumped Hydro":
      return "pumped_hydro";
    case "Vanadium Flow":
      return "vanadium_flow";
    case "NaS":
      return "nas";
    default:
      return "custom";
  }
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}
