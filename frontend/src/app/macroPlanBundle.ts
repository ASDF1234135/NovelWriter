import { mergeMacroBibles } from "../features/macro-plan/macroPlanHelpers";
import type { MacroCompileData, MacroPlanPutBody } from "../types";

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

const STORYLINE_TYPES = new Set<string>(["MAIN", "S_TIER", "A_TIER", "B_TIER"]);

function parseStorylinesFromCandidate(candidate: Record<string, unknown>): NonNullable<MacroPlanPutBody["storylines"]> {
  const raw = candidate.storylines;
  if (!Array.isArray(raw)) return [];
  const out: NonNullable<MacroPlanPutBody["storylines"]> = [];
  for (const row of raw) {
    if (!isObjectRecord(row)) continue;
    const id = String(row.id ?? "").trim();
    const typ = String(row.type ?? "").trim();
    if (!id || !STORYLINE_TYPES.has(typ)) continue;
    out.push({
      id,
      type: typ as NonNullable<MacroPlanPutBody["storylines"]>[number]["type"],
      title: String(row.title ?? ""),
      overall_goal: String(row.overall_goal ?? ""),
      involved_entities: Array.isArray(row.involved_entities)
        ? row.involved_entities.map((x) => String(x).trim()).filter(Boolean)
        : [],
    });
  }
  return out;
}

/** Prefix ids with `storyId_` when importing a macro plan into another story (matches volume/anchor legacy rules). */
export function idUnderStoryPrefix(storyId: string, rawId: string): string {
  const s = String(rawId ?? "").trim();
  if (!s) return s;
  return s.startsWith(`${storyId}_`) ? s : `${storyId}_${s}`;
}

export function buildMacroPutBody(data: MacroCompileData): MacroPlanPutBody {
  const derivedAnchorNodes =
    data.anchor_nodes && data.anchor_nodes.length > 0
      ? data.anchor_nodes
      : (data.anchors ?? []).map((a) => ({
          id: a.anchor_id,
          storyline_ids: [] as string[],
          volume_id: a.volume_id ?? "",
          node_kind: "NORMAL" as const,
          title: a.title ?? "",
          description: a.description ?? "",
          depends_on: [] as string[],
          status: "UNLOCKED" as const,
          estimated_chapter: a.chapter_target,
        }));
  const storylines = (data.storylines ?? []).map((s) => ({
    id: String(s.id),
    type: s.type,
    title: String(s.title ?? ""),
    overall_goal: String(s.overall_goal ?? ""),
    involved_entities: [...(s.involved_entities ?? [])],
  }));
  return {
    bible: isObjectRecord(data.bible) ? { ...data.bible } : {},
    volumes: [...(data.volumes ?? [])],
    anchors: (data.anchors ?? []).map((a) => ({
      anchor_id: a.anchor_id,
      volume_id: a.volume_id ?? "",
      title: a.title ?? "",
      description: a.description ?? "",
      target_state: isObjectRecord(a.target_state) ? { ...a.target_state } : {},
      chapter_target: a.chapter_target,
      priority: a.priority ?? 1,
    })),
    storylines,
    anchor_nodes: derivedAnchorNodes.map((n) => ({
      id: String(n.id),
      storyline_ids: [...(n.storyline_ids ?? [])],
      volume_id: String(n.volume_id ?? ""),
      node_kind: n.node_kind ?? "NORMAL",
      title: String(n.title ?? ""),
      description: String(n.description ?? ""),
      depends_on: [...(n.depends_on ?? [])],
      status: n.status ?? "UNLOCKED",
      estimated_chapter: n.estimated_chapter ?? null,
    })),
    cast: [...(data.cast ?? [])],
    protagonist_character_id: data.protagonist_character_id?.trim() || null,
  };
}

export function parseMacroImportJson(raw: string): MacroPlanPutBody {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("compile JSON 格式不正確");
  }
  const candidate = isObjectRecord(parsed) && parsed.kind === "macro_compile" ? parsed.macro_plan : parsed;
  if (!isObjectRecord(candidate)) throw new Error("compile JSON 結構錯誤");
  const volumes = Array.isArray(candidate.volumes) ? candidate.volumes : [];
  const anchors = Array.isArray(candidate.anchors) ? candidate.anchors : [];
  const anchorNodesRaw = Array.isArray(candidate.anchor_nodes) ? candidate.anchor_nodes : [];
  if (volumes.length === 0 || (anchors.length === 0 && anchorNodesRaw.length === 0)) {
    throw new Error("volumes 與 anchor_nodes/anchors 不可為空");
  }
  const volumeIds = new Set<string>();
  for (const row of volumes) {
    const item = row as { volume_id?: unknown };
    const volumeId = String(item.volume_id ?? "").trim();
    if (!volumeId) throw new Error("volumes 內含空白 volume_id");
    if (volumeIds.has(volumeId)) throw new Error(`volumes 出現重複 volume_id：${volumeId}`);
    volumeIds.add(volumeId);
  }
  const anchorIds = new Set<string>();
  for (const row of anchors) {
    const item = row as { anchor_id?: unknown; volume_id?: unknown };
    const anchorId = String(item.anchor_id ?? "").trim();
    if (!anchorId) throw new Error("anchors 內含空白 anchor_id");
    if (anchorIds.has(anchorId)) throw new Error(`anchors 出現重複 anchor_id：${anchorId}`);
    anchorIds.add(anchorId);
    const linkedVolumeId = String(item.volume_id ?? "").trim();
    if (!linkedVolumeId) throw new Error(`anchor ${anchorId} 缺少 volume_id`);
    if (!volumeIds.has(linkedVolumeId)) throw new Error(`anchor ${anchorId} 指向不存在的 volume_id：${linkedVolumeId}`);
  }
  const storylines = parseStorylinesFromCandidate(candidate);
  return {
    bible: isObjectRecord(candidate.bible) ? candidate.bible : {},
    volumes: volumes as MacroPlanPutBody["volumes"],
    anchors: anchors as MacroPlanPutBody["anchors"],
    storylines,
    anchor_nodes:
      anchorNodesRaw.length > 0
        ? (anchorNodesRaw as MacroPlanPutBody["anchor_nodes"])
        : anchors.map((a) => ({
            id: String((a as { anchor_id?: string }).anchor_id ?? ""),
            storyline_ids: [],
            volume_id: String((a as { volume_id?: string }).volume_id ?? ""),
            node_kind: "NORMAL" as const,
            title: String((a as { title?: string }).title ?? ""),
            description: String((a as { description?: string }).description ?? ""),
            depends_on: [],
            status: "UNLOCKED" as const,
            estimated_chapter: Number((a as { chapter_target?: number }).chapter_target ?? 1),
          })),
    cast: Array.isArray(candidate.cast) ? (candidate.cast as MacroPlanPutBody["cast"]) : [],
    protagonist_character_id:
      typeof candidate.protagonist_character_id === "string" || candidate.protagonist_character_id === null
        ? candidate.protagonist_character_id
        : null,
  };
}

export function mergeMacroPlan(current: MacroPlanPutBody, incoming: MacroPlanPutBody): MacroPlanPutBody {
  const volumes = [...current.volumes];
  const volumeIds = new Set(current.volumes.map((v) => v.volume_id));
  for (const v of incoming.volumes) {
    if (!volumeIds.has(v.volume_id)) {
      volumes.push(v);
      volumeIds.add(v.volume_id);
    }
  }
  const anchors = [...(current.anchors ?? [])];
  const anchorIds = new Set((current.anchors ?? []).map((a) => a.anchor_id));
  for (const a of incoming.anchors ?? []) {
    if (!anchorIds.has(a.anchor_id)) {
      anchors.push(a);
      anchorIds.add(a.anchor_id);
    }
  }
  const cast = [...current.cast];
  const castIds = new Set(current.cast.map((c) => c.node_id));
  for (const c of incoming.cast) {
    if (!castIds.has(c.node_id)) {
      cast.push(c);
      castIds.add(c.node_id);
    }
  }
  const anchorNodes = [...(current.anchor_nodes ?? [])];
  const anchorNodeIds = new Set(anchorNodes.map((n) => n.id));
  for (const n of incoming.anchor_nodes ?? []) {
    if (!anchorNodeIds.has(n.id)) {
      anchorNodes.push(n);
      anchorNodeIds.add(n.id);
    }
  }
  const storylines = [...(current.storylines ?? [])];
  const storylineIds = new Set(storylines.map((s) => s.id));
  for (const s of incoming.storylines ?? []) {
    if (!storylineIds.has(s.id)) {
      storylines.push(s);
      storylineIds.add(s.id);
    }
  }
  return {
    bible: mergeMacroBibles(
      (current.bible ?? {}) as Record<string, unknown>,
      (incoming.bible ?? {}) as Record<string, unknown>,
    ) as MacroPlanPutBody["bible"],
    volumes,
    anchors,
    storylines,
    anchor_nodes: anchorNodes,
    cast,
    protagonist_character_id: current.protagonist_character_id ?? incoming.protagonist_character_id ?? null,
  };
}

export function namespaceMacroPlanIdsForStory(body: MacroPlanPutBody, storyId: string): MacroPlanPutBody {
  const mappedVolumes = body.volumes.map((v) => {
    const original = String(v.volume_id ?? "").trim();
    const volume_id = original.startsWith(`${storyId}_`) ? original : `${storyId}_${original}`;
    return { ...v, volume_id };
  });
  const volumeMap = new Map<string, string>();
  for (const v of mappedVolumes) {
    const original = String(v.volume_id ?? "").trim();
    if (original.startsWith(`${storyId}_`)) {
      const raw = original.slice(storyId.length + 1);
      volumeMap.set(raw, original);
      volumeMap.set(original, original);
    }
  }
  const mapVolumeId = (rawVolumeId: string) => {
    const raw = String(rawVolumeId ?? "").trim();
    if (!raw) return raw;
    return volumeMap.get(raw) ?? (raw.startsWith(`${storyId}_`) ? raw : `${storyId}_${raw}`);
  };

  const mappedAnchors = (body.anchors ?? []).map((a) => {
    const rawAnchorId = String(a.anchor_id ?? "").trim();
    const anchor_id = idUnderStoryPrefix(storyId, rawAnchorId);
    const rawVolumeId = String(a.volume_id ?? "").trim();
    const volume_id = mapVolumeId(rawVolumeId);
    return { ...a, anchor_id, volume_id };
  });

  const castIdMap = new Map<string, string>();
  const mappedCast = body.cast.map((c) => {
    const rawNodeId = String(c.node_id ?? "").trim();
    const node_id = idUnderStoryPrefix(storyId, rawNodeId);
    if (rawNodeId) castIdMap.set(rawNodeId, node_id);
    castIdMap.set(node_id, node_id);
    return { ...c, node_id };
  });

  const mappedStorylines = (body.storylines ?? []).map((s) => ({
    ...s,
    id: idUnderStoryPrefix(storyId, s.id),
    involved_entities: (s.involved_entities ?? []).map((e) => {
      const raw = String(e).trim();
      if (!raw) return raw;
      return castIdMap.get(raw) ?? idUnderStoryPrefix(storyId, raw);
    }),
  }));

  const mappedAnchorNodes = (body.anchor_nodes ?? []).map((n) => ({
    ...n,
    id: idUnderStoryPrefix(storyId, n.id),
    volume_id: mapVolumeId(String(n.volume_id ?? "")),
    storyline_ids: (n.storyline_ids ?? []).map((sid) => idUnderStoryPrefix(storyId, sid)),
    depends_on: (n.depends_on ?? []).map((dep) => idUnderStoryPrefix(storyId, dep)),
  }));

  const rawProtagonistId = String(body.protagonist_character_id ?? "").trim();
  const protagonist_character_id =
    castIdMap.get(rawProtagonistId) ??
    (rawProtagonistId.startsWith(`${storyId}_`) ? rawProtagonistId : null);

  return {
    ...body,
    volumes: mappedVolumes,
    anchors: mappedAnchors,
    storylines: mappedStorylines,
    anchor_nodes: mappedAnchorNodes,
    cast: mappedCast,
    protagonist_character_id,
  };
}
