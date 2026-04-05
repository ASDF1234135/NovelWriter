import { useEffect, useState } from "react";
import type { StoryCastSeedEntry, StoryInput } from "../../types";

const MACRO_NOTES_SOFT_MAX = 8000;

type CastSeedRow = {
  canonical_name: string;
  role: "" | "protagonist" | "antagonist" | "supporting";
  short_hint: string;
};

function normalizeCastSeedPayload(rows: CastSeedRow[]): StoryCastSeedEntry[] {
  return rows
    .map((r) => ({
      canonical_name: r.canonical_name.trim(),
      role: r.role || undefined,
      short_hint: r.short_hint.trim() || undefined,
    }))
    .filter((r) => r.canonical_name.length > 0)
    .map((r) => {
      const out: StoryCastSeedEntry = { canonical_name: r.canonical_name };
      if (r.role) out.role = r.role;
      if (r.short_hint) out.short_hint = r.short_hint;
      return out;
    });
}

function castSeedToRows(seed: StoryCastSeedEntry[] | undefined): CastSeedRow[] {
  if (!seed?.length) return [];
  return seed.map((s) => ({
    canonical_name: s.canonical_name,
    role: (s.role ?? "") as CastSeedRow["role"],
    short_hint: s.short_hint ?? "",
  }));
}

type Props = {
  onSubmit: (payload: StoryInput) => Promise<void>;
  disabled?: boolean;
  locked?: boolean;
  /** When set (e.g. after create or GET /stories/:id), drives field values. Null = new-project demo defaults. */
  initialValues?: StoryInput | null;
  /** Bump when loading a story / create / refetch so fields re-hydrate without reacting to every keystroke. */
  resetKey: string;
  /** Called when unlocked and any field changes (parent keeps snapshot for navigation). */
  onValuesChange?: (payload: StoryInput) => void;
  /** When set with unlocked story, show "儲存設定" to PATCH server before macro compile. */
  onSaveSettings?: (payload: StoryInput) => Promise<void>;
  /** True when creating a new story (show 建立故事); false when editing existing. */
  showCreateButton?: boolean;
};

function hydrateFromStoryInput(input: StoryInput): {
  title: string;
  premise: string;
  targetTotalWords: number;
  planRetryLimit: number;
  draftLoopRetryLimit: number;
  macroAuthorNotes: string;
  castRows: CastSeedRow[];
} {
  return {
    title: input.title,
    premise: input.premise,
    targetTotalWords: input.target_total_words,
    planRetryLimit: input.plan_retry_limit,
    draftLoopRetryLimit: input.draft_loop_retry_limit,
    macroAuthorNotes: input.macro_author_notes ?? "",
    castRows: castSeedToRows(input.cast_seed),
  };
}

function buildStoryPayload(
  title: string,
  premise: string,
  targetTotalWords: number,
  planRetryLimit: number,
  draftLoopRetryLimit: number,
  macroAuthorNotes: string,
  castRows: CastSeedRow[],
): StoryInput {
  return {
    title,
    premise,
    target_total_words: targetTotalWords,
    plan_retry_limit: planRetryLimit,
    draft_loop_retry_limit: draftLoopRetryLimit,
    bible: {},
    macro_author_notes: macroAuthorNotes,
    cast_seed: normalizeCastSeedPayload(castRows),
  };
}

export function StorySetupForm({
  onSubmit,
  disabled,
  locked = false,
  initialValues,
  resetKey,
  onValuesChange,
  onSaveSettings,
  showCreateButton = true,
}: Props) {
  const [title, setTitle] = useState("王都疑雲");
  const [premise, setPremise] = useState("一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。");
  const [targetTotalWords, setTargetTotalWords] = useState(100000);
  const [planRetryLimit, setPlanRetryLimit] = useState(3);
  const [draftLoopRetryLimit, setDraftLoopRetryLimit] = useState(3);
  const [macroAuthorNotes, setMacroAuthorNotes] = useState("");
  const [castRows, setCastRows] = useState<CastSeedRow[]>([]);
  const [saveBusy, setSaveBusy] = useState(false);

  useEffect(() => {
    if (initialValues) {
      const h = hydrateFromStoryInput(initialValues);
      setTitle(h.title);
      setPremise(h.premise);
      setTargetTotalWords(h.targetTotalWords);
      setPlanRetryLimit(h.planRetryLimit);
      setDraftLoopRetryLimit(h.draftLoopRetryLimit);
      setMacroAuthorNotes(h.macroAuthorNotes);
      setCastRows(h.castRows);
    } else {
      setTitle("王都疑雲");
      setPremise("一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。");
      setTargetTotalWords(100000);
      setPlanRetryLimit(3);
      setDraftLoopRetryLimit(3);
      setMacroAuthorNotes("");
      setCastRows([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate only when resetKey bumps
  }, [resetKey]);

  useEffect(() => {
    if (locked || !onValuesChange) return;
    onValuesChange(
      buildStoryPayload(title, premise, targetTotalWords, planRetryLimit, draftLoopRetryLimit, macroAuthorNotes, castRows),
    );
  }, [
    locked,
    onValuesChange,
    title,
    premise,
    targetTotalWords,
    planRetryLimit,
    draftLoopRetryLimit,
    macroAuthorNotes,
    castRows,
  ]);

  const fieldDisabled = Boolean(disabled || locked);
  const sectionClassName = locked
    ? "flex flex-col gap-6 rounded-xl border-2 border-primary/25 bg-primary/5 p-6 shadow-glow md:p-8"
    : "flex flex-col gap-6 rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow md:p-8";

  const notesLen = macroAuthorNotes.length;
  const notesWarn = notesLen > MACRO_NOTES_SOFT_MAX;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (locked) return;
    await onSubmit(
      buildStoryPayload(title, premise, targetTotalWords, planRetryLimit, draftLoopRetryLimit, macroAuthorNotes, castRows),
    );
  }

  async function handleSaveSettings() {
    if (!onSaveSettings || locked) return;
    setSaveBusy(true);
    try {
      await onSaveSettings(
        buildStoryPayload(title, premise, targetTotalWords, planRetryLimit, draftLoopRetryLimit, macroAuthorNotes, castRows),
      );
    } finally {
      setSaveBusy(false);
    }
  }

  return (
    <section className={sectionClassName}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="flex items-center gap-2 font-headline text-lg font-bold text-primary">
          <span className="material-symbols-outlined">tune</span>
          設定項目
        </h2>
        {locked ? (
          <span className="rounded-full border border-primary/30 bg-primary/15 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-widest text-primary">
            已鎖定（撰寫本章後不可修改）
          </span>
        ) : null}
      </div>
      <p className="font-body text-sm text-on-surface-variant">
        世界觀總表會依你的故事梗概與補充筆記，在執行世界觀編譯後自動產生；一般無需手動編輯結構化檔案。
      </p>
      <form className="flex flex-col gap-5" onSubmit={handleSubmit}>
        <div className="space-y-1">
          <label className="auteur-label">書名</label>
          <input className="auteur-input" value={title} onChange={(e) => setTitle(e.target.value)} disabled={fieldDisabled} readOnly={locked} />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <label className="auteur-label">全書目標字數</label>
            <input
              type="number"
              className="auteur-input text-center font-label"
              value={targetTotalWords}
              onChange={(e) => setTargetTotalWords(Number(e.target.value))}
              disabled={fieldDisabled}
              readOnly={locked}
            />
          </div>
          <div className="space-y-1">
            <label className="auteur-label">大綱重試次數上限</label>
            <input
              type="number"
              min={0}
              max={20}
              className="auteur-input text-center font-label"
              value={planRetryLimit}
              onChange={(e) => setPlanRetryLimit(Number(e.target.value))}
              disabled={fieldDisabled}
              readOnly={locked}
            />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <label className="auteur-label">內文與閱讀檢查重試次數</label>
            <input
              type="number"
              min={0}
              max={20}
              className="auteur-input text-center font-label"
              value={draftLoopRetryLimit}
              onChange={(e) => setDraftLoopRetryLimit(Number(e.target.value))}
              disabled={fieldDisabled}
              readOnly={locked}
            />
          </div>
        </div>
        <div className="space-y-1">
          <label className="auteur-label">故事核心／梗概</label>
          <textarea
            className="auteur-input min-h-[120px] resize-y font-body leading-relaxed"
            value={premise}
            onChange={(e) => setPremise(e.target.value)}
            rows={4}
            disabled={fieldDisabled}
            readOnly={locked}
          />
        </div>
        <div className="space-y-3 rounded-lg border border-outline-variant/15 bg-surface-container/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="auteur-label mb-0">核心角色種子（選填）</label>
            {fieldDisabled ? null : (
              <button
                type="button"
                className="btn-secondary shrink-0 px-3 py-1.5 text-xs"
                onClick={() => setCastRows((r) => [...r, { canonical_name: "", role: "", short_hint: "" }])}
              >
                <span className="material-symbols-outlined text-base">person_add</span>
                新增角色
              </button>
            )}
          </div>
          <p className="font-body text-xs text-on-surface-variant">
            留空則人物完全由系統依梗概與筆記生成。若填寫，請列出貫穿主線的核心人物；編譯時會保留這些姓名。
          </p>
          {castRows.length === 0 ? (
            <p className="font-body text-sm italic text-on-surface-variant">尚未新增種子角色。</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {castRows.map((row, index) => (
                <li
                  key={`cast-${index}`}
                  className="grid grid-cols-1 gap-2 rounded-md border border-outline-variant/10 bg-surface-container-low p-3 sm:grid-cols-12"
                >
                  <div className="sm:col-span-4">
                    <label className="auteur-label text-[10px]">正式名稱</label>
                    <input
                      className="auteur-input font-body"
                      value={row.canonical_name}
                      onChange={(e) => {
                        const v = e.target.value;
                        setCastRows((rows) => rows.map((x, i) => (i === index ? { ...x, canonical_name: v } : x)));
                      }}
                      disabled={fieldDisabled}
                      readOnly={locked}
                      placeholder="例如：林澈"
                    />
                  </div>
                  <div className="sm:col-span-3">
                    <label className="auteur-label text-[10px]">角色類型（選填）</label>
                    <select
                      className="auteur-input font-body"
                      value={row.role}
                      onChange={(e) => {
                        const v = e.target.value as CastSeedRow["role"];
                        setCastRows((rows) => rows.map((x, i) => (i === index ? { ...x, role: v } : x)));
                      }}
                      disabled={fieldDisabled}
                    >
                      <option value="">未指定</option>
                      <option value="protagonist">主角</option>
                      <option value="antagonist">反派</option>
                      <option value="supporting">配角</option>
                    </select>
                  </div>
                  <div className="sm:col-span-4">
                    <label className="auteur-label text-[10px]">一句提示（選填）</label>
                    <input
                      className="auteur-input font-body text-sm"
                      value={row.short_hint}
                      onChange={(e) => {
                        const v = e.target.value;
                        setCastRows((rows) => rows.map((x, i) => (i === index ? { ...x, short_hint: v } : x)));
                      }}
                      disabled={fieldDisabled}
                      readOnly={locked}
                      placeholder="給系統的短註（例如性格關鍵字）"
                    />
                  </div>
                  <div className="flex items-end justify-end sm:col-span-1">
                    {fieldDisabled ? null : (
                      <button
                        type="button"
                        className="rounded-md p-2 text-on-surface-variant hover:bg-error/10 hover:text-error"
                        aria-label="移除此列"
                        onClick={() => setCastRows((rows) => rows.filter((_, i) => i !== index))}
                      >
                        <span className="material-symbols-outlined text-xl">close</span>
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="space-y-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <label className="auteur-label">作者補充（自由格式）</label>
            <span className={`font-mono text-xs ${notesWarn ? "text-tertiary" : "text-on-surface-variant"}`}>
              {notesLen} / ~{MACRO_NOTES_SOFT_MAX} 建議上限
              {notesWarn ? "（過長時系統會自動截短）" : ""}
            </span>
          </div>
          <textarea
            className="auteur-input min-h-[160px] resize-y font-body text-sm leading-relaxed"
            value={macroAuthorNotes}
            onChange={(e) => setMacroAuthorNotes(e.target.value)}
            rows={6}
            placeholder="世界觀細節、角色關係、禁忌、篇幅節奏……格式不拘（Markdown、條列皆可）。"
            disabled={fieldDisabled}
            readOnly={locked}
          />
        </div>
        {locked ? null : (
          <div className="flex flex-col gap-3 sm:flex-row">
            {showCreateButton ? (
              <button type="submit" className="btn-primary-gradient flex-1 justify-center" disabled={disabled}>
                <span className="material-symbols-outlined">add_circle</span>
                建立故事
              </button>
            ) : null}
            {onSaveSettings ? (
              <button
                type="button"
                className="btn-secondary flex-1 justify-center"
                disabled={disabled || saveBusy}
                onClick={() => void handleSaveSettings()}
              >
                <span className="material-symbols-outlined">save</span>
                儲存設定
              </button>
            ) : null}
          </div>
        )}
      </form>
    </section>
  );
}
