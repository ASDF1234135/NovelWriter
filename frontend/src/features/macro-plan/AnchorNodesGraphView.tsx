import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import G6 from "@antv/g6";
import { useI18n } from "../../i18n/useI18n";

export type StorylineLite = {
  id: string;
  type: "MAIN" | "S_TIER" | "A_TIER" | "B_TIER";
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

type Props = {
  nodes: AnchorNodeLite[];
  storylines?: StorylineLite[];
  selectedId: string | null;
  onSelect: (nodeId: string) => void;
  /** Viewport height in CSS px; graph is panned horizontally inside this band. */
  height?: number;
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
  S_TIER: 1,
  A_TIER: 2,
  B_TIER: 3,
};

function inferTierFromId(sid: string): StorylineLite["type"] {
  const s = sid.toLowerCase();
  if (s.endsWith("_main") || s.includes("_main")) return "MAIN";
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
    (a, b) => TIER_ORDER[tierFromStorylinesOrId(a, byId)] - TIER_ORDER[tierFromStorylinesOrId(b, byId)] || a.localeCompare(b),
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

export function AnchorNodesGraphView({ nodes, storylines, selectedId, onSelect, height = 420 }: Props) {
  const { locale } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<import("@antv/g6").IGraph | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const [highlightStorylineId, setHighlightStorylineId] = useState<string>("ALL");

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

  /** S → A → B, then by id; defines vertical band order (outward from center). */
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

  const tierShort = useCallback(
    (t: StorylineLite["type"]) => {
      if (locale === "en") {
        if (t === "MAIN") return "MAIN";
        if (t === "S_TIER") return "S";
        if (t === "A_TIER") return "A";
        return "B";
      }
      if (t === "MAIN") return "主線";
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

  useEffect(() => {
    if (highlightStorylineId === "ALL") return;
    if (!storylineOptions.some((r) => r.id === highlightStorylineId)) {
      setHighlightStorylineId("ALL");
    }
  }, [highlightStorylineId, storylineOptions]);

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

    const mappedNodes = nodes.map((n) => {
      const color = nodeColor(String(n.status ?? "LOCKED"));
      const prefix = kindBadge(String(n.node_kind ?? "NORMAL"));
      const isSelected = selectedId === n.id;
      const kind = String(n.node_kind ?? "NORMAL").toUpperCase();
      const belongsHighlight =
        highlightStorylineId === "ALL" || (n.storyline_ids ?? []).includes(highlightStorylineId);
      const layer = layerById.get(n.id) ?? 0;
      const x = 160 + layer * xStep;

      const ids = n.storyline_ids ?? [];
      const onlyMain = Boolean(mainId) && ids.length > 0 && ids.every((id) => id === mainId);
      const onSpineY =
        kind === "CHECKPOINT" ||
        kind === "ENDING" ||
        (onlyMain && (kind === "NORMAL" || kind === "FORK" || kind === "MERGE"));

      let y = centerY;
      if (onSpineY) {
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

      return {
        id: n.id,
        label: `[${prefix}] ${String(n.title ?? n.id).slice(0, 32)}`,
        x,
        y,
        style: {
          fill: color.fill,
          stroke: isSelected ? "#f59e0b" : color.stroke,
          lineWidth: isSelected ? 2.8 : 1.6,
          opacity: belongsHighlight ? 1 : 0.28,
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
  }, [height, highlightStorylineId, mainId, nodes, selectedId, sidToBandIndex, slById]);

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
        default: ["drag-canvas", "zoom-canvas"],
      },
    } as any);
    g.on("node:click", (evt: { item?: { getModel?: () => { id?: string } } }) => {
      const id = String(evt?.item?.getModel?.()?.id ?? "");
      if (!id) return;
      onSelectRef.current(id);
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
    const g = graphRef.current;
    if (!g) return;
    g.changeData(graphData);
    g.render();
    g.fitView(20);
  }, [graphData]);

  return (
    <div
      className="overflow-hidden rounded-2xl border border-outline-variant/20 bg-gradient-to-b from-[#040a16] to-[#070f22] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]"
      style={{ minHeight: height + 48 }}
    >
      <div className="flex flex-col gap-2 border-b border-white/5 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-3">
        <label className="flex min-w-0 flex-1 flex-col gap-1.5 sm:max-w-md">
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
        <p className="font-body text-[11px] leading-relaxed text-slate-500 sm:pt-5">
          {locale === "en"
            ? "Fixed height · Pan horizontally. Main spine is straight; side threads S→A→B outward."
            : locale === "zh-Hans"
              ? "固定高度 · 左右平移。主線水平拉直，副线按 S→A→B 由近到远；横轴由依赖层决定。"
              : "固定高度 · 左右平移。主線水平拉直，副線依 S→A→B 由近到遠；橫軸由依賴層決定。"}
        </p>
      </div>
      <div
        ref={containerRef}
        className="w-full overflow-hidden"
        style={{ height, minHeight: height, maxHeight: height }}
      />
    </div>
  );
}
