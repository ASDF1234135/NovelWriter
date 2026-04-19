import { type ChangeEvent, useEffect, useRef, useState } from "react";
import type { ImportMergeMode, StoryInput } from "../../types";

const MACRO_NOTES_SOFT_MAX = 8000;

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
  onExportProjectBundle?: () => void;
  onImportProjectBundle?: (jsonText: string, mode: ImportMergeMode) => Promise<void>;
  onBusy?: (busy: boolean) => void;
  onError?: (message: string) => void;
};

function hydrateFromStoryInput(input: StoryInput): {
  title: string;
  premise: string;
  targetTotalWords: number;
  planRetryLimit: number;
  draftLoopRetryLimit: number;
  macroAuthorNotes: string;
} {
  return {
    title: input.title,
    premise: input.premise,
    targetTotalWords: input.target_total_words,
    planRetryLimit: input.plan_retry_limit,
    draftLoopRetryLimit: input.draft_loop_retry_limit,
    macroAuthorNotes: input.macro_author_notes ?? "",
  };
}

function buildStoryPayload(
  title: string,
  premise: string,
  targetTotalWords: number,
  planRetryLimit: number,
  draftLoopRetryLimit: number,
  macroAuthorNotes: string,
): StoryInput {
  return {
    title,
    premise,
    target_total_words: targetTotalWords,
    plan_retry_limit: planRetryLimit,
    draft_loop_retry_limit: draftLoopRetryLimit,
    bible: {},
    macro_author_notes: macroAuthorNotes,
    cast_seed: [],
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
  onExportProjectBundle,
  onImportProjectBundle,
  onBusy,
  onError,
}: Props) {
  const [title, setTitle] = useState("王都疑雲");
  const [premise, setPremise] = useState("一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。");
  const [targetTotalWords, setTargetTotalWords] = useState(100000);
  const [planRetryLimit, setPlanRetryLimit] = useState(3);
  const [draftLoopRetryLimit, setDraftLoopRetryLimit] = useState(3);
  const [macroAuthorNotes, setMacroAuthorNotes] = useState("");
  const [saveBusy, setSaveBusy] = useState(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (initialValues) {
      const h = hydrateFromStoryInput(initialValues);
      setTitle(h.title);
      setPremise(h.premise);
      setTargetTotalWords(h.targetTotalWords);
      setPlanRetryLimit(h.planRetryLimit);
      setDraftLoopRetryLimit(h.draftLoopRetryLimit);
      setMacroAuthorNotes(h.macroAuthorNotes);
    } else {
      setTitle("王都疑雲");
      setPremise("一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。");
      setTargetTotalWords(100000);
      setPlanRetryLimit(3);
      setDraftLoopRetryLimit(3);
      setMacroAuthorNotes("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate only when resetKey bumps
  }, [resetKey]);

  useEffect(() => {
    if (locked || !onValuesChange) return;
    onValuesChange(
      buildStoryPayload(title, premise, targetTotalWords, planRetryLimit, draftLoopRetryLimit, macroAuthorNotes),
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
      buildStoryPayload(title, premise, targetTotalWords, planRetryLimit, draftLoopRetryLimit, macroAuthorNotes),
    );
  }

  async function handleSaveSettings() {
    if (!onSaveSettings || locked) return;
    setSaveBusy(true);
    try {
      await onSaveSettings(
        buildStoryPayload(title, premise, targetTotalWords, planRetryLimit, draftLoopRetryLimit, macroAuthorNotes),
      );
    } finally {
      setSaveBusy(false);
    }
  }

  function askImportMode(): ImportMergeMode {
    const replace = window.confirm("匯入模式：按「確定」= 覆蓋目前資料；按「取消」= 合併（已有值優先）");
    return replace ? "replace" : "merge";
  }

  async function handleImportProjectBundleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !onImportProjectBundle) return;
    const mode = askImportMode();
    onBusy?.(true);
    onError?.("");
    try {
      const text = await file.text();
      await onImportProjectBundle(text, mode);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "匯入專案 JSON 失敗");
    } finally {
      onBusy?.(false);
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
        <div className="border-t border-outline-variant/10 pt-4">
          <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
            專案 JSON（故事 + 宏觀規劃）
          </p>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void handleImportProjectBundleFile(e)}
          />
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              className="btn-secondary flex-1 justify-center"
              onClick={onExportProjectBundle}
              disabled={!onExportProjectBundle}
            >
              匯出專案 JSON
            </button>
            <button
              type="button"
              className="btn-secondary flex-1 justify-center"
              onClick={() => importInputRef.current?.click()}
              disabled={!onImportProjectBundle || fieldDisabled}
            >
              匯入專案 JSON
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}
