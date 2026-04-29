import { forwardRef, useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// ============ ICONS (inline SVG, single stroke) ============
type IconName =
  | "grid" | "activity" | "sliders" | "history" | "battery" | "database"
  | "chevR" | "chevD" | "plus" | "play" | "refresh" | "download" | "settings"
  | "bolt" | "flow" | "target" | "bell" | "search" | "sun" | "wind" | "trash"
  | "edit" | "pause" | "check" | "x" | "info" | "save" | "arrowR";

export function Icon({ name, size = 14, className = "" }: { name: IconName; size?: number; className?: string }) {
  const common = {
    width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
    className,
  };
  const paths: Record<IconName, ReactNode> = {
    grid: <g><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></g>,
    activity: <polyline points="3 12 7 12 10 4 14 20 17 12 21 12"/>,
    sliders: <g><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="7" cy="18" r="2"/></g>,
    history: <polyline points="3 12 6 12 8 6 12 18 14 9 16 12 21 12"/>,
    battery: <g><rect x="3" y="8" width="16" height="8" rx="1"/><line x1="21" y1="11" x2="21" y2="13"/><rect x="5" y="10" width="3" height="4" fill="currentColor" stroke="none"/><rect x="9" y="10" width="3" height="4" fill="currentColor" stroke="none"/></g>,
    database: <g><ellipse cx="12" cy="5" rx="8" ry="2.5"/><path d="M4 5v6c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5V5"/><path d="M4 11v6c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-6"/></g>,
    chevR: <polyline points="9 6 15 12 9 18"/>,
    chevD: <polyline points="6 9 12 15 18 9"/>,
    plus: <g><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></g>,
    play: <polygon points="6 4 20 12 6 20 6 4"/>,
    refresh: <g><polyline points="3 12 3 7 8 7"/><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/></g>,
    download: <g><line x1="12" y1="4" x2="12" y2="14"/><polyline points="8 11 12 15 16 11"/><line x1="4" y1="20" x2="20" y2="20"/></g>,
    settings: <g><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1A2 2 0 1 1 4.4 17l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1A2 2 0 1 1 7 4.4l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></g>,
    bolt: <polygon points="13 2 4 14 12 14 11 22 20 10 12 10 13 2"/>,
    flow: <path d="M3 6h12a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h12"/>,
    target: <g><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></g>,
    bell: <g><path d="M18 16v-5a6 6 0 1 0-12 0v5l-2 2h16z"/><path d="M10 21a2 2 0 0 0 4 0"/></g>,
    search: <g><circle cx="11" cy="11" r="7"/><line x1="16" y1="16" x2="20" y2="20"/></g>,
    sun: <g><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="5" y1="5" x2="6.5" y2="6.5"/><line x1="17.5" y1="17.5" x2="19" y2="19"/><line x1="5" y1="19" x2="6.5" y2="17.5"/><line x1="17.5" y1="6.5" x2="19" y2="5"/></g>,
    wind: <g><path d="M3 8h11a3 3 0 1 0-3-3"/><path d="M3 16h15a3 3 0 1 1-3 3"/><path d="M3 12h6"/></g>,
    trash: <g><polyline points="4 7 20 7"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/></g>,
    edit: <g><path d="M4 20h4l11-11-4-4L4 16v4z"/><line x1="13" y1="6" x2="18" y2="11"/></g>,
    pause: <g><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></g>,
    check: <polyline points="4 12 10 18 20 6"/>,
    x: <g><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></g>,
    info: <g><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><circle cx="12" cy="8" r="0.5" fill="currentColor"/></g>,
    save: <g><path d="M5 3h11l3 3v15H5z"/><polyline points="8 3 8 9 15 9 15 3"/><rect x="8" y="14" width="8" height="6"/></g>,
    arrowR: <g><line x1="4" y1="12" x2="20" y2="12"/><polyline points="14 6 20 12 14 18"/></g>,
  };
  return <svg {...common}>{paths[name]}</svg>;
}

// ============ HOOK ============
export function useSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0].contentRect;
      setSize({ w: cr.width, h: cr.height });
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return { ref, ...size };
}

// ============ CARD / KPI / TAG / SEG / TOGGLE / SLIDER ============
export const Card = forwardRef<HTMLDivElement, {
  title?: ReactNode; meta?: ReactNode; actions?: ReactNode; children?: ReactNode;
  foot?: ReactNode; flush?: boolean; className?: string;
}>(function Card({ title, meta, actions, children, foot, flush, className }, ref) {
  return (
    <div ref={ref} className={cn("bos-card", className)}>
      {(title || actions) && (
        <div className="bos-card-head">
          {title && <h3>{title}</h3>}
          {meta && <span className="bos-card-meta">{meta}</span>}
          {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
        </div>
      )}
      <div className={cn("bos-card-body", flush && "flush")}>{children}</div>
      {foot && <div className="border-t border-line px-4 py-2.5 font-mono-tnum text-[10px] text-fg-3">{foot}</div>}
    </div>
  );
});

export function KPI({
  label, value, unit, delta, sub, featured, spark,
}: {
  label: ReactNode; value: ReactNode; unit?: ReactNode;
  delta?: { tone: "up" | "down" | "neu"; text: ReactNode };
  sub?: ReactNode; featured?: boolean; spark?: ReactNode;
}) {
  return (
    <div className={cn("bos-kpi", featured && "featured")}>
      <div className="label">
        {label}
        {sub && <span className="ml-auto text-[10px] tracking-normal normal-case text-fg-3">{sub}</span>}
      </div>
      <div className="v">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {delta && (
        <div className={cn("delta", delta.tone)}>
          {delta.tone === "up" && "▲ "}
          {delta.tone === "down" && "▼ "}
          {delta.text}
        </div>
      )}
      {spark && <div className="mt-2.5 h-7">{spark}</div>}
    </div>
  );
}

export const Tag = forwardRef<HTMLSpanElement, { tone?: "acc" | "amber" | "red" | "mag" | "blue"; dot?: boolean; children: ReactNode; className?: string }>(
  function Tag({ tone, dot, children, className }, ref) {
    return (
      <span ref={ref} className={cn("bos-tag", tone, className)}>
        {dot && <span className="dot" />}
        {children}
      </span>
    );
  }
);

export function Seg<T extends string>({
  value, onChange, options,
}: { value: T; onChange: (v: T) => void; options: { v: T; l: string }[] }) {
  return (
    <div className="bos-seg">
      {options.map((o) => (
        <span key={o.v} className={cn("opt", value === o.v && "on")} onClick={() => onChange(o.v)}>
          {o.l}
        </span>
      ))}
    </div>
  );
}

export function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return <span className={cn("bos-toggle", on && "on")} onClick={() => onChange(!on)} />;
}

export function Slider({
  min, max, step, value, onChange,
}: { min: number; max: number; step: number; value: number; onChange: (v: number) => void }) {
  return (
    <input
      className="bos-slider"
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(parseFloat(e.target.value))}
    />
  );
}

export function ParamRow({
  label, hint, value, children,
}: { label: ReactNode; hint?: ReactNode; value: ReactNode; children: ReactNode }) {
  return (
    <div className="param-row">
      <span className="lbl">
        {label}
        {hint && <span className="hint">{hint}</span>}
      </span>
      {children}
      <span className="val">{value}</span>
    </div>
  );
}

export function StatusDot({ s }: { s: "ok" | "warn" | "err" }) {
  return <span className={cn("sdot", s)} />;
}

export function Legend({ items }: { items: { color: string; label: string; bar?: boolean; dashed?: boolean }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-4 text-[10px] font-mono-tnum text-fg-2">
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1.5">
          <span
            className="inline-block"
            style={{
              width: it.bar ? 4 : 10,
              height: it.bar ? 8 : 2,
              background: it.dashed ? "transparent" : it.color,
              borderTop: it.dashed ? `1px dashed ${it.color}` : undefined,
            }}
          />
          {it.label}
        </span>
      ))}
    </div>
  );
}
