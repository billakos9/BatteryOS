/**
 * Single backend API client. Every visualization in the UI must read
 * from these hooks — no synthetic data is allowed in components.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { BatteryAsset } from "./types";

export interface SourceRow {
  id: string;
  name: string;
  desc: string;
  status: "ok" | "warn" | "err";
  latency: string;
  rows: string;
  lastSync: string;
  latency_minutes?: number | null;
  rows_24h?: number | null;
  last_sync_iso?: string | null;
  feature_freshness_minutes?: number | null;
}

export interface SourcesPayload {
  generated_at?: string;
  source?: string;
  sources: SourceRow[];
}

export interface TickerRow {
  l: string;
  v: string;
  d: string;
  up: boolean | null;
}

export interface BacktestSummary {
  days: number;
  equity: { batteryOS: number[]; naive: number[]; perfect: number[] };
  dayProfits: { d: number; date: string; bos: number; naive: number; perfect: number; capture: number }[];
  heatmap: number[][];
  source?: string;
}

export type WorkflowLaneId = "data" | "forecast" | "optimize" | "evaluate";

export interface WorkflowNode {
  id: string;
  label: string;
  lane: WorkflowLaneId;
  modules: string[];
  summary: string;
  inputs: string[];
  outputs: string[];
}

export interface WorkflowEdge {
  from: string;
  to: string;
  kind?: "primary" | "loopback";
}

export interface WorkflowLane {
  id: WorkflowLaneId;
  label: string;
  color: string;
}

export interface WorkflowGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  lanes: WorkflowLane[];
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return (await res.json()) as T;
}

export function useSources(): UseQueryResult<SourcesPayload> {
  return useQuery({
    queryKey: ["api", "sources"],
    queryFn: () => getJson<SourcesPayload>("/api/sources"),
    staleTime: 60_000,
  });
}

export function useTicker(): UseQueryResult<TickerRow[]> {
  return useQuery({
    queryKey: ["api", "ticker"],
    queryFn: () => getJson<TickerRow[]>("/api/ticker"),
    staleTime: 30_000,
  });
}

export function useBatteries(): UseQueryResult<BatteryAsset[]> {
  return useQuery({
    queryKey: ["api", "batteries"],
    queryFn: () => getJson<BatteryAsset[]>("/api/batteries"),
    staleTime: 60_000,
  });
}

export function useBacktestSummary(
  days: number = 90,
  profile: string = "all",
): UseQueryResult<BacktestSummary> {
  const params = new URLSearchParams({ days: String(days) });
  if (profile && profile !== "all") {
    params.set("profile", profile);
  }
  return useQuery({
    queryKey: ["api", "backtest", "summary", days, profile],
    queryFn: () => getJson<BacktestSummary>(`/api/backtest/summary?${params.toString()}`),
    staleTime: 30_000,
  });
}

export function useWorkflow(): UseQueryResult<WorkflowGraph> {
  return useQuery({
    queryKey: ["api", "workflow"],
    queryFn: () => getJson<WorkflowGraph>("/api/workflow"),
    staleTime: 5 * 60_000,
  });
}
