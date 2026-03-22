import type { GraphSnapshot } from "../../types";

type Props = {
  graph: GraphSnapshot | null;
};

export function GraphView({ graph }: Props) {
  return (
    <section className="panel">
      <h2>動態圖譜視覺化</h2>
      {!graph ? (
        <p>尚未載入圖譜。</p>
      ) : (
        <div className="output-grid">
          <article>
            <h3>Nodes</h3>
            <pre>{JSON.stringify(graph.nodes, null, 2)}</pre>
          </article>
          <article>
            <h3>Edges</h3>
            <pre>{JSON.stringify(graph.edges, null, 2)}</pre>
          </article>
        </div>
      )}
    </section>
  );
}
