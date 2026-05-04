import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { ConfirmModal } from "../../components/ConfirmModal";
import type { ImportMergeMode, StoryInput, StoryOutputLanguage } from "../../types";
import { useI18n } from "../../i18n/useI18n";

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
  /** Preview lines for import confirmation modal (paired with `onImportProjectBundle`). */
  getImportBundlePreview?: (jsonText: string) => { storyLine: string; macroLine: string };
  onBusy?: (busy: boolean) => void;
  onError?: (message: string) => void;
};

function hydrateFromStoryInput(input: StoryInput): {
  title: string;
  premise: string;
  targetTotalWords: number;
  branchCountOverride: number | null;
  planRetryLimit: number;
  draftLoopRetryLimit: number;
  macroAuthorNotes: string;
  outputLanguage: StoryOutputLanguage;
} {
  const ol = input.output_language;
  return {
    title: input.title,
    premise: input.premise,
    targetTotalWords: input.target_total_words,
    branchCountOverride: input.branch_count_override ?? null,
    planRetryLimit: input.plan_retry_limit,
    draftLoopRetryLimit: input.draft_loop_retry_limit,
    macroAuthorNotes: input.macro_author_notes ?? "",
    outputLanguage: ol === "en" || ol === "zh-Hans" || ol === "zh-Hant" ? ol : "zh-Hant",
  };
}

function buildStoryPayload(
  title: string,
  premise: string,
  targetTotalWords: number,
  branchCountOverride: number | null,
  planRetryLimit: number,
  draftLoopRetryLimit: number,
  macroAuthorNotes: string,
  outputLanguage: StoryOutputLanguage,
): StoryInput {
  return {
    title,
    premise,
    target_total_words: targetTotalWords,
    branch_count_override: branchCountOverride,
    plan_retry_limit: planRetryLimit,
    draft_loop_retry_limit: draftLoopRetryLimit,
    bible: {},
    macro_author_notes: macroAuthorNotes,
    cast_seed: [],
    output_language: outputLanguage,
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
  getImportBundlePreview,
  onBusy,
  onError,
}: Props) {
  const { locale, t } = useI18n();
  const seedTitle = locale === "en" ? "Mists of the Royal Capital" : "王都疑雲";
  const seedPremise =
    locale === "en"
      ? "A young exiled knight returns to the capital to uncover the truth behind a royal murder."
      : "一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。";
  const seedOutputLanguage: StoryOutputLanguage = locale === "en" ? "en" : locale === "zh-Hans" ? "zh-Hans" : "zh-Hant";
  const [title, setTitle] = useState(seedTitle);
  const [premise, setPremise] = useState(seedPremise);
  const [targetTotalWords, setTargetTotalWords] = useState(100000);
  const [branchCountOverride, setBranchCountOverride] = useState<number | null>(null);
  const [planRetryLimit, setPlanRetryLimit] = useState(3);
  const [draftLoopRetryLimit, setDraftLoopRetryLimit] = useState(3);
  const [macroAuthorNotes, setMacroAuthorNotes] = useState("");
  const [outputLanguage, setOutputLanguage] = useState<StoryOutputLanguage>(seedOutputLanguage);
  const [saveBusy, setSaveBusy] = useState(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const [importModeOpen, setImportModeOpen] = useState(false);
  const [importConfirmOpen, setImportConfirmOpen] = useState(false);
  const importPendingTextRef = useRef<string | null>(null);
  const [importPreview, setImportPreview] = useState<{ mode: ImportMergeMode; storyLine: string; macroLine: string } | null>(
    null,
  );

  useEffect(() => {
    if (initialValues) {
      const h = hydrateFromStoryInput(initialValues);
      setTitle(h.title);
      setPremise(h.premise);
      setTargetTotalWords(h.targetTotalWords);
      setBranchCountOverride(h.branchCountOverride);
      setPlanRetryLimit(h.planRetryLimit);
      setDraftLoopRetryLimit(h.draftLoopRetryLimit);
      setMacroAuthorNotes(h.macroAuthorNotes);
      setOutputLanguage(h.outputLanguage);
    } else {
      setTitle(seedTitle);
      setPremise(seedPremise);
      setTargetTotalWords(100000);
      setBranchCountOverride(null);
      setPlanRetryLimit(3);
      setDraftLoopRetryLimit(3);
      setMacroAuthorNotes("");
      setOutputLanguage(seedOutputLanguage);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate only when resetKey bumps
  }, [resetKey, seedOutputLanguage, seedPremise, seedTitle]);

  useEffect(() => {
    if (locked || !onValuesChange) return;
    onValuesChange(
      buildStoryPayload(
        title,
        premise,
        targetTotalWords,
        branchCountOverride,
        planRetryLimit,
        draftLoopRetryLimit,
        macroAuthorNotes,
        outputLanguage,
      ),
    );
  }, [
    locked,
    onValuesChange,
    title,
    premise,
    targetTotalWords,
    branchCountOverride,
    planRetryLimit,
    draftLoopRetryLimit,
    macroAuthorNotes,
    outputLanguage,
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
      buildStoryPayload(
        title,
        premise,
        targetTotalWords,
        branchCountOverride,
        planRetryLimit,
        draftLoopRetryLimit,
        macroAuthorNotes,
        outputLanguage,
      ),
    );
  }

  async function handleSaveSettings() {
    if (!onSaveSettings || locked) return;
    setSaveBusy(true);
    try {
      await onSaveSettings(
        buildStoryPayload(
          title,
          premise,
          targetTotalWords,
          branchCountOverride,
          planRetryLimit,
          draftLoopRetryLimit,
          macroAuthorNotes,
          outputLanguage,
        ),
      );
    } finally {
      setSaveBusy(false);
    }
  }

  function cancelSetupImportFlow() {
    importPendingTextRef.current = null;
    setImportModeOpen(false);
    setImportConfirmOpen(false);
    setImportPreview(null);
  }

  function openSetupImportConfirm(mode: ImportMergeMode) {
    const text = importPendingTextRef.current;
    if (!text || !getImportBundlePreview) return;
    try {
      const { storyLine, macroLine } = getImportBundlePreview(text);
      setImportPreview({ mode, storyLine, macroLine });
      setImportModeOpen(false);
      setImportConfirmOpen(true);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : t("setup.importFailed"));
      cancelSetupImportFlow();
    }
  }

  async function handleImportProjectBundleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !onImportProjectBundle || !getImportBundlePreview) return;
    onError?.("");
    try {
      const text = await file.text();
      importPendingTextRef.current = text;
      setImportModeOpen(true);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : t("setup.importFailed"));
    }
  }

  async function confirmSetupImportProjectBundle() {
    const text = importPendingTextRef.current;
    const prev = importPreview;
    if (!text || !prev || !onImportProjectBundle) return;
    setImportConfirmOpen(false);
    setImportPreview(null);
    importPendingTextRef.current = null;
    onBusy?.(true);
    onError?.("");
    try {
      await onImportProjectBundle(text, prev.mode);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : t("setup.importFailed"));
    } finally {
      onBusy?.(false);
    }
  }

  return (
    <section className={sectionClassName}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="flex items-center gap-2 font-headline text-lg font-bold text-primary">
          <span className="material-symbols-outlined">tune</span>
          {t("setup.items")}
        </h2>
        {locked ? (
          <span className="rounded-full border border-primary/30 bg-primary/15 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-widest text-primary">
            {t("setup.locked")}
          </span>
        ) : null}
      </div>
      <p className="font-body text-sm text-on-surface-variant">
        {t("setup.worldHint")}
      </p>
      <form className="flex flex-col gap-5" onSubmit={handleSubmit}>
        <div className="space-y-1">
          <label className="auteur-label">{t("setup.title")}</label>
          <input className="auteur-input" value={title} onChange={(e) => setTitle(e.target.value)} disabled={fieldDisabled} readOnly={locked} />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <label className="auteur-label">{t("setup.targetWords")}</label>
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
            <label className="auteur-label">{t("setup.planRetryLimit")}</label>
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
          <div className="space-y-1">
            <label className="auteur-label">
              {locale === "en" ? "Branch Override (optional)" : locale === "zh-Hans" ? "支线数量覆写（可选）" : "支線數量覆寫（可選）"}
            </label>
            <input
              type="number"
              min={0}
              className="auteur-input text-center font-label"
              value={branchCountOverride ?? ""}
              placeholder={locale === "en" ? "auto by word count" : "依字數自動"}
              onChange={(e) => {
                const raw = e.target.value.trim();
                setBranchCountOverride(raw === "" ? null : Number(raw));
              }}
              disabled={fieldDisabled}
              readOnly={locked}
            />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <label className="auteur-label">{t("setup.draftRetryLimit")}</label>
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
          <label className="auteur-label">{t("setup.outputLanguage")}</label>
          <select
            className="auteur-input font-body"
            value={outputLanguage}
            onChange={(e) => setOutputLanguage(e.target.value as StoryOutputLanguage)}
            disabled={fieldDisabled}
            aria-label="Story output language"
          >
            <option value="zh-Hant">{t("lang.zhHant")}</option>
            <option value="zh-Hans">{t("lang.zhHans")}</option>
            <option value="en">{t("lang.en")}</option>
          </select>
          <p className="text-xs text-on-surface-variant">
            {t("setup.outputLanguageHint")}
          </p>
        </div>
        <div className="space-y-1">
          <label className="auteur-label">{t("setup.premise")}</label>
          <textarea
            className="auteur-input min-h-[120px] resize-y font-body leading-relaxed"
            value={premise}
            onChange={(e) => setPremise(e.target.value)}
            rows={4}
            disabled={fieldDisabled}
            readOnly={locked}
          />
        </div>
        <div className="space-y-1 rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <label className="auteur-label">{t("setup.authorNotes")}</label>
            <span className={`font-mono text-xs ${notesWarn ? "text-tertiary" : "text-on-surface-variant"}`}>
              {t("setup.notesSoftCap", undefined, { count: notesLen, max: MACRO_NOTES_SOFT_MAX })}
              {notesWarn ? t("setup.notesSoftCapOverflow") : ""}
            </span>
          </div>
          <textarea
            className="auteur-input min-h-[160px] resize-y font-body text-sm leading-relaxed"
            value={macroAuthorNotes}
            onChange={(e) => setMacroAuthorNotes(e.target.value)}
            rows={6}
            placeholder={t("setup.authorNotesPlaceholder")}
            disabled={fieldDisabled}
            readOnly={locked}
          />
        </div>
        {locked ? null : (
          <div className="flex flex-col gap-3 sm:flex-row">
            {showCreateButton ? (
              <button type="submit" className="btn-primary-gradient flex-1 justify-center" disabled={disabled}>
                <span className="material-symbols-outlined">add_circle</span>
                {t("setup.createStory")}
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
                {t("setup.saveSettings")}
              </button>
            ) : null}
          </div>
        )}
        <div className="border-t border-outline-variant/10 pt-4">
          <p className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">{t("setup.projectFiles")}</p>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void handleImportProjectBundleFile(e)}
          />
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              className="btn-secondary flex-1 justify-center"
              onClick={onExportProjectBundle}
              disabled={!onExportProjectBundle}
            >
              {t("setup.exportProjectJson")}
            </button>
            <button
              type="button"
              className="btn-secondary flex-1 justify-center"
              onClick={() => importInputRef.current?.click()}
              disabled={!onImportProjectBundle || fieldDisabled}
            >
              {t("setup.importProjectJson")}
            </button>
          </div>
        </div>
      </form>
      <ConfirmModal
        mount={typeof document !== "undefined" ? document.body : null}
        open={importModeOpen}
        danger
        title={t("app.confirm.importModeTitle")}
        message={t("app.confirm.importModeBody")}
        cancelLabel={t("common.cancel")}
        secondaryLabel={t("app.confirm.importMerge")}
        onSecondary={() => openSetupImportConfirm("merge")}
        confirmLabel={t("app.confirm.importReplace")}
        onConfirm={() => openSetupImportConfirm("replace")}
        onCancel={cancelSetupImportFlow}
      />
      <ConfirmModal
        mount={typeof document !== "undefined" ? document.body : null}
        open={importConfirmOpen && importPreview !== null}
        title={t("app.confirm.importProjectTitle")}
        message={
          importPreview
            ? t("app.confirm.importProjectBody", undefined, {
                modeLabel:
                  importPreview.mode === "replace" ? t("app.confirm.importReplace") : t("app.confirm.importMerge"),
                storyLine: importPreview.storyLine,
                macroLine: importPreview.macroLine,
              })
            : ""
        }
        confirmLabel={t("app.confirm.importProjectConfirm")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => void confirmSetupImportProjectBundle()}
        onCancel={() => {
          setImportConfirmOpen(false);
          setImportModeOpen(true);
        }}
      />
    </section>
  );
}
