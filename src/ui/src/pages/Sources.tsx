import { Card, KPI, Tag, Icon } from "@/components/bos/Primitives";
import { useSources } from "@/lib/api";
import { downloadJson } from "@/lib/export";
import { toast } from "sonner";

export default function PageSources() {
  const { data, isLoading, isError, refetch } = useSources();
  const sources = data?.sources ?? [];
  const okCount = sources.filter((s) => s.status === "ok").length;
  const rows24h = sources.reduce((sum, s) => sum + (s.rows_24h ?? 0), 0);
  const freshnessValues = sources
    .map((s) => s.feature_freshness_minutes ?? s.latency_minutes)
    .filter((v): v is number => typeof v === "number");
  const freshnessMedian = freshnessValues.length
    ? median(freshnessValues)
    : null;
  const generatedAt = data?.generated_at ? new Date(data.generated_at) : null;
  const generatedTime = generatedAt
    ? generatedAt.toLocaleTimeString("en-GB", {
        timeZone: "Europe/Athens",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "—";
  const generatedAgoMin = generatedAt
    ? Math.max(0, Math.round((Date.now() - generatedAt.getTime()) / 60000))
    : null;
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
          <button
            className="bos-btn"
            onClick={() => {
              void refetch()
                .then(() => toast.success("Source registry refreshed"))
                .catch((err) => toast.error(err instanceof Error ? err.message : "Source refresh failed"));
            }}
          >
            <Icon name="refresh" size={12} />Sync all
          </button>

        </div>
      </div>

      <div className="mb-4 grid grid-cols-4 gap-4">
        <KPI
          featured
          label="Sources online"
          value={okCount}
          unit={`of ${sources.length}`}
          delta={{ tone: "neu", text: `${sources.filter((s) => s.status !== "ok").length} degraded/offline` }}
        />
        <KPI
          label="Last full sync"
          value={generatedTime}
          unit="EEST"
          delta={{ tone: "up", text: generatedAgoMin == null ? "no posted artifact yet" : `${generatedAgoMin}m ago` }}
        />
        <KPI
          label="Rows ingested · 24h"
          value={formatCompact(rows24h)}
          unit="rows"
          delta={{ tone: "up", text: `${sources.length} registered feeds` }}
        />
        <KPI
          label="Feature freshness"
          value={freshnessMedian == null ? "—" : `${Math.round(freshnessMedian)} min`}
          unit="median"
          delta={{ tone: "up", text: data?.source === "pipeline_post" ? "posted by ingestion pipeline" : "demo artifact" }}
        />
      </div>

      <Card title="Source registry" meta="health · latency · cadence" flush>
        {isLoading && <div className="px-4 py-3 font-mono-tnum text-[11px] text-fg-3">Loading sources…</div>}
        {isError && <div className="px-4 py-3 font-mono-tnum text-[11px] text-red">Sources unavailable.</div>}
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
                <td>
                  <button
                    className="bos-btn sm ghost"
                    onClick={() => {
                      void refetch()
                        .then(() => toast.success(`${s.name} refreshed`))
                        .catch((err) => toast.error(err instanceof Error ? err.message : "Source refresh failed"));
                    }}
                  >
                    <Icon name="refresh" size={11} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="mt-4 grid grid-cols-12 gap-4">
        <div className="col-span-12">
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
      </div>
    </div>
  );
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

function formatCompact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}
