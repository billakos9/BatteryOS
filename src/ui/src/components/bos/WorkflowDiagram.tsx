/**
 * Workflow diagram for the BatteryOS pipeline.
 * Pulls graph from /api/workflow — never hardcoded.
 */
import { useMemo, useState } from "react";
import { Card } from "@/components/bos/Primitives";
import { useWorkflow, type WorkflowEdge, type WorkflowNode } from "@/lib/api";

interface PositionedNode extends WorkflowNode {
  x: number;
  y: number;
  laneIndex: number;
}

const NODE_W = 168;
const NODE_H = 56;
const COL_GAP = 220;
const ROW_GAP = 88;
const PADDING_X = 24;
const PADDING_Y = 56;

function laneColumns(nodes: WorkflowNode[]): Map<string, number> {
  // Topological columns by lane order, with collisions in same lane stacking.
  const byLane = new Map<string, WorkflowNode[]>();
  for (const n of nodes) {
    if (!byLane.has(n.lane)) byLane.set(n.lane, []);
    byLane.get(n.lane)!.push(n);
  }
  const cols = new Map<string, number>();
  let columnCursor = 0;
  for (const [, group] of byLane) {
    for (let i = 0; i < group.length; i++) {
      cols.set(group[i].id, columnCursor + i);
    }
    columnCursor += group.length;
  }
  return cols;
}

export default function WorkflowDiagram() {
  const { data, isLoading, isError } = useWorkflow();
  const [activeId, setActiveId] = useState<string | null>(null);

  const positioned = useMemo<PositionedNode[]>(() => {
    if (!data) return [];
    const cols = laneColumns(data.nodes);
    const laneIndex = new Map(data.lanes.map((l, i) => [l.id, i] as const));
    return data.nodes.map((n) => {
      const col = cols.get(n.id) ?? 0;
      const lane = laneIndex.get(n.lane) ?? 0;
      return {
        ...n,
        x: PADDING_X + col * COL_GAP,
        y: PADDING_Y + lane * ROW_GAP,
        laneIndex: lane,
      };
    });
  }, [data]);

  const width = useMemo(() => {
    if (!positioned.length) return 800;
    return Math.max(...positioned.map((p) => p.x)) + NODE_W + PADDING_X;
  }, [positioned]);

  const height = useMemo(() => {
    if (!data) return 320;
    return PADDING_Y + data.lanes.length * ROW_GAP + 32;
  }, [data]);

  const nodeById = useMemo(() => {
    const map = new Map<string, PositionedNode>();
    positioned.forEach((p) => map.set(p.id, p));
    return map;
  }, [positioned]);

  const focusEdges = (e: WorkflowEdge): boolean => {
    if (!activeId) return false;
    return e.from === activeId || e.to === activeId;
  };

  const focusNodes = (id: string): boolean => activeId === id || (!!activeId && (
    data?.edges.some((e) => (e.from === activeId && e.to === id) || (e.to === activeId && e.from === id)) ?? false
  ));

  return (
    <Card
      title="Pipeline workflow"
      meta="forecaster → optimizer → backtest"
    >
      {isLoading && <div className="font-mono-tnum text-[11px] text-fg-3">Loading pipeline diagram…</div>}
      {isError && <div className="font-mono-tnum text-[11px] text-red">Pipeline diagram unavailable.</div>}
      {data && (
        <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(0,1fr) 320px" }}>
          <div className="overflow-x-auto">
            <svg
              viewBox={`0 0 ${width} ${height}`}
              width="100%"
              height={height}
              style={{ display: "block" }}
            >
              {/* lane bands */}
              {data.lanes.map((lane, idx) => (
                <g key={lane.id}>
                  <rect
                    x={0}
                    y={PADDING_Y - ROW_GAP / 2 + idx * ROW_GAP}
                    width={width}
                    height={ROW_GAP}
                    fill={idx % 2 === 0 ? "hsl(var(--bg-2))" : "hsl(var(--bg-3))"}
                    opacity={0.35}
                  />
                  <text
                    x={12}
                    y={PADDING_Y + idx * ROW_GAP - ROW_GAP / 2 + 16}
                    fontSize="9"
                    fontFamily="IBM Plex Mono"
                    fill={lane.color}
                    style={{ letterSpacing: "0.12em", textTransform: "uppercase" }}
                  >
                    {lane.label}
                  </text>
                </g>
              ))}

              {/* edges */}
              {data.edges.map((edge, i) => {
                const a = nodeById.get(edge.from);
                const b = nodeById.get(edge.to);
                if (!a || !b) return null;
                const x1 = a.x + NODE_W;
                const y1 = a.y + NODE_H / 2;
                const x2 = b.x;
                const y2 = b.y + NODE_H / 2;
                const midX = (x1 + x2) / 2;
                const isLoopback = edge.kind === "loopback";
                const isFocused = focusEdges(edge);
                const stroke = isFocused
                  ? "hsl(var(--acc))"
                  : isLoopback
                  ? "hsl(var(--fg-3))"
                  : "hsl(var(--line-strong))";
                const dash = isLoopback ? "4 3" : undefined;
                return (
                  <g key={i}>
                    <path
                      d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
                      fill="none"
                      stroke={stroke}
                      strokeWidth={isFocused ? 1.6 : 1}
                      strokeDasharray={dash}
                    />
                    <polygon
                      points={`${x2},${y2} ${x2 - 5},${y2 - 3} ${x2 - 5},${y2 + 3}`}
                      fill={stroke}
                    />
                  </g>
                );
              })}

              {/* nodes */}
              {positioned.map((node) => {
                const lane = data.lanes.find((l) => l.id === node.lane);
                const isActive = activeId === node.id;
                const dim = !!activeId && !isActive && !focusNodes(node.id);
                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    onMouseEnter={() => setActiveId(node.id)}
                    onMouseLeave={() => setActiveId((cur) => (cur === node.id ? null : cur))}
                    style={{ cursor: "pointer", opacity: dim ? 0.4 : 1 }}
                  >
                    <rect
                      width={NODE_W}
                      height={NODE_H}
                      rx={6}
                      fill="hsl(var(--bg-1))"
                      stroke={isActive ? "hsl(var(--acc))" : lane?.color ?? "hsl(var(--line-strong))"}
                      strokeWidth={isActive ? 1.6 : 1}
                    />
                    <text
                      x={12}
                      y={20}
                      fontSize="11"
                      fontFamily="IBM Plex Mono"
                      fill="hsl(var(--fg-0))"
                      style={{ fontWeight: 500 }}
                    >
                      {node.label}
                    </text>
                    <text
                      x={12}
                      y={38}
                      fontSize="9"
                      fontFamily="IBM Plex Mono"
                      fill="hsl(var(--fg-3))"
                    >
                      {node.modules[0] ?? ""}
                    </text>
                    <circle cx={NODE_W - 12} cy={12} r={3.5} fill={lane?.color ?? "hsl(var(--fg-3))"} />
                  </g>
                );
              })}
            </svg>
          </div>

          {/* details panel */}
          <div className="rounded border border-line bg-bg-2 p-3 text-[11px]">
            {(() => {
              const node = activeId ? nodeById.get(activeId) : positioned[0];
              if (!node) return null;
              const lane = data.lanes.find((l) => l.id === node.lane);
              return (
                <div className="flex flex-col gap-3">
                  <div>
                    <div className="eyebrow" style={{ color: lane?.color }}>
                      {lane?.label}
                    </div>
                    <div className="mt-1 font-mono-tnum text-fg-0">{node.label}</div>
                  </div>
                  <div className="text-fg-2">{node.summary}</div>
                  <div>
                    <div className="eyebrow mb-1">Modules</div>
                    <ul className="font-mono-tnum text-fg-2">
                      {node.modules.map((m) => (
                        <li key={m}>{m}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <div className="eyebrow mb-1">Inputs</div>
                      <ul className="font-mono-tnum text-fg-2">
                        {node.inputs.map((x) => (
                          <li key={x}>{x}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <div className="eyebrow mb-1">Outputs</div>
                      <ul className="font-mono-tnum text-fg-2">
                        {node.outputs.map((x) => (
                          <li key={x}>{x}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  <div className="mt-1 border-t border-line pt-2 font-mono-tnum text-[10px] text-fg-3">
                    Hover any block to inspect its role.
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      )}
    </Card>
  );
}
