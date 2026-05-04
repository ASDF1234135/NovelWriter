/** Pure DAG validation for manual macro anchor edits (mirrors backend rules). */

export type AnchorNodeLike = {
  id: string;
  title?: string;
  description?: string;
  storyline_ids?: string[];
  node_kind?: string;
  depends_on?: string[];
};

export type StorylineLike = { id: string; type?: string };

export type DagValidateLocale = "en" | "zh-Hans" | "zh-Hant";

export type AnchorDagValidationIssue = {
  code: string;
  /** English fallback for logs/tests; UI should use `formatAnchorDagValidationIssue`. */
  message: string;
  nodeId?: string;
  storylineId?: string;
  regionCount?: number;
};

/** User-facing copy for notices and dialogs (en / zh-Hans / zh-Hant). */
export function formatAnchorDagValidationIssue(issue: AnchorDagValidationIssue, loc: DagValidateLocale): string {
  switch (issue.code) {
    case "USER_EDIT_NO_CHECKPOINT": {
      const id = issue.nodeId ?? "?";
      if (loc === "en") {
        return `Your user-edit milestone “${id}” is not linked forward to any checkpoint. Without that link, the story may not fully complete.`;
      }
      if (loc === "zh-Hans") {
        return `您的「用户编辑」里程碑「${id}」尚未沿剧情方向接到任何 checkpoint；未接入 checkpoint 时，剧情可能无法完全完成。`;
      }
      return `您的「使用者編輯」里程碑「${id}」尚未沿劇情方向接到任何 checkpoint；未接入 checkpoint 時，劇情可能無法完全完成。`;
    }
    case "DAG_CYCLE": {
      if (loc === "en") {
        return "Your dependency arrows form a loop. Remove one link so milestones stay in order.";
      }
      if (loc === "zh-Hans") {
        return "您的依赖箭头形成了环路。请移除其中一条连线，让里程碑保持先后顺序。";
      }
      return "您的依賴箭頭形成了迴圈。請移除其中一條連線，讓里程碑維持先後順序。";
    }
    case "UNKNOWN_STORYLINE": {
      const nid = issue.nodeId ?? "?";
      const sid = issue.storylineId ?? "?";
      if (loc === "en") {
        return `Milestone “${nid}” points to a storyline ID that is not in this plan (“${sid}”). Choose a storyline that exists here.`;
      }
      if (loc === "zh-Hans") {
        return `里程碑「${nid}」引用了本计划中不存在的剧情线 ID「${sid}」。请改为已存在的剧情线。`;
      }
      return `里程碑「${nid}」指向了本計畫中不存在的劇情線 ID「${sid}」。請改選此處已有的劇情線。`;
    }
    case "DAG_ISLANDS": {
      const w = issue.regionCount ?? 0;
      if (loc === "en") {
        return `Your graph splits into ${w} separate groups. Add dependencies so every milestone is reachable from the rest.`;
      }
      if (loc === "zh-Hans") {
        return `您的图谱分裂成 ${w} 个互不相连的区域。请用依赖边把它们连成一体，确保彼此可达。`;
      }
      return `您的圖譜分裂成 ${w} 個互不相連的區域。請用依賴邊把它們連成一體，確保彼此可達。`;
    }
    default:
      return issue.message;
  }
}

const MAIN_HINT = /_main$/i;

export function isMainStorylineId(storylineId: string, mainId: string | null): boolean {
  if (mainId && storylineId === mainId) return true;
  return MAIN_HINT.test(storylineId) || storylineId.toLowerCase().includes("_main");
}

export function isUserEditStoryline(sl: StorylineLike | undefined): boolean {
  return String(sl?.type ?? "").toUpperCase() === "USER_EDIT";
}

export function findMainStorylineId(storylines: StorylineLike[]): string | null {
  const m = storylines.find((s) => String(s.type ?? "").toUpperCase() === "MAIN");
  if (m) return m.id;
  const bySuffix = storylines.find((s) => MAIN_HINT.test(s.id));
  return bySuffix?.id ?? null;
}

/** Directed edges: dep -> node */
export function anchorEdges(nodes: AnchorNodeLike[]): Array<{ from: string; to: string }> {
  const out: Array<{ from: string; to: string }> = [];
  const known = new Set(nodes.map((n) => n.id));
  for (const n of nodes) {
    for (const d of n.depends_on ?? []) {
      if (known.has(d)) out.push({ from: d, to: n.id });
    }
  }
  return out;
}

/** Edge dep -> node (same as anchorEdges). Returns true if cycle exists. */
export function detectCycle(nodes: AnchorNodeLike[]): boolean {
  const ids = new Set(nodes.map((n) => n.id));
  const adj = new Map<string, string[]>();
  for (const id of ids) adj.set(id, []);
  for (const n of nodes) {
    for (const d of n.depends_on ?? []) {
      if (ids.has(d) && ids.has(n.id)) adj.get(d)!.push(n.id);
    }
  }
  const WHITE = 0;
  const GREY = 1;
  const BLACK = 2;
  const color = new Map<string, number>();
  for (const id of ids) color.set(id, WHITE);

  const dfs = (u: string): boolean => {
    color.set(u, GREY);
    for (const v of adj.get(u) ?? []) {
      const cv = color.get(v) ?? WHITE;
      if (cv === GREY) return true;
      if (cv === WHITE && dfs(v)) return true;
    }
    color.set(u, BLACK);
    return false;
  };

  for (const id of ids) {
    if (color.get(id) === WHITE && dfs(id)) return true;
  }
  return false;
}

/** Undirected connected components; returns count (isolated nodes each count as one). */
export function countWeaklyConnectedComponents(nodes: AnchorNodeLike[]): number {
  if (nodes.length === 0) return 0;
  const ids = nodes.map((n) => n.id);
  const idSet = new Set(ids);
  const adj = new Map<string, Set<string>>();
  for (const id of ids) adj.set(id, new Set());
  for (const n of nodes) {
    for (const d of n.depends_on ?? []) {
      if (!idSet.has(d)) continue;
      adj.get(d)!.add(n.id);
      adj.get(n.id)!.add(d);
    }
  }
  let components = 0;
  const seen = new Set<string>();
  for (const id of ids) {
    if (seen.has(id)) continue;
    components++;
    const stack = [id];
    while (stack.length) {
      const u = stack.pop()!;
      if (seen.has(u)) continue;
      seen.add(u);
      for (const v of adj.get(u) ?? []) {
        if (!seen.has(v)) stack.push(v);
      }
    }
  }
  return components;
}

export function storylineRefsValid(nodes: AnchorNodeLike[], storylines: StorylineLike[]): AnchorDagValidationIssue | null {
  const allowed = new Set(storylines.map((s) => s.id));
  for (const n of nodes) {
    for (const sid of n.storyline_ids ?? []) {
      if (!allowed.has(sid)) {
        return {
          code: "UNKNOWN_STORYLINE",
          message: `Node ${n.id}: unknown storyline ${sid}`,
          nodeId: n.id,
          storylineId: sid,
        };
      }
    }
  }
  return null;
}

/** USER_EDIT storyline nodes must reach some CHECKPOINT via forward edges (dependents). Returns per-node warning lines. */
export function userEditCheckpointWarnings(
  nodes: AnchorNodeLike[],
  storylines: StorylineLike[],
): AnchorDagValidationIssue[] {
  const ueIds = new Set(
    storylines.filter((s) => String(s.type ?? "").toUpperCase() === "USER_EDIT").map((s) => s.id),
  );
  if (ueIds.size === 0) return [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const children = new Map<string, string[]>();
  for (const n of nodes) {
    for (const d of n.depends_on ?? []) {
      if (!children.has(d)) children.set(d, []);
      children.get(d)!.push(n.id);
    }
  }
  const kindOf = (id: string) => String(byId.get(id)?.node_kind ?? "NORMAL").toUpperCase();

  const reachesCheckpoint = (start: string): boolean => {
    const q = [start];
    const seen = new Set<string>();
    while (q.length) {
      const id = q.shift()!;
      if (seen.has(id)) continue;
      seen.add(id);
      if (kindOf(id) === "CHECKPOINT") return true;
      for (const c of children.get(id) ?? []) q.push(c);
    }
    return false;
  };

  const out: AnchorDagValidationIssue[] = [];
  for (const n of nodes) {
    const hasUe = (n.storyline_ids ?? []).some((sid) => ueIds.has(sid));
    if (!hasUe) continue;
    if (!reachesCheckpoint(n.id)) {
      out.push({
        code: "USER_EDIT_NO_CHECKPOINT",
        message: `USER_EDIT node ${n.id}: no forward path to CHECKPOINT`,
        nodeId: n.id,
      });
    }
  }
  return out;
}

export type AnchorDagValidationResult = {
  blocking: AnchorDagValidationIssue | null;
  warnings: AnchorDagValidationIssue[];
};

/** Full check: blocking = cycle, unknown storyline, or multiple islands; warnings = USER_EDIT checkpoint (non-blocking). */
export function validateAnchorDagComprehensive(
  nodes: AnchorNodeLike[],
  storylines: StorylineLike[],
): AnchorDagValidationResult {
  const warnings = userEditCheckpointWarnings(nodes, storylines);

  if (detectCycle(nodes)) {
    return { blocking: { code: "DAG_CYCLE", message: "Cycle in depends_on" }, warnings };
  }
  const sr = storylineRefsValid(nodes, storylines);
  if (sr) return { blocking: sr, warnings };

  const n = nodes.length;
  if (n > 1) {
    const wcc = countWeaklyConnectedComponents(nodes);
    if (wcc > 1) {
      return {
        blocking: {
          code: "DAG_ISLANDS",
          message: `${wcc} weakly connected regions`,
          regionCount: wcc,
        },
        warnings,
      };
    }
  }

  return { blocking: null, warnings };
}

/** Nodes whose `title` or `description` is empty/whitespace only. */
export function findAnchorNodesWithEmptyTitleOrDescription(nodes: AnchorNodeLike[]): string[] {
  const out: string[] = [];
  for (const n of nodes) {
    const t = String(n.title ?? "").trim();
    const d = String((n as { description?: string }).description ?? "").trim();
    if (!t || !d) out.push(n.id);
  }
  return out;
}

/** First directed cycle closing edge `parentId -> childId` plus both endpoints (minimal highlight). */
export function findDirectedCycleHighlight(
  nodes: AnchorNodeLike[],
): { nodeIds: string[]; edges: Array<{ parentId: string; childId: string }> } {
  const ids = nodes.map((n) => n.id);
  const idSet = new Set(ids);
  const children = new Map<string, string[]>();
  for (const id of idSet) children.set(id, []);
  for (const n of nodes) {
    for (const dep of n.depends_on ?? []) {
      if (idSet.has(dep)) children.get(dep)!.push(n.id);
    }
  }
  const WHITE = 0;
  const GREY = 1;
  const BLACK = 2;
  const color = new Map(ids.map((id) => [id, WHITE]));

  const dfs = (u: string): { parentId: string; childId: string } | null => {
    color.set(u, GREY);
    for (const v of children.get(u) ?? []) {
      const cv = color.get(v) ?? WHITE;
      if (cv === GREY) {
        return { parentId: u, childId: v };
      }
      if (cv === WHITE) {
        const found = dfs(v);
        if (found) return found;
      }
    }
    color.set(u, BLACK);
    return null;
  };

  for (const id of ids) {
    if (color.get(id) !== WHITE) continue;
    const closing = dfs(id);
    if (closing) {
      return {
        nodeIds: [closing.parentId, closing.childId],
        edges: [closing],
      };
    }
  }
  return { nodeIds: [], edges: [] };
}

function weaklyConnectedComponents(nodes: AnchorNodeLike[]): string[][] {
  if (nodes.length === 0) return [];
  const idSet = new Set(nodes.map((n) => n.id));
  const adj = new Map<string, Set<string>>();
  for (const id of idSet) adj.set(id, new Set());
  for (const n of nodes) {
    for (const d of n.depends_on ?? []) {
      if (!idSet.has(d)) continue;
      adj.get(d)!.add(n.id);
      adj.get(n.id)!.add(d);
    }
  }
  const comps: string[][] = [];
  const seen = new Set<string>();
  for (const id of idSet) {
    if (seen.has(id)) continue;
    const comp: string[] = [];
    const stack = [id];
    while (stack.length) {
      const u = stack.pop()!;
      if (seen.has(u)) continue;
      seen.add(u);
      comp.push(u);
      for (const v of adj.get(u) ?? []) {
        if (!seen.has(v)) stack.push(v);
      }
    }
    comps.push(comp);
  }
  return comps;
}

/** Highlight nodes in every weak component except the largest (islands / disconnected regions). */
export function findIslandHighlightNodeIds(nodes: AnchorNodeLike[]): string[] {
  if (nodes.length <= 1) return [];
  const comps = weaklyConnectedComponents(nodes);
  if (comps.length <= 1) return [];
  const sorted = [...comps].sort((a, b) => b.length - a.length);
  const main = new Set(sorted[0]);
  const out: string[] = [];
  for (let i = 1; i < sorted.length; i++) out.push(...sorted[i]);
  return out;
}

export function findUnknownStorylineNodeIds(nodes: AnchorNodeLike[], storylines: StorylineLike[]): string[] {
  const allowed = new Set(storylines.map((s) => s.id));
  const out = new Set<string>();
  for (const n of nodes) {
    for (const sid of n.storyline_ids ?? []) {
      if (!allowed.has(sid)) out.add(n.id);
    }
  }
  return [...out];
}

/** Map blocking validation to graph highlights (red stroke on nodes / dependency edges). */
export function computeDagBlockingHighlights(
  nodes: AnchorNodeLike[],
  storylines: StorylineLike[],
  blocking: AnchorDagValidationIssue,
): { nodeIds: string[]; edges: Array<{ parentId: string; childId: string }> } {
  switch (blocking.code) {
    case "DAG_CYCLE":
      return findDirectedCycleHighlight(nodes);
    case "DAG_ISLANDS":
      return { nodeIds: findIslandHighlightNodeIds(nodes), edges: [] };
    case "UNKNOWN_STORYLINE":
      return { nodeIds: findUnknownStorylineNodeIds(nodes, storylines), edges: [] };
    default:
      return { nodeIds: [], edges: [] };
  }
}

/** @deprecated Prefer validateAnchorDagComprehensive — returns first blocking issue only (no warnings). */
export function validateAnchorDagForPut(
  nodes: AnchorNodeLike[],
  storylines: StorylineLike[],
): AnchorDagValidationIssue | null {
  return validateAnchorDagComprehensive(nodes, storylines).blocking;
}
