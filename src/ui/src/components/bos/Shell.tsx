import { NavLink, useLocation } from "react-router-dom";
import { Icon } from "@/components/bos/Primitives";
import { ticker } from "@/lib/data";
import { cn } from "@/lib/utils";

const NAV = [
  { id: "dashboard", to: "/",           label: "Dashboard",    icon: "grid",     group: "Overview" },
  { id: "forecaster", to: "/forecaster", label: "Forecaster",   icon: "activity", group: "Analytics" },
  { id: "optimizer", to: "/optimizer",  label: "Optimizer",    icon: "sliders",  group: "Analytics" },
  { id: "backtest",  to: "/backtest",   label: "Backtest",     icon: "history",  group: "Analytics" },
  { id: "assets",    to: "/assets",     label: "Assets",       icon: "battery",  group: "Operations" },
  { id: "sources",   to: "/sources",    label: "Data Sources", icon: "database", group: "Operations" },
] as const;

const LABEL_BY_PATH: Record<string, { label: string; group: string }> = NAV.reduce(
  (m, n) => ({ ...m, [n.to]: { label: n.label, group: n.group } }),
  {}
);

export default function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const meta = LABEL_BY_PATH[location.pathname] ?? { label: "Dashboard", group: "Overview" };

  const groups: Record<string, typeof NAV[number][]> = {};
  NAV.forEach((n) => ((groups[n.group] = groups[n.group] || []).push(n)));

  return (
    <div className="grid min-h-screen" style={{ gridTemplateColumns: "220px 1fr" }}>
      {/* Sidebar */}
      <aside className="sticky top-0 flex h-screen flex-col overflow-auto border-r border-line bg-bg-1 py-[18px]">
        <div className="flex items-center gap-2.5 px-[18px] pb-[22px] pt-1.5 text-[16px] font-semibold tracking-[-0.02em] text-fg-0">
          <span
            className="grid h-[22px] w-[22px] place-items-center rounded-[3px] font-mono-tnum text-[12px] font-semibold"
            style={{ background: "hsl(var(--acc))", color: "hsl(var(--bg-0))", boxShadow: "0 0 18px hsla(152,100%,71%,0.35)" }}
          >
            B
          </span>
          <span>BatteryOS</span>
          <span className="ml-auto font-mono-tnum text-[9px] uppercase tracking-[0.12em] text-fg-3">v1.0</span>
        </div>

        {Object.entries(groups).map(([g, items]) => (
          <div key={g}>
            <div className="px-[18px] pb-1.5 pt-[18px] font-mono-tnum text-[9px] uppercase tracking-[0.16em] text-fg-3">{g}</div>
            {items.map((n) => (
              <NavLink key={n.id} to={n.to} end={n.to === "/"} className={({ isActive }) => cn("sb-link", isActive && "active")}>
                <Icon name={n.icon as never} size={14} className="text-fg-3" />
                <span>{n.label}</span>
                {n.id === "optimizer" && <span className="ml-auto font-mono-tnum text-[9px] tracking-[0.06em] text-fg-3">⌘O</span>}
              </NavLink>
            ))}
          </div>
        ))}

        <div className="mt-auto flex items-center gap-2 border-t border-line px-[18px] py-3.5 font-mono-tnum text-[10px] text-fg-3">
          <span className="h-1.5 w-1.5 rounded-full bg-acc" style={{ boxShadow: "0 0 8px hsl(var(--acc))" }} />
          <span>HEnEx · live</span>
          <span className="ml-auto">EEST</span>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-col">
        {/* Topbar */}
        <div className="sticky top-0 z-10 flex h-14 items-center gap-4 border-b border-line bg-bg-0 px-6">
          <div className="flex items-center gap-2 font-mono-tnum text-[11px] tracking-[0.04em] text-fg-3">
            <span>BatteryOS</span>
            <Icon name="chevR" size={11} />
            <span>{meta.group}</span>
            <Icon name="chevR" size={11} />
            <span className="text-fg-0">{meta.label}</span>
          </div>
          <div className="flex-1" />
          <div className="bos-pill ghost"><Icon name="search" size={12} />Search runs, assets…</div>
          <div className="bos-pill"><span className="dot" />Solver: HiGHS</div>
          <div className="bos-pill"><Icon name="bell" size={12} />3</div>
          <div className="bos-pill">
            <span
              className="block h-[18px] w-[18px] rounded-full"
              style={{ background: "linear-gradient(135deg, hsl(var(--acc)), hsl(var(--blue)))" }}
            />
            ops@batteryos.gr
            <Icon name="chevD" size={11} />
          </div>
        </div>

        {/* Ticker */}
        <div className="bos-ticker">
          {ticker.concat(ticker).map((t, i) => (
            <span key={i} className="it">
              <span className="text-fg-3">{t.l}</span>
              <span className="v">{t.v}</span>
              <span className={cn("d", t.up === true && "up", t.up === false && "down")}>{t.d}</span>
            </span>
          ))}
        </div>

        <main className="w-full max-w-[1480px] px-8 pb-16 pt-7">{children}</main>
      </div>
    </div>
  );
}
