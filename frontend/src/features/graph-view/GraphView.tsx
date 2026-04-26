import { useEffect, useMemo, useState } from "react";
import type { GraphSnapshot } from "../../types";
import { LEGEND_NODE_TYPES, NODE_TYPE_STYLES } from "./nodeTypeStyles";
import { UniverseGraphAntv } from "./UniverseGraphAntv";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  graph: GraphSnapshot | null;
  /** Radial center preference when this node exists in the graph. */
  protagonistCharacterId?: string;
};

type RawNode = Record<string, unknown>;
type RawEdge = Record<string, unknown>;
type ViewMode = "all" | "ego" | "location-item" | "epoch";
type LayoutMode = "fixed" | "dagre-ltr";
type DagEditMode = "read" | "edit";

const EDGE_LIMIT = 400;
const EPOCH_DEBOUNCE_MS = 300;

function edgeLabel(e: RawEdge): string {
  const rel = String(e.relation_type ?? e.edge_type ?? "REL");
  return `${e.source_id ?? "?"} —[${rel}]→ ${e.target_id ?? "?"}`;
}

const NODE_TYPE_ZH: Record<string, { "zh-Hant": string; "zh-Hans": string; en: string }> = {
  CHARACTER: { "zh-Hant": "角色", "zh-Hans": "角色", en: "Character" },
  PERSONA: { "zh-Hant": "人格／分身", "zh-Hans": "人格/分身", en: "Persona" },
  EPOCH: { "zh-Hant": "時間段", "zh-Hans": "时间段", en: "Epoch" },
  LOCATION: { "zh-Hant": "地點", "zh-Hans": "地点", en: "Location" },
  ITEM: { "zh-Hant": "物品", "zh-Hans": "物品", en: "Item" },
  EVENT: { "zh-Hant": "事件", "zh-Hans": "事件", en: "Event" },
  CONCEPT: { "zh-Hant": "概念", "zh-Hans": "概念", en: "Concept" },
};

function nodeTypeLegend(t: string, locale: "zh-Hant" | "zh-Hans" | "en"): string {
  return NODE_TYPE_ZH[t]?.[locale] ?? t;
}

function toNodeId(v: unknown): string {
  return String(v ?? "");
}

function fuzzyContains(haystack: string, needle: string): boolean {
  return haystack.toLowerCase().includes(needle.trim().toLowerCase());
}

function parseAliases(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => String(v ?? "").trim()).filter(Boolean);
}

function epochSortKey(node: RawNode): number {
  const n = Number(node.order_index);
  if (Number.isFinite(n)) return n;
  return Number.MAX_SAFE_INTEGER;
}

function bfsNeighborhood(nodeIds: Set<string>, edges: RawEdge[], centerId: string, maxHop: 1 | 2): Set<string> {
  const neighbors = new Map<string, Set<string>>();
  for (const e of edges) {
    const s = String(e.source_id ?? "");
    const t = String(e.target_id ?? "");
    if (!nodeIds.has(s) || !nodeIds.has(t)) continue;
    if (!neighbors.has(s)) neighbors.set(s, new Set());
    if (!neighbors.has(t)) neighbors.set(t, new Set());
    neighbors.get(s)?.add(t);
    neighbors.get(t)?.add(s);
  }
  const visited = new Set<string>([centerId]);
  let frontier = new Set<string>([centerId]);
  for (let hop = 0; hop < maxHop; hop += 1) {
    const next = new Set<string>();
    for (const curr of frontier) {
      for (const nb of neighbors.get(curr) ?? []) {
        if (visited.has(nb)) continue;
        visited.add(nb);
        next.add(nb);
      }
    }
    frontier = next;
    if (!frontier.size) break;
  }
  return visited;
}

function detectCycle(nodes: RawNode[], edges: RawEdge[]): boolean {
  const ids = new Set(nodes.map((n) => toNodeId(n.node_id)).filter(Boolean));
  const indeg = new Map<string, number>();
  const graph = new Map<string, string[]>();
  for (const id of ids) {
    indeg.set(id, 0);
    graph.set(id, []);
  }
  for (const e of edges) {
    const s = String(e.source_id ?? "");
    const t = String(e.target_id ?? "");
    if (!ids.has(s) || !ids.has(t) || s === t) continue;
    graph.get(s)?.push(t);
    indeg.set(t, (indeg.get(t) ?? 0) + 1);
  }
  const q: string[] = [];
  for (const [id, d] of indeg.entries()) {
    if (d === 0) q.push(id);
  }
  let seen = 0;
  while (q.length > 0) {
    const cur = q.shift()!;
    seen += 1;
    for (const nxt of graph.get(cur) ?? []) {
      const d = (indeg.get(nxt) ?? 1) - 1;
      indeg.set(nxt, d);
      if (d === 0) q.push(nxt);
    }
  }
  return seen !== ids.size;
}

export function GraphView({ graph, protagonistCharacterId }: Props) {
  const { locale } = useI18n();
  const nodes = (graph?.nodes ?? []) as RawNode[];
  const edges = (graph?.edges ?? []) as RawEdge[];
  const [viewMode, setViewMode] = useState<ViewMode>("all");
  const [egoHop, setEgoHop] = useState<1 | 2>(1);
  const [egoQuery, setEgoQuery] = useState("");
  const [selectedEgoCenterId, setSelectedEgoCenterId] = useState<string>(protagonistCharacterId ?? "");
  const [pendingEpochIndex, setPendingEpochIndex] = useState(0);
  const [activeEpochIndex, setActiveEpochIndex] = useState(0);
  const [pruneIsolatedNodes, setPruneIsolatedNodes] = useState(true);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("dagre-ltr");
  const [dagEditMode, setDagEditMode] = useState<DagEditMode>("read");

  useEffect(() => {
    const timer = window.setTimeout(() => setActiveEpochIndex(pendingEpochIndex), EPOCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [pendingEpochIndex]);

  useEffect(() => {
    if (!selectedEgoCenterId && protagonistCharacterId) setSelectedEgoCenterId(protagonistCharacterId);
  }, [protagonistCharacterId, selectedEgoCenterId]);

  const epochNodes = useMemo(() => {
    return nodes
      .filter((n) => String(n.node_type ?? "").toUpperCase() === "EPOCH")
      .slice()
      .sort((a, b) => epochSortKey(a) - epochSortKey(b));
  }, [nodes]);

  const epochOptions = useMemo(
    () =>
      epochNodes.map((n) => ({
        id: toNodeId(n.node_id),
        label: String(n.canonical_name ?? n.title ?? n.node_id ?? "Epoch"),
      })),
    [epochNodes],
  );

  useEffect(() => {
    if (!epochOptions.length) {
      setPendingEpochIndex(0);
      setActiveEpochIndex(0);
      return;
    }
    const max = epochOptions.length - 1;
    if (pendingEpochIndex > max) setPendingEpochIndex(max);
    if (activeEpochIndex > max) setActiveEpochIndex(max);
  }, [epochOptions, pendingEpochIndex, activeEpochIndex]);

  const selectedEpochId = epochOptions[activeEpochIndex]?.id ?? "";

  const egoCandidates = useMemo(() => {
    const q = egoQuery.trim();
    return nodes
      .filter((n) => {
        const type = String(n.node_type ?? "").toUpperCase();
        return type === "CHARACTER" || type === "PERSONA";
      })
      .map((n) => {
        const id = toNodeId(n.node_id);
        const name = String(n.canonical_name ?? id);
        const aliases = parseAliases(n.aliases);
        const searchable = `${name} ${aliases.join(" ")}`;
        return { id, name, aliases, searchable };
      })
      .filter((n) => !q || fuzzyContains(n.searchable, q))
      .slice(0, 20);
  }, [nodes, egoQuery]);

  const filteredGraph = useMemo(() => {
    const validNodeIds = new Set(nodes.map((n) => toNodeId(n.node_id)).filter(Boolean));
    let workingEdges = edges.filter((e) => {
      const s = String(e.source_id ?? "");
      const t = String(e.target_id ?? "");
      return validNodeIds.has(s) && validNodeIds.has(t);
    });

    if (viewMode === "epoch" && selectedEpochId) {
      workingEdges = workingEdges.filter((e) => {
        const validEpoch = String(e.valid_epoch ?? "");
        const ended = String(e.end_event_id ?? "").trim().length > 0;
        const epochMatched = !validEpoch || validEpoch === selectedEpochId;
        return epochMatched && !ended;
      });
    }

    if (viewMode === "location-item") {
      const allowType = new Set(["LOCATION", "ITEM"]);
      const keepNodeIds = new Set(
        nodes
          .filter((n) => allowType.has(String(n.node_type ?? "").toUpperCase()))
          .map((n) => toNodeId(n.node_id)),
      );
      const allowRel = new Set(["LOCATED_IN", "HAS_ITEM"]);
      workingEdges = workingEdges.filter((e) => {
        const rel = String(e.relation_type ?? "").toUpperCase();
        const s = String(e.source_id ?? "");
        const t = String(e.target_id ?? "");
        return allowRel.has(rel) && keepNodeIds.has(s) && keepNodeIds.has(t);
      });
    }

    if (viewMode === "ego" && selectedEgoCenterId) {
      const idSet = new Set(nodes.map((n) => toNodeId(n.node_id)));
      const kept = bfsNeighborhood(idSet, workingEdges, selectedEgoCenterId, egoHop);
      workingEdges = workingEdges.filter(
        (e) => kept.has(String(e.source_id ?? "")) && kept.has(String(e.target_id ?? "")),
      );
    }

    const connectedNodeIds = new Set<string>();
    for (const e of workingEdges) {
      connectedNodeIds.add(String(e.source_id ?? ""));
      connectedNodeIds.add(String(e.target_id ?? ""));
    }

    const shouldPrune = pruneIsolatedNodes && (viewMode === "location-item" || viewMode === "ego" || viewMode === "epoch");
    const workingNodes = shouldPrune
      ? nodes.filter((n) => connectedNodeIds.has(toNodeId(n.node_id)))
      : nodes;

    const keepNodeIds = new Set(workingNodes.map((n) => toNodeId(n.node_id)));
    const boundedEdges = workingEdges
      .filter((e) => keepNodeIds.has(String(e.source_id ?? "")) && keepNodeIds.has(String(e.target_id ?? "")))
      .slice(0, EDGE_LIMIT);

    return { nodes: workingNodes, edges: boundedEdges } as GraphSnapshot;
  }, [nodes, edges, viewMode, selectedEpochId, selectedEgoCenterId, egoHop, pruneIsolatedNodes]);

  const drawnEdges = (filteredGraph.edges ?? []) as RawEdge[];
  const validNodeIds = new Set(((filteredGraph.nodes ?? []) as RawNode[]).map((n) => String(n.node_id ?? "")));
  const connectedNodeIds = new Set<string>();
  for (const e of drawnEdges) {
    const s = String(e.source_id ?? "");
    const t = String(e.target_id ?? "");
    if (validNodeIds.has(s)) connectedNodeIds.add(s);
    if (validNodeIds.has(t)) connectedNodeIds.add(t);
  }
  const nodesWithEdges = ((filteredGraph.nodes ?? []) as RawNode[]).filter((n) =>
    connectedNodeIds.has(String(n.node_id ?? "")),
  );
  const displayNodes = pruneIsolatedNodes
    ? nodesWithEdges
    : ((filteredGraph.nodes ?? []) as RawNode[]);
  const dagCycleDetected = useMemo(
    () => detectCycle(displayNodes, drawnEdges),
    [displayNodes, drawnEdges],
  );
  const hasCharacterInGraph = displayNodes.some((n) => String(n.node_type).toUpperCase() === "CHARACTER");

  return (
    <section className="canvas-grid min-h-[60vh] rounded-xl border border-outline-variant/10 bg-background p-6 md:p-10">
      <h2 className="mb-2 font-headline text-2xl font-bold text-on-surface">
        {locale === "en" ? "World Graph" : locale === "zh-Hans" ? "世界观图谱" : "世界觀圖譜"}
      </h2>
      <p className="mb-6 max-w-3xl font-body text-sm text-on-surface-variant">
        {locale === "en"
          ? "Interactive tactical canvas with view modes and time slicing; up to 400 edges are rendered for readability."
          : locale === "zh-Hans"
            ? "互动式战术沙盘：可切换视角、时间切片与信息层级；最多绘制 400 条关联线。"
            : "互動式戰術沙盤：可切換視角、時間切片與情報層級；畫面上最多繪製 400 條關聯線以利閱讀。"}
      </p>
      {!graph ? (
        <p className="text-on-surface-variant">
          {locale === "en" ? "Graph not loaded yet." : locale === "zh-Hans" ? "尚未加载图谱。" : "尚未載入圖譜。"}
        </p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <article className="lg:col-span-2">
            <div className="mb-4 grid gap-3 rounded-xl border border-outline-variant/15 bg-surface-container-low p-3 md:grid-cols-6">
              <label className="flex flex-col gap-1 md:col-span-2">
                <span className="font-label text-[11px] uppercase tracking-wider text-on-surface-variant">
                  {locale === "en" ? "View Mode" : locale === "zh-Hans" ? "视角模式" : "視角模式"}
                </span>
                <select
                  className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest px-2 py-2 text-sm"
                  value={viewMode}
                  onChange={(e) => setViewMode(e.target.value as ViewMode)}
                >
                  <option value="all">{locale === "en" ? "Global Overview" : locale === "zh-Hans" ? "全局总览" : "全域總覽"}</option>
                  <option value="ego">{locale === "en" ? "Ego View" : locale === "zh-Hans" ? "主角中心（Ego）" : "主角中心（Ego）"}</option>
                  <option value="location-item">{locale === "en" ? "Location & Assets" : locale === "zh-Hans" ? "地理与资产" : "地理與資產"}</option>
                  <option value="epoch">{locale === "en" ? "Time Slice" : locale === "zh-Hans" ? "时空切片" : "時空切片"}</option>
                </select>
              </label>

              {viewMode === "ego" ? (
                <>
                  <label className="flex flex-col gap-1 md:col-span-2">
                    <span className="font-label text-[11px] uppercase tracking-wider text-on-surface-variant">
                      {locale === "en" ? "Search Center Node" : locale === "zh-Hans" ? "搜索中心节点（角色/别名）" : "搜尋中心節點（角色/別名）"}
                    </span>
                    <input
                      type="text"
                      className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest px-2 py-2 text-sm"
                      value={egoQuery}
                      onChange={(e) => setEgoQuery(e.target.value)}
                      placeholder={locale === "en" ? "Type character name or aliases" : locale === "zh-Hans" ? "输入角色名或 aliases" : "輸入角色名或 aliases"}
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="font-label text-[11px] uppercase tracking-wider text-on-surface-variant">
                      {locale === "en" ? "Center Node" : locale === "zh-Hans" ? "中心节点" : "中心節點"}
                    </span>
                    <select
                      className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest px-2 py-2 text-sm"
                      value={selectedEgoCenterId}
                      onChange={(e) => setSelectedEgoCenterId(e.target.value)}
                    >
                      <option value="">{locale === "en" ? "Select..." : locale === "zh-Hans" ? "请选择" : "請選擇"}</option>
                      {egoCandidates.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="font-label text-[11px] uppercase tracking-wider text-on-surface-variant">Hop</span>
                    <select
                      className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest px-2 py-2 text-sm"
                      value={egoHop}
                      onChange={(e) => setEgoHop(Number(e.target.value) === 2 ? 2 : 1)}
                    >
                      <option value={1}>1 hop</option>
                      <option value={2}>2 hops</option>
                    </select>
                  </label>
                </>
              ) : null}

              {viewMode === "epoch" ? (
                <label className="flex flex-col gap-1 md:col-span-4">
                    <span className="font-label text-[11px] uppercase tracking-wider text-on-surface-variant">
                      {locale === "en" ? "Epoch Slider" : locale === "zh-Hans" ? "Epoch 滑杆（按 order_index）" : "Epoch 滑桿（依 order_index 排序）"}
                    </span>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(epochOptions.length - 1, 0)}
                    step={1}
                    value={pendingEpochIndex}
                    onChange={(e) => setPendingEpochIndex(Number(e.target.value))}
                    disabled={!epochOptions.length}
                  />
                  <div className="text-xs text-on-surface-variant">
                    {epochOptions.length
                      ? `${locale === "en" ? "Current" : locale === "zh-Hans" ? "当前" : "目前"}：${epochOptions[activeEpochIndex]?.label ?? "—"}`
                      : locale === "en"
                        ? "No EPOCH node found"
                        : locale === "zh-Hans"
                          ? "目前没有 EPOCH 节点"
                          : "目前沒有 EPOCH 節點"}
                  </div>
                </label>
              ) : null}

              <label className="flex items-center gap-2 md:col-span-2">
                <input
                  type="checkbox"
                  checked={pruneIsolatedNodes}
                  onChange={(e) => setPruneIsolatedNodes(e.target.checked)}
                />
                <span className="text-sm text-on-surface-variant">
                  {locale === "en" ? "Prune orphan nodes" : locale === "zh-Hans" ? "清理孤立节点（Orphan）" : "清理無邊界點（Orphan）"}
                </span>
              </label>
              <label className="flex flex-col gap-1 md:col-span-2">
                <span className="font-label text-[11px] uppercase tracking-wider text-on-surface-variant">
                  {locale === "en" ? "Layout Strategy" : locale === "zh-Hans" ? "布局策略" : "佈局策略"}
                </span>
                <select
                  className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest px-2 py-2 text-sm"
                  value={layoutMode}
                  onChange={(e) => setLayoutMode(e.target.value as LayoutMode)}
                >
                  <option value="dagre-ltr">Hierarchical Left-to-Right (Dagre)</option>
                  <option value="fixed">Fixed Positioning</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 md:col-span-2">
                <span className="font-label text-[11px] uppercase tracking-wider text-on-surface-variant">
                  {locale === "en" ? "DAG Edit Mode" : locale === "zh-Hans" ? "DAG 编辑模式" : "DAG 編輯模式"}
                </span>
                <select
                  className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest px-2 py-2 text-sm"
                  value={dagEditMode}
                  onChange={(e) => setDagEditMode(e.target.value as DagEditMode)}
                >
                  <option value="read">{locale === "en" ? "Read" : locale === "zh-Hans" ? "只读" : "唯讀"}</option>
                  <option value="edit">{locale === "en" ? "Edit" : locale === "zh-Hans" ? "编辑" : "編輯"}</option>
                </select>
              </label>
            </div>
            {dagEditMode === "edit" && dagCycleDetected ? (
              <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                {locale === "en"
                  ? "Cycle detected. DAG guardrail would block edit-save."
                  : locale === "zh-Hans"
                    ? "检测到循环依赖，DAG 防护会阻止保存。"
                    : "偵測到循環依賴，DAG 防護會阻擋儲存。"}
              </div>
            ) : null}

            <h3 className="mb-3 font-headline text-sm font-bold uppercase tracking-wider text-secondary">
              {locale === "en"
                ? `Overview · ${displayNodes.length} nodes · ${drawnEdges.length} edges`
                : locale === "zh-Hans"
                  ? `概览 · ${displayNodes.length} 个节点 · ${drawnEdges.length} 条关联`
                  : `概覽 · ${displayNodes.length} 個節點 · ${drawnEdges.length} 條關聯`}
            </h3>
            {displayNodes.length === 0 ? (
              <p className="text-on-surface-variant">
                {viewMode === "ego" && !selectedEgoCenterId
                  ? locale === "en"
                    ? "Please select an ego center node first."
                    : locale === "zh-Hans"
                      ? "请先在上方选择 Ego 中心节点。"
                      : "請先在上方選擇 Ego 中心節點。"
                  : locale === "en"
                    ? "No nodes currently."
                    : locale === "zh-Hans"
                      ? "目前没有节点。"
                      : "目前沒有節點。"}
              </p>
            ) : (
              <>
                <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                  <span className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">
                    {layoutMode === "fixed"
                      ? locale === "en"
                        ? "Layout: Fixed Positioning"
                        : locale === "zh-Hans"
                          ? "布局：固定坐标"
                          : "佈局：固定座標"
                      : viewMode === "ego"
                      ? locale === "en"
                        ? "Layout: Concentric/Radial (Ego)"
                        : locale === "zh-Hans"
                          ? "布局：同心/放射（Ego）"
                          : "佈局：同心/放射（Ego）"
                      : viewMode === "location-item"
                        ? locale === "en"
                          ? "Layout: Force/Hierarchical (Location & Item)"
                          : locale === "zh-Hans"
                            ? "布局：力导向/层次（Location & Item）"
                            : "佈局：力導向/層次（Location & Item）"
                        : hasCharacterInGraph
                          ? locale === "en"
                            ? "Layout: Radial (Character-first)"
                            : locale === "zh-Hans"
                              ? "布局：放射状（角色优先）"
                              : "佈局：放射狀（角色優先）"
                          : locale === "en"
                            ? "Layout: Force-directed"
                            : locale === "zh-Hans"
                              ? "布局：力导向"
                              : "佈局：力導向"}
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
                          {nodeTypeLegend(t, locale)}
                        </span>
                      );
                    })}
                    <span className="text-on-surface-variant/70">{locale === "en" ? "Others -> Gray" : locale === "zh-Hans" ? "其他 -> 灰色" : "其他 → 灰"}</span>
                  </div>
                </div>
                <UniverseGraphAntv
                  graph={filteredGraph}
                  protagonistCharacterId={viewMode === "ego" ? selectedEgoCenterId || protagonistCharacterId : protagonistCharacterId}
                  viewMode={viewMode}
                  layoutMode={layoutMode}
                  pruneIsolatedNodes={pruneIsolatedNodes}
                  onSetEgoCenter={(nodeId) => {
                    setViewMode("ego");
                    setSelectedEgoCenterId(nodeId);
                    setEgoQuery("");
                  }}
                />
              </>
            )}
          </article>
          <article>
            <h3 className="mb-2 font-headline text-xs font-bold text-primary">{locale === "en" ? "Nodes" : locale === "zh-Hans" ? "节点" : "節點"}</h3>
            <div className="max-h-80 overflow-auto rounded-xl border border-outline-variant/15 bg-surface-container-low">
              <table className="w-full border-collapse text-left text-xs">
                <thead className="sticky top-0 bg-surface-container-high">
                  <tr>
                    <th className="p-2 font-label text-outline">{locale === "en" ? "ID" : locale === "zh-Hans" ? "内部编号" : "內部編號"}</th>
                    <th className="p-2 font-label text-outline">{locale === "en" ? "Type" : locale === "zh-Hans" ? "类型" : "類型"}</th>
                    <th className="p-2 font-label text-outline">{locale === "en" ? "Name" : locale === "zh-Hans" ? "名称" : "名稱"}</th>
                  </tr>
                </thead>
                <tbody>
                  {displayNodes.map((n) => (
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
            <h3 className="mb-2 font-headline text-xs font-bold text-primary">{locale === "en" ? "Edges" : locale === "zh-Hans" ? "关联" : "關聯"}</h3>
            <div className="max-h-80 overflow-auto rounded-xl border border-outline-variant/15 bg-surface-container-low">
              <table className="w-full border-collapse text-left text-xs">
                <thead className="sticky top-0 bg-surface-container-high">
                  <tr>
                    <th className="p-2 font-label text-outline">{locale === "en" ? "Source" : locale === "zh-Hans" ? "来源" : "來源"}</th>
                    <th className="p-2 font-label text-outline">{locale === "en" ? "Relation" : locale === "zh-Hans" ? "关系" : "關係"}</th>
                    <th className="p-2 font-label text-outline">{locale === "en" ? "Target" : locale === "zh-Hans" ? "指向" : "指向"}</th>
                  </tr>
                </thead>
                <tbody>
                  {drawnEdges.map((e) => (
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
            <h3 className="mb-2 font-headline text-xs font-bold text-primary">{locale === "en" ? "Raw Data (Advanced)" : locale === "zh-Hans" ? "原始数据（进阶）" : "原始資料（進階）"}</h3>
            <details className="rounded-xl border border-outline-variant/15 bg-surface-container-lowest p-4">
              <summary className="cursor-pointer font-label text-sm text-on-surface">
                {locale === "en" ? "Expand nodes and edges" : locale === "zh-Hans" ? "展开节点与关联清单" : "展開節點與關聯清單"}
              </summary>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <pre className="auteur-pre max-h-96 text-[11px]">{JSON.stringify(filteredGraph.nodes, null, 2)}</pre>
                <pre className="auteur-pre max-h-96 text-[11px]">{JSON.stringify(filteredGraph.edges, null, 2)}</pre>
              </div>
            </details>
          </article>
        </div>
      )}
    </section>
  );
}
