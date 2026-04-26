/** Pure helpers for macro plan bible shape (extra + active_b_stories) and validation copy. */

export const BIBLE_LINE_KEYS = [
  "genre",
  "tone",
  "theme",
  "narrative_pov",
  "writing_style",
  "world_rules",
  "factions",
  "writing_note",
] as const;
export const BIBLE_ALIAS_KEYS = new Set(["story_genre", "story_tone"]);
export const BIBLE_OPTIONAL_TOP_KEYS = new Set(["theme", "themes", "narrative_pov", "writing_style"]);

export const BIBLE_RESERVED_TOP_KEYS = new Set<string>([
  ...BIBLE_LINE_KEYS,
  "themes",
  "story_genre",
  "story_tone",
  "extra",
  "active_b_stories",
  "storylines",
  "anchor_nodes",
]);

export type ExtraRow = { key: string; value: string; isList: boolean };

export type BStoryRow = {
  id: string;
  desc: string;
  type: string;
  resolution_condition: string;
};

export function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function asLines(v: unknown): string {
  if (Array.isArray(v)) return v.map((x) => String(x).trim()).filter(Boolean).join("\n");
  if (v == null) return "";
  return String(v).trim();
}

export function parseNonEmptyLines(v: string): string[] {
  return v.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
}

/** Serialize one value for extra / migration (never String(object)). */
export function serializeExtraValue(v: unknown): { text: string; isList: boolean } {
  if (Array.isArray(v)) {
    const lines = v.map((x) => {
      if (x !== null && typeof x === "object") return JSON.stringify(x);
      return String(x);
    });
    return { text: lines.join("\n"), isList: true };
  }
  if (v !== null && typeof v === "object") return { text: JSON.stringify(v), isList: false };
  if (v === true) return { text: "是", isList: false };
  if (v === false) return { text: "否", isList: false };
  return { text: String(v ?? ""), isList: false };
}

export function parseBStories(raw: unknown): BStoryRow[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    if (!isObjectRecord(item)) return { id: "", desc: "", type: "UNKNOWN", resolution_condition: "" };
    return {
      id: String(item.id ?? "").trim(),
      desc: String(item.desc ?? "").trim(),
      type: String(item.type ?? "UNKNOWN").trim() || "UNKNOWN",
      resolution_condition: String(item.resolution_condition ?? "").trim(),
    };
  });
}

export type LegacySplit = {
  extraRows: ExtraRow[];
  activeBStories: BStoryRow[];
};

/** Load bible into extra rows + active b-stories; migrate flat keys into extra. */
export function splitBibleForForm(bible: Record<string, unknown>): LegacySplit {
  const extraRows: ExtraRow[] = [];
  const extraObj = bible.extra;
  if (isObjectRecord(extraObj)) {
    for (const [k, v] of Object.entries(extraObj)) {
      if (BIBLE_OPTIONAL_TOP_KEYS.has(k)) continue;
      const ser = serializeExtraValue(v);
      extraRows.push({ key: k, value: ser.text, isList: ser.isList });
    }
  }
  for (const [k, v] of Object.entries(bible)) {
    if (BIBLE_RESERVED_TOP_KEYS.has(k)) continue;
    const ser = serializeExtraValue(v);
    extraRows.push({ key: k, value: ser.text, isList: ser.isList });
  }
  return { extraRows, activeBStories: parseBStories(bible.active_b_stories) };
}

export function buildExtraObject(rows: ExtraRow[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const seen = new Set<string>();
  for (const row of rows) {
    const key = row.key.trim();
    const value = row.value.trim();
    if (!key || !value) continue;
    if (BIBLE_OPTIONAL_TOP_KEYS.has(key)) continue;
    if (seen.has(key)) continue;
    seen.add(key);
    out[key] = row.isList ? parseNonEmptyLines(value) : value;
  }
  return out;
}

export function bStoriesToPayload(rows: BStoryRow[]): Array<Record<string, unknown>> {
  return rows
    .filter((r) => r.id.trim())
    .map((r) => ({
      id: r.id.trim(),
      desc: r.desc,
      type: r.type || "UNKNOWN",
      resolution_condition: r.resolution_condition,
    }));
}

export function newLocalId(prefix: string): string {
  const id =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 10)
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  return `${prefix}_${id}`;
}

export function mergeMacroBibles(current: Record<string, unknown>, incoming: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...incoming, ...current };
  const curExtra = isObjectRecord(current.extra) ? current.extra : {};
  const incExtra = isObjectRecord(incoming.extra) ? incoming.extra : {};
  if (Object.keys(curExtra).length || Object.keys(incExtra).length) {
    out.extra = { ...incExtra, ...curExtra };
  }
  const curStories = Array.isArray(current.active_b_stories) ? current.active_b_stories : [];
  const incStories = Array.isArray(incoming.active_b_stories) ? incoming.active_b_stories : [];
  const byId = new Map<string, unknown>();
  for (const s of incStories) {
    if (isObjectRecord(s) && s.id != null) byId.set(String(s.id), s);
  }
  for (const s of curStories) {
    if (isObjectRecord(s) && s.id != null) byId.set(String(s.id), s);
  }
  if (byId.size) out.active_b_stories = [...byId.values()];
  return out;
}

export function extractAnchorGoal(targetState: Record<string, unknown> | undefined): string {
  if (!targetState || typeof targetState !== "object") return "";
  const chapterGoal = targetState.chapter_goal;
  if (typeof chapterGoal === "string") return chapterGoal.trim();
  const narrativeGoal = targetState.narrative_goal;
  if (typeof narrativeGoal === "string") return narrativeGoal.trim();
  const firstString = Object.values(targetState).find((x) => typeof x === "string");
  if (typeof firstString === "string") return firstString.trim();
  const json = JSON.stringify(targetState);
  return json === "{}" ? "" : json;
}

export type AnchorForNormalize = {
  anchor_id: string;
  chapter_target: number;
  volume_id?: string;
  priority?: number;
};

export function normalizeAnchors<T extends AnchorForNormalize>(anchors: T[]): T[] {
  const sorted = [...anchors].sort((a, b) => {
    const chapterDiff = Number(a.chapter_target || 0) - Number(b.chapter_target || 0);
    if (chapterDiff !== 0) return chapterDiff;
    return String(a.anchor_id).localeCompare(String(b.anchor_id));
  });
  return sorted.map((row, idx) => ({ ...row, priority: idx + 1 }));
}

export function findOverlappingVolumes(
  volumes: Array<{ volume_id: string; title: string; chapter_start: number; chapter_end: number }>,
): Array<[string, string]> {
  const overlaps: Array<[string, string]> = [];
  for (let i = 0; i < volumes.length; i += 1) {
    for (let j = i + 1; j < volumes.length; j += 1) {
      const a = volumes[i];
      const b = volumes[j];
      if (!a || !b) continue;
      const intersect = a.chapter_start <= b.chapter_end && b.chapter_start <= a.chapter_end;
      if (intersect) overlaps.push([a.volume_id, b.volume_id]);
    }
  }
  return overlaps;
}
