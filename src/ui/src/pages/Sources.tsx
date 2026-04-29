import { Card, KPI, Tag, Icon } from "@/components/bos/Primitives";
import { useSources } from "@/lib/api";

export default function PageSources() {
  const { data: sources = [], isLoading, isError } = useSources();
  return (
    <div>
      <div className="mb-6 flex items-end gap-6 border-b border-line pb-5">
        <div>
          <div className="eyebrow mb-2">Pipeline · Data Sources</div>
          <h1 className="h-display">Ingest & feature <em>health</em></h1>
          <div className="mt-2 max-w-[72ch] text-[13px] text-fg-2">
            Seven external feeds, point-in-time joined, gate-close-aware. The moat is not the model — it's this pipeline.
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button className="bos-btn"><Icon name="refresh" size={12} />Sync all</button>
          <button className="bos-btn primary"><Icon name="plus" size={12} />New source</button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-4 gap-4">
        <KPI featured label="Sources online" value="6" unit="of 7" delta={{ tone: "neu", text: "REMIT outage feed degraded" }} />
        <KPI label="Last full sync" value="12:43" unit="EEST" delta={{ tone: "up", text: "19m ago" }} />
        <KPI label="Rows ingested · 24h" value="12.4M" unit="rows" delta={{ tone: "up", text: "+0.8%" }} />
        <KPI label="Feature freshness" value="11 min" unit="median" delta={{ tone: "up", text: "well within gate close" }} />
      </div>

      <Card title="Source registry" meta="health · latency · cadence" flush>
        {isLoading && <div className="px-4 py-3 font-mono-tnum text-[11px] text-fg-3">Loading sources from /api/sources…</div>}
        {isError && <div className="px-4 py-3 font-mono-tnum text-[11px] text-red">Backend /api/sources unavailable.</div>}
        <table className="bos-tbl">
          <thead><tr>
            <th>Source</th><th>Description</th><th>Status</th><th>Latency</th>
            <th className="num">Rows</th><th>Last sync</th><th></th>
          </tr></thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td>
                  <div className="flex items-center gap-2.5">
                    <span className="grid h-6 w-6 place-items-center rounded" style={{ background: "hsl(var(--bg-3))", color: "hsl(var(--fg-2))" }}>
                      <Icon name={s.id === "openmeteo" ? "sun" : s.id === "ttf" ? "flow" : s.id === "eua" ? "bolt" : "database"} size={12} />
                    </span>
                    <span className="font-mono-tnum text-fg-0">{s.name}</span>
                  </div>
                </td>
                <td className="text-fg-3">{s.desc}</td>
                <td><Tag tone={s.status === "ok" ? "acc" : s.status === "warn" ? "amber" : "red"} dot>
                  {s.status === "ok" ? "healthy" : s.status === "warn" ? "degraded" : "offline"}
                </Tag></td>
                <td className="font-mono-tnum">{s.latency}</td>
                <td className="num">{s.rows}</td>
                <td className="font-mono-tnum">{s.lastSync}</td>
                <td><button className="bos-btn sm ghost"><Icon name="refresh" size={11} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="mt-4 grid grid-cols-12 gap-4">
        <div className="col-span-7">
          <Card title="Pipeline map" meta="raw → processed → features → model">
            <svg viewBox="0 0 600 220" width="100%" height="220">
              {[
                { y: 20, l: "HEnEx" }, { y: 56, l: "IPTO" }, { y: 92, l: "Open-Meteo" },
                { y: 128, l: "ENTSO-E" }, { y: 164, l: "TTF · EUA" }, { y: 200, l: "REMIT" },
              ].map((n, i) => (
                <g key={i}>
                  <rect x={20} y={n.y - 10} width="100" height="20" rx="3" fill="hsl(var(--bg-2))" stroke="hsl(var(--line-strong))" />
                  <text x={70} y={n.y + 4} fontSize="10" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-1))" textAnchor="middle">{n.l}</text>
                  <line x1={120} y1={n.y} x2="200" y2="110" stroke="hsl(var(--line-strong))" strokeWidth="1" />
                </g>
              ))}
              <rect x="200" y="100" width="120" height="20" rx="3" fill="hsl(var(--bg-3))" stroke="hsl(var(--line-strong))" />
              <text x="260" y="114" fontSize="10" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-0))" textAnchor="middle">processed/</text>
              <line x1="320" y1="110" x2="380" y2="110" stroke="hsl(var(--acc-dim))" strokeWidth="1.2" />
              <rect x="380" y="100" width="120" height="20" rx="3" fill="hsl(var(--bg-3))" stroke="hsl(var(--acc-dim))" />
              <text x="440" y="114" fontSize="10" fontFamily="IBM Plex Mono" fill="hsl(var(--acc))" textAnchor="middle">features/ × 184</text>
              <line x1="500" y1="110" x2="540" y2="110" stroke="hsl(var(--acc))" strokeWidth="1.6" />
              <polygon points="540,110 535,107 535,113" fill="hsl(var(--acc))" />
              <text x="540" y="100" fontSize="10" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-2))">model</text>
            </svg>
          </Card>
        </div>

        <div className="col-span-5">
          <Card title="Feature build log" meta="last run">
            <div className="font-mono-tnum text-[11px] leading-7 text-fg-2">
              {[
                ["12:43:01", "ingest.henex: pulled 96 MTU prices for 2026-04-29", "acc"],
                ["12:43:04", "ingest.ipto: load_fc → 96 rows, res_fc → 96 rows", "acc"],
                ["12:43:06", "ingest.openmeteo: temp,wind,irradiance @ 11 stations", "acc"],
                ["12:43:09", "ingest.ttf: cached value < 2h, using EOD", "amber"],
                ["12:43:11", "features.calendar: 12 features ✓", "acc"],
                ["12:43:13", "features.market: 38 lags + spreads ✓", "acc"],
                ["12:43:18", "features.fundamentals: residual_load + fuel_cost ✓", "acc"],
                ["12:43:24", "features.cross_border: DE/IT/BG residuals ✓", "acc"],
                ["12:43:27", "features.build: 184 features × 96 MTU written", "acc"],
                ["12:43:28", "✓ no leakage detected", "acc"],
                ["12:43:28", "✓ all asof_ts ≤ gate_close(D−1)", "acc"],
              ].map(([t, m, c], i) => (
                <div key={i}>
                  <span style={{ color: c === "acc" ? "hsl(var(--acc))" : c === "amber" ? "hsl(var(--amber))" : "hsl(var(--fg-3))" }}>[{t}]</span>{" "}{m}
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
