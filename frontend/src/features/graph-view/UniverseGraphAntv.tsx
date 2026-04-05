import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphSnapshot } from "../../types";
import G6 from "@antv/g6";
import { styleForNodeType } from "./nodeTypeStyles";

type Props = {
  graph: GraphSnapshot;
  /** Prefer this node as radial center when present in the graph. */
  protagonistCharacterId?: string;
};

type RawNode = Record<string, unknown>;
type RawEdge = Record<string, unknown>;

type MappedNode = Record<string, unknown> & {
  id: string;
  node_type: string;
};

function nodeLabel(n: RawNode): string {
  const name = String(n.canonical_name ?? n.title ?? "");
  const id = String(n.node_id ?? "");
  const t = String(n.node_type ?? "");
  return name ? `${name} (${t})` : `${id || "?"} (${t})`;
}

function pickRadialFocusNode(
  nodes: MappedNode[],
  protagonistCharacterId: string | undefined,
): string | undefined {
  if (!nodes.length) return undefined;
  const ids = new Set(nodes.map((n) => String(n.id)));
  const pid = protagonistCharacterId?.trim();
  if (pid && ids.has(pid)) return pid;
  const firstChar = nodes.find((n) => String(n.node_type).toUpperCase() === "CHARACTER");
  if (firstChar) return String(firstChar.id);
  return String(nodes[0].id);
}

export function UniverseGraphAntv({ graph, protagonistCharacterId }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<any>(null);
  const [selectedNodeModel, setSelectedNodeModel] = useState<Record<string, unknown> | null>(null);

  const { safeNodes, safeEdges, layoutCfg } = useMemo(() => {
    const nodes = (graph.nodes ?? []) as RawNode[];
    const edges = (graph.edges ?? []) as RawEdge[];

    const mappedNodes = nodes
      .map((n) => {
        const id = String(n.node_id ?? "");
        if (!id) return null;
        const nodeType = String(n.node_type ?? "");
        const { fill, stroke } = styleForNodeType(nodeType);
        return {
          id,
          label: nodeLabel(n).slice(0, 28),
          node_id: id,
          node_type: nodeType,
          canonical_name: String(n.canonical_name ?? ""),
          title: String(n.title ?? ""),
          style: {
            fill,
            stroke,
            lineWidth: 1,
          },
        } as MappedNode;
      })
      .filter(Boolean) as MappedNode[];

    const validNodeIds = new Set(mappedNodes.map((n) => String(n.id)));

    const slicedEdges = edges
      .slice(0, 400)
      .map((e) => {
        const source = String(e.source_id ?? "");
        const target = String(e.target_id ?? "");
        const relation_type = String(e.relation_type ?? e.edge_type ?? "REL");
        const edge_id = String(e.edge_id ?? `${source}-${target}-${relation_type}`);
        return { id: edge_id, source, target, relation_type };
      })
      .filter((e) => validNodeIds.has(String(e.source)) && validNodeIds.has(String(e.target)));

    const connectedNodeIds = new Set<string>();
    for (const e of slicedEdges) {
      connectedNodeIds.add(String(e.source));
      connectedNodeIds.add(String(e.target));
    }
    const connected = mappedNodes.filter((n) => connectedNodeIds.has(String(n.id)));

    const safeNodeIdSet = new Set(connected.map((n) => String(n.id)));
    const safeEdges = slicedEdges.filter(
      (e) => safeNodeIdSet.has(String(e.source)) && safeNodeIdSet.has(String(e.target)),
    );

    const hasCharacterNode = connected.some((n) => String(n.node_type).toUpperCase() === "CHARACTER");
    const focusId = pickRadialFocusNode(connected, protagonistCharacterId);

    let layoutCfg: Record<string, unknown>;
    if (hasCharacterNode && focusId) {
      layoutCfg = {
        type: "radial",
        focusNode: focusId,
        unitRadius: 72,
        linkDistance: 120,
        preventOverlap: true,
        nodeSpacing: 28,
        nodeSize: 22,
        maxPreventOverlap: 120,
      };
    } else {
      layoutCfg = {
        type: "force",
        preventOverlap: true,
        linkDistance: 80,
        nodeStrength: 0.8,
        edgeStrength: 0.6,
      };
    }

    return { safeNodes: connected, safeEdges, layoutCfg };
  }, [graph, protagonistCharacterId]);

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
          type: "force",
          preventOverlap: true,
          linkDistance: 80,
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
        setSelectedNodeModel(model);
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
        ref={containerRef}
        style={{ width: "100%", height: 600, background: "#060e20", borderRadius: 16 }}
        className="overflow-hidden border border-outline-variant/20"
      />

      {selectedNodeModel ? (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setSelectedNodeModel(null);
          }}
        >
          <div className="w-full max-w-xl rounded-xl border border-outline-variant/20 bg-surface-container-lowest p-4 shadow-lg">
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <div className="font-headline text-sm font-bold uppercase tracking-wider text-primary">節點詳情</div>
                <div className="mt-1 text-xs text-on-surface-variant">
                  {String((selectedNodeModel as any).node_id ?? "")}{" "}
                  {String((selectedNodeModel as any).node_type ?? "")
                    ? `(${String((selectedNodeModel as any).node_type ?? "")})`
                    : ""}
                </div>
              </div>
              <button
                type="button"
                className="rounded-lg border border-outline-variant/20 bg-surface-container-low px-3 py-1 text-xs font-label text-primary hover:bg-surface-container-lowest"
                onClick={() => setSelectedNodeModel(null)}
              >
                關閉
              </button>
            </div>

            <div className="space-y-2 text-xs text-on-surface-variant">
              <div>
                <span className="font-mono">內部編號</span>：{String((selectedNodeModel as any).node_id ?? "")}
              </div>
              <div>
                <span className="font-mono">類型</span>：{String((selectedNodeModel as any).node_type ?? "")}
              </div>
              <div>
                <span className="font-mono">正式名稱</span>：{String((selectedNodeModel as any).canonical_name ?? "")}
              </div>
              <div>
                <span className="font-mono">標題</span>：{String((selectedNodeModel as any).title ?? "")}
              </div>
              <div>
                <span className="font-mono">顯示標籤</span>：{String((selectedNodeModel as any).label ?? "")}
              </div>
            </div>

            <details className="mt-3 rounded-xl border border-outline-variant/15 bg-surface-container-lowest p-3">
              <summary className="cursor-pointer font-label text-xs text-on-surface-variant">完整資料（進階）</summary>
              <pre className="mt-2 max-h-64 overflow-auto text-[11px] text-on-surface-variant">
                {JSON.stringify(selectedNodeModel, null, 2)}
              </pre>
            </details>
          </div>
        </div>
      ) : null}
    </div>
  );
}
