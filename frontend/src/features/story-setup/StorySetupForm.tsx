import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { StoryInput, StoryOutputLanguage } from "../../types";
import { ProjectBundleFileActions } from "./ProjectBundleFileActions";
import { useI18n } from "../../i18n/useI18n";
import {
  MAX_TOTAL_WORDS,
  MIN_TOTAL_WORDS,
  OUTPUT_LANGUAGE_OPTIONS,
  SUBPLOT_TIERS,
  TOTAL_WORDS_STEP,
  autoChapterCount,
  autoVolumeCount,
  clampTotalWords,
  composeNotes,
  createSubplotEntry,
  decomposeNotes,
  getDefaultTotalWords,
  resolveVolumeCount,
  seedDefaultSubplots,
  subplotCountRange,
  suggestNextSubplotVolume,
  totalNotesLength,
  type DecomposedNotes,
  type SubplotEntry,
  type SubplotTier,
  type VolumeGoal,
} from "./setupPhases";

const MACRO_NOTES_SOFT_MAX = 8000;
const MAX_VOLUME_GOALS = 32;

type PhaseIndex = 1 | 2 | 3;

const PHASES: Array<{
  index: PhaseIndex;
  numeral: "I" | "II" | "III";
  nameKey: string;
  kickerKey: string;
}> = [
  { index: 1, numeral: "I", nameKey: "setup.phase1.name", kickerKey: "setup.phase1.kicker" },
  { index: 2, numeral: "II", nameKey: "setup.phase2.name", kickerKey: "setup.phase2.kicker" },
  { index: 3, numeral: "III", nameKey: "setup.phase3.name", kickerKey: "setup.phase3.kicker" },
];

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
  /**
   * When set with unlocked story, render a single "Save & Compile" primary CTA on the final phase.
   * The parent is expected to (a) PATCH the story whenever the snapshot is dirty and (b) trigger
   * macro compile in one click.
   */
  onCompile?: () => void | Promise<void>;
  /** True while parent is running save+compile, so the merged CTA can show a busy state. */
  compileBusy?: boolean;
  /** True when creating a new story (show 建立故事); false when editing existing. */
  showCreateButton?: boolean;
  onExportProjectBundle?: () => void;
  onImportProjectBundle?: (jsonText: string) => Promise<void>;
  /** Preview lines for import confirmation modal (paired with `onImportProjectBundle`). */
  getImportBundlePreview?: (jsonText: string) => { storyLine: string; macroLine: string };
  onBusy?: (busy: boolean) => void;
  onError?: (message: string) => void;
  /** Shown inside the wizard when macro compile exists and no chapter is completed yet. */
  compiledResultsSlot?: ReactNode;
};

type WizardState = {
  title: string;
  premise: string;
  targetTotalWords: number;
  /** Null = use auto-derived count (frontend computes from total words + language). */
  branchCountOverride: number | null;
  planRetryLimit: number;
  draftLoopRetryLimit: number;
  outputLanguage: StoryOutputLanguage;
  parts: DecomposedNotes;
  /** True once the user has explicitly typed in the total words field; gates language-driven default resets. */
  wordsManual: boolean;
};

function clampOutputLanguage(value: unknown): StoryOutputLanguage {
  return value === "en" || value === "zh-Hans" || value === "zh-Hant" ? value : "zh-Hant";
}

function hydrateFromStoryInput(input: StoryInput): WizardState {
  const parts = decomposeNotes(input.macro_author_notes ?? "");
  const language = clampOutputLanguage(input.output_language);
  const branchOverride = input.branch_count_override ?? null;
  return {
    title: input.title,
    premise: input.premise,
    targetTotalWords: input.target_total_words,
    branchCountOverride: branchOverride,
    planRetryLimit: input.plan_retry_limit,
    draftLoopRetryLimit: input.draft_loop_retry_limit,
    outputLanguage: language,
    parts: ensureSubplotSeed(parts, resolveVolumeCount(branchOverride, input.target_total_words, language)),
    wordsManual: true,
  };
}

function buildStoryPayload(state: WizardState): StoryInput {
  // Always send a clamped value to the backend so out-of-range typing during
  // editing can't slip through (even if the user never blurred the input).
  const clampedWords = clampTotalWords(state.targetTotalWords, state.outputLanguage);
  const volumes = resolveVolumeCount(state.branchCountOverride, clampedWords, state.outputLanguage);
  return {
    title: state.title,
    premise: state.premise,
    target_total_words: clampedWords,
    branch_count_override: volumes,
    plan_retry_limit: state.planRetryLimit,
    draft_loop_retry_limit: state.draftLoopRetryLimit,
    bible: {},
    macro_author_notes: composeNotes(state.parts, volumes),
    cast_seed: [],
    output_language: state.outputLanguage,
  };
}

/**
 * When the resolved volume count moves to a new integer, prune per-volume goals
 * to the new range and reseed subplots to the per-tier minimum
 * (per spec: "支線變化成最小數量").
 * Returns `state` unchanged when the count hasn't moved.
 */
function applyVolumeCountSync(state: WizardState, previousVolumes: number): WizardState {
  const nextVolumes = resolveVolumeCount(state.branchCountOverride, state.targetTotalWords, state.outputLanguage);
  if (nextVolumes === previousVolumes) return state;
  return {
    ...state,
    parts: {
      ...state.parts,
      hasStructuredMarkers: true,
      volumeGoals: state.parts.volumeGoals.filter((g) => g.volume >= 1 && g.volume <= nextVolumes),
      subplots: seedDefaultSubplots(nextVolumes),
    },
  };
}

function resolvedVolumesOf(state: WizardState): number {
  return resolveVolumeCount(state.branchCountOverride, state.targetTotalWords, state.outputLanguage);
}

/**
 * Pre-seed empty S/A/B rows when hydrating notes that have never been touched by
 * the wizard (no structured markers). Once the user has saved at least once we
 * respect their data — including an explicitly empty subplot list.
 */
function ensureSubplotSeed(parts: DecomposedNotes, volumeCount: number | null): DecomposedNotes {
  if (parts.hasStructuredMarkers) return parts;
  if (parts.subplots.length > 0) return parts;
  return { ...parts, subplots: seedDefaultSubplots(volumeCount) };
}

function resolveSeedDefaults(locale: "zh-Hant" | "zh-Hans" | "en"): WizardState {
  const seedTitle = locale === "en" ? "Mists of the Royal Capital" : "王都疑雲";
  const seedPremise =
    locale === "en"
      ? "A young exiled knight returns to the capital to uncover the truth behind a royal murder."
      : "一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。";
  const outputLanguage: StoryOutputLanguage =
    locale === "en" ? "en" : locale === "zh-Hans" ? "zh-Hans" : "zh-Hant";
  const targetTotalWords = getDefaultTotalWords(outputLanguage);
  const autoVolumes = autoVolumeCount(targetTotalWords, outputLanguage);
  return {
    title: seedTitle,
    premise: seedPremise,
    targetTotalWords,
    branchCountOverride: null,
    planRetryLimit: 3,
    draftLoopRetryLimit: 3,
    outputLanguage,
    parts: {
      world: "",
      characters: "",
      style: "",
      volumeGoals: [],
      subplots: seedDefaultSubplots(autoVolumes),
      hasStructuredMarkers: false,
    },
    wordsManual: false,
  };
}

export function StorySetupForm({
  onSubmit,
  disabled,
  locked = false,
  initialValues,
  resetKey,
  onValuesChange,
  onCompile,
  compileBusy = false,
  showCreateButton = true,
  onExportProjectBundle,
  onImportProjectBundle,
  getImportBundlePreview,
  onBusy,
  onError,
  compiledResultsSlot,
}: Props) {
  const { locale, t } = useI18n();
  const seedDefaults = useMemo(() => resolveSeedDefaults(locale), [locale]);
  const [state, setState] = useState<WizardState>(seedDefaults);
  const [phase, setPhase] = useState<PhaseIndex>(1);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // Set right before parent-initiated re-hydration to keep the user on phase 3
  // after the first "Create & generate" click (instead of bouncing back to 1).
  const justSubmittedRef = useRef(false);
  // The resolved volume count at the last "committed" sync point — used so
  // mid-typing doesn't reseed subplots on every keystroke. We only reseed when
  // the resolved count crosses a new integer boundary on blur.
  const lastSyncedVolumesRef = useRef<number>(resolvedVolumesOf(seedDefaults));

  useEffect(() => {
    const next = initialValues ? hydrateFromStoryInput(initialValues) : seedDefaults;
    setState(next);
    lastSyncedVolumesRef.current = resolvedVolumesOf(next);
    if (justSubmittedRef.current) {
      justSubmittedRef.current = false;
    } else {
      setPhase(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate only when resetKey bumps
  }, [resetKey, seedDefaults]);

  useEffect(() => {
    if (locked || !onValuesChange) return;
    onValuesChange(buildStoryPayload(state));
  }, [locked, onValuesChange, state]);

  const fieldDisabled = Boolean(disabled || locked);

  const notesLen = useMemo(
    () => totalNotesLength(state.parts, state.branchCountOverride),
    [state.parts, state.branchCountOverride],
  );
  const notesWarn = notesLen > MACRO_NOTES_SOFT_MAX;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (locked) return;
    // Tell the resetKey-driven hydrate effect to keep the current phase across
    // this submit — without this, the user gets bounced back to phase 1 right
    // after pressing "Create & generate". Cleared on a macrotask so the effect
    // (which runs during commit) has already consumed it before it flips back.
    justSubmittedRef.current = true;
    try {
      await onSubmit(buildStoryPayload(state));
    } finally {
      setTimeout(() => {
        justSubmittedRef.current = false;
      }, 0);
    }
  }

  async function handleCompileClick() {
    if (!onCompile || locked) return;
    await onCompile();
  }

  function patchState<K extends keyof WizardState>(key: K, value: WizardState[K]) {
    setState((prev) => ({ ...prev, [key]: value }));
  }

  function handleTargetWordsChange(value: number) {
    // Cheap state update on every keystroke — no clamp / no reseed yet so the
    // user can type freely. Clamping + downstream sync happens on blur.
    const next = Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
    setState((prev) => ({ ...prev, targetTotalWords: next, wordsManual: true }));
  }

  /** Called on blur (or after a step) — clamps to range and resyncs volumes/subplots. */
  function handleTargetWordsCommit() {
    setState((prev) => {
      const clamped = clampTotalWords(prev.targetTotalWords, prev.outputLanguage);
      const pinned = { ...prev, targetTotalWords: clamped };
      const synced = applyVolumeCountSync(pinned, lastSyncedVolumesRef.current);
      lastSyncedVolumesRef.current = resolvedVolumesOf(synced);
      return synced;
    });
  }

  function handleLanguageChange(language: StoryOutputLanguage) {
    setState((prev) => {
      // Reset to the language default only when the user hasn't pinned a manual
      // word count; either way, keep the value within [MIN, MAX].
      const nextWords = prev.wordsManual
        ? clampTotalWords(prev.targetTotalWords, language)
        : getDefaultTotalWords(language);
      const pinned = { ...prev, outputLanguage: language, targetTotalWords: nextWords };
      const synced = applyVolumeCountSync(pinned, lastSyncedVolumesRef.current);
      lastSyncedVolumesRef.current = resolvedVolumesOf(synced);
      return synced;
    });
  }

  function patchParts(patch: Partial<DecomposedNotes>) {
    setState((prev) => ({ ...prev, parts: { ...prev.parts, ...patch } }));
  }

  function patchVolumeGoals(updater: (current: VolumeGoal[]) => VolumeGoal[]) {
    setState((prev) => ({
      ...prev,
      parts: {
        ...prev.parts,
        hasStructuredMarkers: true,
        volumeGoals: updater(prev.parts.volumeGoals),
      },
    }));
  }

  function setVolumeGoal(volume: number, goal: string) {
    patchVolumeGoals((current) => {
      const next = current.slice();
      const idx = next.findIndex((g) => g.volume === volume);
      if (idx === -1) {
        next.push({ volume, goal });
      } else {
        next[idx] = { volume, goal };
      }
      return next;
    });
  }

  function patchSubplots(updater: (current: SubplotEntry[]) => SubplotEntry[]) {
    setState((prev) => ({
      ...prev,
      parts: {
        ...prev.parts,
        hasStructuredMarkers: true,
        subplots: updater(prev.parts.subplots),
      },
    }));
  }

  function addSubplotEntry(tier: SubplotTier) {
    setState((prev) => {
      const resolvedVolumes = resolvedVolumesOf(prev);
      const nextVolume = suggestNextSubplotVolume(tier, resolvedVolumes, prev.parts.subplots);
      const entry = createSubplotEntry(tier, { volume: nextVolume });
      return {
        ...prev,
        parts: {
          ...prev.parts,
          hasStructuredMarkers: true,
          subplots: [...prev.parts.subplots, entry],
        },
      };
    });
  }

  function updateSubplotEntry(id: string, patch: Partial<Omit<SubplotEntry, "id" | "tier">>) {
    patchSubplots((current) =>
      current.map((e) => {
        if (e.id !== id) return e;
        // Volume is meaningless for S_TIER; silently coerce attempts to set one.
        const nextVolume =
          "volume" in patch
            ? e.tier === "S"
              ? null
              : patch.volume == null
                ? null
                : Math.max(1, Math.floor(patch.volume))
            : e.volume;
        return { ...e, ...patch, volume: nextVolume };
      }),
    );
  }

  function deleteSubplotEntry(id: string) {
    patchSubplots((current) => current.filter((e) => e.id !== id));
  }

  function handleVolumeCountChange(raw: string) {
    const trimmed = raw.trim();
    const next = trimmed === "" ? null : Math.max(0, Math.min(Number(trimmed), MAX_VOLUME_GOALS));
    setState((prev) => ({
      ...prev,
      branchCountOverride: Number.isFinite(next as number) || next === null ? next : prev.branchCountOverride,
    }));
  }

  /** Commit (blur) for the volumes input — resyncs goals + subplots to the new count. */
  function handleVolumeCountCommit() {
    setState((prev) => {
      const synced = applyVolumeCountSync(prev, lastSyncedVolumesRef.current);
      lastSyncedVolumesRef.current = resolvedVolumesOf(synced);
      return synced;
    });
  }

  const sectionClassName = locked
    ? "relative overflow-hidden rounded-3xl border-2 border-primary/30 bg-primary/5 p-6 shadow-glow md:p-10"
    : "relative overflow-hidden rounded-3xl border border-outline-variant/15 bg-surface-container-low/85 p-6 shadow-glow md:p-10";

  const currentPhase = PHASES.find((p) => p.index === phase) ?? PHASES[0];

  return (
    <section className={sectionClassName}>
      <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-primary/10 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute -bottom-24 -left-24 h-64 w-64 rounded-full bg-secondary/10 blur-3xl" aria-hidden />

      <div className="relative flex flex-wrap items-center gap-3">
        <h2 className="flex items-center gap-2 font-headline text-lg font-bold text-primary">
          <span className="material-symbols-outlined">menu_book</span>
          {t("setup.items")}
        </h2>
        {locked ? (
          <span className="rounded-full border border-primary/30 bg-primary/15 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-widest text-primary">
            {t("setup.locked")}
          </span>
        ) : null}
      </div>

      <SetupStepper
        phases={PHASES}
        currentPhase={phase}
        onSelect={(next) => setPhase(next)}
        labelFor={(p) => t(p.nameKey)}
        kickerFor={(p) => t(p.kickerKey)}
        gotoTitleFor={(p) => t("setup.phaseGoTo", undefined, { n: p.index, name: t(p.nameKey) })}
      />

      <form className="relative mt-8 flex flex-col gap-6" onSubmit={handleSubmit}>
        <header className="setup-phase-enter" key={`hdr-${phase}`}>
          <span className="block font-label text-[11px] font-semibold uppercase tracking-[0.32em] text-secondary">
            {t(currentPhase.kickerKey)}
          </span>
          <h3 className="mt-1 font-headline text-2xl font-black tracking-tight text-on-surface md:text-3xl">
            {t(`setup.phase${currentPhase.index}.title`)}
          </h3>
          <p className="mt-2 max-w-2xl font-body text-base italic leading-relaxed text-on-surface-variant">
            {t(`setup.phase${currentPhase.index}.subtitle`)}
          </p>
        </header>

        <div className="setup-phase-enter min-w-0" key={`body-${phase}`}>
          {phase === 1 ? (
            <PhaseOnePanel
              title={state.title}
              premise={state.premise}
              outputLanguage={state.outputLanguage}
              fieldDisabled={fieldDisabled}
              locked={locked}
              onTitleChange={(v) => patchState("title", v)}
              onPremiseChange={(v) => patchState("premise", v)}
              onLanguageChange={handleLanguageChange}
              t={t}
            />
          ) : null}
          {phase === 2 ? (
            <PhaseTwoPanel
              parts={state.parts}
              fieldDisabled={fieldDisabled}
              locked={locked}
              notesLen={notesLen}
              notesWarn={notesWarn}
              onWorldChange={(v) => patchParts({ world: v })}
              onCharactersChange={(v) => patchParts({ characters: v })}
              onStyleChange={(v) => patchParts({ style: v })}
              t={t}
            />
          ) : null}
          {phase === 3 ? (
            <PhaseThreePanel
              state={state}
              fieldDisabled={fieldDisabled}
              locked={locked}
              advancedOpen={advancedOpen}
              onTargetWordsChange={handleTargetWordsChange}
              onTargetWordsCommit={handleTargetWordsCommit}
              onVolumesChange={handleVolumeCountChange}
              onVolumesCommit={handleVolumeCountCommit}
              onPlanRetryChange={(v) => patchState("planRetryLimit", v)}
              onDraftRetryChange={(v) => patchState("draftLoopRetryLimit", v)}
              onVolumeGoalChange={setVolumeGoal}
              onVolumeGoalsReset={() => patchVolumeGoals(() => [])}
              onSubplotAdd={addSubplotEntry}
              onSubplotChange={updateSubplotEntry}
              onSubplotDelete={deleteSubplotEntry}
              onToggleAdvanced={() => setAdvancedOpen((v) => !v)}
              t={t}
            />
          ) : null}
        </div>

        {compiledResultsSlot ? (
          <div className="setup-phase-enter border-t border-outline-variant/12 pt-6">
            <div className="rounded-2xl border border-secondary/20 bg-gradient-to-br from-secondary/6 via-surface-container/40 to-surface-container-low/80 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] md:p-5">
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">
                  {t("app.setup.compiledResultsKicker")}
                </p>
                <span className="font-body text-[11px] italic text-on-surface-variant/80">
                  {t("setup.compiledResultsInFormHint")}
                </span>
              </div>
              {compiledResultsSlot}
            </div>
          </div>
        ) : null}

        <WizardFooter
          phase={phase}
          locked={locked}
          showCreateButton={showCreateButton}
          onCompile={onCompile}
          compileBusy={compileBusy}
          disabled={Boolean(disabled)}
          onBack={() => setPhase((p) => (p > 1 ? ((p - 1) as PhaseIndex) : p))}
          onNext={() => setPhase((p) => (p < 3 ? ((p + 1) as PhaseIndex) : p))}
          onCompileClick={() => void handleCompileClick()}
          t={t}
        />
      </form>

      <ProjectBundleFileActions
        className="relative mt-8 border-t border-outline-variant/10 pt-6"
        onExportProjectBundle={onExportProjectBundle}
        onImportProjectBundle={onImportProjectBundle}
        getImportBundlePreview={getImportBundlePreview}
        disabled={fieldDisabled}
        onBusy={onBusy}
        onError={onError}
      />
    </section>
  );
}

type TFn = ReturnType<typeof useI18n>["t"];

type StepperProps = {
  phases: typeof PHASES;
  currentPhase: PhaseIndex;
  onSelect: (phase: PhaseIndex) => void;
  labelFor: (phase: (typeof PHASES)[number]) => string;
  kickerFor: (phase: (typeof PHASES)[number]) => string;
  gotoTitleFor: (phase: (typeof PHASES)[number]) => string;
};

function SetupStepper({ phases, currentPhase, onSelect, labelFor, kickerFor, gotoTitleFor }: StepperProps) {
  return (
    <nav aria-label="Setup phases" className="relative mt-8">
      <div className="setup-stepper-rule absolute left-6 right-6 top-[1.65rem] h-px opacity-60" aria-hidden />
      <ol className="relative grid grid-cols-1 gap-3 md:grid-cols-3">
        {phases.map((p) => {
          const active = p.index === currentPhase;
          const done = p.index < currentPhase;
          const numeralRing = active
            ? "border-primary bg-primary text-on-primary shadow-primarySoft"
            : done
              ? "border-secondary/60 bg-secondary/15 text-secondary"
              : "border-outline-variant/35 bg-surface-container-highest/60 text-on-surface-variant";
          const labelTint = active
            ? "text-on-surface"
            : done
              ? "text-on-surface/85"
              : "text-on-surface-variant/75";
          return (
            <li key={p.index}>
              <button
                type="button"
                title={gotoTitleFor(p)}
                onClick={() => onSelect(p.index)}
                aria-current={active ? "step" : undefined}
                className={`group flex w-full items-center gap-4 rounded-2xl border px-4 py-3 text-left transition-[transform,background-color,border-color,box-shadow] ${
                  active
                    ? "border-primary/40 bg-surface-container/80 shadow-glow"
                    : "border-outline-variant/15 bg-surface-container-low/40 hover:-translate-y-[1px] hover:border-outline-variant/30 hover:bg-surface-container/70"
                }`}
              >
                <span
                  className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full border font-headline text-base font-black tracking-wider transition-colors ${numeralRing}`}
                >
                  {p.numeral}
                </span>
                <span className="min-w-0 flex-1">
                  <span className={`block truncate font-label text-[10px] font-semibold uppercase tracking-[0.28em] ${active ? "text-secondary" : "text-on-surface-variant/70"}`}>
                    {kickerFor(p)}
                  </span>
                  <span className={`mt-0.5 block truncate font-headline text-sm font-bold tracking-tight ${labelTint}`}>
                    {labelFor(p)}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

type PhaseOneProps = {
  title: string;
  premise: string;
  outputLanguage: StoryOutputLanguage;
  fieldDisabled: boolean;
  locked: boolean;
  onTitleChange: (v: string) => void;
  onPremiseChange: (v: string) => void;
  onLanguageChange: (v: StoryOutputLanguage) => void;
  t: TFn;
};

function PhaseOnePanel({
  title,
  premise,
  outputLanguage,
  fieldDisabled,
  locked,
  onTitleChange,
  onPremiseChange,
  onLanguageChange,
  t,
}: PhaseOneProps) {
  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
      <div className="space-y-2 md:col-span-2">
        <label className="auteur-label">{t("setup.phase1.titleLabel")}</label>
        <input
          className="auteur-input text-lg"
          value={title}
          placeholder={t("setup.phase1.titlePlaceholder")}
          onChange={(e) => onTitleChange(e.target.value)}
          disabled={fieldDisabled}
          readOnly={locked}
        />
      </div>
      <div className="space-y-2">
        <label className="auteur-label">{t("setup.phase1.languageLabel")}</label>
        <select
          className="auteur-input font-body"
          value={outputLanguage}
          onChange={(e) => onLanguageChange(e.target.value as StoryOutputLanguage)}
          disabled={fieldDisabled}
          aria-label={t("setup.phase1.languageLabel")}
        >
          {OUTPUT_LANGUAGE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
        <p className="font-body text-xs text-on-surface-variant">{t("setup.outputLanguageHint")}</p>
      </div>
      <div className="space-y-2 md:row-span-2 md:col-span-2 md:col-start-1 md:row-start-3">
        <label className="auteur-label">{t("setup.phase1.loglineLabel")}</label>
        <textarea
          className="auteur-input min-h-[140px] resize-y font-body text-base leading-relaxed"
          value={premise}
          rows={5}
          placeholder={t("setup.phase1.loglinePlaceholder")}
          onChange={(e) => onPremiseChange(e.target.value)}
          disabled={fieldDisabled}
          readOnly={locked}
        />
        <p className="font-body text-xs text-on-surface-variant">{t("setup.phase1.loglineHint")}</p>
      </div>
    </div>
  );
}

type PhaseTwoProps = {
  parts: DecomposedNotes;
  fieldDisabled: boolean;
  locked: boolean;
  notesLen: number;
  notesWarn: boolean;
  onWorldChange: (v: string) => void;
  onCharactersChange: (v: string) => void;
  onStyleChange: (v: string) => void;
  t: TFn;
};

function PhaseTwoPanel({
  parts,
  fieldDisabled,
  locked,
  notesLen,
  notesWarn,
  onWorldChange,
  onCharactersChange,
  onStyleChange,
  t,
}: PhaseTwoProps) {
  return (
    <div className="flex flex-col gap-5">
      <SectionTextarea
        label={t("setup.phase2.worldLabel")}
        hint={t("setup.phase2.worldHint")}
        placeholder={t("setup.phase2.worldPlaceholder")}
        value={parts.world}
        onChange={onWorldChange}
        disabled={fieldDisabled}
        readOnly={locked}
        rows={6}
        accent="primary"
      />
      <SectionTextarea
        label={t("setup.phase2.charactersLabel")}
        hint={t("setup.phase2.charactersHint")}
        placeholder={t("setup.phase2.charactersPlaceholder")}
        value={parts.characters}
        onChange={onCharactersChange}
        disabled={fieldDisabled}
        readOnly={locked}
        rows={6}
        accent="secondary"
      />
      <SectionTextarea
        label={t("setup.phase2.styleLabel")}
        hint={t("setup.phase2.styleHint")}
        placeholder={t("setup.phase2.stylePlaceholder")}
        value={parts.style}
        onChange={onStyleChange}
        disabled={fieldDisabled}
        readOnly={locked}
        rows={5}
        accent="tertiary"
      />
      <p className={`text-right font-mono text-xs ${notesWarn ? "text-tertiary" : "text-on-surface-variant"}`}>
        {t("setup.notesSoftCap", undefined, { count: notesLen, max: MACRO_NOTES_SOFT_MAX })}
        {notesWarn ? t("setup.notesSoftCapOverflow") : ""}
      </p>
    </div>
  );
}

type SectionTextareaProps = {
  label: string;
  hint: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  readOnly: boolean;
  rows: number;
  accent: "primary" | "secondary" | "tertiary";
};

const ACCENT_BORDER: Record<SectionTextareaProps["accent"], string> = {
  primary: "border-l-2 border-primary/45",
  secondary: "border-l-2 border-secondary/50",
  tertiary: "border-l-2 border-tertiary/45",
};

const ACCENT_LABEL: Record<SectionTextareaProps["accent"], string> = {
  primary: "text-primary",
  secondary: "text-secondary",
  tertiary: "text-tertiary",
};

function SectionTextarea({ label, hint, placeholder, value, onChange, disabled, readOnly, rows, accent }: SectionTextareaProps) {
  return (
    <div className={`rounded-xl bg-surface-container-highest/30 p-4 ${ACCENT_BORDER[accent]}`}>
      <div className="mb-1 flex flex-wrap items-baseline gap-3">
        <label className={`font-label text-[11px] font-bold uppercase tracking-[0.25em] ${ACCENT_LABEL[accent]}`}>{label}</label>
        <span className="font-body text-xs italic text-on-surface-variant/70">{hint}</span>
      </div>
      <textarea
        className="auteur-input min-h-[140px] resize-y bg-surface-container-lowest/70 font-body text-sm leading-relaxed"
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        readOnly={readOnly}
      />
    </div>
  );
}

type PhaseThreeProps = {
  state: WizardState;
  fieldDisabled: boolean;
  locked: boolean;
  advancedOpen: boolean;
  onTargetWordsChange: (v: number) => void;
  onTargetWordsCommit: () => void;
  onVolumesChange: (raw: string) => void;
  onVolumesCommit: () => void;
  onPlanRetryChange: (v: number) => void;
  onDraftRetryChange: (v: number) => void;
  onVolumeGoalChange: (volume: number, goal: string) => void;
  onVolumeGoalsReset: () => void;
  onSubplotAdd: (tier: SubplotTier) => void;
  onSubplotChange: (id: string, patch: Partial<Omit<SubplotEntry, "id" | "tier">>) => void;
  onSubplotDelete: (id: string) => void;
  onToggleAdvanced: () => void;
  t: TFn;
};

function PhaseThreePanel({
  state,
  fieldDisabled,
  locked,
  advancedOpen,
  onTargetWordsChange,
  onTargetWordsCommit,
  onVolumesChange,
  onVolumesCommit,
  onPlanRetryChange,
  onDraftRetryChange,
  onVolumeGoalChange,
  onVolumeGoalsReset,
  onSubplotAdd,
  onSubplotChange,
  onSubplotDelete,
  onToggleAdvanced,
  t,
}: PhaseThreeProps) {
  const resolvedVolumes = resolveVolumeCount(state.branchCountOverride, state.targetTotalWords, state.outputLanguage);
  const isVolumesAuto = state.branchCountOverride == null;
  const perVolumeRows = Math.max(0, Math.min(resolvedVolumes, MAX_VOLUME_GOALS));
  const estimatedChapters = autoChapterCount(state.targetTotalWords, state.outputLanguage);
  const wordsOutOfRange =
    state.targetTotalWords < MIN_TOTAL_WORDS || state.targetTotalWords > MAX_TOTAL_WORDS;
  const volumeGoals = state.parts.volumeGoals;
  const goalsLookup = useMemo(() => {
    const map = new Map<number, string>();
    for (const g of volumeGoals) map.set(g.volume, g.goal);
    return map;
  }, [volumeGoals]);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <div className="space-y-2">
          <label className="auteur-label">{t("setup.phase3.targetWordsLabel")}</label>
          <input
            type="number"
            min={MIN_TOTAL_WORDS}
            max={MAX_TOTAL_WORDS}
            step={TOTAL_WORDS_STEP}
            inputMode="numeric"
            className="auteur-input text-center font-label"
            value={state.targetTotalWords}
            onChange={(e) => onTargetWordsChange(Number(e.target.value))}
            onBlur={onTargetWordsCommit}
            disabled={fieldDisabled}
            readOnly={locked}
            aria-invalid={wordsOutOfRange}
          />
          <p className={`font-body text-xs ${wordsOutOfRange ? "text-warning" : "text-on-surface-variant"}`}>
            {t("setup.phase3.targetWordsRangeHint", undefined, {
              min: MIN_TOTAL_WORDS.toLocaleString(),
              max: MAX_TOTAL_WORDS.toLocaleString(),
            })}
          </p>
        </div>
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <label className="auteur-label">{t("setup.phase3.volumesLabel")}</label>
            {isVolumesAuto && !locked ? (
              <span className="font-label text-[10px] font-semibold uppercase tracking-[0.22em] text-secondary">
                {t("setup.phase3.volumesAutoBadge")}
              </span>
            ) : null}
          </div>
          <input
            type="number"
            min={1}
            max={MAX_VOLUME_GOALS}
            className="auteur-input text-center font-label"
            value={resolvedVolumes}
            onChange={(e) => onVolumesChange(e.target.value)}
            onBlur={onVolumesCommit}
            disabled={fieldDisabled}
            readOnly={locked}
          />
          <p className="flex flex-wrap items-baseline justify-between gap-2 font-body text-xs text-on-surface-variant">
            <span>{t("setup.phase3.volumesHint")}</span>
            <span className="font-mono text-[11px] text-secondary">
              {t("setup.phase3.volumesEstimate", undefined, { volumes: resolvedVolumes, chapters: estimatedChapters })}
            </span>
          </p>
        </div>
      </div>

      <VolumeGoalsPanel
        rows={perVolumeRows}
        goalsLookup={goalsLookup}
        fieldDisabled={fieldDisabled}
        locked={locked}
        onChange={onVolumeGoalChange}
        onReset={onVolumeGoalsReset}
        t={t}
      />

      <SubplotsPanel
        subplots={state.parts.subplots}
        volumeCount={resolvedVolumes}
        fieldDisabled={fieldDisabled}
        locked={locked}
        onAdd={onSubplotAdd}
        onChange={onSubplotChange}
        onDelete={onSubplotDelete}
        t={t}
      />

      <div className="rounded-2xl border border-outline-variant/10 bg-surface-container-low/50 p-3">
        <button
          type="button"
          onClick={onToggleAdvanced}
          className="flex w-full items-center justify-between gap-3 px-2 py-1 text-left font-label text-[11px] font-bold uppercase tracking-[0.22em] text-on-surface-variant hover:text-on-surface"
          aria-expanded={advancedOpen}
        >
          <span>{advancedOpen ? t("setup.phase3.advancedClose") : t("setup.phase3.advancedToggle")}</span>
          <span className={`material-symbols-outlined text-base transition-transform ${advancedOpen ? "rotate-180" : ""}`}>
            expand_more
          </span>
        </button>
        {advancedOpen ? (
          <div className="setup-phase-enter mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-1">
              <label className="auteur-label">{t("setup.planRetryLimit")}</label>
              <input
                type="number"
                min={0}
                max={20}
                className="auteur-input text-center font-label"
                value={state.planRetryLimit}
                onChange={(e) => onPlanRetryChange(Number(e.target.value))}
                disabled={fieldDisabled}
                readOnly={locked}
              />
            </div>
            <div className="space-y-1">
              <label className="auteur-label">{t("setup.draftRetryLimit")}</label>
              <input
                type="number"
                min={0}
                max={20}
                className="auteur-input text-center font-label"
                value={state.draftLoopRetryLimit}
                onChange={(e) => onDraftRetryChange(Number(e.target.value))}
                disabled={fieldDisabled}
                readOnly={locked}
              />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

type VolumeGoalsPanelProps = {
  rows: number;
  goalsLookup: Map<number, string>;
  fieldDisabled: boolean;
  locked: boolean;
  onChange: (volume: number, goal: string) => void;
  onReset: () => void;
  t: TFn;
};

function VolumeGoalsPanel({ rows, goalsLookup, fieldDisabled, locked, onChange, onReset, t }: VolumeGoalsPanelProps) {
  const hasAny = Array.from(goalsLookup.values()).some((v) => v.trim() !== "");
  return (
    <details className="group rounded-2xl border border-outline-variant/15 bg-surface-container-highest/25 p-4 open:bg-surface-container-highest/35">
      <summary className="flex cursor-pointer items-center justify-between gap-3 font-label text-[11px] font-bold uppercase tracking-[0.22em] text-secondary">
        <span className="flex flex-wrap items-center gap-2">
          <span>{t("setup.phase3.volumeGoalsTitle")}</span>
          <AiFreeHintChip text={t("setup.phase3.aiFreeHint")} />
        </span>
        <span className="material-symbols-outlined text-base text-on-surface-variant transition-transform group-open:rotate-180">
          expand_more
        </span>
      </summary>
      <p className="mt-2 font-body text-xs italic text-on-surface-variant/80">{t("setup.phase3.volumeGoalsHint")}</p>
      {rows === 0 ? (
        <p className="mt-3 rounded-lg border border-outline-variant/20 bg-surface-container-low/70 px-3 py-2 font-body text-xs text-on-surface-variant">
          {t("setup.phase3.volumeGoalsNeedsCount")}
        </p>
      ) : (
        <>
          <ol className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            {Array.from({ length: rows }).map((_, idx) => {
              const vol = idx + 1;
              return (
                <li key={vol} className="rounded-xl border border-outline-variant/15 bg-surface-container-lowest/70 p-3">
                  <span className="font-label text-[10px] font-bold uppercase tracking-[0.22em] text-secondary">
                    {t("setup.phase3.volumeGoalsRow", undefined, { n: vol })}
                  </span>
                  <textarea
                    className="auteur-input mt-1 min-h-[88px] resize-y bg-transparent font-body text-sm leading-relaxed"
                    rows={3}
                    value={goalsLookup.get(vol) ?? ""}
                    placeholder={t("setup.phase3.volumeGoalsPlaceholder")}
                    onChange={(e) => onChange(vol, e.target.value)}
                    disabled={fieldDisabled}
                    readOnly={locked}
                  />
                </li>
              );
            })}
          </ol>
          {!locked ? (
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={onReset}
                disabled={fieldDisabled || !hasAny}
                className="font-label text-[10px] font-bold uppercase tracking-[0.22em] text-on-surface-variant hover:text-on-surface disabled:opacity-40"
              >
                {t("setup.phase3.volumeGoalsReset")}
              </button>
            </div>
          ) : null}
        </>
      )}
    </details>
  );
}

type SubplotsPanelProps = {
  subplots: SubplotEntry[];
  volumeCount: number | null;
  fieldDisabled: boolean;
  locked: boolean;
  onAdd: (tier: SubplotTier) => void;
  onChange: (id: string, patch: Partial<Omit<SubplotEntry, "id" | "tier">>) => void;
  onDelete: (id: string) => void;
  t: TFn;
};

const SUBPLOT_TIER_LABEL_KEY: Record<SubplotTier, string> = {
  S: "setup.phase3.subplotS",
  A: "setup.phase3.subplotA",
  B: "setup.phase3.subplotB",
};

const SUBPLOT_TIER_DESC_KEY: Record<SubplotTier, string> = {
  S: "setup.phase3.subplotSDesc",
  A: "setup.phase3.subplotADesc",
  B: "setup.phase3.subplotBDesc",
};

const SUBPLOT_TIER_ACCENT: Record<SubplotTier, string> = {
  S: "from-primary/70 to-primary/30 text-on-primary",
  A: "from-secondary/70 to-secondary/30 text-on-secondary",
  B: "from-tertiary/70 to-tertiary/30 text-on-tertiary",
};

function SubplotsPanel({ subplots, volumeCount, fieldDisabled, locked, onAdd, onChange, onDelete, t }: SubplotsPanelProps) {
  return (
    <details className="group rounded-2xl border border-outline-variant/15 bg-surface-container-highest/25 p-4 open:bg-surface-container-highest/35">
      <summary className="flex cursor-pointer items-center justify-between gap-3 font-label text-[11px] font-bold uppercase tracking-[0.22em] text-secondary">
        <span className="flex flex-wrap items-center gap-2">
          <span>{t("setup.phase3.subplotTitle")}</span>
          <AiFreeHintChip text={t("setup.phase3.aiFreeHint")} />
        </span>
        <span className="material-symbols-outlined text-base text-on-surface-variant transition-transform group-open:rotate-180">
          expand_more
        </span>
      </summary>
      <p className="mt-2 font-body text-xs italic text-on-surface-variant/80">{t("setup.phase3.subplotHint")}</p>
      <p className="mt-2 inline-flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/8 px-3 py-2 font-body text-xs leading-relaxed text-on-surface">
        <span className="material-symbols-outlined text-[16px] text-warning">shield</span>
        <span>{t("setup.phase3.subplotQuotaNotice")}</span>
      </p>
      <div className="mt-4 flex flex-col gap-4">
        {SUBPLOT_TIERS.map((tier) => (
          <SubplotTierGroup
            key={tier}
            tier={tier}
            entries={subplots.filter((s) => s.tier === tier)}
            range={subplotCountRange(tier, volumeCount)}
            volumeCount={Math.max(1, volumeCount ?? 1)}
            fieldDisabled={fieldDisabled}
            locked={locked}
            onAdd={onAdd}
            onChange={onChange}
            onDelete={onDelete}
            t={t}
          />
        ))}
      </div>
    </details>
  );
}

function AiFreeHintChip({ text }: { text: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-tertiary/40 bg-tertiary/10 px-2 py-0.5 font-label text-[9px] font-semibold uppercase tracking-[0.22em] text-tertiary"
      title={text}
    >
      <span className="material-symbols-outlined text-[12px]">auto_awesome</span>
      {text}
    </span>
  );
}

type SubplotTierGroupProps = {
  tier: SubplotTier;
  entries: SubplotEntry[];
  range: { min: number; max: number };
  volumeCount: number;
  fieldDisabled: boolean;
  locked: boolean;
  onAdd: (tier: SubplotTier) => void;
  onChange: (id: string, patch: Partial<Omit<SubplotEntry, "id" | "tier">>) => void;
  onDelete: (id: string) => void;
  t: TFn;
};

function SubplotTierGroup({
  tier,
  entries,
  range,
  volumeCount,
  fieldDisabled,
  locked,
  onAdd,
  onChange,
  onDelete,
  t,
}: SubplotTierGroupProps) {
  const tierLabel = t(SUBPLOT_TIER_LABEL_KEY[tier]);
  const tierDesc = t(SUBPLOT_TIER_DESC_KEY[tier]);
  const accent = SUBPLOT_TIER_ACCENT[tier];
  const underTarget = entries.length < range.min;
  const overTarget = entries.length > range.max;
  return (
    <section className="rounded-xl border border-outline-variant/15 bg-surface-container-lowest/70 p-3">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${accent} font-headline text-sm font-black tracking-wider shadow`}>
            {tier}
          </span>
          <div className="min-w-0">
            <h4 className="font-headline text-sm font-bold tracking-tight text-on-surface">{tierLabel}</h4>
            <p className="mt-0.5 font-body text-xs leading-relaxed text-on-surface-variant/85">{tierDesc}</p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 font-label text-[10px] uppercase tracking-[0.22em]">
          <span className="text-on-surface-variant/70">{t("setup.phase3.subplotSuggested", undefined, { min: range.min, max: range.max })}</span>
          <span className={`${underTarget ? "text-warning" : overTarget ? "text-tertiary" : "text-secondary"}`}>
            {t("setup.phase3.subplotCurrent", undefined, { n: entries.length })}
          </span>
          <span
            className="font-mono text-[9px] normal-case tracking-normal text-on-surface-variant/55"
            title={t("setup.phase3.subplotQuotaTooltip", undefined, { min: range.min })}
          >
            {t("setup.phase3.subplotQuotaNote", undefined, { min: range.min })}
          </span>
        </div>
      </header>

      {entries.length === 0 ? (
        <p className="mt-3 rounded-lg border border-dashed border-outline-variant/30 bg-surface-container-low/40 px-3 py-2 font-body text-xs text-on-surface-variant">
          {t("setup.phase3.subplotEmpty", undefined, { tier })}
        </p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {entries.map((entry) => (
            <SubplotRow
              key={entry.id}
              entry={entry}
              volumeCount={volumeCount}
              fieldDisabled={fieldDisabled}
              locked={locked}
              onChange={onChange}
              onDelete={onDelete}
              t={t}
            />
          ))}
        </ul>
      )}

      {!locked ? (
        <div className="mt-3 flex justify-start">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-full border border-outline-variant/30 bg-surface-container-high/60 px-3 py-1.5 font-label text-[10px] font-bold uppercase tracking-[0.22em] text-on-surface transition-colors hover:bg-surface-bright/40 disabled:opacity-40"
            onClick={() => onAdd(tier)}
            disabled={fieldDisabled}
          >
            <span className="material-symbols-outlined text-base">add</span>
            {t("setup.phase3.subplotAdd", undefined, { tier })}
          </button>
        </div>
      ) : null}
    </section>
  );
}

type SubplotRowProps = {
  entry: SubplotEntry;
  volumeCount: number;
  fieldDisabled: boolean;
  locked: boolean;
  onChange: (id: string, patch: Partial<Omit<SubplotEntry, "id" | "tier">>) => void;
  onDelete: (id: string) => void;
  t: TFn;
};

function SubplotRow({ entry, volumeCount, fieldDisabled, locked, onChange, onDelete, t }: SubplotRowProps) {
  const supportsVolume = entry.tier !== "S";
  const cap = Math.max(1, volumeCount);
  // A blank `<select>` value represents "auto / not pinned" so the backend can
  // fall back to its original per-volume distribution path. Out-of-range volumes
  // (e.g. after the user drops volume count) coerce back to the auto sentinel.
  const selectValue =
    supportsVolume && entry.volume != null && entry.volume >= 1 && entry.volume <= cap
      ? String(entry.volume)
      : "";
  const gridCols = supportsVolume
    ? "md:grid-cols-[minmax(7rem,8rem)_minmax(0,1fr)_minmax(0,2fr)_auto]"
    : "md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]";
  return (
    <li className={`grid grid-cols-1 gap-2 rounded-lg border border-outline-variant/10 bg-surface-container-low/40 p-3 ${gridCols}`}>
      {supportsVolume ? (
        <label className="flex min-w-0 flex-col gap-1">
          <span className="font-label text-[10px] font-semibold uppercase tracking-[0.22em] text-on-surface-variant">
            {t("setup.phase3.subplotVolumeLabel")}
          </span>
          <select
            className="auteur-input bg-surface-container-lowest/70 font-body text-sm"
            value={selectValue}
            onChange={(e) =>
              onChange(entry.id, {
                volume: e.target.value === "" ? null : Number(e.target.value),
              })
            }
            disabled={fieldDisabled || locked}
            aria-label={t("setup.phase3.subplotVolumeLabel")}
            title={t("setup.phase3.subplotVolumeHint")}
          >
            <option value="">{t("setup.phase3.subplotVolumeAuto")}</option>
            {Array.from({ length: cap }).map((_, idx) => {
              const vol = idx + 1;
              return (
                <option key={vol} value={vol}>
                  {t("setup.phase3.subplotVolumeOption", undefined, { n: vol })}
                </option>
              );
            })}
          </select>
        </label>
      ) : null}
      <input
        type="text"
        className="auteur-input bg-surface-container-lowest/70 font-body text-sm"
        placeholder={t("setup.phase3.subplotTitlePlaceholder")}
        value={entry.title}
        onChange={(e) => onChange(entry.id, { title: e.target.value })}
        disabled={fieldDisabled}
        readOnly={locked}
      />
      <textarea
        className="auteur-input min-h-[64px] resize-y bg-surface-container-lowest/70 font-body text-sm leading-relaxed"
        rows={2}
        placeholder={t("setup.phase3.subplotGoalPlaceholder")}
        value={entry.goal}
        onChange={(e) => onChange(entry.id, { goal: e.target.value })}
        disabled={fieldDisabled}
        readOnly={locked}
      />
      {!locked ? (
        <button
          type="button"
          onClick={() => onDelete(entry.id)}
          disabled={fieldDisabled}
          className="inline-flex h-9 w-9 items-center justify-center self-start rounded-full text-on-surface-variant transition-colors hover:bg-error/15 hover:text-error disabled:opacity-40 md:self-center"
          aria-label={t("setup.phase3.subplotDelete")}
          title={t("setup.phase3.subplotDelete")}
        >
          <span className="material-symbols-outlined text-base">delete</span>
        </button>
      ) : null}
    </li>
  );
}

type WizardFooterProps = {
  phase: PhaseIndex;
  locked: boolean;
  showCreateButton: boolean;
  onCompile?: () => void | Promise<void>;
  compileBusy: boolean;
  disabled: boolean;
  onBack: () => void;
  onNext: () => void;
  onCompileClick: () => void;
  t: TFn;
};

function WizardFooter({
  phase,
  locked,
  showCreateButton,
  onCompile,
  compileBusy,
  disabled,
  onBack,
  onNext,
  onCompileClick,
  t,
}: WizardFooterProps) {
  if (locked) return null;
  const onLastPhase = phase === 3;
  return (
    <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-outline-variant/10 pt-5">
      <span className="font-label text-[10px] font-semibold uppercase tracking-[0.28em] text-on-surface-variant">
        {t("setup.phaseLabel", undefined, { n: phase })}
      </span>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn-secondary"
          onClick={onBack}
          disabled={phase === 1}
        >
          <span className="material-symbols-outlined text-base">chevron_left</span>
          {t("setup.phaseBack")}
        </button>
        {!onLastPhase ? (
          <button type="button" className="btn-primary-gradient" onClick={onNext} disabled={disabled}>
            {t("setup.phaseNext")}
            <span className="material-symbols-outlined text-base">chevron_right</span>
          </button>
        ) : null}
        {onLastPhase && showCreateButton ? (
          <button type="submit" className="btn-primary-gradient" disabled={disabled || compileBusy}>
            <span className="material-symbols-outlined">auto_awesome</span>
            {t("setup.createAndCompile")}
          </button>
        ) : null}
        {onLastPhase && !showCreateButton && onCompile ? (
          <button
            type="button"
            className="btn-primary-gradient"
            onClick={onCompileClick}
            disabled={disabled || compileBusy}
            title={t("app.confirm.saveAndCompile")}
          >
            <span className="material-symbols-outlined">auto_awesome</span>
            {t("app.confirm.saveAndCompile")}
          </button>
        ) : null}
      </div>
    </footer>
  );
}
