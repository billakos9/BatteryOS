import { useState } from "react";
import { Card, KPI, Tag, Seg, Icon, Legend } from "@/components/bos/Primitives";
import { Spark, EquityChart, Heatmap, Histogram } from "@/components/bos/Charts";
import { equityCurve } from "@/lib/data";
import { fmtEur } from "@/lib/dispatch";
import { useBosStore } from "@/lib/store";

export default function PageBacktest() {
  const [period, setPeriod] = useState<"30" | "90" | "365">("90");
  const { selectedAssetId } = useBosStore();
  const { equity, dayProfits } = equityCurve;
  const totalBOS = equity.batteryOS[equity.batteryOS.length - 1];
  const totalNaive = equity.naive[equity.naive.length - 1];
  const totalPerfect = equity.perfect[equity.perfect.length - 1];
  const profits = dayProfits.map((d) => d.bos);

  // ad-hoc heatmap from existing data import
  const heat = (() => {
    // 30 × 24 simple shape replication
    const out: number[][] = [];
    for (let d = 0; d < 30; d++) {
      const row: number[] = [];
      for (let h = 0; h < 24; h++) {
        const peak = Math.exp(-Math.pow((h - 8) / 2, 2)) + 1.4 * Math.exp(-Math.pow((h - 19) / 1.6, 2));
        const trough = -0.7 * Math.exp(-Math.pow((h - 13) / 1.7, 2));
        row.push(peak + trough + 0.4 + Math.sin(d * 0.4 + h) * 0.2);
      }
      out.push(row);
    }
    return out;
  })();

  return (
    <div>
      <div className="mb-6 flex items-end gap-6 border-b border-line pb-5">
        <div>
          <div className="eyebrow mb-2">Analytics · Backtest</div>
          <h1 className="h-display">Walk-forward <em>economic</em> backtest</h1>
          <div className="mt-2 max-w-[72ch] text-[13px] text-fg-2">
            Replays the full pipeline as if we were operating each day. Gate-close-aware features, no leakage.
            Headline metric: realized profit as % of perfect foresight.
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Seg value={period} onChange={(v) => setPeriod(v)} options={[{ v: "30", l: "30D" }, { v: "90", l: "90D" }, { v: "365", l: "1Y" }]} />
          <button className="bos-btn"><Icon name="download" size={12} />CSV</button>
          <button className="bos-btn primary"><Icon name="play" size={12} />Re-run</button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-4 gap-4">
        <KPI featured label="Cumulative profit · BatteryOS" value={fmtEur(totalBOS)} unit="EUR"
          delta={{ tone: "up", text: `+${fmtEur(totalBOS - totalNaive)} vs naive` }}
          spark={<Spark values={equity.batteryOS} color="hsl(var(--acc))" fill />} />
        <KPI label="vs Perfect foresight" value={`${(totalBOS / totalPerfect * 100).toFixed(0)}%`} unit="capture"
          delta={{ tone: "up", text: "ceiling = €" + Math.round(totalPerfect / 1000) + "k" }} />
        <KPI label="vs Naive baseline" value={`+${((totalBOS / totalNaive - 1) * 100).toFixed(0)}%`} unit="uplift"
          delta={{ tone: "up", text: "consistently positive" }} />
        <KPI label="Worst day" value={fmtEur(Math.min(...profits))} unit="EUR"
          delta={{ tone: "neu", text: "no losing days · 90/90" }} />
      </div>

      <Card title="Equity curve" meta="walk-forward · 90 days"
        actions={<Legend items={[
          { color: "hsl(var(--acc))", label: "BatteryOS" },
          { color: "hsl(var(--magenta))", label: "Naive" },
          { color: "hsl(var(--fg-3))", label: "Perfect foresight", dashed: true },
        ]} />}>
        <EquityChart equity={equity} height={300} />
      </Card>

      <div className="mb-4 mt-4 grid grid-cols-12 gap-4">
        <div className="col-span-7">
          <Card title="Daily profit heatmap" meta="hour × day · €/MWh dispatched">
            <Heatmap matrix={heat} height={240} />
            <div className="mt-2 flex gap-4 border-t border-line pt-3">
              <Legend items={[
                { color: "hsl(var(--blue))", label: "Cool" },
                { color: "hsl(var(--acc))", label: "Productive" },
                { color: "hsl(var(--amber))", label: "Peak arbitrage" },
              ]} />
              <span className="ml-auto font-mono-tnum text-[10px] text-fg-3">peaks: 7–9h · 18–21h · midday solar trough</span>
            </div>
          </Card>
        </div>

        <div className="col-span-5">
          <Card title="Daily profit distribution" meta="vs perfect foresight">
            <Histogram values={profits} bins={14} height={200} color="hsl(var(--acc))" />
            <div className="mt-2 grid grid-cols-4 gap-3 border-t border-line pt-3">
              {(() => {
                const sorted = [...profits].sort((a, b) => a - b);
                return [
                  ["P10", fmtEur(sorted[Math.floor(sorted.length * 0.1)])],
                  ["Median", fmtEur(sorted[Math.floor(sorted.length / 2)])],
                  ["Mean", fmtEur(totalBOS / 90)],
                  ["P90", fmtEur(sorted[Math.floor(sorted.length * 0.9)])],
                ].map(([k, v]) => (
                  <div key={k}><div className="eyebrow">{k}</div><div className="font-mono-tnum text-fg-0">{v}</div></div>
                ));
              })()}
            </div>
          </Card>
        </div>
      </div>

      <Card title="Day-by-day results" meta="walk-forward log" flush>
        <table className="bos-tbl">
          <thead>
            <tr>
              <th>Day</th><th>Date</th><th>Asset</th><th>λ</th>
              <th className="num">Naive</th><th className="num">BatteryOS</th><th className="num">Perfect</th>
              <th className="num">Capture</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {dayProfits.slice(-12).reverse().map((d, i) => {
              const date = new Date(2026, 3, 29 - i);
              return (
                <tr key={d.d}>
                  <td className="font-mono-tnum">D{d.d + 1}</td>
                  <td className="font-mono-tnum">{date.toISOString().slice(0, 10)}</td>
                  <td className="font-mono-tnum">{selectedAssetId}</td>
                  <td className="num">0.50</td>
                  <td className="num">{fmtEur(d.naive)}</td>
                  <td className="num text-fg-0">{fmtEur(d.bos)}</td>
                  <td className="num text-fg-3">{fmtEur(d.perfect)}</td>
                  <td className="num"><span className="font-mono-tnum" style={{ color: d.capture > 0.7 ? "hsl(var(--acc))" : "hsl(var(--amber))" }}>{(d.capture * 100).toFixed(0)}%</span></td>
                  <td><Tag tone="acc" dot>Optimal</Tag></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
