import { create } from "zustand";
import { persist } from "zustand/middleware";
import { defaultAssets } from "./data";
import type { BatteryAsset, OptimizerParams, OptimizerRun } from "./types";

interface BosState {
  assets: BatteryAsset[];
  selectedAssetId: string;
  optimizer: OptimizerParams;
  runs: OptimizerRun[];

  setSelectedAsset: (id: string) => void;
  upsertAsset: (a: BatteryAsset) => void;
  removeAsset: (id: string) => void;
  resetAssets: () => void;
  toggleAssetStatus: (id: string) => void;

  setOptimizer: (patch: Partial<OptimizerParams>) => void;
  resetOptimizer: () => void;
  recordRun: (r: OptimizerRun) => void;
}

const defaultOptimizer: OptimizerParams = {
  assetId: "liion_100_2h",
  riskProfile: "balanced",
  lambda: 0.35,
  alpha: 0.10,
  cyclesCap: 1.5,
  eff: 0.949,
  agingCost: 2.0,
  terminalSoc: "free",
  robust: true,
  scenarios: 20,
  solver: "HiGHS",
  socStartPct: 0.5,
  gateCloseHour: 12,
};

const seedRuns: OptimizerRun[] = [
  { id: "run-2042", time: "12:48", day: "2026-04-29", assetId: "liion_100_2h", lambda: 0.5, profit: 29443, status: "Optimal", capture: 0.72 },
  { id: "run-2041", time: "12:31", day: "2026-04-29", assetId: "liion_200_2h", lambda: 0.5, profit: 58812, status: "Optimal", capture: 0.71 },
  { id: "run-2040", time: "12:18", day: "2026-04-28", assetId: "liion_100_2h", lambda: 0.7, profit: 26701, status: "Optimal", capture: 0.69 },
  { id: "run-2039", time: "11:54", day: "2026-04-28", assetId: "phs_100_8h",   lambda: 0.5, profit: 18430, status: "Optimal", capture: 0.78 },
  { id: "run-2038", time: "11:22", day: "2026-04-27", assetId: "liion_100_2h", lambda: 0.0, profit: 31102, status: "Optimal", capture: 0.65 },
  { id: "run-2037", time: "10:58", day: "2026-04-27", assetId: "flow_100_6h",  lambda: 0.5, profit: 14820, status: "Suboptimal", capture: 0.61 },
];

export const useBosStore = create<BosState>()(
  persist(
    (set) => ({
      assets: defaultAssets,
      selectedAssetId: "liion_100_2h",
      optimizer: defaultOptimizer,
      runs: seedRuns,

      setSelectedAsset: (id) =>
        set((s) => ({
          selectedAssetId: id,
          optimizer: { ...s.optimizer, assetId: id },
        })),

      upsertAsset: (a) =>
        set((s) => {
          const idx = s.assets.findIndex((x) => x.id === a.id);
          const next = idx >= 0 ? s.assets.map((x, i) => (i === idx ? a : x)) : [...s.assets, a];
          return { assets: next };
        }),

      removeAsset: (id) =>
        set((s) => {
          const next = s.assets.filter((x) => x.id !== id);
          const sel = s.selectedAssetId === id ? next[0]?.id ?? "" : s.selectedAssetId;
          return {
            assets: next,
            selectedAssetId: sel,
            optimizer: { ...s.optimizer, assetId: sel },
          };
        }),

      resetAssets: () => set({ assets: defaultAssets }),

      toggleAssetStatus: (id) =>
        set((s) => ({
          assets: s.assets.map((a) =>
            a.id === id ? { ...a, status: a.status === "active" ? "paused" : "active" } : a
          ),
        })),

      setOptimizer: (patch) => set((s) => ({ optimizer: { ...s.optimizer, ...patch } })),
      resetOptimizer: () => set((s) => ({ optimizer: { ...defaultOptimizer, assetId: s.selectedAssetId } })),

      recordRun: (r) => set((s) => ({ runs: [r, ...s.runs].slice(0, 30) })),
    }),
    {
      name: "batteryos-store-v1",
      version: 2,
      migrate: (persistedState: unknown) => {
        const state = persistedState as Partial<BosState> & { optimizer?: Partial<OptimizerParams> };
        const optimizer = { ...defaultOptimizer, ...state.optimizer };
        if (!optimizer.riskProfile) {
          optimizer.riskProfile = "custom";
        }
        return {
          ...state,
          optimizer,
        } as BosState;
      },
    }
  )
);
