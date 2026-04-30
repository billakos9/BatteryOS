import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Icon } from "@/components/bos/Primitives";
import { useBatteries } from "@/lib/api";
import { useBosStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const NAV = [
  { id: "dashboard", to: "/",           label: "Dashboard",    icon: "grid",     group: "Overview" },
  { id: "forecaster", to: "/forecaster", label: "Forecaster",   icon: "activity", group: "Analytics" },
  { id: "optimizer", to: "/optimizer",  label: "Optimizer",    icon: "sliders",  group: "Analytics" },
  { id: "backtest",  to: "/backtest",   label: "Backtest",     icon: "history",  group: "Analytics" },
  { id: "assets",    to: "/assets",     label: "Assets",       icon: "battery",  group: "Operations" },
] as const;

const LABEL_BY_PATH: Record<string, { label: string; group: string }> = NAV.reduce(
  (m, n) => ({ ...m, [n.to]: { label: n.label, group: n.group } }),
  {}
);

export default function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const meta = LABEL_BY_PATH[location.pathname] ?? { label: "Dashboard", group: "Overview" };
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Hydrate the asset store from /api/batteries on every shell mount.
  // No synthetic seed: pages render against backend-driven profiles only.
  const { data: backendBatteries } = useBatteries();
  const hydrateAssets = useBosStore((s) => s.hydrateAssets);
  useEffect(() => {
    if (backendBatteries && backendBatteries.length > 0) hydrateAssets(backendBatteries);
  }, [backendBatteries, hydrateAssets]);

  const groups: Record<string, typeof NAV[number][]> = {};
  NAV.forEach((n) => ((groups[n.group] = groups[n.group] || []).push(n)));

  useEffect(() => {
    const saved = window.localStorage.getItem("batteryos.sidebar.open");
    if (saved !== null) setSidebarOpen(saved === "true");
  }, []);

  useEffect(() => {
    window.localStorage.setItem("batteryos.sidebar.open", String(sidebarOpen));
  }, [sidebarOpen]);

  return (
    <div
      className={cn("grid min-h-screen", !sidebarOpen && "bos-shell-collapsed")}
      style={{ gridTemplateColumns: sidebarOpen ? "220px 1fr" : "72px 1fr" }}
    >
      {/* Sidebar */}
      <aside className="sticky top-0 flex h-screen flex-col overflow-auto border-r border-line bg-bg-1 py-[18px]">
        <div className={cn("flex items-center gap-2.5 px-[18px] pb-[22px] pt-1.5 text-[16px] font-semibold tracking-[-0.02em] text-fg-0", !sidebarOpen && "justify-center px-3")}>
          <span
            className="grid h-[22px] w-[22px] place-items-center rounded-[3px] font-mono-tnum text-[12px] font-semibold"
            style={{ background: "hsl(var(--acc))", color: "hsl(var(--bg-0))", boxShadow: "0 0 18px hsla(152,100%,71%,0.35)" }}
          >
            B
          </span>
          {sidebarOpen && <span>BatteryOS</span>}
          {sidebarOpen && <span className="ml-auto font-mono-tnum text-[9px] uppercase tracking-[0.12em] text-fg-3">v1.0</span>}
        </div>

        {Object.entries(groups).map(([g, items]) => (
          <div key={g}>
            <div className={cn("px-[18px] pb-1.5 pt-[18px] font-mono-tnum text-[9px] uppercase tracking-[0.16em] text-fg-3", !sidebarOpen && "px-0 text-center")}>
              {sidebarOpen ? g : "•"}
            </div>
            {items.map((n) => (
              <NavLink
                key={n.id}
                to={n.to}
                end={n.to === "/"}
                title={!sidebarOpen ? n.label : undefined}
                className={({ isActive }) => cn("sb-link", !sidebarOpen && "collapsed", isActive && "active")}
              >
                <Icon name={n.icon as never} size={14} className="text-fg-3" />
                {sidebarOpen && <span>{n.label}</span>}
                {sidebarOpen && n.id === "optimizer" && <span className="ml-auto font-mono-tnum text-[9px] tracking-[0.06em] text-fg-3">⌘O</span>}
              </NavLink>
            ))}
          </div>
        ))}

        <div className={cn("mt-auto flex items-center gap-2 border-t border-line px-[18px] py-3.5 font-mono-tnum text-[10px] text-fg-3", !sidebarOpen && "justify-center px-3")}>
          <span className="h-1.5 w-1.5 rounded-full bg-acc" style={{ boxShadow: "0 0 8px hsl(var(--acc))" }} />
          {sidebarOpen ? (
            <>
              <span>HEnEx · live</span>
              <span className="ml-auto">EEST</span>
            </>
          ) : null}
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-col">
        {/* Topbar */}
        <div className="sticky top-0 z-10 flex h-14 items-center gap-4 border-b border-line bg-bg-0 px-6">
          <button className="bos-btn ghost" onClick={() => setSidebarOpen((open) => !open)} title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}>
            <Icon name={sidebarOpen ? "chevL" : "chevR"} size={12} />
          </button>
          <div className="flex items-center gap-2 font-mono-tnum text-[11px] tracking-[0.04em] text-fg-3">
            <span>BatteryOS</span>
            <Icon name="chevR" size={11} />
            <span>{meta.group}</span>
            <Icon name="chevR" size={11} />
            <span className="text-fg-0">{meta.label}</span>
          </div>
          <div className="flex-1" />
          <div className="bos-pill">
            <span
              className="block h-[18px] w-[18px] rounded-full"
              style={{ background: "linear-gradient(135deg, hsl(var(--acc)), hsl(var(--blue)))" }}
            />
            ops@batteryos.gr
            <Icon name="chevD" size={11} />
          </div>
        </div>

        <main className="w-full max-w-[1480px] px-8 pb-16 pt-7">{children}</main>
      </div>
    </div>
  );
}
