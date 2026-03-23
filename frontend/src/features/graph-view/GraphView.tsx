import { useMemo } from "react";
import type { GraphSnapshot } from "../../types";

type Props = {
  graph: GraphSnapshot | null;
};

type RawNode = Record<string, unknown>;
type RawEdge = Record<string, unknown>;

function nodeLabel(n: RawNode): string {
  const name = String(n.canonical_name ?? n.title ?? "");
  const id = String(n.node_id ?? "");
  const t = String(n.node_type ?? "");
  return name ? `${name} (${t})` : `${id || "?"} (${t})`;
}

function edgeLabel(e: RawEdge): string {
  const rel = String(e.relation_type ?? e.edge_type ?? "REL");
  return `${e.source_id ?? "?"} —[${rel}]→ ${e.target_id ?? "?"}`;
}

/** Evenly spaced on a circle for a readable overview of the full graph. */
function GraphSvg({ nodes, edges }: { nodes: RawNode[]; edges: RawEdge[] }) {
  const layout = useMemo(() => {
    const n = nodes.length;
    const w = 720;
    const h = 480;
    const cx = w / 2;
    const cy = h / 2;
    const r = Math.min(w, h) / 2 - 56;
    const pos = new Map<string, { x: number; y: number }>();
    nodes.forEach((node, i) => {
      const id = String(node.node_id ?? "");
      if (!id) return;
      const angle = (2 * Math.PI * i) / Math.max(n, 1) - Math.PI / 2;
      pos.set(id, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
    });
    return { w, h, cx, cy, pos };
  }, [nodes]);

  const { w, h, pos } = layout;
  const maxEdgesDraw = 400;
  const drawnEdges = edges.slice(0, maxEdgesDraw);

  return (
    <svg className="graph-svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="故事圖譜概覽">
      <rect width={w} height={h} fill="#020617" rx={12} />
      {drawnEdges.map((e) => {
        const s = pos.get(String(e.source_id ?? ""));
        const t = pos.get(String(e.target_id ?? ""));
        if (!s || !t) return null;
        return (
          <line
            key={String(e.edge_id ?? `${e.source_id}-${e.target_id}`)}
            x1={s.x}
            y1={s.y}
            x2={t.x}
            y2={t.y}
            stroke="#475569"
            strokeWidth={1}
            strokeOpacity={0.55}
          />
        );
      })}
      {nodes.map((node) => {
        const id = String(node.node_id ?? "");
        const p = pos.get(id);
        if (!p) return null;
        return (
          <g key={id} transform={`translate(${p.x},${p.y})`}>
            <circle r={10} fill="#1d4ed8" stroke="#93c5fd" strokeWidth={1} />
            <text x={14} y={4} fill="#cbd5e1" fontSize={10} className="graph-svg-label">
              {nodeLabel(node).slice(0, 28)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function GraphView({ graph }: Props) {
  const nodes = (graph?.nodes ?? []) as RawNode[];
  const edges = (graph?.edges ?? []) as RawEdge[];

  return (
    <section className="panel">
      <h2>動態圖譜視覺化</h2>
      <p className="muted graph-intro">
        顯示後端 <code>/graph/full</code> 的完整節點與邊（無 POV／epoch 過濾）。節點過多時僅繪製前 400 條邊；完整資料見下方 JSON。
      </p>
      {!graph ? (
        <p>尚未載入圖譜。</p>
      ) : (
        <div className="output-grid graph-view-grid">
          <article className="graph-visual-column">
            <h3>概覽（{nodes.length} 節點 · {edges.length} 邊）</h3>
            {nodes.length === 0 ? (
              <p>目前沒有節點。</p>
            ) : (
              <GraphSvg nodes={nodes} edges={edges} />
            )}
          </article>
          <article>
            <h3>節點列表</h3>
            <div className="graph-table-wrap">
              <table className="graph-table">
                <thead>
                  <tr>
                    <th>node_id</th>
                    <th>type</th>
                    <th>名稱</th>
                  </tr>
                </thead>
                <tbody>
                  {nodes.map((n) => (
                    <tr key={String(n.node_id)}>
                      <td className="mono">{String(n.node_id)}</td>
                      <td>{String(n.node_type)}</td>
                      <td>{String(n.canonical_name ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
          <article>
            <h3>邊列表</h3>
            <div className="graph-table-wrap">
              <table className="graph-table">
                <thead>
                  <tr>
                    <th>source</th>
                    <th>relation</th>
                    <th>target</th>
                  </tr>
                </thead>
                <tbody>
                  {edges.map((e) => (
                    <tr key={String(e.edge_id ?? edgeLabel(e))}>
                      <td className="mono">{String(e.source_id)}</td>
                      <td>{String(e.relation_type)}</td>
                      <td className="mono">{String(e.target_id)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
          <article className="graph-raw-json">
            <h3>完整 JSON</h3>
            <details>
              <summary>展開 nodes / edges 原始資料</summary>
              <div className="output-grid graph-json-split">
                <pre>{JSON.stringify(nodes, null, 2)}</pre>
                <pre>{JSON.stringify(edges, null, 2)}</pre>
              </div>
            </details>
          </article>
        </div>
      )}
    </section>
  );
}
