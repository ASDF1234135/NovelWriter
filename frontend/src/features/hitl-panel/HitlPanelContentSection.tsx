import { HITL_REASON } from "./hitlCopy";
import { HitlPanelSection } from "./HitlPanelSection";
import type { AnchorMilestoneRow } from "./hitlNarrative";
import type { HitlContextPayload } from "../../types";

type HitlTranslate = (key: string, fallback?: string, params?: Record<string, string | number>) => string;

type Props = {
  reason: string;
  hitlContext: HitlContextPayload | null;
  feedbackLines: string[];
  anchorMilestones?: AnchorMilestoneRow[];
  t: HitlTranslate;
};

export function HitlPanelContentSection({ reason, hitlContext, feedbackLines, anchorMilestones = [], t }: Props) {
  const draftSnippet = String(hitlContext?.problematic_draft_snippet ?? "").trim();
  const hasLanguageMeta =
    hitlContext?.context_metadata?.payload_type === "output_language" &&
    Boolean(hitlContext.context_metadata.expected_output_language);
  const hasFeedback = feedbackLines.length > 0;
  const showDraft =
    draftSnippet.length > 0 &&
    (reason === HITL_REASON.B_STORY ||
      reason === HITL_REASON.ANCHOR_RESOLVE ||
      reason === HITL_REASON.DRAFT_LOOP ||
      reason === HITL_REASON.EXTRACTION_GATE ||
      reason === HITL_REASON.OUTPUT_LANGUAGE);

  const showAnchorMilestones = reason === HITL_REASON.ANCHOR_RESOLVE && anchorMilestones.length > 0;

  const showPrimaryIssue =
    Boolean(hitlContext?.primary_issue) &&
    reason !== HITL_REASON.ALIGNMENT_RULES_REQUIRED &&
    !(reason === HITL_REASON.ANCHOR_RESOLVE && showAnchorMilestones);

  if (!hasFeedback && !showDraft && !hasLanguageMeta && !showPrimaryIssue && !showAnchorMilestones) {
    return null;
  }

  return (
    <HitlPanelSection sectionId="hitl-section-content" title={t("hitl.section.content")}>
      {showPrimaryIssue ? (
        <p className="rounded-md bg-surface-container-highest/60 px-2 py-2 font-body text-xs leading-relaxed text-on-surface">
          {hitlContext.primary_issue}
        </p>
      ) : null}

      {hasLanguageMeta ? (
        <div className="mt-2 space-y-1">
          <p className="font-label text-xs text-on-surface-variant">
            {t("hitl.outputLanguage.projectLang")}
            <span className="text-on-surface">{String(hitlContext?.context_metadata?.expected_output_language)}</span>
          </p>
          {hitlContext?.context_metadata?.language_detection_summary ? (
            <p className="font-body text-xs text-on-surface-variant">{hitlContext.context_metadata.language_detection_summary}</p>
          ) : null}
        </div>
      ) : null}

      {hasFeedback ? (
        <div className={showDraft || hitlContext?.primary_issue ? "mt-3" : ""}>
          <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.systemFeedback")}</p>
          <ul className="mt-1 list-inside list-disc font-body text-sm text-on-surface">
            {feedbackLines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {showDraft ? (
        <div className="mt-3 rounded-md border border-outline-variant/20 bg-surface-container-low/70 px-2 py-2">
          <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.draft.title")}</p>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-body text-xs leading-relaxed text-on-surface">
            {draftSnippet}
          </pre>
        </div>
      ) : null}

      {showAnchorMilestones ? (
        <div className="mt-3 space-y-2">
          <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.anchorResolve.details")}</p>
          {anchorMilestones.map((row) => (
            <div
              key={row.anchorId || row.title}
              className="rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 px-2.5 py-2"
            >
              <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.anchorResolve.milestoneTitle")}</p>
              <p className="mt-0.5 font-body text-sm font-medium text-on-surface">{row.title}</p>
              <p className="mt-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.anchorResolve.milestoneDesc")}</p>
              <p className="mt-0.5 whitespace-pre-wrap font-body text-xs leading-relaxed text-on-surface">{row.description}</p>
            </div>
          ))}
        </div>
      ) : null}
    </HitlPanelSection>
  );
}
