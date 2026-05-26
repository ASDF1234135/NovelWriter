import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GraphSnapshot } from "../../types";
import G6 from "@antv/g6";
import { styleForNodeType } from "./nodeTypeStyles";
import { useI18n } from "../../i18n/useI18n";
import {
  buildDisplayNameMap,
  GraphDetailDrawer,
  GraphEdgeDetailPanel,
  GraphNodeDetailPanel,
} from "./graphDetailPanels";

type Props = {
  graph: GraphSnapshot;
  /** Prefer this node as radial center when present in the graph. */
  protagonistCharacterId?: string;
  viewMode?: "all" | "ego" | "location-item" | "epoch";
  layoutMode?: "fixed" | "dagre-ltr";
  /** When false, keep orphan nodes visible. */
  pruneIsolatedNodes?: boolean;
  /** Switch parent to Ego mode and center on this node. */
  onSetEgoCenter?: (nodeId: string) => void;
};

type RawNode = Record<string, unknown>;
type RawEdge = Record<string, unknown>;

type MappedNode = Record<string, unknown> & {
  id: string;
  node_type: string;
};

type MappedEdge = Record<string, unknown> & {
  id: string;
  source: string;
  target: string;
  relation_type: string;
};

function nodeLabel(n: RawNode): string {
  return String(n.canonical_name ?? n.title ?? n.node_id ?? "?").slice(0, 28);
}

function distributedCurveOffset(index: number): number {
  if (index === 0) return 0;
  const mag = Math.ceil(index / 2) * 18;
  return index % 2 === 0 ? -mag : mag;
}

export function UniverseGraphAntv({
  graph,
  protagonistCharacterId,
  viewMode = "all",
  layoutMode = "dagre-ltr",
  pruneIsolatedNodes = true,
  onSetEgoCenter,
}: Props) {
  void protagonistCharacterId;
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<any>(null);
  const [selectedNodeModel, setSelectedNodeModel] = useState<Record<string, unknown> | null>(null);
  const [selectedEdgeModel, setSelectedEdgeModel] = useState<Record<string, unknown> | null>(null);

  const displayNames = useMemo(() => buildDisplayNameMap(graph.nodes ?? []), [graph.nodes]);

  const focusNodeById = useCallback((id: string) => {
    const g = graphRef.current;
    if (!g || !id) return;
    const item = g.findById(id);
    if (!item || item.getType?.() !== "node") return;
    try {
      g.focusItem(item, true, { duration: 220 } as object);
    } catch {
      g.focusItem(item, true);
    }
    setSelectedEdgeModel(null);
    setSelectedNodeModel(item.getModel());
  }, []);

  const { safeNodes, safeEdges, layoutCfg } = useMemo(() => {
    const nodes = (graph.nodes ?? []) as RawNode[];
    const edges = (graph.edges ?? []) as RawEdge[];

    const mappedNodes = nodes
      .map((n) => {
        const id = String(n.node_id ?? "");
        if (!id) return null;
        const nodeType = String(n.node_type ?? "");
        const { fill, stroke } = styleForNodeType(nodeType);
        const isCharacter = nodeType.toUpperCase() === "CHARACTER";
        const isLocation = nodeType.toUpperCase() === "LOCATION";
        const isRule = nodeType.toUpperCase() === "RULE";
        const isDead = isCharacter && n.is_alive === false;
        const isInaccessible = isLocation && n.is_accessible === false;
        const ruleInactive = isRule && n.is_active === false;
        const statusBadge = isDead ? " ☠" : isInaccessible ? " 🔒" : ruleInactive ? " ⊗" : "";
        return {
          ...n,
          id,
          label: `${nodeLabel(n)}${statusBadge}`.slice(0, 28),
          node_id: id,
          node_type: nodeType,
          canonical_name: String(n.canonical_name ?? ""),
          title: String(n.title ?? ""),
          style: {
            fill: isDead || ruleInactive ? "#9ca3af" : fill,
            stroke: isDead || ruleInactive ? "#d1d5db" : stroke,
            lineWidth: 1,
            opacity: isDead || ruleInactive ? 0.55 : 1,
          },
          x: Number(n.x ?? 0),
          y: Number(n.y ?? 0),
        } as MappedNode;
      })
      .filter(Boolean) as MappedNode[];

    const validNodeIds = new Set(mappedNodes.map((n) => String(n.id)));

    const mappedEdges = edges
      .slice(0, 400)
      .map((e) => {
        const source = String(e.source_id ?? "");
        const target = String(e.target_id ?? "");
        const relation_type = String(e.relation_type ?? e.edge_type ?? "REL");
        const edge_id = String(e.edge_id ?? `${source}-${target}-${relation_type}`);
        const isTruth = e.is_truth !== false;
        return {
          ...e,
          id: edge_id,
          source,
          target,
          relation_type,
          label: relation_type.slice(0, 24),
          type: "line",
          style: {
            stroke: isTruth ? "#64748b" : "#ef4444",
            lineWidth: 1.6,
            opacity: isTruth ? 0.75 : 0.9,
            lineDash: isTruth ? undefined : [6, 4],
            endArrow: {
              path: G6.Arrow.triangle(6, 8, 2),
              fill: isTruth ? "#64748b" : "#ef4444",
            },
          },
          labelCfg: {
            autoRotate: true,
            style: {
              fill: "#e5e7eb",
              fontSize: 10,
              background: {
                fill: "#111827",
                stroke: "#374151",
                radius: 4,
                padding: [2, 4, 2, 4],
              },
            },
          },
        } as MappedEdge;
      })
      .filter((e) => validNodeIds.has(String(e.source)) && validNodeIds.has(String(e.target)));

    const byPair = new Map<string, MappedEdge[]>();
    for (const edge of mappedEdges) {
      const key = `${edge.source}::${edge.target}`;
      const arr = byPair.get(key) ?? [];
      arr.push(edge);
      byPair.set(key, arr);
    }
    const slicedEdges = [...mappedEdges];
    for (const group of byPair.values()) {
      if (group.length <= 1) continue;
      group.forEach((edge, idx) => {
        edge.type = "quadratic";
        edge.curveOffset = distributedCurveOffset(idx);
      });
    }

    const connectedNodeIds = new Set<string>();
    for (const e of slicedEdges) {
      connectedNodeIds.add(String(e.source));
      connectedNodeIds.add(String(e.target));
    }
    const safeNodes = pruneIsolatedNodes
      ? mappedNodes.filter((n) => connectedNodeIds.has(String(n.id)))
      : mappedNodes;

    const safeNodeIdSet = new Set(safeNodes.map((n) => String(n.id)));
    const safeEdges = slicedEdges.filter(
      (e) => safeNodeIdSet.has(String(e.source)) && safeNodeIdSet.has(String(e.target)),
    );

    let layoutCfg: Record<string, unknown>;
    if (layoutMode === "fixed") {
      // Keep persisted coordinates when available; fallback to deterministic grid.
      safeNodes.forEach((n, idx) => {
        if (!Number.isFinite(Number(n.x)) || !Number.isFinite(Number(n.y))) {
          n.x = (idx % 12) * 120 + 60;
          n.y = Math.floor(idx / 12) * 90 + 60;
        }
      });
      layoutCfg = { type: "preset" };
    } else {
      layoutCfg = {
        type: "dagre",
        rankdir: "LR",
        nodesep: 42,
        ranksep: 88,
        preventOverlap: true,
      };
    }

    return { safeNodes, safeEdges, layoutCfg };
  }, [graph, protagonistCharacterId, viewMode, pruneIsolatedNodes, layoutMode]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const width = Math.max(Math.round(rect.width), 1);
    const height = Math.max(Math.round(rect.height), 1);

    if (!graphRef.current) {
      const g = new G6.Graph({
        container,
        width,
        height,
        layout: {
          type: "dagre",
          rankdir: "LR",
          preventOverlap: true,
        },
        modes: {
          default: ["drag-canvas", "zoom-canvas", "drag-node"],
        },
        defaultNode: {
          type: "circle",
          size: 22,
          style: {
            fill: "#64748b",
            stroke: "#cbd5e1",
            lineWidth: 1,
          },
          labelCfg: {
            position: "bottom",
            style: {
              fill: "#dae2fd",
              fontSize: 10,
              fontFamily: "Manrope, sans-serif",
              textAlign: "center",
              textBaseline: "top",
            },
          },
        },
        defaultEdge: {
          type: "line",
          style: {
            stroke: "#464554",
            lineWidth: 1.5,
            opacity: 0.65,
          },
        },
      });
      graphRef.current = g;

      g.on("node:click", (evt: any) => {
        const model = evt?.item?.getModel?.();
        if (!model) return;
        setSelectedEdgeModel(null);
        setSelectedNodeModel(model);
      });
      g.on("edge:click", (evt: any) => {
        const model = evt?.item?.getModel?.();
        if (!model) return;
        setSelectedNodeModel(null);
        setSelectedEdgeModel(model);
      });
    }

    const g = graphRef.current;
    if (!g) return;

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      const cr = entry?.contentRect;
      const w = Math.round(cr?.width ?? 0);
      const h = Math.round(cr?.height ?? 0);
      if (!w || !h) return;
      g.changeSize(w, h);
      g.fitView();
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      try {
        graphRef.current?.destroy?.();
      } finally {
        graphRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const g = graphRef.current;
    if (!g) return;

    const container = containerRef.current;
    const rect = container?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return;

    g.changeData({ nodes: safeNodes, edges: safeEdges });
    const gl = g as unknown as { updateLayout?: (cfg: object) => void };
    if (typeof gl.updateLayout === "function") {
      gl.updateLayout(layoutCfg);
    }
    g.render();
    g.fitView();
  }, [safeNodes, safeEdges, layoutCfg]);

  return (
    <div className="space-y-4">
      <div
        className="flex w-full overflow-hidden rounded-2xl border border-outline-variant/20 bg-[#060e20]"
        style={{ minHeight: 600 }}
      >
        <div
          ref={containerRef}
          style={{ height: 600, flex: 1, minWidth: 0, background: "#060e20" }}
          className="overflow-hidden"
        />
        {selectedNodeModel ? (
          <GraphDetailDrawer open title={t("graphDrawer.nodeTitle")} onClose={() => setSelectedNodeModel(null)}>
            <GraphNodeDetailPanel
              model={selectedNodeModel}
              graph={graph}
              displayNames={displayNames}
              onFocusNodeId={focusNodeById}
              onSetEgoCenter={onSetEgoCenter}
            />
          </GraphDetailDrawer>
        ) : selectedEdgeModel ? (
          <GraphDetailDrawer open title={t("graphDrawer.edgeTitle")} onClose={() => setSelectedEdgeModel(null)}>
            <GraphEdgeDetailPanel
              model={selectedEdgeModel}
              graph={graph}
              displayNames={displayNames}
              onFocusNodeId={focusNodeById}
            />
          </GraphDetailDrawer>
        ) : null}
      </div>
    </div>
  );
}
