/** 世界觀與結構產出（欄位編輯）— 用語面向一般文字工作者 */

import { useEffect, useMemo, useState } from "react";
import type { Anchor, CastMember, MacroCompileData, MacroPlanPutBody, VolumePlan } from "../../types";
import { putMacroPlan } from "../../api";
import {
  BIBLE_LINE_KEYS,
  type BStoryRow,
  type ExtraRow,
  asLines,
  bStoriesToPayload,
  buildExtraObject,
  extractAnchorGoal,
  findOverlappingVolumes,
  isObjectRecord,
  mergeMacroBibles,
  newLocalId,
  normalizeAnchors,
  parseNonEmptyLines,
  parseBStories,
  splitBibleForForm,
} from "./macroPlanHelpers";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  macroData: MacroCompileData | null;
  storyId: string | null;
  configurationLocked: boolean;
  onMacroDataUpdate: (next: MacroCompileData) => void;
  onBusy: (busy: boolean) => void;
  onError: (msg: string) => void;
};

type MacroTab = "bible" | "volumes" | "cast" | "anchors";
type EditSurface = "off" | "bible" | "volume" | "cast" | "anchor";

const FIELD_LABELS: Record<(typeof BIBLE_LINE_KEYS)[number], { "zh-Hant": string; "zh-Hans": string; en: string }> = {
  genre: { "zh-Hant": "故事類型", "zh-Hans": "故事类型", en: "Genre" },
  tone: { "zh-Hant": "氛圍基調", "zh-Hans": "氛围基调", en: "Tone" },
  theme: { "zh-Hant": "主題（選填）", "zh-Hans": "主题（选填）", en: "Theme (optional)" },
  narrative_pov: { "zh-Hant": "敘事視角（選填）", "zh-Hans": "叙事视角（选填）", en: "Narrative POV (optional)" },
  writing_style: { "zh-Hant": "文風（選填）", "zh-Hans": "文风（选填）", en: "Writing Style (optional)" },
  world_rules: { "zh-Hant": "世界規則", "zh-Hans": "世界规则", en: "World Rules" },
  factions: { "zh-Hant": "勢力與陣營", "zh-Hans": "势力与阵营", en: "Factions" },
  writing_note: { "zh-Hant": "寫作備註", "zh-Hans": "写作备注", en: "Writing Notes" },
};

type FormState = {
  genre: string;
  tone: string;
  theme: string;
  narrative_pov: string;
  writing_style: string;
  world_rules: string;
  factions: string;
  writing_note: string;
  extraRows: ExtraRow[];
  activeBStories: BStoryRow[];
};

type AnchorEdit = {
  title: string;
  description: string;
  chapter_target: string;
  chapter_goal: string;
};
function tr(locale: "zh-Hant" | "zh-Hans" | "en", zhHant: string, zhHans: string, en: string): string {
  if (locale === "en") return en;
  if (locale === "zh-Hans") return zhHans;
  return zhHant;
}

function isEditingSurface(surface: EditSurface): boolean {
  return surface !== "off";
}

function cloneMacro(m: MacroCompileData): MacroCompileData {
  return JSON.parse(JSON.stringify(m)) as MacroCompileData;
}

function toFormState(macro: MacroCompileData): FormState {
  const bibleRaw = macro.bible;
  const bible = isObjectRecord(bibleRaw) ? bibleRaw : {};
  const split = splitBibleForForm(bible as Record<string, unknown>);
  return {
    genre: String(bible.story_genre ?? bible.genre ?? "").trim(),
    tone: asLines(bible.tone),
    theme: asLines(bible.theme ?? bible.themes),
    narrative_pov: asLines(bible.narrative_pov),
    writing_style: asLines(bible.writing_style),
    world_rules: asLines(bible.world_rules),
    factions: asLines(bible.factions),
    writing_note: asLines(bible.writing_note),
    extraRows: split.extraRows,
    activeBStories: split.activeBStories,
  };
}

function emptyFormState(): FormState {
  return {
    genre: "",
    tone: "",
    theme: "",
    narrative_pov: "",
    writing_style: "",
    world_rules: "",
    factions: "",
    writing_note: "",
    extraRows: [],
    activeBStories: [],
  };
}

function buildBiblePayload(form: FormState): Record<string, unknown> {
  return {
    genre: form.genre.trim(),
    tone: form.tone.trim(),
    theme: form.theme.trim(),
    narrative_pov: form.narrative_pov.trim(),
    writing_style: form.writing_style.trim(),
    world_rules: parseNonEmptyLines(form.world_rules),
    factions: parseNonEmptyLines(form.factions),
    writing_note: parseNonEmptyLines(form.writing_note),
    extra: buildExtraObject(form.extraRows),
    active_b_stories: bStoriesToPayload(form.activeBStories),
  };
}

function anchorEditsFromMacro(anchors: Anchor[] | undefined): Record<string, AnchorEdit> {
  const out: Record<string, AnchorEdit> = {};
  for (const a of anchors ?? []) {
    const ts = isObjectRecord(a.target_state) ? a.target_state : {};
    out[a.anchor_id] = {
      title: String(a.title ?? ""),
      description: String(a.description ?? ""),
      chapter_target: String(a.chapter_target ?? ""),
      chapter_goal: extractAnchorGoal(ts as Record<string, unknown>),
    };
  }
  return out;
}

function sortAnchorsForUi(list: Anchor[]): Anchor[] {
  return normalizeAnchors(list.map((a) => ({ ...a })));
}

function findVolumeIdByChapter(
  volumes: VolumePlan[] | undefined,
  chapterTargetRaw: number | string,
): string {
  const chapterTarget = Number(chapterTargetRaw);
  if (!Number.isFinite(chapterTarget)) return "";
  const hit = (volumes ?? []).find(
    (v) => Number(chapterTarget) >= Number(v.chapter_start) && Number(chapterTarget) <= Number(v.chapter_end),
  );
  return hit?.volume_id ?? "";
}

function formatBibleReadRows(locale: "zh-Hant" | "zh-Hans" | "en", form: FormState): Array<{ label: string; value: string }> {
  return [
    { label: FIELD_LABELS.genre[locale], value: form.genre.trim() || "—" },
    { label: FIELD_LABELS.tone[locale], value: form.tone.trim() || "—" },
    { label: tr(locale, "主題", "主题", "Theme"), value: form.theme.trim() || "—" },
    { label: tr(locale, "敘事視角", "叙事视角", "Narrative POV"), value: form.narrative_pov.trim() || "—" },
    { label: tr(locale, "文風", "文风", "Writing Style"), value: form.writing_style.trim() || "—" },
    { label: FIELD_LABELS.world_rules[locale], value: form.world_rules.trim() || "—" },
    { label: FIELD_LABELS.factions[locale], value: form.factions.trim() || "—" },
    { label: FIELD_LABELS.writing_note[locale], value: form.writing_note.trim() || "—" },
  ];
}

function ReadonlyId({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="mb-1 font-label text-[10px] font-semibold uppercase tracking-wide text-on-surface-variant">{label}</p>
      <div className="break-all rounded-lg border border-outline-variant/20 bg-surface-container-highest px-2 py-1.5 font-mono text-xs text-on-surface">
        {value || "—"}
      </div>
    </div>
  );
}

export function MacroPlanPanel({
  macroData,
  storyId,
  configurationLocked,
  onMacroDataUpdate,
  onBusy,
  onError,
}: Props) {
  const { locale } = useI18n();
  const canEdit = Boolean(storyId && !configurationLocked);

  const [tab, setTab] = useState<MacroTab>("bible");
  const [editSurface, setEditSurface] = useState<EditSurface>("off");
  const [draftMacro, setDraftMacro] = useState<MacroCompileData | null>(null);
  const [form, setForm] = useState<FormState>(emptyFormState());
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedBStoryId, setSelectedBStoryId] = useState<string | null>(null);
  const [anchorEdits, setAnchorEdits] = useState<Record<string, AnchorEdit>>({});
  const [inlineError, setInlineError] = useState("");

  const displayMacro = draftMacro ?? macroData;
  const isDirtySession = isEditingSurface(editSurface);

  useEffect(() => {
    setTab("bible");
    setEditSurface("off");
    setDraftMacro(null);
    setForm(macroData ? toFormState(macroData) : emptyFormState());
    setSelectedEntityId(null);
    setSelectedBStoryId(null);
    setAnchorEdits(macroData ? anchorEditsFromMacro(macroData.anchors) : {});
    setInlineError("");
  }, [macroData]);

  function cancelEdit() {
    if (!macroData) {
      setEditSurface("off");
      setDraftMacro(null);
      setForm(emptyFormState());
      setSelectedEntityId(null);
      setSelectedBStoryId(null);
      setAnchorEdits({});
      setInlineError("");
      return;
    }
    setEditSurface("off");
    setDraftMacro(null);
    setForm(toFormState(macroData));
    setSelectedEntityId(null);
    setSelectedBStoryId(null);
    setAnchorEdits(anchorEditsFromMacro(macroData.anchors));
    setInlineError("");
  }

  function switchTab(next: MacroTab) {
    if (next === tab) return;
    if (isDirtySession && editSurface !== "off") {
      const ok = window.confirm(
        tr(
          locale,
          "尚未儲存的變更會被捨棄。確定要切換分頁嗎？",
          "尚未保存的变更会被舍弃。确定切换分页吗？",
          "Unsaved changes will be discarded. Switch tab anyway?",
        ),
      );
      if (!ok) return;
      cancelEdit();
    }
    setTab(next);
  }

  function ensureDraft(): MacroCompileData | null {
    if (!macroData) return null;
    if (draftMacro) return draftMacro;
    const d = cloneMacro(macroData);
    setDraftMacro(d);
    setForm(toFormState(d));
    setAnchorEdits(anchorEditsFromMacro(d.anchors));
    return d;
  }

  function startEditBible() {
    if (!canEdit || !macroData) return;
    ensureDraft();
    setEditSurface("bible");
    setSelectedEntityId(null);
    setSelectedBStoryId(null);
  }

  function startEditVolume(volumeId: string) {
    if (!canEdit || !macroData) return;
    ensureDraft();
    setEditSurface("volume");
    setSelectedEntityId(volumeId);
  }

  function startEditCast(nodeId: string) {
    if (!canEdit || !macroData) return;
    ensureDraft();
    setEditSurface("cast");
    setSelectedEntityId(nodeId);
  }

  function startEditAnchor(anchorId: string) {
    if (!canEdit || !macroData) return;
    ensureDraft();
    setEditSurface("anchor");
    setSelectedEntityId(anchorId);
  }

  function validateAndBuildPutBody(d: MacroCompileData, biblePayload: Record<string, unknown>): MacroPlanPutBody {
    const genre = String(biblePayload.genre ?? "").trim();
    const tone = String(biblePayload.tone ?? "").trim();
    if (!genre) throw new Error("請填寫「故事類型」。");
    if (!tone) throw new Error("請填寫「氛圍基調」。");
    const wr = biblePayload.world_rules;
    const fac = biblePayload.factions;
    const wn = biblePayload.writing_note;
    if (!Array.isArray(wr) || wr.length === 0) throw new Error("請至少填寫一條「世界規則」。");
    if (!Array.isArray(fac) || fac.length === 0) throw new Error("請至少填寫一條「勢力與陣營」。");
    if (!Array.isArray(wn) || wn.length === 0) throw new Error("請至少填寫一條「寫作備註」。");

    const mergedBible = mergeMacroBibles(
      biblePayload as Record<string, unknown>,
      isObjectRecord(d.bible) ? d.bible : {},
    );
    const mergedGenre = String(mergedBible.genre ?? mergedBible.story_genre ?? "").trim();
    if (!mergedGenre) {
      (mergedBible as Record<string, unknown>).genre = genre;
    } else {
      (mergedBible as Record<string, unknown>).genre = mergedGenre;
    }
    delete (mergedBible as { story_genre?: unknown }).story_genre;
    delete (mergedBible as { themes?: unknown }).themes;
    const mergedExtra = isObjectRecord((mergedBible as { extra?: unknown }).extra)
      ? { ...((mergedBible as { extra?: Record<string, unknown> }).extra ?? {}) }
      : {};
    delete mergedExtra.theme;
    delete mergedExtra.narrative_pov;
    delete mergedExtra.writing_style;
    (mergedBible as Record<string, unknown>).extra = mergedExtra;

    const volumes = [...(d.volumes ?? [])];
    const volumeModels = volumes.map((v) => ({
      volume_id: v.volume_id,
      title: v.title,
      chapter_start: Number(v.chapter_start),
      chapter_end: Number(v.chapter_end),
    }));
    for (const v of volumes) {
      const cs = Number(v.chapter_start);
      const ce = Number(v.chapter_end);
      if (!Number.isFinite(cs) || !Number.isFinite(ce)) throw new Error(`「${v.title || v.volume_id}」的章節範圍需為有效數字。`);
      if (cs > ce) throw new Error(tr(locale, `「${v.title || v.volume_id}」的起始章不可大於結束章。`, `「${v.title || v.volume_id}」的起始章不可大于结束章。`, `Start chapter cannot exceed end chapter for "${v.title || v.volume_id}".`));
    }
    const overlaps = findOverlappingVolumes(
      volumes.map((v) => ({
        volume_id: v.volume_id,
        title: v.title || v.volume_id,
        chapter_start: Number(v.chapter_start),
        chapter_end: Number(v.chapter_end),
      })),
    );
    if (overlaps.length > 0) {
      const [a, b] = overlaps[0] ?? ["", ""];
      const ta = volumes.find((x) => x.volume_id === a)?.title ?? a;
      const tb = volumes.find((x) => x.volume_id === b)?.title ?? b;
      throw new Error(
        tr(
          locale,
          `分卷章節範圍不可重疊：「${ta}」與「${tb}」區間相衝突。請調整範圍或合併分卷。`,
          `分卷章节范围不可重叠：「${ta}」与「${tb}」区间冲突。请调整范围或合并分卷。`,
          `Volume chapter ranges overlap between "${ta}" and "${tb}". Please adjust ranges.`,
        ),
      );
    }

    const cast = [...(d.cast ?? [])];
    if (cast.length === 0) throw new Error(tr(locale, "請至少保留一位人物。", "请至少保留一位人物。", "Keep at least one character."));

    const prot = d.protagonist_character_id?.trim() || "";
    if (prot && !cast.some((c) => c.node_id === prot)) {
      throw new Error(tr(locale, "敘事視角主角所選的人物不在人物清單中。", "叙事视角主角所选人物不在清单中。", "Selected POV protagonist is not in cast list."));
    }

    const rawAnchors = [...(d.anchors ?? [])];
    const withEdits = rawAnchors.map((a) => {
      const e = anchorEdits[a.anchor_id];
      if (!e) return { ...a };
      const ct = Number(e.chapter_target);
      const volume_id = findVolumeIdByChapter(d.volumes ?? [], ct);
      const goal = e.chapter_goal.trim();
      const target_state = goal ? { chapter_goal: goal } : {};
      return {
        ...a,
        volume_id,
        title: e.title,
        description: e.description,
        chapter_target: Number.isFinite(ct) ? ct : a.chapter_target,
        target_state,
      };
    });
    const anchorsPayload = sortAnchorsForUi(withEdits).map((a) => ({
      anchor_id: a.anchor_id,
      volume_id: String(a.volume_id ?? ""),
      title: a.title ?? "",
      description: a.description ?? "",
      chapter_target: Number(a.chapter_target),
      priority: a.priority,
      target_state: isObjectRecord(a.target_state) ? a.target_state : {},
    }));

    for (const a of anchorsPayload) {
      if (!a.volume_id) throw new Error(tr(locale, "情節節點的目標章節未落在任何分卷範圍，請先調整分卷章節區間。", "情节节点目标章节未落在任何分卷范围，请先调整分卷区间。", "Anchor chapter is outside all volume ranges."));
      if (!volumeModels.some((v) => v.volume_id === a.volume_id)) {
        throw new Error(tr(locale, "情節節點所掛的分卷不存在，請重新選擇。", "情节节点挂载的分卷不存在，请重新选择。", "Anchor volume does not exist."));
      }
      if (!Number.isFinite(a.chapter_target) || a.chapter_target < 1) {
        throw new Error(tr(locale, "情節節點的「發生章節」需為有效的章次。", "情节节点的“发生章节”需为有效章次。", "Anchor chapter target must be valid."));
      }
      const vol = volumeModels.find((v) => v.volume_id === a.volume_id);
      if (vol && (a.chapter_target < vol.chapter_start || a.chapter_target > vol.chapter_end)) {
        throw new Error(
          tr(
            locale,
            `情節節點「${a.title || a.anchor_id}」的章次需落在所選分卷的範圍內。`,
            `情节节点「${a.title || a.anchor_id}」章次需落在所选分卷范围内。`,
            `Anchor "${a.title || a.anchor_id}" chapter must be inside selected volume range.`,
          ),
        );
      }
    }

    return {
      bible: mergedBible as Record<string, unknown>,
      volumes,
      anchors: anchorsPayload,
      cast,
      protagonist_character_id: d.protagonist_character_id?.trim() || null,
    };
  }

  async function handleSave() {
    const d = draftMacro;
    if (!storyId || !d) return;
    onError("");
    setInlineError("");
    let body: MacroPlanPutBody;
    try {
      const biblePayload = buildBiblePayload(form);
      body = validateAndBuildPutBody(d, biblePayload);
    } catch (err) {
      const msg = err instanceof Error ? err.message : tr(locale, "無法儲存", "无法保存", "Unable to save");
      setInlineError(msg);
      onError(msg);
      return;
    }
    onBusy(true);
    try {
      const updated = await putMacroPlan(storyId, body);
      onMacroDataUpdate({
        story_id: updated.story_id,
        bible: updated.bible,
        macro_author_notes: updated.macro_author_notes,
        cast_seed: updated.cast_seed,
        volumes: updated.volumes ?? [],
        anchors: updated.anchors ?? [],
        cast: updated.cast ?? [],
        protagonist_character_id: updated.protagonist_character_id,
      });
      cancelEdit();
    } catch (err) {
      const msg = err instanceof Error ? err.message : tr(locale, "儲存失敗", "保存失败", "Save failed");
      setInlineError(msg);
      onError(msg);
    } finally {
      onBusy(false);
    }
  }

  function updateVolume(volumeId: string, patch: Partial<VolumePlan>) {
    const dm = ensureDraft();
    if (!dm) return;
    setInlineError(
      tr(
        locale,
        "提醒：新增或調整分卷章節後，可能讓既有情節節點與分卷範圍衝突。建議避免大幅調整；必要時可先更新故事設定重新編譯，再進行微調。",
        "提醒：新增或调整分卷章节后，可能与既有情节节点范围冲突。建议避免大幅调整。",
        "Note: changing volume ranges may conflict with existing anchors. Avoid major adjustments.",
      ),
    );
    setDraftMacro({
      ...dm,
      volumes: (dm.volumes ?? []).map((v) => (v.volume_id === volumeId ? { ...v, ...patch } : v)),
    });
  }

  function updateCastMember(nodeId: string, patch: Partial<CastMember>) {
    const dm = ensureDraft();
    if (!dm) return;
    setDraftMacro({
      ...dm,
      cast: (dm.cast ?? []).map((c) => (c.node_id === nodeId ? { ...c, ...patch } : c)),
    });
  }

  function deleteVolume(volumeId: string) {
    const dm = ensureDraft();
    if (!dm) return;
    const used = (dm.anchors ?? []).filter((a) => a.volume_id === volumeId);
    if (used.length > 0) {
      window.alert(tr(locale, "仍有情節節點掛在此分卷上，請先刪除或改掛節點後再刪除分卷。", "仍有情节节点挂在此分卷上，请先处理后再删除分卷。", "This volume still has anchors. Reassign/remove them before deleting."));
      return;
    }
    if (!window.confirm(tr(locale, "確定要刪除此分卷嗎？此動作無法復原。", "确定删除此分卷吗？此操作不可恢复。", "Delete this volume? This cannot be undone."))) return;
    const next = (dm.volumes ?? []).filter((v) => v.volume_id !== volumeId);
    setDraftMacro({ ...dm, volumes: next });
    if (selectedEntityId === volumeId) setSelectedEntityId(next[0]?.volume_id ?? null);
  }

  function deleteCastMember(nodeId: string) {
    const dm = ensureDraft();
    if (!dm) return;
    const list = dm.cast ?? [];
    if (list.length <= 1) {
      window.alert(tr(locale, "至少需要保留一位人物。", "至少需要保留一位人物。", "At least one character is required."));
      return;
    }
    if (!window.confirm(tr(locale, "確定要刪除此人物嗎？", "确定删除此人物吗？", "Delete this character?"))) return;
    const next = list.filter((c) => c.node_id !== nodeId);
    let prot = dm.protagonist_character_id;
    if (prot === nodeId) prot = next[0]?.node_id ?? "";
    setDraftMacro({ ...dm, cast: next, protagonist_character_id: prot });
    if (selectedEntityId === nodeId) setSelectedEntityId(next[0]?.node_id ?? null);
  }

  function deleteAnchor(anchorId: string) {
    const dm = ensureDraft();
    if (!dm) return;
    if (!window.confirm(tr(locale, "確定要刪除此情節節點嗎？", "确定删除此情节节点吗？", "Delete this anchor?"))) return;
    const nextAnchors = (dm.anchors ?? []).filter((a) => a.anchor_id !== anchorId);
    const nextEdits = { ...anchorEdits };
    delete nextEdits[anchorId];
    setAnchorEdits(nextEdits);
    setDraftMacro({ ...dm, anchors: normalizeAnchors(nextAnchors.map((a) => ({ ...a }))) });
    if (selectedEntityId === anchorId) setSelectedEntityId(nextAnchors[0]?.anchor_id ?? null);
  }

  function addVolume() {
    const dm = ensureDraft();
    if (!dm) return;
    setInlineError(
      tr(
        locale,
        "提醒：新增分卷後，請留意情節節點章節是否仍落在正確範圍。若要大幅改結構，建議先更新故事設定重新編譯，再回來微調。",
        "提醒：新增分卷后，请留意情节节点章节范围是否正确。",
        "Note: after adding volumes, verify anchor chapter ranges are still valid.",
      ),
    );
    const id = newLocalId("vol");
    const next: VolumePlan = {
      volume_id: id,
      title: tr(locale, "新分卷", "新分卷", "New Volume"),
      summary: "",
      chapter_start: 1,
      chapter_end: 1,
      target_volume_words: undefined,
    };
    setDraftMacro({ ...dm, volumes: [...(dm.volumes ?? []), next] });
    setEditSurface("volume");
    setSelectedEntityId(id);
  }

  function addCastMember() {
    const dm = ensureDraft();
    if (!dm) return;
    const id = newLocalId("char");
    const row: CastMember = {
      node_id: id,
      canonical_name: tr(locale, "新人物", "新人物", "New Character"),
      role: "supporting",
      short_bio: "",
    };
    setDraftMacro({ ...dm, cast: [...(dm.cast ?? []), row] });
    setEditSurface("cast");
    setSelectedEntityId(id);
  }

  function addAnchor() {
    const dm = ensureDraft();
    if (!dm) return;
    const vols = dm.volumes ?? [];
    const defaultVol = vols[0]?.volume_id ?? "";
    const id = newLocalId("anc");
    const vs = vols[0];
    const ct = vs ? Math.min(Math.max(1, vs.chapter_start), vs.chapter_end) : 1;
    const row: Anchor = {
      anchor_id: id,
      volume_id: defaultVol,
      title: tr(locale, "新節點", "新节点", "New Anchor"),
      description: "",
      chapter_target: ct,
      target_state: {},
      priority: 1,
    };
    const merged = normalizeAnchors([...(dm.anchors ?? []), row].map((a) => ({ ...a })));
    setDraftMacro({ ...dm, anchors: merged });
    setAnchorEdits({
      ...anchorEditsFromMacro(merged),
      [id]: {
        title: tr(locale, "新節點", "新节点", "New Anchor"),
        description: "",
        chapter_target: String(ct),
        chapter_goal: "",
      },
    });
    setEditSurface("anchor");
    setSelectedEntityId(id);
  }

  function addBStory() {
    const dm = ensureDraft();
    if (!dm) return;
    const id = newLocalId("bs");
    const row: BStoryRow = { id, desc: "", type: "UNKNOWN", resolution_condition: "" };
    setForm((f) => ({ ...f, activeBStories: [...f.activeBStories, row] }));
    setSelectedBStoryId(id);
    setEditSurface("bible");
  }

  function removeBStory(id: string) {
    setForm((f) => ({ ...f, activeBStories: f.activeBStories.filter((r) => r.id !== id) }));
    if (selectedBStoryId === id) setSelectedBStoryId(null);
  }

  const sortedVolumes = useMemo(() => [...(displayMacro?.volumes ?? [])], [displayMacro?.volumes]);
  const sortedAnchors = useMemo(
    () => sortAnchorsForUi([...(displayMacro?.anchors ?? [])]),
    [displayMacro?.anchors],
  );
  const castList = displayMacro?.cast ?? [];

  if (!macroData) {
    return (
      <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low p-5 text-on-surface-variant">
        <p className="font-body text-sm">
          {locale === "en"
            ? "No world/structure data yet. Run macro compile or import a project first."
            : locale === "zh-Hans"
              ? "尚无世界观与结构资料。请先完成宏观规划编译或导入项目。"
              : "尚無世界觀與結構資料。請先完成宏觀規畫編譯或匯入專案。"}
        </p>
      </section>
    );
  }

  const showSaveBar = isDirtySession;

  return (
    <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low p-4 sm:p-5">
      <div className="mb-4 flex flex-col gap-2 border-b border-outline-variant/10 pb-3">
        <p className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
          {locale === "en" ? "Book Structure" : locale === "zh-Hans" ? "全书结构" : "全書結構"}
        </p>
        <h2 className="font-title text-lg text-on-surface">
          {locale === "en" ? "World & Structure Output" : locale === "zh-Hans" ? "世界观与结构产出" : "世界觀與結構產出"}
        </h2>
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["bible", locale === "en" ? "World Bible" : locale === "zh-Hans" ? "世界观总表" : "世界觀總表"],
              ["volumes", locale === "en" ? "Volumes" : locale === "zh-Hans" ? "分卷" : "分卷"],
              ["cast", locale === "en" ? "Cast" : locale === "zh-Hans" ? "人物" : "人物"],
              ["anchors", locale === "en" ? "Anchors" : locale === "zh-Hans" ? "情节节点" : "情節節點"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => switchTab(id)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium transition ${
                tab === id ? "bg-secondary/15 text-secondary" : "bg-surface-container-highest text-on-surface-variant hover:bg-surface-container"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {inlineError ? (
        <div
          role="alert"
          className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 font-body text-sm text-red-200"
        >
          {inlineError}
        </div>
      ) : null}

      {showSaveBar ? (
        <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-outline-variant/10 pb-3">
          <button
            type="button"
            onClick={handleSave}
            disabled={!canEdit}
            className="rounded-lg bg-secondary px-4 py-2 text-sm font-semibold text-on-secondary disabled:opacity-40"
          >
            {tr(locale, "儲存", "保存", "Save")}
          </button>
          <button
            type="button"
            onClick={() => cancelEdit()}
            className="rounded-lg border border-outline-variant/30 px-4 py-2 text-sm text-on-surface"
          >
            {tr(locale, "取消", "取消", "Cancel")}
          </button>
        </div>
      ) : null}

      {/* 世界觀總表 */}
      {tab === "bible" ? (
        <div className="space-y-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="font-body font-semibold text-on-surface">
                {locale === "en" ? "World Bible" : locale === "zh-Hans" ? "世界观总表" : "世界觀總表"}
              </h3>
              <p className="mt-1 text-xs text-on-surface-variant">
                {locale === "en"
                  ? "Book-level world settings and long-arc subplots (maintained separately from story settings bible fields)."
                  : locale === "zh-Hans"
                    ? "全书世界设定与长线副线（与故事设置中的圣经栏位分开维护）。"
                    : "全書世界設定與長線副線（與故事設定中的聖經欄位分開維護）。"}
              </p>
            </div>
            {canEdit && editSurface !== "bible" ? (
              <button
                type="button"
                onClick={startEditBible}
                className="shrink-0 rounded-lg border border-secondary/40 px-3 py-2 text-sm font-semibold text-secondary"
              >
                {locale === "en" ? "Edit World Bible" : locale === "zh-Hans" ? "编辑世界观总表" : "編輯世界觀總表"}
              </button>
            ) : null}
          </div>

          {editSurface === "bible" && canEdit ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-2">
              <button
                type="button"
                onClick={addBStory}
                className="rounded-lg bg-surface-container-highest px-3 py-2 text-sm font-medium text-on-surface ring-1 ring-outline-variant/20"
              >
                {tr(locale, "新增長線副線", "新增长线副线", "Add Long-arc Subplot")}
              </button>
              <button
                type="button"
                onClick={() =>
                  setForm((f) => ({
                    ...f,
                    extraRows: [...f.extraRows, { key: "", value: "", isList: false }],
                  }))
                }
                className="rounded-lg bg-surface-container-highest px-3 py-2 text-sm font-medium text-on-surface ring-1 ring-outline-variant/20"
              >
                {tr(locale, "新增延伸筆記", "新增延伸笔记", "Add Extra Note")}
              </button>
            </div>
          ) : null}

          {editSurface === "bible" && canEdit ? (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {BIBLE_LINE_KEYS.map((key) => (
                  <label key={key} className="block min-w-0">
                    <span className="mb-1 block font-label text-[10px] font-semibold uppercase tracking-wide text-on-surface-variant">
                      {FIELD_LABELS[key][locale]}
                    </span>
                    {key === "genre" || key === "tone" ? (
                      <input
                        value={key === "genre" ? form.genre : form.tone}
                        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                        className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm text-on-surface"
                      />
                    ) : (
                      <textarea
                        value={String(form[key as keyof FormState] ?? "")}
                        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                        rows={4}
                        className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm text-on-surface"
                      />
                    )}
                  </label>
                ))}
              </div>

              <div>
                <h4 className="mb-2 font-body text-sm font-semibold text-on-surface">
                  {tr(locale, "長線副線", "长线副线", "Long-arc Subplots")}
                </h4>
                <div className="space-y-3">
                  {form.activeBStories.map((row) => {
                    const selected = selectedBStoryId === row.id;
                    return (
                      <div
                        key={row.id}
                        className={`rounded-xl border p-3 ${selected ? "border-secondary/50 bg-secondary/5" : "border-outline-variant/15 bg-surface-container-highest/60"}`}
                      >
                        <div className="grid grid-cols-12 gap-3">
                          <div className="col-span-12 sm:col-span-2">
                            <ReadonlyId label={tr(locale, "內部編號", "内部编号", "Internal ID")} value={row.id} />
                          </div>
                          <label className="col-span-12 block min-w-0 sm:col-span-5">
                            <span className="mb-1 block font-label text-[10px] font-semibold text-on-surface-variant">
                              {tr(locale, "說明", "说明", "Description")}
                            </span>
                            <textarea
                              value={row.desc}
                              onChange={(e) =>
                                setForm((f) => ({
                                  ...f,
                                  activeBStories: f.activeBStories.map((r) =>
                                    r.id === row.id ? { ...r, desc: e.target.value } : r,
                                  ),
                                }))
                              }
                              rows={3}
                              className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                            />
                          </label>
                          <div className="col-span-12 sm:col-span-2">
                            <ReadonlyId
                              label={tr(locale, "類型（自動）", "类型（自动）", "Type (auto)")}
                              value={row.type === "UNKNOWN" || !row.type ? tr(locale, "未分類", "未分类", "Uncategorized") : row.type}
                            />
                          </div>
                          <label className="col-span-12 block min-w-0 sm:col-span-2">
                            <span className="mb-1 block font-label text-[10px] font-semibold text-on-surface-variant">
                              {tr(locale, "收尾條件", "收尾条件", "Resolution Condition")}
                            </span>
                            <textarea
                              value={row.resolution_condition}
                              onChange={(e) =>
                                setForm((f) => ({
                                  ...f,
                                  activeBStories: f.activeBStories.map((r) =>
                                    r.id === row.id ? { ...r, resolution_condition: e.target.value } : r,
                                  ),
                                }))
                              }
                              rows={3}
                              className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                            />
                          </label>
                          <div className="col-span-12 flex items-end justify-end sm:col-span-1">
                            <button
                              type="button"
                              onClick={() => removeBStory(row.id)}
                              className="rounded-lg border border-outline-variant/30 px-2 py-1 text-xs text-on-surface-variant hover:bg-surface-container"
                            >
                              {tr(locale, "移除", "移除", "Remove")}
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div>
                <h4 className="mb-2 font-body text-sm font-semibold text-on-surface">
                  {tr(locale, "延伸筆記", "延伸笔记", "Extra Notes")}
                </h4>
                <p className="mb-2 text-xs text-on-surface-variant">
                  {tr(locale, "自訂欄位名與內容；若內容為多行清單，請勾選「多行清單」。", "自定义栏位名与内容；若内容为多行清单，请勾选“多行清单”。", "Use custom field name/content; if value is a list, enable multiline list.")}
                </p>
                <div className="space-y-3">
                  {form.extraRows.map((row, idx) => (
                    <div key={`${row.key}-${idx}`} className="grid grid-cols-12 gap-3 rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-3">
                      <label className="col-span-12 min-w-0 sm:col-span-3">
                        <span className="mb-1 block font-label text-[10px] font-semibold text-on-surface-variant">
                          {tr(locale, "欄位名稱", "栏位名称", "Field Name")}
                        </span>
                        <input
                          value={row.key}
                          onChange={(e) =>
                            setForm((f) => {
                              const next = [...f.extraRows];
                              const cur = next[idx];
                              if (cur) next[idx] = { ...cur, key: e.target.value };
                              return { ...f, extraRows: next };
                            })
                          }
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 min-w-0 sm:col-span-6">
                        <span className="mb-1 block font-label text-[10px] font-semibold text-on-surface-variant">
                          {tr(locale, "內容", "内容", "Content")}
                        </span>
                        <textarea
                          value={row.value}
                          onChange={(e) =>
                            setForm((f) => {
                              const next = [...f.extraRows];
                              const cur = next[idx];
                              if (cur) next[idx] = { ...cur, value: e.target.value };
                              return { ...f, extraRows: next };
                            })
                          }
                          rows={3}
                          className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-6 flex flex-col justify-end sm:col-span-2">
                        <span className="mb-1 block font-label text-[10px] font-semibold text-on-surface-variant">
                          {tr(locale, "多行清單", "多行清单", "Multiline List")}
                        </span>
                        <input
                          type="checkbox"
                          checked={row.isList}
                          onChange={(e) =>
                            setForm((f) => {
                              const next = [...f.extraRows];
                              const cur = next[idx];
                              if (cur) next[idx] = { ...cur, isList: e.target.checked };
                              return { ...f, extraRows: next };
                            })
                          }
                          className="h-4 w-4"
                        />
                      </label>
                      <div className="col-span-6 flex items-end justify-end sm:col-span-1">
                        <button
                          type="button"
                          onClick={() => setForm((f) => ({ ...f, extraRows: f.extraRows.filter((_, j) => j !== idx) }))}
                          className="rounded-lg border border-outline-variant/30 px-2 py-1 text-xs"
                        >
                          {tr(locale, "刪除", "删除", "Delete")}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3 text-sm text-on-surface">
              {formatBibleReadRows(locale, form).map((row) => (
                <div key={row.label}>
                  <p className="text-on-surface-variant">{row.label}</p>
                  <p className="whitespace-pre-wrap">{row.value}</p>
                </div>
              ))}
              <div>
                <p className="text-on-surface-variant">{tr(locale, "長線副線", "长线副线", "Long-arc Subplots")}</p>
                <ul className="mt-1 list-disc space-y-1 pl-5">
                  {parseBStories(macroData.bible?.active_b_stories).map((r) => (
                    <li key={r.id}>
                      <p>{r.desc || r.id}</p>
                      {r.resolution_condition ? (
                        <p className="text-xs text-on-surface-variant">
                          {tr(locale, "收尾條件", "收尾条件", "Resolution Condition")}：{r.resolution_condition}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="text-on-surface-variant">{tr(locale, "延伸筆記", "延伸笔记", "Extra Notes")}</p>
                <div className="mt-1 space-y-2">
                  {form.extraRows.length === 0 ? <p>—</p> : null}
                  {form.extraRows.map((row, idx) => (
                    <div key={`${row.key}-${idx}`} className="rounded-lg border border-outline-variant/15 bg-surface-container-highest/40 p-2">
                      <p className="text-xs text-on-surface-variant">{row.key || tr(locale, "（未命名欄位）", "（未命名栏位）", "(Unnamed field)")}</p>
                      <p className="whitespace-pre-wrap">{row.value || "—"}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      ) : null}

      {tab === "volumes" ? (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="font-body font-semibold text-on-surface">{tr(locale, "分卷", "分卷", "Volumes")}</h3>
            {canEdit ? (
              <button type="button" onClick={() => addVolume()} className="rounded-lg border border-secondary/40 px-3 py-2 text-sm font-semibold text-secondary">
                {tr(locale, "新增分卷", "新增分卷", "Add Volume")}
              </button>
            ) : null}
          </div>
          <div className="space-y-3">
            {sortedVolumes.map((v) => {
              const editing = editSurface === "volume" && selectedEntityId === v.volume_id;
              const show = draftMacro ? editing : false;
              const dataVol = displayMacro?.volumes?.find((x) => x.volume_id === v.volume_id) ?? v;
              return (
                <div key={v.volume_id} className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4">
                  <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start">
                    <div className="min-w-0 flex-1 space-y-2">
                      <p className="font-medium text-on-surface">{dataVol.title || tr(locale, "（未命名分卷）", "（未命名分卷）", "(Untitled volume)")}</p>
                      <p className="text-xs text-on-surface-variant">
                        {locale === "en"
                          ? `Chapter ${dataVol.chapter_start}-${dataVol.chapter_end}`
                          : locale === "zh-Hans"
                            ? `第 ${dataVol.chapter_start}–${dataVol.chapter_end} 章`
                            : `第 ${dataVol.chapter_start}–${dataVol.chapter_end} 章`}
                      </p>
                      <p className="text-sm text-on-surface">{dataVol.summary || "—"}</p>
                    </div>
                    {canEdit ? (
                      <div className="flex min-w-[5.5rem] shrink-0 flex-col gap-2 self-start">
                        <button
                          type="button"
                          onClick={() => startEditVolume(v.volume_id)}
                          className="rounded-lg border border-outline-variant/30 px-3 py-1.5 text-sm"
                        >
                          {tr(locale, "編輯", "编辑", "Edit")}
                        </button>
                        {show ? (
                          <button type="button" onClick={() => deleteVolume(v.volume_id)} className="rounded-lg border border-red-500/30 px-3 py-1.5 text-sm text-red-300">
                            {tr(locale, "刪除", "删除", "Delete")}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  {show && draftMacro ? (
                    <div className="grid grid-cols-12 gap-3 border-t border-outline-variant/10 pt-3">
                      <div className="col-span-12 sm:col-span-3">
                        <ReadonlyId label={tr(locale, "內部編號", "内部编号", "Internal ID")} value={v.volume_id} />
                      </div>
                      <label className="col-span-12 sm:col-span-9">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "分卷標題", "分卷标题", "Volume title")}</span>
                        <input
                          value={dataVol.title}
                          onChange={(e) => updateVolume(v.volume_id, { title: e.target.value })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-12">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "梗概", "梗概", "Summary")}</span>
                        <textarea
                          value={dataVol.summary}
                          onChange={(e) => updateVolume(v.volume_id, { summary: e.target.value })}
                          rows={3}
                          className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-6 sm:col-span-3">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "起始章", "起始章", "Start chapter")}</span>
                        <input
                          type="number"
                          value={dataVol.chapter_start}
                          onChange={(e) => updateVolume(v.volume_id, { chapter_start: Number(e.target.value) })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-6 sm:col-span-3">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "結束章", "结束章", "End chapter")}</span>
                        <input
                          type="number"
                          value={dataVol.chapter_end}
                          onChange={(e) => updateVolume(v.volume_id, { chapter_end: Number(e.target.value) })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-3">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "本卷字數目標（選填）", "本卷字数目标（选填）", "Target words (optional)")}</span>
                        <input
                          type="number"
                          value={dataVol.target_volume_words ?? ""}
                          onChange={(e) =>
                            updateVolume(v.volume_id, {
                              target_volume_words: e.target.value === "" ? undefined : Number(e.target.value),
                            })
                          }
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {tab === "cast" ? (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="font-body font-semibold text-on-surface">{tr(locale, "人物", "人物", "Cast")}</h3>
            {canEdit ? (
              <button type="button" onClick={() => addCastMember()} className="rounded-lg border border-secondary/40 px-3 py-2 text-sm font-semibold text-secondary">
                {tr(locale, "新增人物", "新增人物", "Add Character")}
              </button>
            ) : null}
          </div>
          {canEdit ? (
            <label className="mb-2 block max-w-md">
              <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "敘事視角主角", "叙事视角主角", "POV Protagonist")}</span>
              <select
                value={displayMacro?.protagonist_character_id ?? ""}
                onChange={(e) => {
                  const dm = ensureDraft();
                  if (!dm) return;
                  setDraftMacro({ ...dm, protagonist_character_id: e.target.value || undefined });
                  setEditSurface("cast");
                }}
                className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
              >
                <option value="">{tr(locale, "（未指定）", "（未指定）", "(Unspecified)")}</option>
                {castList.map((c) => (
                  <option key={c.node_id} value={c.node_id}>
                    {c.canonical_name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="space-y-3">
            {castList.map((c) => {
              const editing = editSurface === "cast" && selectedEntityId === c.node_id;
              const show = draftMacro ? editing : false;
              return (
                <div key={c.node_id} className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4">
                  <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="font-medium">{c.canonical_name}</p>
                      <p className="text-xs text-on-surface-variant">{roleLabel(c.role, locale)}</p>
                      <p className="text-sm">{c.short_bio || "—"}</p>
                      <p className="text-xs text-on-surface-variant">{tr(locale, "核心動機", "核心动机", "Core Motivation")}：{c.core_motivation || "—"}</p>
                      <p className="text-xs text-on-surface-variant">{tr(locale, "核心價值", "核心价值", "Core Value")}：{c.core_value || "—"}</p>
                      <details className="mt-2 rounded-lg border border-outline-variant/15 bg-surface-container-highest/40 p-2">
                        <summary className="cursor-pointer text-xs font-semibold text-secondary">{tr(locale, "展開完整人物資訊", "展开完整人物信息", "Expand full character info")}</summary>
                        <div className="mt-2 grid grid-cols-1 gap-1 text-xs text-on-surface-variant sm:grid-cols-2">
                          <p>{tr(locale, "別名", "别名", "Aliases")}：{(c.aliases ?? []).join("、") || "—"}</p>
                          <p>{tr(locale, "年齡", "年龄", "Age")}：{c.age || "—"}</p>
                          <p>{tr(locale, "個性", "个性", "Personality")}：{c.personality || "—"}</p>
                          <p>{tr(locale, "語氣風格", "语气风格", "Speech Style")}：{c.speech_style || "—"}</p>
                          <p>{tr(locale, "致命弱點", "致命弱点", "Fatal Flaw")}：{c.fatal_flaw || "—"}</p>
                          <p>{tr(locale, "習慣與怪癖", "习惯与怪癖", "Quirks & Habits")}：{c.quirks_and_habits || "—"}</p>
                        </div>
                      </details>
                    </div>
                    {canEdit ? (
                      <div className="flex min-w-[5.5rem] shrink-0 flex-col gap-2 self-start">
                        <button type="button" onClick={() => startEditCast(c.node_id)} className="rounded-lg border border-outline-variant/30 px-3 py-1.5 text-sm">
                          {tr(locale, "編輯", "编辑", "Edit")}
                        </button>
                        {show ? (
                          <button type="button" onClick={() => deleteCastMember(c.node_id)} className="rounded-lg border border-red-500/30 px-3 py-1.5 text-sm text-red-300">
                            {tr(locale, "刪除", "删除", "Delete")}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  {show && draftMacro ? (
                    <div className="grid grid-cols-12 gap-3 border-t border-outline-variant/10 pt-3">
                      <div className="col-span-12 sm:col-span-3">
                        <ReadonlyId label={tr(locale, "內部編號", "内部编号", "Internal ID")} value={c.node_id} />
                      </div>
                      <label className="col-span-12 sm:col-span-4">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "姓名／稱呼", "姓名/称呼", "Name / Display Name")}</span>
                        <input
                          value={c.canonical_name}
                          onChange={(e) => updateCastMember(c.node_id, { canonical_name: e.target.value })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-3">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "戲劇角色", "戏剧角色", "Role")}</span>
                        <select
                          value={c.role}
                          onChange={(e) => updateCastMember(c.node_id, { role: e.target.value })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        >
                          <option value="protagonist">{tr(locale, "主角", "主角", "Protagonist")}</option>
                          <option value="supporting">{tr(locale, "配角", "配角", "Supporting")}</option>
                          <option value="antagonist">{tr(locale, "對立角色", "对立角色", "Antagonist")}</option>
                        </select>
                      </label>
                      <label className="col-span-12">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "簡短小傳", "简短小传", "Short Bio")}</span>
                        <textarea
                          value={c.short_bio ?? ""}
                          onChange={(e) => updateCastMember(c.node_id, { short_bio: e.target.value })}
                          rows={3}
                          className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-6">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "別名（每行一個）", "别名（每行一个）", "Aliases (one per line)")}</span>
                        <textarea
                          value={(c.aliases ?? []).join("\n")}
                          onChange={(e) =>
                            updateCastMember(c.node_id, {
                              aliases: e.target.value
                                .split(/\r?\n/)
                                .map((x) => x.trim())
                                .filter(Boolean),
                            })
                          }
                          rows={3}
                          className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-3">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "年齡（選填）", "年龄（选填）", "Age (optional)")}</span>
                        <input
                          value={c.age ?? ""}
                          onChange={(e) => updateCastMember(c.node_id, { age: e.target.value })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-3">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "個性（選填）", "个性（选填）", "Personality (optional)")}</span>
                        <input
                          value={c.personality ?? ""}
                          onChange={(e) => updateCastMember(c.node_id, { personality: e.target.value })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-6">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "核心動機", "核心动机", "Core Motivation")}</span>
                        <input
                          value={c.core_motivation ?? ""}
                          onChange={(e) => updateCastMember(c.node_id, { core_motivation: e.target.value })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-6">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "核心價值", "核心价值", "Core Value")}</span>
                        <input
                          value={c.core_value ?? ""}
                          onChange={(e) => updateCastMember(c.node_id, { core_value: e.target.value })}
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-6">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "語氣風格", "语气风格", "Speech Style")}</span>
                        <textarea
                          value={c.speech_style ?? ""}
                          onChange={(e) => updateCastMember(c.node_id, { speech_style: e.target.value })}
                          rows={2}
                          className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-6">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "致命弱點", "致命弱点", "Fatal Flaw")}</span>
                        <textarea
                          value={c.fatal_flaw ?? ""}
                          onChange={(e) => updateCastMember(c.node_id, { fatal_flaw: e.target.value })}
                          rows={2}
                          className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "習慣與怪癖", "习惯与怪癖", "Quirks & Habits")}</span>
                        <textarea
                          value={c.quirks_and_habits ?? ""}
                          onChange={(e) => updateCastMember(c.node_id, { quirks_and_habits: e.target.value })}
                          rows={2}
                          className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {tab === "anchors" ? (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="font-body font-semibold text-on-surface">{tr(locale, "情節節點", "情节节点", "Anchors")}</h3>
            {canEdit ? (
              <button
                type="button"
                onClick={() => addAnchor()}
                className="rounded-lg border border-secondary/40 px-3 py-2 text-sm font-semibold text-secondary"
              >
                {tr(locale, "新增情節節點", "新增情节节点", "Add Anchor")}
              </button>
            ) : null}
          </div>
          <div className="space-y-3">
            {sortedAnchors.map((a) => {
              const editing = editSurface === "anchor" && selectedEntityId === a.anchor_id;
              const show = draftMacro ? editing : false;
              const e = anchorEdits[a.anchor_id] ?? {
                title: a.title ?? "",
                description: a.description ?? "",
                chapter_target: String(a.chapter_target ?? ""),
                chapter_goal: extractAnchorGoal(isObjectRecord(a.target_state) ? (a.target_state as Record<string, unknown>) : {}),
              };
              const resolvedVolumeId = findVolumeIdByChapter(displayMacro?.volumes ?? [], e.chapter_target);
              const resolvedVolumeName =
                (displayMacro?.volumes ?? []).find((v) => v.volume_id === resolvedVolumeId)?.title || resolvedVolumeId || tr(locale, "未匹配到分卷", "未匹配到分卷", "No matched volume");
              return (
                <div key={a.anchor_id} className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4">
                  <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="font-medium">
                        {locale === "en" ? `Chapter ${a.chapter_target}` : `第 ${a.chapter_target} 章`} · {a.title}
                      </p>
                      <p className="text-sm text-on-surface-variant">{a.description || "—"}</p>
                    </div>
                    {canEdit ? (
                      <div className="flex min-w-[5.5rem] shrink-0 flex-col gap-2 self-start">
                        <button type="button" onClick={() => startEditAnchor(a.anchor_id)} className="rounded-lg border border-outline-variant/30 px-3 py-1.5 text-sm">
                          {tr(locale, "編輯", "编辑", "Edit")}
                        </button>
                        {show ? (
                          <button type="button" onClick={() => deleteAnchor(a.anchor_id)} className="rounded-lg border border-red-500/30 px-3 py-1.5 text-sm text-red-300">
                            {tr(locale, "刪除", "删除", "Delete")}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  {show && draftMacro ? (
                    <div className="grid grid-cols-12 gap-3 border-t border-outline-variant/10 pt-3">
                      <div className="col-span-12 sm:col-span-3">
                        <ReadonlyId label={tr(locale, "內部編號", "内部编号", "Internal ID")} value={a.anchor_id} />
                      </div>
                      <label className="col-span-12 sm:col-span-5">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "節點標題", "节点标题", "Anchor Title")}</span>
                        <input
                          value={e.title}
                          onChange={(ev) =>
                            setAnchorEdits((prev) => ({
                              ...prev,
                              [a.anchor_id]: { ...e, title: ev.target.value },
                            }))
                          }
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <label className="col-span-12 sm:col-span-4">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "發生章節", "发生章节", "Chapter Target")}</span>
                        <input
                          type="number"
                          value={e.chapter_target}
                          onChange={(ev) =>
                            setAnchorEdits((prev) => ({
                              ...prev,
                              [a.anchor_id]: { ...e, chapter_target: ev.target.value },
                            }))
                          }
                          className="w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                      </label>
                      <div className="col-span-12 sm:col-span-3">
                        <ReadonlyId label={tr(locale, "自動匹配分卷", "自动匹配分卷", "Matched Volume")} value={resolvedVolumeName} />
                      </div>
                      <label className="col-span-12">
                        <span className="mb-1 block font-label text-[10px] text-on-surface-variant">{tr(locale, "本章敘事目標", "本章叙事目标", "Narrative Goal")}</span>
                        <textarea
                          aria-label={tr(locale, "本章敘事目標（可留空；細節可交給後續流程補全）", "本章叙事目标（可留空；细节可交给后续流程补全）", "Narrative goal (optional)") }
                          value={e.chapter_goal}
                          onChange={(ev) =>
                            setAnchorEdits((prev) => ({
                              ...prev,
                              [a.anchor_id]: { ...e, chapter_goal: ev.target.value },
                            }))
                          }
                          rows={3}
                          className="w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                        />
                        <p className="mt-1 text-xs text-on-surface-variant">
                          {tr(locale, "僅需描述此章要達成的敘事目標；細節可由後續步驟協助補齊。", "仅需描述本章叙事目标；细节可由后续步骤补齐。", "Describe this chapter's narrative goal; details can be filled by later steps.")}
                        </p>
                      </label>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function roleLabel(role: string, locale: "zh-Hant" | "zh-Hans" | "en"): string {
  if (role === "protagonist") return tr(locale, "主角", "主角", "Protagonist");
  if (role === "supporting") return tr(locale, "配角", "配角", "Supporting");
  if (role === "antagonist") return tr(locale, "對立角色", "对立角色", "Antagonist");
  return role || "—";
}
