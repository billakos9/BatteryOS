import { useSize } from "./Primitives";

function scale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain, [r0, r1] = range;
  const span = (d1 - d0) || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}
function lineP(xs: number[], ys: number[], sx: (n: number) => number, sy: (n: number) => number) {
  let d = "";
  for (let i = 0; i < xs.length; i++) {
    d += (i === 0 ? "M" : "L") + sx(xs[i]).toFixed(1) + "," + sy(ys[i]).toFixed(1) + " ";
  }
  return d;
}
function areaP(xs: number[], yLo: number[], yHi: number[], sx: (n: number) => number, sy: (n: number) => number) {
  let d = "";
  for (let i = 0; i < xs.length; i++) d += (i === 0 ? "M" : "L") + sx(xs[i]).toFixed(1) + "," + sy(yHi[i]).toFixed(1) + " ";
  for (let i = xs.length - 1; i >= 0; i--) d += "L" + sx(xs[i]).toFixed(1) + "," + sy(yLo[i]).toFixed(1) + " ";
  return d + "Z";
}

export function Spark({
  values, color = "hsl(var(--acc))", height = 28, fill = false,
}: { values: number[]; color?: string; height?: number; fill?: boolean }) {
  const { ref, w } = useSize<HTMLDivElement>();
  const min = Math.min(...values), max = Math.max(...values);
  const sx = scale([0, values.length - 1], [0, w]);
  const sy = scale([min, max], [height - 2, 2]);
  const xs = values.map((_, i) => i);
  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {w > 0 && (
        <svg width={w} height={height}>
          {fill && <path d={areaP(xs, values.map(() => min), values, sx, sy)} fill={color} opacity="0.15" />}
          <path d={lineP(xs, values, sx, sy)} stroke={color} strokeWidth="1.25" fill="none" />
        </svg>
      )}
    </div>
  );
}

export interface DispatchData {
  realized: number[];
  forecast?: number[];
  charge: number[];
  discharge: number[];
  soc: number[];
  p10?: number[];
  p90?: number[];
}

export function DispatchChart({
  data, height = 300, showSoc = true, showForecast = false,
}: { data: DispatchData; height?: number; showSoc?: boolean; showForecast?: boolean }) {
  const { ref, w } = useSize<HTMLDivElement>();
  const pad = { l: 38, r: 42, t: 14, b: 26 };
  const N = data.realized.length;
  const sx = scale([0, N], [pad.l, w - pad.r]);
  const allP = [...data.realized, ...(data.forecast || [])];
  const pMin = Math.min(...allP, 0), pMax = Math.max(...allP) * 1.1;
  const sy = scale([pMin, pMax], [height - pad.b, pad.t]);

  const powerMax = Math.max(...data.charge, ...data.discharge, 100) * 1.1;
  const syPower = scale([-powerMax, powerMax], [height - pad.b, pad.t]);
  const baseY = syPower(0);

  const socMax = Math.max(...data.soc, 1) * 1.05;
  const sySoc = scale([0, socMax], [height - pad.b, pad.t]);

  const xs = data.realized.map((_, i) => i);
  const priceTicks = [0, 50, 100, 150, 200].filter((t) => t >= pMin && t <= pMax);

  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {w > 0 && (
        <svg width={w} height={height}>
          <defs>
            <linearGradient id="dispatch-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--blue))" stopOpacity="0.18" />
              <stop offset="100%" stopColor="hsl(var(--blue))" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="forecast-band" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--magenta))" stopOpacity="0.16" />
              <stop offset="100%" stopColor="hsl(var(--magenta))" stopOpacity="0.04" />
            </linearGradient>
          </defs>

          {priceTicks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={w - pad.r} y1={sy(t)} y2={sy(t)} stroke="hsl(var(--line))" strokeDasharray="2 4" />
              <text x={pad.l - 6} y={sy(t) + 3} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">{t}</text>
            </g>
          ))}

          {[0, 4, 8, 12, 16, 20, 24].map((h0) => {
            const i = h0 * 4;
            return (
              <g key={h0}>
                <line x1={sx(i)} x2={sx(i)} y1={pad.t} y2={height - pad.b} stroke="hsl(var(--line))" strokeDasharray="2 4" opacity="0.5" />
                <text x={sx(i)} y={height - pad.b + 14} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="middle">
                  {String(h0).padStart(2, "0")}:00
                </text>
              </g>
            );
          })}

          {xs.map((i) => {
            const cw = (sx(1) - sx(0)) * 0.85;
            const cx = sx(i + 0.075);
            if (data.charge[i] > 0) {
              const top = syPower(data.charge[i]);
              return <rect key={"c" + i} x={cx} y={top} width={cw} height={baseY - top} fill="hsl(var(--acc))" opacity="0.85" />;
            }
            if (data.discharge[i] > 0) {
              const ht = syPower(0) - syPower(data.discharge[i]);
              return <rect key={"d" + i} x={cx} y={baseY} width={cw} height={ht} fill="hsl(var(--amber))" opacity="0.9" />;
            }
            return null;
          })}

          <line x1={pad.l} x2={w - pad.r} y1={baseY} y2={baseY} stroke="hsl(var(--line-strong))" />

          {showForecast && data.p10 && data.p90 && (
            <path d={areaP(xs, data.p10, data.p90, sx, sy)} fill="url(#forecast-band)" stroke="none" />
          )}

          <path d={areaP(xs, data.realized.map(() => pMin), data.realized, sx, sy)} fill="url(#dispatch-area)" stroke="none" />
          <path d={lineP(xs, data.realized, sx, sy)} stroke="hsl(var(--blue))" strokeWidth="1.5" fill="none" />

          {showForecast && data.forecast && (
            <path d={lineP(xs, data.forecast, sx, sy)} stroke="hsl(var(--magenta))" strokeWidth="1.25" strokeDasharray="3 3" fill="none" />
          )}

          {showSoc && (
            <>
              <path d={lineP(xs, data.soc, sx, sySoc)} stroke="hsl(var(--acc))" strokeWidth="1.25" fill="none" opacity="0.85" />
              <text x={w - pad.r + 6} y={pad.t - 4} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--acc))" textAnchor="start">
                SoC
              </text>
            </>
          )}
          <text x={pad.l - 6} y={pad.t - 4} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">
            €/MWh
          </text>
        </svg>
      )}
    </div>
  );
}

export function ProfitChart({
  periodProfit, cumProfit, height = 200,
}: { periodProfit: number[]; cumProfit: number[]; height?: number }) {
  const { ref, w } = useSize<HTMLDivElement>();
  const pad = { l: 38, r: 56, t: 14, b: 26 };
  const N = periodProfit.length;
  const sx = scale([0, N], [pad.l, w - pad.r]);
  const pMin = Math.min(...periodProfit, 0);
  const pMax = Math.max(...periodProfit, 0);
  const sy = scale([pMin * 1.2, pMax * 1.2 || 1], [height - pad.b, pad.t]);
  const cMin = Math.min(...cumProfit, 0);
  const cMax = Math.max(...cumProfit) * 1.05 || 1;
  const sCum = scale([cMin, cMax], [height - pad.b, pad.t]);
  const baseY = sy(0);
  const xs = periodProfit.map((_, i) => i);

  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {w > 0 && (
        <svg width={w} height={height}>
          <line x1={pad.l} x2={w - pad.r} y1={baseY} y2={baseY} stroke="hsl(var(--line-strong))" />
          {[0, 4, 8, 12, 16, 20, 24].map((h0) => {
            const i = h0 * 4;
            return (
              <g key={h0}>
                <line x1={sx(i)} x2={sx(i)} y1={pad.t} y2={height - pad.b} stroke="hsl(var(--line))" strokeDasharray="2 4" opacity="0.4" />
                <text x={sx(i)} y={height - pad.b + 14} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="middle">
                  {String(h0).padStart(2, "0")}
                </text>
              </g>
            );
          })}
          {xs.map((i) => {
            const v = periodProfit[i];
            if (Math.abs(v) < 0.5) return null;
            const cw = (sx(1) - sx(0)) * 0.85;
            const cx = sx(i + 0.075);
            const top = v >= 0 ? sy(v) : baseY;
            const ht = Math.abs(sy(v) - baseY);
            return <rect key={i} x={cx} y={top} width={cw} height={ht} fill={v >= 0 ? "hsl(var(--acc))" : "hsl(var(--red))"} opacity="0.7" />;
          })}
          <path d={lineP(xs, cumProfit, sx, sCum)} stroke="hsl(var(--amber))" strokeWidth="1.5" fill="none" />
          <text x={w - pad.r + 6} y={sCum(cumProfit[cumProfit.length - 1]) + 3} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--amber))" textAnchor="start">
            €{Math.round(cumProfit[cumProfit.length - 1]).toLocaleString()}
          </text>
          <text x={pad.l - 6} y={pad.t - 4} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">€/MTU</text>
        </svg>
      )}
    </div>
  );
}

export function FanChart({
  timestamps, p10, p50, p90, realized, height = 280,
}: {
  timestamps: string[];
  p10: number[]; p50: number[]; p90: number[];
  realized?: number[];
  height?: number;
}) {
  const { ref, w } = useSize<HTMLDivElement>();
  const pad = { l: 44, r: 16, t: 14, b: 28 };
  const N = p50.length;
  const sx = scale([0, Math.max(1, N - 1)], [pad.l, w - pad.r]);
  const all = [...p10, ...p90, ...(realized || [])];
  const pMin = Math.min(...all, 0);
  const pMax = Math.max(...all, 1) * 1.08;
  const sy = scale([pMin, pMax], [height - pad.b, pad.t]);
  const xs = p50.map((_, i) => i);

  const yTicks = 5;
  const ticks = Array.from({ length: yTicks + 1 }, (_, i) => pMin + ((pMax - pMin) * i) / yTicks);
  const xTickIdx: number[] = [];
  const tickEvery = Math.max(1, Math.round(N / 8));
  for (let i = 0; i < N; i += tickEvery) xTickIdx.push(i);

  const fmtTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  };

  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {w > 0 && N > 0 && (
        <svg width={w} height={height}>
          <defs>
            <linearGradient id="fan-band" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--magenta))" stopOpacity="0.32" />
              <stop offset="100%" stopColor="hsl(var(--magenta))" stopOpacity="0.08" />
            </linearGradient>
          </defs>

          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={pad.l} x2={w - pad.r} y1={sy(t)} y2={sy(t)} stroke="hsl(var(--line))" strokeDasharray="2 4" />
              <text x={pad.l - 6} y={sy(t) + 3} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">
                {t.toFixed(0)}
              </text>
            </g>
          ))}

          {xTickIdx.map((i) => (
            <g key={i}>
              <line x1={sx(i)} x2={sx(i)} y1={pad.t} y2={height - pad.b} stroke="hsl(var(--line))" strokeDasharray="2 4" opacity="0.4" />
              <text x={sx(i)} y={height - pad.b + 14} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="middle">
                {timestamps[i] ? fmtTime(timestamps[i]) : i}
              </text>
            </g>
          ))}

          {/* P10–P90 band */}
          <path d={areaP(xs, p10, p90, sx, sy)} fill="url(#fan-band)" stroke="none" />
          {/* P10 / P90 outlines */}
          <path d={lineP(xs, p10, sx, sy)} stroke="hsl(var(--magenta))" strokeWidth="0.9" strokeDasharray="3 3" fill="none" opacity="0.7" />
          <path d={lineP(xs, p90, sx, sy)} stroke="hsl(var(--magenta))" strokeWidth="0.9" strokeDasharray="3 3" fill="none" opacity="0.7" />
          {/* P50 median */}
          <path d={lineP(xs, p50, sx, sy)} stroke="hsl(var(--magenta))" strokeWidth="1.6" fill="none" />

          {realized && realized.length > 0 && (
            <path d={lineP(realized.map((_, i) => i), realized, sx, sy)} stroke="hsl(var(--blue))" strokeWidth="1.5" fill="none" />
          )}

          <text x={pad.l - 6} y={pad.t - 4} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">
            €/MWh
          </text>
        </svg>
      )}
    </div>
  );
}

export function ScenarioChart({
  scenarios, realized, forecast, height = 240,
}: { scenarios: number[][]; realized?: number[]; forecast?: number[]; height?: number }) {
  const { ref, w } = useSize<HTMLDivElement>();
  const pad = { l: 38, r: 14, t: 14, b: 26 };
  const N = scenarios[0]?.length ?? 0;
  const sx = scale([0, N], [pad.l, w - pad.r]);
  const all = scenarios.flat().concat(realized || []);
  const pMax = Math.max(...all, 1) * 1.05;
  const sy = scale([0, pMax], [height - pad.b, pad.t]);
  const xs = scenarios[0]?.map((_, i) => i) ?? [];
  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {w > 0 && N > 0 && (
        <svg width={w} height={height}>
          {[0, 50, 100, 150, 200].filter((t) => t <= pMax).map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={w - pad.r} y1={sy(t)} y2={sy(t)} stroke="hsl(var(--line))" strokeDasharray="2 4" />
              <text x={pad.l - 6} y={sy(t) + 3} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">{t}</text>
            </g>
          ))}
          {[0, 6, 12, 18, 24].map((h0) => (
            <text key={h0} x={sx(h0 * 4)} y={height - pad.b + 14} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="middle">
              {String(h0).padStart(2, "0")}:00
            </text>
          ))}
          {scenarios.map((s, k) => (
            <path key={k} d={lineP(xs, s, sx, sy)} stroke="hsl(var(--magenta))" strokeWidth="0.7" fill="none" opacity="0.22" />
          ))}
          {forecast && <path d={lineP(xs, forecast, sx, sy)} stroke="hsl(var(--magenta))" strokeWidth="1.5" fill="none" />}
          {realized && <path d={lineP(xs, realized, sx, sy)} stroke="hsl(var(--blue))" strokeWidth="1.5" fill="none" />}
        </svg>
      )}
    </div>
  );
}

export function EquityChart({
  equity, height = 280,
}: { equity: { batteryOS: number[]; naive: number[]; perfect: number[] }; height?: number }) {
  const { ref, w } = useSize<HTMLDivElement>();
  const pad = { l: 50, r: 16, t: 14, b: 26 };
  const N = equity.batteryOS.length;
  const sx = scale([0, N - 1], [pad.l, w - pad.r]);
  const all = [...equity.batteryOS, ...equity.naive, ...equity.perfect];
  const pMin = Math.min(...all, 0), pMax = Math.max(...all) * 1.05;
  const sy = scale([pMin, pMax], [height - pad.b, pad.t]);
  const xs = equity.batteryOS.map((_, i) => i);
  const ticks = [0, 1, 2, 3].map((i) => Math.round((pMax * i) / 3));
  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {w > 0 && (
        <svg width={w} height={height}>
          <defs>
            <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--acc))" stopOpacity="0.16" />
              <stop offset="100%" stopColor="hsl(var(--acc))" stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={w - pad.r} y1={sy(t)} y2={sy(t)} stroke="hsl(var(--line))" strokeDasharray="2 4" />
              <text x={pad.l - 6} y={sy(t) + 3} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">
                €{(t / 1e6).toFixed(2)}M
              </text>
            </g>
          ))}
          {[0, 30, 60, 89].map((d) => (
            <text key={d} x={sx(d)} y={height - pad.b + 14} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="middle">
              D{d + 1}
            </text>
          ))}
          <path d={areaP(xs, equity.batteryOS.map(() => 0), equity.batteryOS, sx, sy)} fill="url(#eq-fill)" />
          <path d={lineP(xs, equity.perfect, sx, sy)} stroke="hsl(var(--fg-3))" strokeWidth="1" strokeDasharray="3 3" fill="none" />
          <path d={lineP(xs, equity.naive, sx, sy)} stroke="hsl(var(--magenta))" strokeWidth="1" fill="none" />
          <path d={lineP(xs, equity.batteryOS, sx, sy)} stroke="hsl(var(--acc))" strokeWidth="1.6" fill="none" />
        </svg>
      )}
    </div>
  );
}

export function Heatmap({ matrix, height = 240 }: { matrix: number[][]; height?: number }) {
  const { ref, w } = useSize<HTMLDivElement>();
  const pad = { l: 30, r: 10, t: 14, b: 24 };
  const rows = matrix.length;
  const cols = matrix[0]?.length ?? 0;
  if (rows === 0) return <div ref={ref} style={{ width: "100%", height }} />;
  const cw = (w - pad.l - pad.r) / cols;
  const ch = (height - pad.t - pad.b) / rows;
  const all = matrix.flat();
  const min = Math.min(...all), max = Math.max(...all);
  const norm = (v: number) => (v - min) / (max - min || 1);
  const colorFor = (v: number) => {
    const n = norm(v);
    if (n < 0.4) return `hsla(215,100%,71%,${0.15 + n * 0.6})`;
    if (n < 0.7) return `hsla(152,100%,71%,${0.2 + (n - 0.4) * 1.2})`;
    return `hsla(35,100%,64%,${0.5 + (n - 0.7) * 1.6})`;
  };
  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {w > 0 && (
        <svg width={w} height={height}>
          {[0, 6, 12, 18, 23].map((h0) => (
            <text key={h0} x={pad.l + h0 * cw + cw / 2} y={height - pad.b + 14} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="middle">
              {String(h0).padStart(2, "0")}h
            </text>
          ))}
          {[0, 10, 20, 29].map((d) => (
            <text key={d} x={pad.l - 6} y={pad.t + d * ch + ch / 2 + 3} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">
              D{d + 1}
            </text>
          ))}
          {matrix.map((row, r) =>
            row.map((v, c) => (
              <rect key={r + "-" + c} x={pad.l + c * cw} y={pad.t + r * ch} width={cw - 0.5} height={ch - 0.5} fill={colorFor(v)} rx={0.5} />
            ))
          )}
        </svg>
      )}
    </div>
  );
}

export function Histogram({
  values, bins = 18, height = 180, color = "hsl(var(--acc))",
}: { values: number[]; bins?: number; height?: number; color?: string }) {
  const { ref, w } = useSize<HTMLDivElement>();
  const pad = { l: 30, r: 12, t: 14, b: 26 };
  if (!values.length) return <div ref={ref} style={{ width: "100%", height }} />;
  const min = Math.min(...values), max = Math.max(...values);
  const step = (max - min) / bins || 1;
  const counts = new Array(bins).fill(0);
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v - min) / step)));
    counts[idx]++;
  }
  const cMax = Math.max(...counts);
  const sx = scale([0, bins], [pad.l, w - pad.r]);
  const sy = scale([0, cMax], [height - pad.b, pad.t]);
  const bw = (w - pad.l - pad.r) / bins;
  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {w > 0 && (
        <svg width={w} height={height}>
          <line x1={pad.l} x2={w - pad.r} y1={sy(0)} y2={sy(0)} stroke="hsl(var(--line-strong))" />
          {counts.map((c, i) => (
            <rect key={i} x={sx(i) + 1} y={sy(c)} width={bw - 2} height={sy(0) - sy(c)} fill={color} opacity="0.75" />
          ))}
          <text x={pad.l} y={height - pad.b + 14} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))">
            €{Math.round(min).toLocaleString()}
          </text>
          <text x={w - pad.r} y={height - pad.b + 14} fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="end">
            €{Math.round(max).toLocaleString()}
          </text>
        </svg>
      )}
    </div>
  );
}

export function BulletBar({ value, max, color = "hsl(var(--acc))", height = 6 }: { value: number; max: number; color?: string; height?: number }) {
  const pct = Math.max(0, Math.min(1, value / max));
  return (
    <div style={{ height, background: "hsl(var(--bg-3))", borderRadius: 2, overflow: "hidden", flex: 1 }}>
      <div style={{ width: pct * 100 + "%", height: "100%", background: color, borderRadius: 2 }} />
    </div>
  );
}

export function BatteryGauge({ socMWh, energyMWh }: { socMWh: number; energyMWh: number }) {
  const pct = Math.max(0, Math.min(1, socMWh / energyMWh));
  return (
    <div style={{ width: 80, flex: "0 0 80px" }}>
      <svg width="80" height="120" viewBox="0 0 80 120">
        <rect x="20" y="6" width="40" height="6" rx="1" fill="hsl(var(--bg-4))" />
        <rect x="10" y="14" width="60" height="100" rx="3" stroke="hsl(var(--line-strong))" strokeWidth="1.5" fill="hsl(var(--bg-2))" />
        <rect x="14" y={14 + 4 + (1 - pct) * 92} width="52" height={pct * 92} fill="hsl(var(--acc))" opacity="0.85" rx="2" />
        <text x="40" y="68" fontSize="14" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-0))" textAnchor="middle" fontWeight="500">
          {Math.round(pct * 100)}%
        </text>
        <text x="40" y="84" fontSize="9" fontFamily="IBM Plex Mono" fill="hsl(var(--fg-3))" textAnchor="middle">
          {socMWh.toFixed(0)}/{energyMWh} MWh
        </text>
      </svg>
    </div>
  );
}
