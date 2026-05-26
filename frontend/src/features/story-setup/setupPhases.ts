/**
 * Helpers for splitting the single `macro_author_notes` blob into structured sub-fields
 * surfaced by the 3-stage Setup wizard, and recomposing them back so the compile LLM
 * receives a clean prose-formatted brief.
 *
 * The encode-into-notes channel keeps the backend untouched: macro compile already
 * reads `macro_author_notes`, so well-formatted prose under labelled section markers
 * doubles as both human-readable notes and an LLM-friendly prompt extension.
 */
import type { StoryOutputLanguage } from "../../types";

export type SubplotTier = "S" | "A" | "B";

export const SUBPLOT_TIERS: readonly SubplotTier[] = ["S", "A", "B"] as const;

export type VolumeGoal = {
  /** 1-indexed volume number this goal belongs to. */
  volume: number;
  /** Plot goal description for this volume (1~3 sentences ideal). */
  goal: string;
};

export type SubplotEntry = {
  /** Stable id used for React keys and edit/delete operations. */
  id: string;
  tier: SubplotTier;
  title: string;
  goal: string;
  /**
   * 1-indexed volume this subplot is anchored to. Only meaningful for A_TIER
   * (per-volume support arc) and B_TIER (per-volume micro beat). Always `null`
   * for S_TIER because S spans the whole book. `null` for A/B means "let the
   * compiler pick a volume" (legacy behaviour).
   */
  volume: number | null;
};

export type PhaseTwoFields = {
  world: string;
  characters: string;
  style: string;
};

export type DecomposedNotes = PhaseTwoFields & {
  volumeGoals: VolumeGoal[];
  subplots: SubplotEntry[];
  /**
   * True when the parsed notes already contained our section markers (so the user
   * has been through the wizard at least once). Used by the form to decide whether
   * to auto-seed empty subplot rows.
   */
  hasStructuredMarkers: boolean;
};

const SECTION_WORLD = "[[WORLD]]";
const SECTION_CHARACTERS = "[[CHARACTERS]]";
const SECTION_STYLE = "[[STYLE]]";
const SECTION_VOLUME_GOALS = "[[VOLUME_GOALS]]";
const SECTION_SUBPLOTS = "[[SUBPLOTS]]";

const ALL_SECTIONS = [
  SECTION_WORLD,
  SECTION_CHARACTERS,
  SECTION_STYLE,
  SECTION_VOLUME_GOALS,
  SECTION_SUBPLOTS,
] as const;

const VOLUME_GOAL_LINE_RE = /^(?:V|第\s*|Volume\s+)(\d+)(?:\s*卷)?\s*[｜|]\s*(.+)$/i;
/**
 * Subplot line format. Tier letter may optionally carry a volume tag (`A:3` /
 * `B:1`); S_TIER spans the whole book so we never emit a volume on it. Both
 * `｜` (full-width) and `|` (ASCII) separators are accepted.
 */
const SUBPLOT_LINE_RE = /^\[([SAB])(?::(\d+))?\]\s*[｜|]\s*([^｜|]*)[｜|]\s*(.*)$/;

let entryIdSeq = 0;
function nextEntryId(): string {
  entryIdSeq += 1;
  return `sp_${Date.now().toString(36)}_${entryIdSeq}`;
}

/**
 * Coerce a tier-volume pair to the value we actually persist. S never carries
 * a volume; A/B accept either `null` (auto / not pinned) or a positive integer.
 */
function normalizeSubplotVolume(tier: SubplotTier, value: number | null | undefined): number | null {
  if (tier === "S") return null;
  if (value == null) return null;
  if (!Number.isFinite(value)) return null;
  const v = Math.floor(value);
  return v > 0 ? v : null;
}

export function createSubplotEntry(
  tier: SubplotTier,
  init?: Partial<Omit<SubplotEntry, "id" | "tier">>,
): SubplotEntry {
  return {
    id: nextEntryId(),
    tier,
    title: init?.title ?? "",
    goal: init?.goal ?? "",
    volume: normalizeSubplotVolume(tier, init?.volume ?? null),
  };
}

function isSubplotTier(value: string): value is SubplotTier {
  return value === "S" || value === "A" || value === "B";
}

function parseVolumeGoalLine(line: string): VolumeGoal | null {
  const match = line.trim().match(VOLUME_GOAL_LINE_RE);
  if (!match) return null;
  const volume = Number(match[1]);
  if (!Number.isFinite(volume) || volume <= 0) return null;
  const goal = match[2].trim();
  if (!goal) return null;
  return { volume: Math.floor(volume), goal };
}

function parseSubplotLine(
  line: string,
): { tier: SubplotTier; title: string; goal: string; volume: number | null } | null {
  const match = line.trim().match(SUBPLOT_LINE_RE);
  if (!match) return null;
  const tier = match[1].toUpperCase();
  if (!isSubplotTier(tier)) return null;
  const volumeRaw = match[2];
  const volume =
    volumeRaw != null ? normalizeSubplotVolume(tier, Number(volumeRaw)) : null;
  return { tier, title: match[3].trim(), goal: match[4].trim(), volume };
}

export function decomposeNotes(notes: string): DecomposedNotes {
  const raw = String(notes ?? "");
  const indices = ALL_SECTIONS.map((marker) => ({ marker, idx: raw.indexOf(marker) }))
    .filter((entry) => entry.idx !== -1)
    .sort((a, b) => a.idx - b.idx);

  if (indices.length === 0) {
    return {
      world: raw.trim(),
      characters: "",
      style: "",
      volumeGoals: [],
      subplots: [],
      hasStructuredMarkers: false,
    };
  }

  const slices: Record<string, string> = {};
  indices.forEach((entry, i) => {
    const start = entry.idx + entry.marker.length;
    const end = i + 1 < indices.length ? indices[i + 1].idx : raw.length;
    slices[entry.marker] = raw.slice(start, end).trim();
  });

  const vgRaw = slices[SECTION_VOLUME_GOALS] ?? "";
  const volumeGoals: VolumeGoal[] = [];
  for (const line of vgRaw.split(/\r?\n/)) {
    const parsed = parseVolumeGoalLine(line);
    if (parsed) volumeGoals.push(parsed);
  }

  const spRaw = slices[SECTION_SUBPLOTS] ?? "";
  const subplots: SubplotEntry[] = [];
  for (const line of spRaw.split(/\r?\n/)) {
    const parsed = parseSubplotLine(line);
    if (parsed) subplots.push({ id: nextEntryId(), ...parsed });
  }

  return {
    world: slices[SECTION_WORLD] ?? "",
    characters: slices[SECTION_CHARACTERS] ?? "",
    style: slices[SECTION_STYLE] ?? "",
    volumeGoals,
    subplots,
    hasStructuredMarkers: true,
  };
}

/**
 * Render the wizard state back into the compile-bound `macro_author_notes` string.
 * - Volume goals are pruned to the declared volume count and sorted ascending.
 * - Empty subplot rows are dropped.
 * - Section markers stay stable so the next hydrate parses correctly.
 */
export function composeNotes(parts: DecomposedNotes, volumeCount: number | null): string {
  const world = parts.world.trim();
  const characters = parts.characters.trim();
  const style = parts.style.trim();

  const cap = volumeCount && volumeCount > 0 ? volumeCount : Number.POSITIVE_INFINITY;
  const volumeGoals = parts.volumeGoals
    .filter((g) => g.goal.trim() !== "" && g.volume >= 1 && g.volume <= cap)
    .map((g) => ({ volume: Math.floor(g.volume), goal: g.goal.trim() }))
    .sort((a, b) => a.volume - b.volume);

  const subplots = parts.subplots.filter((s) => s.title.trim() !== "" || s.goal.trim() !== "");

  if (!world && !characters && !style && volumeGoals.length === 0 && subplots.length === 0) {
    return "";
  }

  const blocks: string[] = [];
  if (world) blocks.push(`${SECTION_WORLD}\n${world}`);
  if (characters) blocks.push(`${SECTION_CHARACTERS}\n${characters}`);
  if (style) blocks.push(`${SECTION_STYLE}\n${style}`);

  if (volumeGoals.length > 0) {
    const lines = volumeGoals.map((g) => `第 ${g.volume} 卷｜${g.goal}`).join("\n");
    blocks.push(`${SECTION_VOLUME_GOALS}\n${lines}`);
  }

  if (subplots.length > 0) {
    const lines = subplots
      .slice()
      .sort((a, b) => {
        const tierDelta =
          SUBPLOT_TIERS.indexOf(a.tier) - SUBPLOT_TIERS.indexOf(b.tier);
        if (tierDelta !== 0) return tierDelta;
        // Within a tier, group by volume so the compile prompt reads naturally.
        const av = a.volume ?? Number.POSITIVE_INFINITY;
        const bv = b.volume ?? Number.POSITIVE_INFINITY;
        return av - bv;
      })
      .map((s) => {
        const volume = normalizeSubplotVolume(s.tier, s.volume);
        const tag = volume != null ? `[${s.tier}:${volume}]` : `[${s.tier}]`;
        return `${tag}｜${s.title.trim()}｜${s.goal.trim()}`;
      })
      .join("\n");
    blocks.push(`${SECTION_SUBPLOTS}\n${lines}`);
  }

  return blocks.join("\n\n");
}

export function totalNotesLength(parts: DecomposedNotes, volumeCount: number | null): number {
  return composeNotes(parts, volumeCount).length;
}

/**
 * Backend compile constraints (anchor_service.py):
 *   S_TIER spans the whole book   → 1~2 lines total
 *   A_TIER is per-volume key side → 1~2 lines per volume
 *   B_TIER is per-volume micro    → 1~3 lines per volume
 * We seed with the lower bound so the form starts compact; users add more freely.
 */
export function suggestSubplotCounts(volumeCount: number | null): Record<SubplotTier, number> {
  const vc = Math.max(1, Math.min(volumeCount ?? 1, 32));
  return { S: 1, A: vc, B: vc };
}

export function subplotCountRange(
  tier: SubplotTier,
  volumeCount: number | null,
): { min: number; max: number } {
  const vc = Math.max(1, volumeCount ?? 1);
  switch (tier) {
    case "S":
      return { min: 1, max: 2 };
    case "A":
      return { min: vc, max: vc * 2 };
    case "B":
      return { min: vc, max: vc * 3 };
  }
}

export function seedDefaultSubplots(volumeCount: number | null): SubplotEntry[] {
  const counts = suggestSubplotCounts(volumeCount);
  const vc = Math.max(1, Math.min(volumeCount ?? 1, 32));
  const out: SubplotEntry[] = [];
  for (const tier of SUBPLOT_TIERS) {
    for (let i = 0; i < counts[tier]; i += 1) {
      // Round-robin assign volumes across the per-tier seeds so each volume
      // gets one starter row — matches the backend's per-volume fishbone
      // expectation for A/B tiers. S spans the whole book → no volume tag.
      const volume = tier === "S" ? null : (i % vc) + 1;
      out.push(createSubplotEntry(tier, { volume }));
    }
  }
  return out;
}

/**
 * Decide which volume a freshly added A/B subplot row should default to. Picks
 * the first volume that currently has the fewest entries of the same tier so
 * adding multiple rows in a row naturally spreads them across the story.
 */
export function suggestNextSubplotVolume(
  tier: SubplotTier,
  volumeCount: number | null,
  existing: readonly SubplotEntry[],
): number | null {
  if (tier === "S") return null;
  const vc = Math.max(1, Math.min(volumeCount ?? 1, 32));
  const tally = new Array<number>(vc).fill(0);
  for (const e of existing) {
    if (e.tier !== tier) continue;
    const v = e.volume;
    if (v != null && v >= 1 && v <= vc) tally[v - 1] += 1;
  }
  let bestIdx = 0;
  for (let i = 1; i < vc; i += 1) {
    if (tally[i] < tally[bestIdx]) bestIdx = i;
  }
  return bestIdx + 1;
}

export type OutputLanguageOption = {
  value: StoryOutputLanguage;
  labelKey: string;
};

export const OUTPUT_LANGUAGE_OPTIONS: OutputLanguageOption[] = [
  { value: "zh-Hant", labelKey: "lang.zhHant" },
  { value: "zh-Hans", labelKey: "lang.zhHans" },
  { value: "en", labelKey: "lang.en" },
];

/**
 * Length conventions differ wildly between CJK characters and English words.
 * Density baselines (10 chapters per volume on average):
 *   zh-Hant / zh-Hans: 2,500 字 / 章 · 25,000 字 / 卷 · default 100k → 4 卷
 *   en               : 1,800 words / chapter · 18,000 words / volume · default 72k → 4 volumes
 */
export const MIN_TOTAL_WORDS = 50_000;
export const MAX_TOTAL_WORDS = 1_000_000;
/** Step used by the number input to keep values nice & round during nudging. */
export const TOTAL_WORDS_STEP = 5_000;

export const DEFAULT_TOTAL_WORDS: Record<StoryOutputLanguage, number> = {
  "zh-Hant": 100000,
  "zh-Hans": 100000,
  en: 72000,
};

export const WORDS_PER_VOLUME: Record<StoryOutputLanguage, number> = {
  "zh-Hant": 25000,
  "zh-Hans": 25000,
  en: 18000,
};

export const WORDS_PER_CHAPTER: Record<StoryOutputLanguage, number> = {
  "zh-Hant": 2500,
  "zh-Hans": 2500,
  en: 1800,
};

export function getDefaultTotalWords(language: StoryOutputLanguage): number {
  return DEFAULT_TOTAL_WORDS[language] ?? DEFAULT_TOTAL_WORDS["zh-Hant"];
}

/**
 * Clamp a raw word-count value to the supported `[MIN, MAX]` range.
 * Returns the language default for nonsensical / non-finite inputs.
 */
export function clampTotalWords(value: number, language: StoryOutputLanguage): number {
  if (!Number.isFinite(value) || value <= 0) return getDefaultTotalWords(language);
  return Math.min(MAX_TOTAL_WORDS, Math.max(MIN_TOTAL_WORDS, Math.floor(value)));
}

/** Auto-derived volume count for a given total word target + output language. */
export function autoVolumeCount(totalWords: number, language: StoryOutputLanguage): number {
  const wpv = WORDS_PER_VOLUME[language] ?? WORDS_PER_VOLUME["zh-Hant"];
  const total = Number.isFinite(totalWords) ? Math.max(0, totalWords) : 0;
  if (total <= 0 || wpv <= 0) return 1;
  return Math.max(1, Math.round(total / wpv));
}

/** Auto-derived total chapter count (purely for UI hints). */
export function autoChapterCount(totalWords: number, language: StoryOutputLanguage): number {
  const wpc = WORDS_PER_CHAPTER[language] ?? WORDS_PER_CHAPTER["zh-Hant"];
  const total = Number.isFinite(totalWords) ? Math.max(0, totalWords) : 0;
  if (total <= 0 || wpc <= 0) return 1;
  return Math.max(1, Math.round(total / wpc));
}

/** Resolve the volume count that should drive compile + subplot suggestions. */
export function resolveVolumeCount(
  override: number | null,
  totalWords: number,
  language: StoryOutputLanguage,
): number {
  if (override && override > 0) return override;
  return autoVolumeCount(totalWords, language);
}
