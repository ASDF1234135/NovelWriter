import { useState, type ReactNode, useRef, type Ref } from "react";
import { useI18n } from "../../i18n/useI18n";
import type { AiFreedomLevel, WritingPreambleResponse } from "../../types";

/** Mirror of the App-level constant that decides when the outline is treated as a full binding. */
export const OUTLINE_FULL_BINDING_MIN_CHARS = 100;

export type ChapterAnchorCandidate = {
  id: string;
  title?: string | null;
  description?: string | null;
};

type Props = {
  nextChapterId: number;
  chapterAlreadyCompleted: boolean;
  formDisabled: boolean;

  referenceSlot?: ReactNode;

  chapterOutline: string;
  setChapterOutline: (next: string) => void;
  chapterHardRules: string;
  setChapterHardRules: (next: string) => void;
  chapterHardRulesRef?: Ref<HTMLTextAreaElement>;

  writingPreamble: WritingPreambleResponse | null;
  preambleHasNonLlmSummary: boolean;
  preamblePrevChapterId: number | null;
  preamblePrevSourceNeedsRegenerate: boolean;
  regenSummaryBusyChapter: number | null;
  onRegeneratePreviousSummary?: (chapterId: number) => void;

  chapterAnchorCandidates: ChapterAnchorCandidate[];
  selectedAnchorIds: string[];
  setSelectedAnchorIds: (next: string[] | ((prev: string[]) => string[])) => void;
  autoNextAnchorTitles: string[];

  aiFreedomLevel: AiFreedomLevel;
  setAiFreedomLevel: (next: AiFreedomLevel) => void;
  /** Called when user clicks the primary Run button; parent decides whether to open a confirm modal first. */
  onRequestRunChapter: () => void;
  /** Workflow stage track + quick nav; rendered in the same footer block as the run button. */
  workflowProgressSlot?: ReactNode;
};

/**
 * Single-flow composer for the chapter-run page (top → bottom):
 * reference → optional milestone picks → optional outline & rules → run.
 * Target chapter is shown in the page title only.
 */
export function ChapterRunComposer({
  nextChapterId,
  chapterAlreadyCompleted,
  formDisabled,
  referenceSlot,
  chapterOutline,
  setChapterOutline,
  chapterHardRules,
  setChapterHardRules,
  chapterHardRulesRef,
  writingPreamble,
  preambleHasNonLlmSummary,
  preamblePrevChapterId,
  preamblePrevSourceNeedsRegenerate,
  regenSummaryBusyChapter,
  onRegeneratePreviousSummary,
  chapterAnchorCandidates,
  selectedAnchorIds,
  setSelectedAnchorIds,
  autoNextAnchorTitles,
  aiFreedomLevel,
  setAiFreedomLevel,
  onRequestRunChapter,
  workflowProgressSlot,
}: Props) {
  const { t } = useI18n();
  const fallbackHardRulesRef = useRef<HTMLTextAreaElement | null>(null);
  const hardRulesRef = chapterHardRulesRef ?? fallbackHardRulesRef;
  const prevChapterN = Math.max(0, nextChapterId - 1);
  const [recapExpanded, setRecapExpanded] = useState(false);
  const [plotPickExpanded, setPlotPickExpanded] = useState(false);
  const [notesExpanded, setNotesExpanded] = useState(false);

  const outlineShortHintVisible =
    chapterOutline.trim().length > 0 &&
    chapterOutline.trim().length < OUTLINE_FULL_BINDING_MIN_CHARS;

  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-2xl border border-outline-variant/20 bg-surface-container-low/70 p-5 shadow-glow md:p-6">
        <div className="flex flex-col">
          <FlowBlock
            index={1}
            title={t("chapterRun.flow.reference")}
            subtitle={t("chapterRun.flow.referenceHint")}
          >
            <div className="mt-2 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="rounded-xl border border-outline-variant/15 bg-surface-container/40 px-4 py-3">
                <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">
                  {t("chapterRun.flow.referencePart.compileResult")}
                </p>
                {referenceSlot ? <div className="w-full">{referenceSlot}</div> : null}
              </div>

              <div className="rounded-xl border border-outline-variant/15 bg-surface-container/40 px-4 py-3 font-body text-sm leading-relaxed text-on-surface-variant">
                <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">
                  {t("chapterRun.flow.referencePart.prevRecap", undefined, { n: prevChapterN })}
                </p>
                {!writingPreamble ? (
                  <p className="flex items-center gap-2 text-on-surface-variant">
                    <span className="material-symbols-outlined animate-spin text-base text-secondary" aria-hidden>
                      progress_activity
                    </span>
                    {t("app.write.preambleLoading")}
                  </p>
                ) : (
                  <div className="space-y-2">
                    <p className={recapExpanded ? "" : "line-clamp-6"}>
                      <span className="text-on-surface-variant/80">{t("app.write.preamblePrevChapter")}</span>
                      {writingPreamble.plot_progress.previous_chapter.plot_summary || t("app.write.preambleNoSummary")}
                    </p>
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 self-start rounded-full border border-outline-variant/25 bg-surface-container-highest/70 px-2.5 py-1 font-label text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant hover:border-secondary/35 hover:text-secondary"
                      onClick={() => setRecapExpanded((v) => !v)}
                    >
                      <span className="material-symbols-outlined text-sm" aria-hidden>
                        {recapExpanded ? "expand_less" : "expand_more"}
                      </span>
                      {recapExpanded ? t("chapterRun.flow.referencePart.collapse") : t("chapterRun.flow.referencePart.expand")}
                    </button>
                    {preambleHasNonLlmSummary ? (
                      <p className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-on-surface">
                        {t("app.write.preambleNonLlmWarn")}
                      </p>
                    ) : null}
                    {preamblePrevChapterId != null && preamblePrevSourceNeedsRegenerate ? (
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={regenSummaryBusyChapter !== null || formDisabled}
                        onClick={() => onRegeneratePreviousSummary?.(preamblePrevChapterId)}
                      >
                        {regenSummaryBusyChapter === preamblePrevChapterId
                          ? t("app.write.regenProcessing")
                          : t("app.write.regenSummary")}
                      </button>
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          </FlowBlock>

          <ExpandableFlowBlock
            index={2}
            title={t("chapterRun.flow.plotPick")}
            subtitle={t("chapterRun.flow.plotPickHint")}
            expanded={plotPickExpanded}
            onToggle={() => setPlotPickExpanded((v) => !v)}
            expandLabel={t("chapterRun.flow.referencePart.expand")}
            collapseLabel={t("chapterRun.flow.referencePart.collapse")}
          >
            <div className="mt-2 space-y-3 rounded-xl border border-outline-variant/15 bg-surface-container/40 px-4 py-4">
              {chapterAnchorCandidates.length === 0 ? (
                <p className="font-body text-xs text-on-surface-variant">{t("app.write.noMilestonesAvailable")}</p>
              ) : (
                <div className="grid max-h-[min(22rem,50vh)] grid-cols-1 gap-2 overflow-y-auto pr-1 md:grid-cols-2">
                  {chapterAnchorCandidates.map((n) => {
                    const checked = selectedAnchorIds.includes(n.id);
                    return (
                      <label
                        key={n.id}
                        className={
                          checked
                            ? "rounded-lg border border-secondary/40 bg-secondary/10 px-3 py-2 font-body text-xs text-on-surface"
                            : "rounded-lg border border-outline-variant/15 bg-surface-container-low px-3 py-2 font-body text-xs text-on-surface"
                        }
                      >
                        <div className="mb-1 font-semibold">{n.title}</div>
                        <div className="mb-2 line-clamp-2 text-on-surface-variant/90">{n.description}</div>
                        <span className="inline-flex items-center gap-1.5">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) =>
                              setSelectedAnchorIds((prev) => {
                                const next = e.target.checked
                                  ? [...prev, n.id]
                                  : prev.filter((id) => id !== n.id);
                                return Array.from(new Set(next)).slice(0, 2);
                              })
                            }
                            disabled={formDisabled}
                          />
                          <span>{t("app.write.anchorPick")}</span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
              {autoNextAnchorTitles.length > 0 ? (
                <p className="font-body text-[11px] text-on-surface-variant/85">
                  {t("app.write.anchorAutoHint", undefined, {
                    titles: autoNextAnchorTitles.join(t("app.write.listSep")),
                  })}
                </p>
              ) : null}
            </div>
          </ExpandableFlowBlock>

          <ExpandableFlowBlock
            index={3}
            title={t("chapterRun.flow.notesAndRules")}
            subtitle={t("chapterRun.flow.notesOptionalHint")}
            expanded={notesExpanded}
            onToggle={() => setNotesExpanded((v) => !v)}
            expandLabel={t("chapterRun.flow.referencePart.expand")}
            collapseLabel={t("chapterRun.flow.referencePart.collapse")}
          >
            <div className="mt-2 rounded-2xl border border-secondary/30 bg-secondary/6 p-4 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="flex min-w-0 flex-col gap-2">
                <label
                  htmlFor="chapter-direction-input"
                  className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary"
                >
                  {t("app.write.chapterDirection")}
                </label>
                <textarea
                  id="chapter-direction-input"
                  value={chapterOutline}
                  onChange={(e) => setChapterOutline(e.target.value)}
                  maxLength={2000}
                  rows={6}
                  placeholder={t("app.write.outlinePlaceholder")}
                  disabled={formDisabled}
                  className="w-full resize-y rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 py-2 font-body text-sm leading-relaxed text-on-surface placeholder:text-on-surface-variant/50 focus:border-secondary/60 focus:outline-none focus:ring-1 focus:ring-secondary/40 disabled:opacity-60"
                />
                <div className="flex items-center justify-between font-body text-[11px] text-on-surface-variant/80">
                  {outlineShortHintVisible ? (
                    <span className="text-secondary/90">
                      {t("app.write.outlineShortHint", undefined, {
                        min: OUTLINE_FULL_BINDING_MIN_CHARS,
                      })}
                    </span>
                  ) : (
                    <span aria-hidden />
                  )}
                  <span className="tabular-nums text-on-surface-variant/60">{chapterOutline.length} / 2000</span>
                </div>
              </div>
              <div className="flex min-w-0 flex-col gap-2">
                <label
                  htmlFor="chapter-hard-rules-input"
                  className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary"
                >
                  {t("app.write.hardRules")}
                </label>
                <textarea
                  id="chapter-hard-rules-input"
                  value={chapterHardRules}
                  onChange={(e) => setChapterHardRules(e.target.value)}
                  ref={hardRulesRef}
                  maxLength={8000}
                  rows={6}
                  placeholder={t("app.write.hardRulesPlaceholder")}
                  disabled={formDisabled}
                  className="w-full resize-y rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 py-2 font-body text-sm leading-relaxed text-on-surface placeholder:text-on-surface-variant/50 focus:border-secondary/60 focus:outline-none focus:ring-1 focus:ring-secondary/40 disabled:opacity-60"
                />
                <div className="flex items-center justify-end font-body text-[11px] text-on-surface-variant/60">
                  <span className="tabular-nums">{chapterHardRules.length} / 8000</span>
                </div>
              </div>
              <div className="flex min-w-0 flex-col gap-2 lg:col-span-2">
                <label
                  htmlFor="chapter-ai-freedom-select"
                  className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary"
                >
                  {t("app.write.aiFreedom")}
                </label>
                <select
                  id="chapter-ai-freedom-select"
                  value={aiFreedomLevel}
                  onChange={(e) => setAiFreedomLevel(e.target.value as AiFreedomLevel)}
                  disabled={formDisabled}
                  className="auteur-input h-10 w-full max-w-md text-sm"
                >
                  <option value="strict">{t("app.write.aiFreedom.strict")}</option>
                  <option value="balanced">{t("app.write.aiFreedom.balanced")}</option>
                  <option value="wild">{t("app.write.aiFreedom.wild")}</option>
                </select>
              </div>
            </div>
            </div>
          </ExpandableFlowBlock>
        </div>
      </section>

      <footer className="sticky bottom-3 z-10 overflow-hidden rounded-2xl border border-outline-variant/25 bg-surface-container/95 shadow-[0_18px_44px_rgba(0,0,0,0.45)] backdrop-blur-md">
        {workflowProgressSlot ? (
          <div className="border-b border-outline-variant/15 bg-surface-container-low/50 px-4 py-3 md:px-5">
            {workflowProgressSlot}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center justify-end gap-3 px-4 py-3 md:px-5">
          {chapterAlreadyCompleted ? (
            <span className="mr-auto rounded-full border border-tertiary/30 bg-tertiary/10 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-wider text-tertiary">
              {t("app.write.chapterCompleteBadge", undefined, { n: nextChapterId })}
            </span>
          ) : null}
          <button
            type="button"
            className="btn-primary-gradient h-11 min-w-[10rem] px-6"
            onClick={onRequestRunChapter}
            disabled={formDisabled}
          >
            <span className="material-symbols-outlined text-base" aria-hidden>
              auto_awesome
            </span>
            {t("app.write.runChapter")}
          </button>
        </div>
      </footer>
    </div>
  );
}

function FlowBlock({
  index,
  title,
  subtitle,
  children,
}: {
  index: number;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-t border-outline-variant/10 pt-7 first:mt-0 first:border-t-0 first:pt-0">
      <FlowBlockHeader index={index} title={title} subtitle={subtitle} />
      {children}
    </div>
  );
}

function ExpandableFlowBlock({
  index,
  title,
  subtitle,
  expanded,
  onToggle,
  expandLabel,
  collapseLabel,
  children,
}: {
  index: number;
  title: string;
  subtitle?: string;
  expanded: boolean;
  onToggle: () => void;
  expandLabel: string;
  collapseLabel: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-t border-outline-variant/10 pt-7 first:mt-0 first:border-t-0 first:pt-0">
      <button
        type="button"
        className="flex w-full items-start gap-4 rounded-xl text-left transition-colors hover:bg-surface-container-highest/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary/50"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span
          aria-hidden
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-secondary/35 bg-secondary/12 font-headline text-base font-black text-secondary shadow-[0_0_0_3px_rgba(0,0,0,0.12)]"
        >
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <FlowBlockHeader index={index} title={title} subtitle={subtitle} showIndex={false} />
            <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full border border-outline-variant/25 bg-surface-container-highest/70 px-2.5 py-1 font-label text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant">
              <span className="material-symbols-outlined text-sm" aria-hidden>
                {expanded ? "expand_less" : "expand_more"}
              </span>
              {expanded ? collapseLabel : expandLabel}
            </span>
          </div>
        </div>
      </button>
      {expanded ? children : null}
    </div>
  );
}

function FlowBlockHeader({
  index,
  title,
  subtitle,
  showIndex = true,
}: {
  index: number;
  title: string;
  subtitle?: string;
  showIndex?: boolean;
}) {
  if (!showIndex) {
    return (
      <div className="min-w-0 flex-1">
        <h3 className="font-headline text-xl font-black tracking-tight text-on-surface">{title}</h3>
        {subtitle ? (
          <p className="mt-1 font-body text-xs leading-relaxed text-on-surface-variant/90">{subtitle}</p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex items-start gap-4">
      <span
        aria-hidden
        className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-secondary/35 bg-secondary/12 font-headline text-base font-black text-secondary shadow-[0_0_0_3px_rgba(0,0,0,0.12)]"
      >
        {index}
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="font-headline text-xl font-black tracking-tight text-on-surface">{title}</h3>
        {subtitle ? (
          <p className="mt-1 font-body text-xs leading-relaxed text-on-surface-variant/90">{subtitle}</p>
        ) : null}
      </div>
    </div>
  );
}
