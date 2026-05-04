import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import G6 from "@antv/g6";
import { useI18n } from "../../i18n/useI18n";
import type { AnchorDagFullscreenApi } from "./AnchorDagSection";

export type StorylineLite = {
  id: string;
  type: "MAIN" | "USER_EDIT" | "S_TIER" | "A_TIER" | "B_TIER";
  title: string;
};

type AnchorNodeLite = {
  id: string;
  title: string;
  status: "LOCKED" | "UNLOCKED" | "RESOLVED";
  node_kind?: "NORMAL" | "FORK" | "MERGE" | "CHECKPOINT" | "ENDING";
  storyline_ids?: string[];
  depends_on: string[];
};

export type AnchorNodesGraphViewProps = {
  nodes: AnchorNodeLite[];
  storylines?: StorylineLite[];
  selectedId: string | null;
  onSelect: (nodeId: string) => void;
  /** Viewport height in CSS px; graph is panned horizontally inside this band. */
  height?: number;
  /** Bump when parent adds/removes nodes so internal drag positions reset with topology. */
  layoutEpoch?: number;
  /** When set with `onToggleDetailPanel`, a compact control is shown beside Reset to show/hide the detail column. */
  detailPanelOpen?: boolean;
  onToggleDetailPanel?: () => void;
  /** Same chrome as Reset / detail — usually from `AnchorDagSection` render prop. */
  fullscreen?: AnchorDagFullscreenApi;
  interactionMode?: "view" | "edit";
  onInteractionModeChange?: (mode: "view" | "edit") => void;
  linkPick?: null | { mode: "parent"; childId: string } | { mode: "child"; parentId: string };
  onResolveLinkPick?: (pickedNodeId: string) => void;
  onCanvasCreateNode?: (canvasPoint: { x: number; y: number }) => void;
  onGraphDeleteNode?: (nodeId: string) => void;
  onGraphStartLinkParent?: (childId: string) => void;
  onGraphStartLinkChild?: (parentId: string) => void;
  /** Remove directed edge parent → child (child.depends_on loses parent). */
  onRemoveDependency?: (parentId: string, childId: string) => void;
  pendingManualPosition?: { id: string; x: number; y: number } | null;
  onConsumePendingManualPosition?: () => void;
  /** Red stroke on these nodes / dependency edges (e.g. validation errors). */
  validationHighlights?: null | { nodeIds: string[]; edges: Array<{ parentId: string; childId: string }> };
};

function nodeColor(status: string): { fill: string; stroke: string } {
  if (status === "RESOLVED") return { fill: "#1f2937", stroke: "#34d399" };
  if (status === "UNLOCKED") return { fill: "#172554", stroke: "#60a5fa" };
  return { fill: "#111827", stroke: "#6b7280" };
}

function kindBadge(kind: string): string {
  if (kind === "FORK") return "Y";
  if (kind === "MERGE") return "M";
  if (kind === "CHECKPOINT") return "C";
  if (kind === "ENDING") return "E";
  return "N";
}

const TIER_ORDER: Record<StorylineLite["type"], number> = {
  MAIN: 0,
  USER_EDIT: 1,
  S_TIER: 2,
  A_TIER: 3,
  B_TIER: 4,
};

function inferTierFromId(sid: string): StorylineLite["type"] {
  const s = sid.toLowerCase();
  if (s.endsWith("_main") || s.includes("_main")) return "MAIN";
  if (s.includes("user_edit")) return "USER_EDIT";
  if (s.includes("s_tier") || s.includes("_s_")) return "S_TIER";
  if (s.includes("a_tier") || s.includes("_a_")) return "A_TIER";
  if (s.includes("b_tier") || s.includes("_b_")) return "B_TIER";
  return "B_TIER";
}

function tierFromStorylinesOrId(sid: string, byId: Map<string, StorylineLite>): StorylineLite["type"] {
  return byId.get(sid)?.type ?? inferTierFromId(sid);
}

function pickPrimarySideId(
  storylineIds: string[] | undefined,
  mainId: string,
  byId: Map<string, StorylineLite>,
): string | null {
  const nonMain = (storylineIds ?? []).filter((id) => id && id !== mainId);
  if (nonMain.length === 0) return null;
  return [...nonMain].sort(
    (a, b) =>
      TIER_ORDER[tierFromStorylinesOrId(a, byId)] - TIER_ORDER[tierFromStorylinesOrId(b, byId)] || a.localeCompare(b),
  )[0]!;
}

/** Longest path depth from sources: x layer = f(dependencies). */
function computeLayers(nodes: AnchorNodeLite[]): Map<string, number> {
  const map = new Map(nodes.map((n) => [n.id, n]));
  const memo = new Map<string, number>();
  const visiting = new Set<string>();

  const dfs = (id: string): number => {
    if (memo.has(id)) return memo.get(id)!;
    if (visiting.has(id)) {
      return 0;
    }
    visiting.add(id);
    const n = map.get(id);
    const deps = (n?.depends_on ?? []).filter((d) => map.has(d));
    if (deps.length === 0) {
      visiting.delete(id);
      memo.set(id, 0);
      return 0;
    }
    const depth = 1 + Math.max(...deps.map((d) => dfs(d)));
    visiting.delete(id);
    memo.set(id, depth);
    return depth;
  };

  for (const n of nodes) {
    dfs(n.id);
  }
  return memo;
}

function buildMainId(orderedSids: string[]): string {
  return orderedSids.find((s) => s.endsWith("_main") || s.includes("_main")) ?? "";
}

/** Topology + viewport height only — not selection or manual drag positions. */
function layoutSignature(nodes: AnchorNodeLite[], h: number): string {
  const parts = nodes
    .map((n) => `${n.id}|${(n.depends_on ?? []).join(",")}`)
    .sort()
    .join(";");
  return `${parts}@${h}`;
}

export function AnchorNodesGraphView({
  nodes,
  storylines,
  selectedId,
  onSelect,
  height = 420,
  layoutEpoch = 0,
  detailPanelOpen = true,
  onToggleDetailPanel,
  fullscreen,
  interactionMode = "view",
  onInteractionModeChange,
  linkPick = null,
  onResolveLinkPick,
  onCanvasCreateNode,
  onGraphDeleteNode,
  onGraphStartLinkParent,
  onGraphStartLinkChild,
  onRemoveDependency,
  pendingManualPosition = null,
  onConsumePendingManualPosition,
  validationHighlights = null,
}: AnchorNodesGraphViewProps) {
  const { locale } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<import("@antv/g6").IGraph | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  type CtxMenu =
    | null
    | { kind: "canvas"; sx: number; sy: number; clientX: number; clientY: number }
    | { kind: "node"; nodeId: string; sx: number; sy: number }
    | { kind: "edge"; parentId: string; childId: string; sx: number; sy: number };
  const [ctxMenu, setCtxMenu] = useState<CtxMenu>(null);

  const apiRef = useRef({
    interactionMode,
    linkPick,
    onResolveLinkPick,
    onCanvasCreateNode,
    onGraphDeleteNode,
    onGraphStartLinkParent,
    onGraphStartLinkChild,
    onRemoveDependency,
    onSelect,
    detailPanelOpen,
    onToggleDetailPanel,
  });

  useEffect(() => {
    apiRef.current = {
      interactionMode,
      linkPick,
      onResolveLinkPick,
      onCanvasCreateNode,
      onGraphDeleteNode,
      onGraphStartLinkParent,
      onGraphStartLinkChild,
      onRemoveDependency,
      onSelect,
      detailPanelOpen,
      onToggleDetailPanel,
    };
  }, [
    interactionMode,
    linkPick,
    onResolveLinkPick,
    onCanvasCreateNode,
    onGraphDeleteNode,
    onGraphStartLinkParent,
    onGraphStartLinkChild,
    onRemoveDependency,
    onSelect,
    detailPanelOpen,
    onToggleDetailPanel,
  ]);

  const [linkRubber, setLinkRubber] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);

  const [highlightStorylineId, setHighlightStorylineId] = useState<string>("ALL");
  const [manualPositions, setManualPositions] = useState<Record<string, { x: number; y: number }>>({});
  /** Bumped when user clicks reset layout so we refit the viewport. */
  const [layoutRefitToken, setLayoutRefitToken] = useState(0);
  const lastEpochFit = useRef<number>(-1);
  const lastRefitToken = useRef(-1);

  useEffect(() => {
    if (!pendingManualPosition || !onConsumePendingManualPosition) return;
    const { id, x, y } = pendingManualPosition;
    if (!nodes.some((n) => n.id === id)) return;
    setManualPositions((prev) => ({ ...prev, [id]: { x, y } }));
    onConsumePendingManualPosition();
  }, [pendingManualPosition, nodes, onConsumePendingManualPosition]);

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (linkPick) {
        e.preventDefault();
        e.stopImmediatePropagation();
        onResolveLinkPick?.("__cancel__");
        return;
      }
      if (ctxMenu) {
        e.preventDefault();
        e.stopImmediatePropagation();
        setCtxMenu(null);
        return;
      }
    };
    window.addEventListener("keydown", onEsc, true);
    return () => window.removeEventListener("keydown", onEsc, true);
  }, [linkPick, ctxMenu, onResolveLinkPick]);

  useEffect(() => {
    if (!ctxMenu) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target;
      if (t instanceof Element && t.closest("[data-anchor-ctx-menu]")) return;
      setCtxMenu(null);
    };
    window.addEventListener("pointerdown", onDown, true);
    return () => window.removeEventListener("pointerdown", onDown, true);
  }, [ctxMenu]);

  const slById = useMemo(() => {
    const m = new Map<string, StorylineLite>();
    for (const s of storylines ?? []) {
      m.set(s.id, s);
    }
    return m;
  }, [storylines]);

  const storylineOptions = useMemo((): StorylineLite[] => {
    const rows: StorylineLite[] = [];
    const seen = new Set<string>();
    for (const s of storylines ?? []) {
      if (!seen.has(s.id)) {
        seen.add(s.id);
        rows.push(s);
      }
    }
    for (const n of nodes) {
      for (const sid of n.storyline_ids ?? []) {
        if (seen.has(sid)) continue;
        seen.add(sid);
        const t = inferTierFromId(sid);
        rows.push({ id: sid, type: t, title: sid });
      }
    }
    return [...rows].sort(
      (a, b) => TIER_ORDER[a.type] - TIER_ORDER[b.type] || a.id.localeCompare(b.id),
    );
  }, [nodes, storylines]);

  const sideStorylineOrder = useMemo(() => {
    const side = storylineOptions.filter((r) => r.type !== "MAIN");
    return side.map((r) => r.id);
  }, [storylineOptions]);

  const sidToBandIndex = useMemo(() => {
    const m = new Map<string, number>();
    sideStorylineOrder.forEach((id, k) => m.set(id, k));
    return m;
  }, [sideStorylineOrder]);

  const mainId = useMemo(() => {
    const o = storylineOptions.map((r) => r.id);
    return buildMainId(o) || o.find((id) => id.includes("main")) || "";
  }, [storylineOptions]);

  const structuralSig = useMemo(() => layoutSignature(nodes, height), [nodes, height]);

  const tierShort = useCallback(
    (t: StorylineLite["type"]) => {
      if (locale === "en") {
        if (t === "MAIN") return "MAIN";
        if (t === "USER_EDIT") return "UE";
        if (t === "S_TIER") return "S";
        if (t === "A_TIER") return "A";
        return "B";
      }
      if (t === "MAIN") return "主線";
      if (t === "USER_EDIT") return "編輯";
      if (t === "S_TIER") return "S";
      if (t === "A_TIER") return "A";
      return "B";
    },
    [locale],
  );

  const allLabel =
    locale === "en" ? "All storylines" : locale === "zh-Hans" ? "全部劇情線" : "全部劇情線";

  const highlightLabel =
    locale === "en" ? "Highlight" : locale === "zh-Hans" ? "劇情線" : "劇情線";

  const detailToggleAria =
    locale === "en"
      ? detailPanelOpen
        ? "Hide node detail panel"
        : "Show node detail panel"
      : detailPanelOpen
        ? "收起節點詳情"
        : "展開節點詳情";

  useEffect(() => {
    if (highlightStorylineId === "ALL") return;
    if (!storylineOptions.some((r) => r.id === highlightStorylineId)) {
      setHighlightStorylineId("ALL");
    }
  }, [highlightStorylineId, storylineOptions]);

  const ueSidSet = useMemo(
    () => new Set((storylines ?? []).filter((s) => s.type === "USER_EDIT").map((s) => s.id)),
    [storylines],
  );

  /** Pending placement must affect graphData in the same render (graph effect runs before pending→manual effect). */
  const effectiveManualPositions = useMemo(() => {
    if (!pendingManualPosition) return manualPositions;
    return { ...manualPositions, [pendingManualPosition.id]: { x: pendingManualPosition.x, y: pendingManualPosition.y } };
  }, [manualPositions, pendingManualPosition]);

  const graphData = useMemo(() => {
    const layerById = computeLayers(nodes);

    const xStep = 280;
    const centerY = height * 0.48;
    const yStep = 68;

    const yForSideBand = (bandK: number) => {
      const r = Math.floor(bandK / 2) + 1;
      const sign = bandK % 2 === 0 ? 1 : -1;
      return centerY + sign * r * yStep;
    };

    const hasUeStoryline = (n: AnchorNodeLite) => (n.storyline_ids ?? []).some((sid) => ueSidSet.has(sid));

    const ordered = [...nodes].sort(
      (a, b) =>
        (layerById.get(a.id) ?? 0) - (layerById.get(b.id) ?? 0) || String(a.id).localeCompare(String(b.id)),
    );

    const pos: Record<string, { x: number; y: number }> = {};

    for (const n of ordered) {
      const kind = String(n.node_kind ?? "NORMAL").toUpperCase();
      const layer = layerById.get(n.id) ?? 0;
      let x = 160 + layer * xStep;
      let y = centerY;

      const ids = n.storyline_ids ?? [];
      const onlyMain = Boolean(mainId) && ids.length > 0 && ids.every((id) => id === mainId);
      const onSpineY =
        kind === "CHECKPOINT" ||
        kind === "ENDING" ||
        (onlyMain && (kind === "NORMAL" || kind === "FORK" || kind === "MERGE"));

      if (hasUeStoryline(n)) {
        const dp = (n.depends_on ?? []).filter((d) => pos[d]);
        if (dp.length > 0) {
          y = dp.reduce((s, d) => s + pos[d].y, 0) / dp.length;
        } else if (onSpineY) {
          y = centerY;
        } else {
          const pSid = pickPrimarySideId(n.storyline_ids, mainId, slById);
          if (pSid) {
            const k = sidToBandIndex.get(pSid) ?? 0;
            y = yForSideBand(k);
          } else {
            y = yForSideBand(0);
          }
        }
      } else if (onSpineY) {
        y = centerY;
      } else {
        const pSid = pickPrimarySideId(n.storyline_ids, mainId, slById);
        if (pSid) {
          const k = sidToBandIndex.get(pSid) ?? 0;
          y = yForSideBand(k);
        } else {
          y = yForSideBand(0);
        }
      }

      pos[n.id] = { x, y };
    }

    const mappedNodes = nodes.map((n) => {
      const color = nodeColor(String(n.status ?? "LOCKED"));
      const prefix = kindBadge(String(n.node_kind ?? "NORMAL"));
      const base = pos[n.id] ?? { x: 160, y: centerY };
      let x = base.x;
      let y = base.y;
      const ov = effectiveManualPositions[n.id];
      if (ov) {
        x = ov.x;
        y = ov.y;
      }

      return {
        id: n.id,
        label: `[${prefix}] ${String(n.title ?? n.id).slice(0, 32)}`,
        x,
        y,
        fx: effectiveManualPositions[n.id] ? x : undefined,
        fy: effectiveManualPositions[n.id] ? y : undefined,
        style: {
          fill: color.fill,
          stroke: color.stroke,
          lineWidth: 1.6,
          opacity: 1,
        },
      };
    });

    const nodeIdSet = new Set(mappedNodes.map((m) => m.id));
    const mappedEdges = nodes.flatMap((n) =>
      (n.depends_on ?? [])
        .filter((dep) => nodeIdSet.has(dep))
        .map((dep) => ({
          id: `${dep}->${n.id}`,
          source: dep,
          target: n.id,
          style: {
            stroke: "#5c6b82",
            opacity: 1,
            lineWidth: 1.8,
            endArrow: {
              path: G6.Arrow.triangle(6, 8, 2),
              fill: "#5c6b82",
            },
          },
        })),
    );
    return { nodes: mappedNodes, edges: mappedEdges };
  }, [height, mainId, nodes, sidToBandIndex, slById, effectiveManualPositions, ueSidSet]);

  const applySelectionStates = useCallback(() => {
    const g = graphRef.current;
    if (!g || typeof g.getNodes !== "function") return;
    const sid = selectedId;
    g.getNodes().forEach((node) => {
      const model = node.getModel() as { id?: string };
      const id = String(model.id ?? "");
      g.setItemState(node, "selected", Boolean(sid && id === sid));
    });
  }, [selectedId]);

  const applyDagErrorHighlights = useCallback(() => {
    const g = graphRef.current as {
      getNodes?: () => Iterable<{ getModel?: () => { id?: string } }>;
      getEdges?: () => Iterable<{ getModel?: () => { source?: string; target?: string } }>;
      setItemState?: (item: unknown, name: string, value: string | boolean) => void;
    } | null;
    if (!g?.getNodes || !g.setItemState) return;
    const nh = new Set(validationHighlights?.nodeIds ?? []);
    const eh = new Set((validationHighlights?.edges ?? []).map((e) => `${e.parentId}->${e.childId}`));
    for (const node of g.getNodes() ?? []) {
      const id = String(node.getModel?.()?.id ?? "");
      g.setItemState(node, "dagError", nh.has(id));
    }
    if (typeof g.getEdges === "function") {
      for (const edge of g.getEdges() ?? []) {
        const m = edge.getModel?.() as { source?: string; target?: string } | undefined;
        const key = `${String(m?.source ?? "")}->${String(m?.target ?? "")}`;
        g.setItemState(edge, "dagError", eh.has(key));
      }
    }
  }, [validationHighlights]);

  const applyHighlightStates = useCallback(() => {
    const g = graphRef.current;
    if (!g || typeof g.getNodes !== "function") return;
    const sid = highlightStorylineId;
    const storySet =
      sid === "ALL"
        ? null
        : new Set<string>([sid]);

    g.getNodes().forEach((node) => {
      const model = node.getModel() as { id?: string };
      const id = String(model.id ?? "");
      const n = nodes.find((x) => x.id === id);
      const belongs =
        sid === "ALL" ? false : Boolean(n && storySet && (n.storyline_ids ?? []).some((x) => storySet.has(x)));
      g.setItemState(node, "highlighted", Boolean(belongs));
    });

    if (typeof g.getEdges === "function") {
      g.getEdges().forEach((edge) => {
        const em = edge.getModel() as { source?: string; target?: string };
        const sId = String(em.source ?? "");
        const tId = String(em.target ?? "");
        const ns = nodes.find((x) => x.id === sId);
        const nt = nodes.find((x) => x.id === tId);
        const hb =
          sid !== "ALL" &&
          Boolean(
            ns &&
              nt &&
              storySet &&
              (ns.storyline_ids ?? []).some((x) => storySet.has(x)) &&
              (nt.storyline_ids ?? []).some((x) => storySet.has(x)),
          );
        g.setItemState(edge, "highlighted", Boolean(hb));
      });
    }
  }, [highlightStorylineId, nodes]);

  const initGraph = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const w = Math.max(Math.round(rect.width), 1);
    const h = Math.max(Math.round(height), 1);
    if (graphRef.current) {
      return;
    }
    const g = new G6.Graph({
      container,
      width: w,
      height: h,
      minZoom: 0.25,
      maxZoom: 2.4,
      nodeStateStyles: {
        dagError: {
          stroke: "#dc2626",
          lineWidth: 4.5,
          shadowColor: "rgba(220,38,38,0.55)",
          shadowBlur: 18,
          shadowOffsetX: 0,
          shadowOffsetY: 0,
        },
        highlighted: {
          stroke: "#fbbf24",
          lineWidth: 2.6,
          shadowColor: "rgba(251,191,36,0.35)",
          shadowBlur: 12,
        },
        /** Stroke-only emphasis; explicit dark fill + label so text never washes out to white. */
        selected: {
          fill: "#0c1424",
          stroke: "#fbbf24",
          lineWidth: 2.85,
          shadowColor: "rgba(251, 191, 36, 0.28)",
          shadowBlur: 14,
          labelCfg: {
            style: {
              fill: "#e8edf5",
              fontSize: 11.5,
              fontWeight: 600,
              fontFamily: "ui-sans-serif, system-ui, sans-serif",
            },
          },
        },
      },
      edgeStateStyles: {
        dagError: {
          stroke: "#dc2626",
          lineWidth: 4,
          shadowColor: "rgba(220,38,38,0.4)",
          shadowBlur: 10,
        },
        highlighted: {
          stroke: "#f59e0b",
          lineWidth: 2.2,
        },
      },
      defaultNode: {
        type: "rect",
        size: [248, 56],
        style: { radius: 10, fill: "#0c1424", stroke: "#5a6a85", lineWidth: 1.4 },
        labelCfg: {
          style: {
            fill: "#e8edf5",
            fontSize: 11.5,
            fontWeight: 500,
            fontFamily: "ui-sans-serif, system-ui, sans-serif",
          },
        },
      },
      defaultEdge: {
        type: "line",
        style: { stroke: "#5c6b82", lineWidth: 1.4 },
      },
      modes: {
        default: ["drag-canvas", "zoom-canvas", "drag-node"],
      },
    } as any);

    g.on("node:dragend", (evt: { item?: { getModel?: () => { id?: string; x?: number; y?: number } } }) => {
      const model = evt?.item?.getModel?.();
      const id = String(model?.id ?? "");
      if (!id) return;
      const x = Number(model?.x);
      const y = Number(model?.y);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        setManualPositions((prev) => ({ ...prev, [id]: { x, y } }));
      }
    });

    g.on("node:click", (evt: any) => {
      const id = String(evt?.item?.getModel?.()?.id ?? "");
      if (!id) return;
      const lp = apiRef.current.linkPick;
      if (lp && apiRef.current.onResolveLinkPick) {
        apiRef.current.onResolveLinkPick(id);
        return;
      }
      apiRef.current.onSelect(id);
    });

    g.on("node:dblclick", (evt: any) => {
      evt?.preventDefault?.();
      const id = String(evt?.item?.getModel?.()?.id ?? "");
      if (!id) return;
      const lp = apiRef.current.linkPick;
      if (lp && apiRef.current.onResolveLinkPick) return;
      apiRef.current.onSelect(id);
      const { detailPanelOpen: panelOpen, onToggleDetailPanel } = apiRef.current;
      if (!panelOpen && onToggleDetailPanel) {
        onToggleDetailPanel();
      }
    });

    g.on("canvas:click", (evt: any) => {
      if (!apiRef.current.linkPick || !apiRef.current.onResolveLinkPick) return;
      evt?.stopPropagation?.();
      apiRef.current.onResolveLinkPick("__cancel__");
    });

    g.on("edge:click", (evt: any) => {
      if (!apiRef.current.linkPick || !apiRef.current.onResolveLinkPick) return;
      evt?.stopPropagation?.();
      apiRef.current.onResolveLinkPick("__cancel__");
    });

    g.on("canvas:contextmenu", (evt: any) => {
      evt?.preventDefault?.();
      if (apiRef.current.interactionMode !== "edit") return;
      const sx = Number(evt.clientX ?? 0);
      const sy = Number(evt.clientY ?? 0);
      setCtxMenu({ kind: "canvas", sx, sy, clientX: sx, clientY: sy });
    });

    g.on("node:contextmenu", (evt: any) => {
      evt?.preventDefault?.();
      if (apiRef.current.interactionMode !== "edit") return;
      const id = String(evt?.item?.getModel?.()?.id ?? "");
      if (!id) return;
      const sx = Number(evt.clientX ?? 0);
      const sy = Number(evt.clientY ?? 0);
      setCtxMenu({ kind: "node", nodeId: id, sx, sy });
    });

    g.on("edge:contextmenu", (evt: any) => {
      evt?.preventDefault?.();
      if (apiRef.current.interactionMode !== "edit") return;
      const model = evt?.item?.getModel?.() as { source?: string; target?: string } | undefined;
      const parentId = String(model?.source ?? "");
      const childId = String(model?.target ?? "");
      if (!parentId || !childId) return;
      const sx = Number(evt.clientX ?? 0);
      const sy = Number(evt.clientY ?? 0);
      setCtxMenu({ kind: "edge", parentId, childId, sx, sy });
    });

    graphRef.current = g as import("@antv/g6").IGraph;
  }, [height]);

  useEffect(() => {
    initGraph();
    return () => {
      try {
        graphRef.current?.destroy?.();
      } finally {
        graphRef.current = null;
      }
    };
  }, [initGraph]);

  useEffect(() => {
    const g = graphRef.current;
    const el = containerRef.current;
    if (!g || !el) return;
    const ro = new ResizeObserver(() => {
      const rect = el.getBoundingClientRect();
      const w = Math.max(1, Math.round(rect.width));
      const h = Math.max(1, Math.round(height));
      g.changeSize(w, h);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);

  useEffect(() => {
    const g = graphRef.current as import("@antv/g6").IGraph & {
      getGroup?: () => { getMatrix?: () => number[] | undefined; setMatrix?: (m: number[]) => void };
    };
    if (!g) return;

    const epochChanged = layoutEpoch !== lastEpochFit.current;
    const refitRequested = layoutRefitToken !== lastRefitToken.current;
    if (epochChanged) lastEpochFit.current = layoutEpoch;
    if (refitRequested) lastRefitToken.current = layoutRefitToken;

    /** Only refit on explicit layout epoch (story / first load) or Reset — not on every node/edge edit. */
    const shouldRefit = (epochChanged || refitRequested) && !pendingManualPosition;
    let savedMatrix: number[] | null = null;
    if (!shouldRefit) {
      try {
        const m = g.getGroup?.()?.getMatrix?.();
        if (m && m.length >= 6) savedMatrix = [...m];
      } catch {
        savedMatrix = null;
      }
    }

    g.changeData(graphData);
    g.render();

    if (shouldRefit) {
      g.fitView(20);
    } else if (savedMatrix) {
      try {
        g.getGroup?.()?.setMatrix?.(savedMatrix);
      } catch {
        /* noop */
      }
    }

    requestAnimationFrame(() => {
      applyHighlightStates();
      applySelectionStates();
      applyDagErrorHighlights();
    });
  }, [
    graphData,
    layoutEpoch,
    layoutRefitToken,
    pendingManualPosition,
    applyHighlightStates,
    applySelectionStates,
    applyDagErrorHighlights,
  ]);

  useEffect(() => {
    if (!linkPick) {
      setLinkRubber(null);
      return;
    }
    const paint = (e: MouseEvent) => {
      const g = graphRef.current as
        | {
            findById?: (id: string) => { getModel?: () => { x?: number; y?: number } };
            getClientByPoint?: (x: number, y: number) => { x: number; y: number };
          }
        | null
        | undefined;
      const box = containerRef.current?.getBoundingClientRect();
      if (!g?.findById || !g.getClientByPoint || !box) return;
      const anchorId = linkPick.mode === "parent" ? linkPick.childId : linkPick.parentId;
      const item = g.findById(anchorId);
      const m = item?.getModel?.();
      const nx = Number(m?.x ?? NaN);
      const ny = Number(m?.y ?? NaN);
      if (!Number.isFinite(nx) || !Number.isFinite(ny)) return;
      const c = g.getClientByPoint(nx, ny);
      setLinkRubber({
        x1: c.x - box.left,
        y1: c.y - box.top,
        x2: e.clientX - box.left,
        y2: e.clientY - box.top,
      });
    };
    window.addEventListener("mousemove", paint, true);
    return () => window.removeEventListener("mousemove", paint, true);
  }, [linkPick, structuralSig]);

  useEffect(() => {
    requestAnimationFrame(() => {
      applyHighlightStates();
      applySelectionStates();
      applyDagErrorHighlights();
    });
  }, [applyHighlightStates, applySelectionStates, applyDagErrorHighlights, highlightStorylineId, selectedId]);

  useEffect(() => {
    requestAnimationFrame(() => {
      applyDagErrorHighlights();
    });
  }, [applyDagErrorHighlights, validationHighlights]);

  const handleResetLayout = () => {
    setManualPositions({});
    lastEpochFit.current = -1;
    setLayoutRefitToken((t) => t + 1);
  };

  const resetTip =
    locale === "en" ? "Reset auto layout" : locale === "zh-Hans" ? "復位：重新計算自動排版" : "復位：重新計算自動排版";
  const fsTip =
    locale === "en"
      ? fullscreen?.active
        ? "Exit fullscreen"
        : "Enter fullscreen"
      : locale === "zh-Hans"
        ? fullscreen?.active
          ? "退出全屏"
          : "全屏显示"
        : fullscreen?.active
          ? "離開全螢幕"
          : "全螢幕顯示";
  const editModeTip =
    locale === "en"
      ? interactionMode === "edit"
        ? "Switch to view mode"
        : "Edit DAG: context menus & links"
      : interactionMode === "edit"
        ? "切換為檢視模式"
        : "編輯 DAG：右鍵選單與依賴連線";

  const linkPickLabel =
    linkPick?.mode === "parent"
      ? locale === "en"
        ? `Click the parent node for “${linkPick.childId}”…`
        : locale === "zh-Hans"
          ? `请点击「${linkPick.childId}」的父节点…`
          : `請點選「${linkPick.childId}」的父節點…`
      : linkPick
        ? locale === "en"
          ? `Click the child node after “${linkPick.parentId}”…`
          : locale === "zh-Hans"
            ? `请点击「${linkPick.parentId}」之后的子节点…`
            : `請點選「${linkPick.parentId}」之後的子節點…`
        : "";

  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-outline-variant/20 bg-gradient-to-b from-[#040a16] to-[#070f22] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]"
      style={{ minHeight: height + 48 }}
      onContextMenu={(e) => {
        if (interactionMode === "edit") e.preventDefault();
      }}
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-white/5 px-3 py-2.5">
        <label className="flex min-w-[min(100%,14rem)] flex-1 flex-col gap-1.5">
          <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-amber-200/90">{highlightLabel}</span>
          <div className="relative">
            <select
              value={highlightStorylineId}
              onChange={(e) => setHighlightStorylineId(e.target.value)}
              className="w-full cursor-pointer appearance-none rounded-xl border border-white/10 bg-[#0a1528]/90 py-2 pl-3 pr-9 text-left text-sm text-slate-100 shadow-inner outline-none transition hover:border-amber-400/25 focus:border-amber-400/50 focus:ring-1 focus:ring-amber-300/30"
            >
              <option value="ALL">{allLabel}</option>
              {storylineOptions.map((r) => (
                <option key={r.id} value={r.id}>
                  {`[${tierShort(r.type)}] ${r.title || r.id}`}
                </option>
              ))}
            </select>
            <span
              className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-amber-200/70"
              aria-hidden
            >
              <span className="material-symbols-outlined text-lg leading-none">expand_more</span>
            </span>
          </div>
        </label>
        <div className="flex shrink-0 items-center gap-1.5 rounded-2xl border border-amber-400/20 bg-[#060d18]/95 py-1 pl-1 pr-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
          {fullscreen ? (
            <>
              <button
                type="button"
                onClick={() => fullscreen.toggle()}
                aria-pressed={fullscreen.active}
                aria-label={fsTip}
                title={fsTip}
                className={
                  fullscreen.active
                    ? "flex h-10 w-10 items-center justify-center rounded-xl text-amber-50 ring-1 ring-amber-400/45 ring-inset transition hover:bg-amber-400/15"
                    : "flex h-10 w-10 items-center justify-center rounded-xl text-amber-50/95 transition hover:bg-white/5"
                }
              >
                <span className="material-symbols-outlined text-[22px] leading-none" aria-hidden>
                  {fullscreen.active ? "fullscreen_exit" : "fullscreen"}
                </span>
              </button>
              <span className="h-7 w-px shrink-0 bg-white/12" aria-hidden />
            </>
          ) : null}
          <button
            type="button"
            className="flex h-10 w-10 items-center justify-center rounded-xl text-amber-50/95 transition hover:bg-white/5"
            onClick={handleResetLayout}
            aria-label={resetTip}
            title={resetTip}
          >
            <span className="material-symbols-outlined text-[22px] leading-none" aria-hidden>
              restart_alt
            </span>
          </button>
          {onInteractionModeChange ? (
            <>
              <span className="h-7 w-px shrink-0 bg-white/12" aria-hidden />
              <button
                type="button"
                onClick={() => onInteractionModeChange(interactionMode === "edit" ? "view" : "edit")}
                aria-pressed={interactionMode === "edit"}
                aria-label={editModeTip}
                title={editModeTip}
                className={
                  interactionMode === "edit"
                    ? "flex h-10 w-10 items-center justify-center rounded-xl bg-amber-400/20 text-amber-50 ring-1 ring-amber-400/50"
                    : "flex h-10 w-10 items-center justify-center rounded-xl text-amber-100/90 hover:bg-amber-400/12"
                }
              >
                <span className="material-symbols-outlined text-[22px] leading-none" aria-hidden>
                  {interactionMode === "edit" ? "edit_off" : "edit"}
                </span>
              </button>
            </>
          ) : null}
          {onToggleDetailPanel ? (
            <>
              <span className="h-7 w-px shrink-0 bg-white/12" aria-hidden />
              <button
                type="button"
                onClick={onToggleDetailPanel}
                aria-label={detailToggleAria}
                title={detailToggleAria}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-amber-100/90 transition hover:bg-amber-400/12 hover:text-amber-50"
              >
                <span className="material-symbols-outlined text-[22px] leading-none" aria-hidden>
                  {detailPanelOpen ? "right_panel_close" : "dock_to_right"}
                </span>
              </button>
            </>
          ) : null}
        </div>
      </div>
      {linkPick ? (
        <div className="flex items-center justify-between gap-2 border-b border-amber-400/25 bg-amber-950/35 px-3 py-1.5">
          <span className="font-label text-[11px] text-amber-100/95">{linkPickLabel}</span>
          <button
            type="button"
            className="shrink-0 rounded-lg border border-white/15 px-2 py-0.5 font-label text-[10px] text-amber-100/90 hover:bg-white/10"
            onClick={() => onResolveLinkPick?.("__cancel__")}
          >
            {locale === "en" ? "Cancel" : "取消"}
          </button>
        </div>
      ) : null}
      <div className="relative w-full" style={{ height, minHeight: height, maxHeight: height }}>
        <div ref={containerRef} className="h-full w-full overflow-hidden" />
        {linkPick && linkRubber ? (
          <svg className="pointer-events-none absolute inset-0 z-30 h-full w-full" aria-hidden>
            <line
              x1={linkRubber.x1}
              y1={linkRubber.y1}
              x2={linkRubber.x2}
              y2={linkRubber.y2}
              stroke="#fbbf24"
              strokeWidth={2}
              strokeDasharray="6 4"
              opacity={0.92}
            />
          </svg>
        ) : null}
      </div>
      {ctxMenu?.kind === "canvas" ? (
        <ul
          role="menu"
          data-anchor-ctx-menu
          className="fixed z-[65010] min-w-[11rem] rounded-xl border border-white/15 bg-[#0a121f] py-1 text-xs shadow-2xl"
          style={{ left: ctxMenu.sx, top: ctxMenu.sy }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <li>
            <button
              type="button"
              role="menuitem"
              className="block w-full px-3 py-2 text-left text-slate-100 hover:bg-white/10"
              onClick={() => {
                const g = graphRef.current as
                  | { getPointByClient?: (cx: number, cy: number) => { x: number; y: number } }
                  | null
                  | undefined;
                const pt = g?.getPointByClient?.(ctxMenu.clientX, ctxMenu.clientY);
                if (pt) onCanvasCreateNode?.({ x: pt.x, y: pt.y });
                setCtxMenu(null);
              }}
            >
              {locale === "en" ? "New node here" : locale === "zh-Hans" ? "在此新建节点" : "在此新建節點"}
            </button>
          </li>
        </ul>
      ) : null}
      {ctxMenu?.kind === "node" ? (
        <ul
          role="menu"
          data-anchor-ctx-menu
          className="fixed z-[65010] min-w-[12rem] rounded-xl border border-white/15 bg-[#0a121f] py-1 text-xs shadow-2xl"
          style={{ left: ctxMenu.sx, top: ctxMenu.sy }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <li>
            <button
              type="button"
              className="block w-full px-3 py-2 text-left text-slate-100 hover:bg-white/10"
              onClick={() => {
                onSelect(ctxMenu.nodeId);
                setCtxMenu(null);
              }}
            >
              {locale === "en" ? "Open in panel" : locale === "zh-Hans" ? "在側欄編輯" : "在側欄編輯"}
            </button>
          </li>
          <li>
            <button
              type="button"
              className="block w-full px-3 py-2 text-left text-slate-100 hover:bg-white/10"
              onClick={() => {
                onGraphStartLinkParent?.(ctxMenu.nodeId);
                setCtxMenu(null);
              }}
            >
              {locale === "en" ? "Link parent (pick)" : locale === "zh-Hans" ? "連接父節點（點選）" : "連接父節點（點選）"}
            </button>
          </li>
          <li>
            <button
              type="button"
              className="block w-full px-3 py-2 text-left text-slate-100 hover:bg-white/10"
              onClick={() => {
                onGraphStartLinkChild?.(ctxMenu.nodeId);
                setCtxMenu(null);
              }}
            >
              {locale === "en" ? "Link child (pick)" : locale === "zh-Hans" ? "連接子節點（點選）" : "連接子節點（點選）"}
            </button>
          </li>
          <li>
            <button
              type="button"
              className="block w-full px-3 py-2 text-left text-red-200 hover:bg-red-950/50"
              onClick={() => {
                onGraphDeleteNode?.(ctxMenu.nodeId);
                setCtxMenu(null);
              }}
            >
              {locale === "en" ? "Delete node" : locale === "zh-Hans" ? "删除节点" : "刪除節點"}
            </button>
          </li>
        </ul>
      ) : null}
      {ctxMenu?.kind === "edge" ? (
        <ul
          role="menu"
          data-anchor-ctx-menu
          className="fixed z-[65010] min-w-[12rem] rounded-xl border border-white/15 bg-[#0a121f] py-1 text-xs shadow-2xl"
          style={{ left: ctxMenu.sx, top: ctxMenu.sy }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <li>
            <button
              type="button"
              className="block w-full px-3 py-2 text-left text-amber-100 hover:bg-white/10"
              onClick={() => {
                onRemoveDependency?.(ctxMenu.parentId, ctxMenu.childId);
                setCtxMenu(null);
              }}
            >
              {locale === "en"
                ? "Remove dependency"
                : locale === "zh-Hans"
                  ? "移除此依赖"
                  : "移除此依賴"}
            </button>
          </li>
        </ul>
      ) : null}
    </div>
  );
}
