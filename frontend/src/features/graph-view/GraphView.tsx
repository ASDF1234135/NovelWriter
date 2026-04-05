import type { GraphSnapshot } from "../../types";
import { LEGEND_NODE_TYPES, NODE_TYPE_STYLES } from "./nodeTypeStyles";
import { UniverseGraphAntv } from "./UniverseGraphAntv";

type Props = {
  graph: GraphSnapshot | null;
  /** Radial center preference when this node exists in the graph. */
  protagonistCharacterId?: string;
};

type RawNode = Record<string, unknown>;
type RawEdge = Record<string, unknown>;

function edgeLabel(e: RawEdge): string {
  const rel = String(e.relation_type ?? e.edge_type ?? "REL");
  return `${e.source_id ?? "?"} —[${rel}]→ ${e.target_id ?? "?"}`;
}

const NODE_TYPE_ZH: Record<string, string> = {
  CHARACTER: "角色",
  PERSONA: "人格／分身",
  EPOCH: "時間段",
  LOCATION: "地點",
  ITEM: "物品",
  EVENT: "事件",
  CONCEPT: "概念",
};

function nodeTypeLegend(t: string): string {
  return NODE_TYPE_ZH[t] ?? t;
}

export function GraphView({ graph, protagonistCharacterId }: Props) {
  const nodes = (graph?.nodes ?? []) as RawNode[];
  const edges = (graph?.edges ?? []) as RawEdge[];

  // Keep UI consistent with the canvas: only show nodes that have at least one edge.
  // We align with UniverseGraphAntv's behavior by slicing edges to 400 for display scope.
  const drawnEdges = edges.slice(0, 400);
  const validNodeIds = new Set(nodes.map((n) => String(n.node_id ?? "")));
  const connectedNodeIds = new Set<string>();
  for (const e of drawnEdges) {
    const s = String(e.source_id ?? "");
    const t = String(e.target_id ?? "");
    if (validNodeIds.has(s)) connectedNodeIds.add(s);
    if (validNodeIds.has(t)) connectedNodeIds.add(t);
  }
  const nodesWithEdges = nodes.filter((n) => connectedNodeIds.has(String(n.node_id ?? "")));
  const hasCharacterInGraph = nodesWithEdges.some((n) => String(n.node_type).toUpperCase() === "CHARACTER");

  return (
    <section className="canvas-grid min-h-[60vh] rounded-xl border border-outline-variant/10 bg-background p-6 md:p-10">
      <h2 className="mb-2 font-headline text-2xl font-bold text-on-surface">世界觀圖譜</h2>
      <p className="mb-6 max-w-3xl font-body text-sm text-on-surface-variant">
        顯示完整故事網路（未依視角或時間段過濾）；畫面上最多繪製 400 條關聯線以利閱讀。
      </p>
      {!graph ? (
        <p className="text-on-surface-variant">尚未載入圖譜。</p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <article className="lg:col-span-2">
            <h3 className="mb-3 font-headline text-sm font-bold uppercase tracking-wider text-secondary">
              概覽 · {nodesWithEdges.length} 個節點 · {edges.length} 條關聯
            </h3>
            {nodesWithEdges.length === 0 ? (
              <p className="text-on-surface-variant">目前沒有節點。</p>
            ) : (
              <>
                <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                  <span className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">
                    {hasCharacterInGraph
                      ? "佈局：放射狀（以角色為中心）"
                      : "佈局：力導向（圖中無角色節點時）"}
                  </span>
                  <div className="flex flex-wrap items-center gap-3 border-l border-outline-variant/20 pl-4">
                    {LEGEND_NODE_TYPES.map((t) => {
                      const s = NODE_TYPE_STYLES[t];
                      return (
                        <span
                          key={t}
                          className="inline-flex items-center gap-1.5 font-label text-[10px] text-on-surface-variant"
                        >
                          <span
                            className="inline-block h-3 w-3 shrink-0 rounded-full border"
                            style={{ background: s.fill, borderColor: s.stroke }}
                          />
                          {nodeTypeLegend(t)}
                        </span>
                      );
                    })}
                    <span className="text-on-surface-variant/70">其他 → 灰</span>
                  </div>
                </div>
                <UniverseGraphAntv graph={graph} protagonistCharacterId={protagonistCharacterId} />
              </>
            )}
          </article>
          <article>
            <h3 className="mb-2 font-headline text-xs font-bold text-primary">節點</h3>
            <div className="max-h-80 overflow-auto rounded-xl border border-outline-variant/15 bg-surface-container-low">
              <table className="w-full border-collapse text-left text-xs">
                <thead className="sticky top-0 bg-surface-container-high">
                  <tr>
                    <th className="p-2 font-label text-outline">內部編號</th>
                    <th className="p-2 font-label text-outline">類型</th>
                    <th className="p-2 font-label text-outline">名稱</th>
                  </tr>
                </thead>
                <tbody>
                  {nodesWithEdges.map((n) => (
                    <tr key={String(n.node_id)} className="border-t border-outline-variant/10">
                      <td className="p-2 font-mono text-on-surface-variant">{String(n.node_id)}</td>
                      <td className="p-2">{String(n.node_type)}</td>
                      <td className="p-2">{String(n.canonical_name ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
          <article>
            <h3 className="mb-2 font-headline text-xs font-bold text-primary">關聯</h3>
            <div className="max-h-80 overflow-auto rounded-xl border border-outline-variant/15 bg-surface-container-low">
              <table className="w-full border-collapse text-left text-xs">
                <thead className="sticky top-0 bg-surface-container-high">
                  <tr>
                    <th className="p-2 font-label text-outline">來源</th>
                    <th className="p-2 font-label text-outline">關係</th>
                    <th className="p-2 font-label text-outline">指向</th>
                  </tr>
                </thead>
                <tbody>
                  {edges.map((e) => (
                    <tr key={String(e.edge_id ?? edgeLabel(e))} className="border-t border-outline-variant/10">
                      <td className="p-2 font-mono">{String(e.source_id)}</td>
                      <td className="p-2">{String(e.relation_type)}</td>
                      <td className="p-2 font-mono">{String(e.target_id)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
          <article className="lg:col-span-2">
            <h3 className="mb-2 font-headline text-xs font-bold text-primary">原始資料（進階）</h3>
            <details className="rounded-xl border border-outline-variant/15 bg-surface-container-lowest p-4">
              <summary className="cursor-pointer font-label text-sm text-on-surface">展開節點與關聯清單</summary>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <pre className="auteur-pre max-h-96 text-[11px]">{JSON.stringify(nodes, null, 2)}</pre>
                <pre className="auteur-pre max-h-96 text-[11px]">{JSON.stringify(edges, null, 2)}</pre>
              </div>
            </details>
          </article>
        </div>
      )}
    </section>
  );
}
