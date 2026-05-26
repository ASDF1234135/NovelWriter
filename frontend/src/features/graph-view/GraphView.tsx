import { useEffect, useMemo, useState } from "react";
import type { GraphSnapshot } from "../../types";
import { LEGEND_NODE_TYPES, NODE_TYPE_STYLES } from "./nodeTypeStyles";
import { UniverseGraphAntv } from "./UniverseGraphAntv";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  graph: GraphSnapshot | null;
  /** Radial center preference when this node exists in the graph. */
  protagonistCharacterId?: string;
  /** Mirrors app chrome: graph route is view-only (no edits on this page). */
  readOnly?: boolean;
};

type RawNode = Record<string, unknown>;
type RawEdge = Record<string, unknown>;
type ViewMode = "all" | "ego" | "location-item" | "epoch";
type LayoutMode = "fixed" | "dagre-ltr";

const EDGE_LIMIT = 400;
const EPOCH_DEBOUNCE_MS = 300;

const NODE_TYPE_ZH: Record<string, { "zh-Hant": string; "zh-Hans": string; en: string }> = {
  CHARACTER: { "zh-Hant": "角色", "zh-Hans": "角色", en: "Character" },
  PERSONA: { "zh-Hant": "人格／分身", "zh-Hans": "人格/分身", en: "Persona" },
  EPOCH: { "zh-Hant": "時間段", "zh-Hans": "时间段", en: "Epoch" },
  LOCATION: { "zh-Hant": "地點", "zh-Hans": "地点", en: "Location" },
  ITEM: { "zh-Hant": "物品", "zh-Hans": "物品", en: "Item" },
  EVENT: { "zh-Hant": "事件", "zh-Hans": "事件", en: "Event" },
  CONCEPT: { "zh-Hant": "概念", "zh-Hans": "概念", en: "Concept" },
};

function nodeTypeLegend(nodeType: string, locale: "zh-Hant" | "zh-Hans" | "en"): string {
  return NODE_TYPE_ZH[nodeType]?.[locale] ?? nodeType;
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

export function GraphView({ graph, protagonistCharacterId, readOnly: _readOnly }: Props) {
  void _readOnly;
  const { locale, t } = useI18n();
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

  const { filteredGraph, edgesWereTruncated } = useMemo(() => {
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
    const filteredForBounds = workingEdges.filter(
      (e) => keepNodeIds.has(String(e.source_id ?? "")) && keepNodeIds.has(String(e.target_id ?? "")),
    );
    const edgesWereTruncatedInner = filteredForBounds.length > EDGE_LIMIT;
    const boundedEdges = filteredForBounds.slice(0, EDGE_LIMIT);

    return {
      filteredGraph: { nodes: workingNodes, edges: boundedEdges } as GraphSnapshot,
      edgesWereTruncated: edgesWereTruncatedInner,
    };
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
  const hasCharacterInGraph = displayNodes.some((n) => String(n.node_type).toUpperCase() === "CHARACTER");

  const layoutDescKey =
    layoutMode === "fixed"
      ? "graphView.layoutDesc.fixed"
      : viewMode === "ego"
        ? "graphView.layoutDesc.ego"
        : viewMode === "location-item"
          ? "graphView.layoutDesc.locItem"
          : hasCharacterInGraph
            ? "graphView.layoutDesc.radial"
            : "graphView.layoutDesc.force";

  return (
    <section className="canvas-grid relative min-h-[60vh] overflow-hidden rounded-2xl border border-outline-variant/20 bg-gradient-to-b from-surface-container-low/40 to-background p-6 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)] md:p-10">
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.035]"
        style={{
          backgroundImage: `radial-gradient(circle at 20% 0%, var(--color-primary, #6366f1) 0%, transparent 45%),
            radial-gradient(circle at 90% 20%, var(--color-secondary, #22c55e) 0%, transparent 40%)`,
        }}
        aria-hidden
      />
      <div className="relative">
        <header className="mb-6 max-w-2xl">
          <h2 className="font-headline text-2xl font-bold tracking-tight text-on-surface md:text-3xl">{t("common.graph")}</h2>
          <p className="mt-3 font-body text-sm leading-relaxed text-on-surface-variant">{t("graphView.subtitle")}</p>
        </header>
        {!graph ? (
          <p className="rounded-xl border border-outline-variant/15 bg-surface-container-low/80 px-4 py-3 text-sm text-on-surface-variant">
            {t("graphView.empty")}
          </p>
        ) : (
          <div className="flex flex-col gap-5">
            <article className="w-full">
              <div
                role="group"
                aria-label={t("graphView.filtersHeading")}
                className="mb-4 grid gap-3 rounded-xl border border-outline-variant/15 bg-surface-container-low/90 p-4 shadow-sm backdrop-blur-sm md:grid-cols-12"
              >
                <label className="flex flex-col gap-1.5 md:col-span-3">
                  <span className="font-label text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
                    {t("graphView.viewModeLabel")}
                  </span>
                  <select
                    className="rounded-lg border border-outline-variant/25 bg-surface-container-lowest px-3 py-2.5 text-sm text-on-surface shadow-sm focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30"
                    value={viewMode}
                    onChange={(e) => setViewMode(e.target.value as ViewMode)}
                  >
                    <option value="all">{t("graphView.viewAll")}</option>
                    <option value="ego">{t("graphView.viewEgo")}</option>
                    <option value="location-item">{t("graphView.viewLocItem")}</option>
                    <option value="epoch">{t("graphView.viewEpoch")}</option>
                  </select>
                </label>

                {viewMode === "ego" ? (
                  <>
                    <label className="flex flex-col gap-1.5 md:col-span-4">
                      <span className="font-label text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
                        {t("graphView.searchCenterLabel")}
                      </span>
                      <input
                        type="search"
                        autoComplete="off"
                        className="rounded-lg border border-outline-variant/25 bg-surface-container-lowest px-3 py-2.5 text-sm text-on-surface shadow-sm focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30"
                        value={egoQuery}
                        onChange={(e) => setEgoQuery(e.target.value)}
                        placeholder={t("graphView.searchCenterPlaceholder")}
                      />
                    </label>
                    <label className="flex flex-col gap-1.5 md:col-span-3">
                      <span className="font-label text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
                        {t("graphView.centerLabel")}
                      </span>
                      <select
                        className="rounded-lg border border-outline-variant/25 bg-surface-container-lowest px-3 py-2.5 text-sm text-on-surface shadow-sm focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30"
                        value={selectedEgoCenterId}
                        onChange={(e) => setSelectedEgoCenterId(e.target.value)}
                      >
                        <option value="">{t("graphView.centerPlaceholder")}</option>
                        {egoCandidates.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1.5 md:col-span-2">
                      <span className="font-label text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
                        {t("graphView.neighborLabel")}
                      </span>
                      <select
                        className="rounded-lg border border-outline-variant/25 bg-surface-container-lowest px-3 py-2.5 text-sm text-on-surface shadow-sm focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30"
                        value={egoHop}
                        onChange={(e) => setEgoHop(Number(e.target.value) === 2 ? 2 : 1)}
                      >
                        <option value={1}>{t("graphView.neighbor1")}</option>
                        <option value={2}>{t("graphView.neighbor2")}</option>
                      </select>
                    </label>
                  </>
                ) : null}

                {viewMode === "epoch" ? (
                  <label className="flex flex-col gap-1.5 md:col-span-6">
                    <span className="font-label text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
                      {t("graphView.epochLabel")}
                    </span>
                    <input
                      type="range"
                      className="accent-primary"
                      min={0}
                      max={Math.max(epochOptions.length - 1, 0)}
                      step={1}
                      value={pendingEpochIndex}
                      onChange={(e) => setPendingEpochIndex(Number(e.target.value))}
                      disabled={!epochOptions.length}
                    />
                    <div className="text-xs text-on-surface-variant">
                      {epochOptions.length
                        ? t("graphView.epochCurrent", undefined, { label: epochOptions[activeEpochIndex]?.label ?? "—" })
                        : t("graphView.noEpochs")}
                    </div>
                  </label>
                ) : null}

                <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-1 py-1 md:col-span-3 md:self-end">
                  <input
                    type="checkbox"
                    className="size-4 rounded border-outline-variant/40 text-primary focus:ring-primary/40"
                    checked={pruneIsolatedNodes}
                    onChange={(e) => setPruneIsolatedNodes(e.target.checked)}
                  />
                  <span className="text-sm text-on-surface-variant">{t("graphView.pruneOrphans")}</span>
                </label>

                <label className="flex flex-col gap-1.5 md:col-span-3">
                  <span className="font-label text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
                    {t("graphView.layoutLabel")}
                  </span>
                  <select
                    className="rounded-lg border border-outline-variant/25 bg-surface-container-lowest px-3 py-2.5 text-sm text-on-surface shadow-sm focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30"
                    value={layoutMode}
                    onChange={(e) => setLayoutMode(e.target.value as LayoutMode)}
                  >
                    <option value="dagre-ltr">{t("graphView.layoutDagre")}</option>
                    <option value="fixed">{t("graphView.layoutFixed")}</option>
                  </select>
                </label>
              </div>

              {edgesWereTruncated ? (
                <p
                  className="mb-1 rounded-lg border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2.5 text-sm leading-snug text-amber-100/95"
                  role="status"
                >
                  {t("graphView.edgesCapped")}
                </p>
              ) : null}

              <div className="mb-1 flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-outline-variant/10 pb-3">
                <p className="font-headline text-sm font-semibold text-on-surface">
                  {t("graphView.statsLine", undefined, { nodes: displayNodes.length, edges: drawnEdges.length })}
                </p>
                <span className="text-on-surface-variant/50" aria-hidden>
                  ·
                </span>
                <p className="text-sm text-on-surface-variant">{t(layoutDescKey)}</p>
              </div>

              <p className="mb-3 text-xs text-on-surface-variant/90">{t("graphView.interactionHint")}</p>

              {displayNodes.length === 0 ? (
                <p className="rounded-xl border border-outline-variant/15 bg-surface-container-low/60 px-4 py-3 text-sm text-on-surface-variant">
                  {viewMode === "ego" && !selectedEgoCenterId ? t("graphView.emptyNoCenter") : t("graphView.emptyNoNodes")}
                </p>
              ) : (
                <>
                  <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg bg-surface-container-low/50 px-3 py-2.5">
                    <span className="font-label text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant/80">
                      {t("graphView.legendHeading")}
                    </span>
                    <div className="hidden h-4 w-px bg-outline-variant/25 sm:block" aria-hidden />
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                      {LEGEND_NODE_TYPES.map((nt) => {
                        const s = NODE_TYPE_STYLES[nt];
                        return (
                          <span
                            key={nt}
                            className="inline-flex items-center gap-1.5 font-label text-[11px] text-on-surface-variant"
                          >
                            <span
                              className="inline-block size-2.5 shrink-0 rounded-full border shadow-sm"
                              style={{ background: s.fill, borderColor: s.stroke }}
                            />
                            {nodeTypeLegend(nt, locale)}
                          </span>
                        );
                      })}
                      <span className="text-[11px] text-on-surface-variant/70">{t("graphView.legendOther")}</span>
                    </div>
                  </div>
                  <UniverseGraphAntv
                    graph={filteredGraph}
                    protagonistCharacterId={
                      viewMode === "ego" ? selectedEgoCenterId || protagonistCharacterId : protagonistCharacterId
                    }
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
          </div>
        )}
      </div>
    </section>
  );
}
