import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import type { GraphSnapshot, HitlContextPayload, WorkflowPayload } from "../../types";
import { fetchGraph } from "../../api";
import { useI18n } from "../../i18n/useI18n";
import { hitlDecisionModeLabel } from "../ui-copy/workflowDisplay";
import {
  buildFeedbackSummary,
  defaultSolutionForReason,
  DRAFT_RESUME_OPTIONS,
  HITL_REASON,
  type HitlSolutionId,
  isDirectorPatchReason,
  isPlanFamilyReason,
  resumeNodeUserLabel,
  solutionsForReason,
} from "./hitlCopy";
import {
  buildHitlPrimaryHeadline,
  filterGraphNodesByType,
  mapHitlOptionHint,
  mapHitlQuickActionLabel,
  parseExtractionRemapHints,
  getRemapExpectedNodeType,
  type GraphNodeLite,
} from "./hitlNarrative";
import { HitlFlowStrip } from "./HitlFlowStrip";

export { HITL_REASON } from "./hitlCopy";

type Props = {
  workflow: WorkflowPayload | null;
  /** Full story graph for extraction remap targets; panel may fetch if absent. */
  graph?: GraphSnapshot | null;
  storyId?: string | null;
  variant?: "default" | "compact";
  /** When true, all HITL actions are disabled to prevent double-submit. */
  busy?: boolean;
  /** Shown inside the panel when HITL is active (e.g. server 422 / validation message). */
  workflowError?: string;
  onDecision: (optionId: string) => Promise<void>;
  onOutlineEdit: (payload: { ground_truth_events: Array<Record<string, unknown>>; narrative_script?: string }) => Promise<void>;
  onStateInjection: (payload: {
    mutations: Array<Record<string, unknown>>;
    chapter_hard_rules?: string;
    resume_from?: string;
    reason?: string;
    this_chapter_pacing_limit?: string;
    future_anchor_title?: string;
    future_anchor_description?: string;
    chapters_to_delay?: number | null;
  }) => Promise<void>;
  onDraftEdit: (payload: {
    chapter_content: string;
    resume_from?: string;
    merge_extraction_hints?: boolean;
  }) => Promise<void>;
  onDirectorPatch?: (payload: {
    chapter_type?: string;
    b_story_directive?: string | null;
    b_story_type?: string | null;
    new_elements_to_introduce?: string[];
    narrative_directive?: string;
    reason?: string;
  }) => Promise<void>;
  onExtractionRemap?: (payload: {
    entity_remaps: Array<{ from_node_id: string; to_node_id: string }>;
    waive_mandatory_node_ids?: string[];
    reason?: string;
  }) => Promise<void>;
  onAnchorResolution?: (payload: {
    action: "force_resolve" | "rewrite" | "delay_anchor";
    resolved_anchor_ids?: string[];
    delayed_anchor_ids?: string[];
    reject_resume_from?: string;
    reason?: string;
  }) => Promise<void>;
  onContextPrune?: (payload: { graph_rag_context_tier: number; reason?: string }) => Promise<void>;
};

function isHitlActive(workflow: WorkflowPayload | null): boolean {
  if (!workflow) return false;
  const st = workflow.state;
  return (
    workflow.run.requires_hitl === true ||
    workflow.run.status === "WAITING_HITL" ||
    st.workflow_status === "WAITING_HITL"
  );
}

const asyncNoop = async () => {};
const formSchema = z.object({
  narrativeScript: z.string().default(""),
  outlineEvents: z
    .array(
      z.object({
        event_id: z.string().trim().min(1, "event_id required"),
        description: z.string().trim().min(1, "description required"),
        caused_by_event_id: z.string().trim().optional(),
      }),
    )
    .default([]),
  draftText: z.string().default(""),
  draftResumeFrom: z.string().default("reader"),
  chapterType: z.string().default(""),
  bStoryDirective: z.string().default(""),
  bStoryType: z.string().default(""),
  newElementsLines: z.string().default(""),
  narrativeDirective: z.string().default(""),
  bResolved: z.array(z.string()).default([]),
  bEvidence: z.array(z.string()).default([]),
  bAnalysis: z.string().default(""),
  pruneProductTier: z.number().min(0).max(2).default(0),
  alignmentRulesInput: z.string().default(""),
  pacingLimitInput: z.string().default(""),
  futureAnchorTitle: z.string().default(""),
  futureAnchorDesc: z.string().default(""),
  futureAnchorDelay: z.string().default(""),
  remaps: z
    .array(
      z.object({
        from_node_id: z.string().trim(),
        to_node_id: z.string().trim(),
      }),
    )
    .default([]),
  injectionJson: z.string().default("[]"),
  advancedInjectAck: z.boolean().default(false),
  directorNotes: z.string().default(""),
});
type HitlFormValues = z.output<typeof formSchema>;

type PreviewPayload = {
  title: string;
  bullets: string[];
  confirmLabel: string;
  onConfirm: () => void;
};

export function HitlPanel({
  workflow,
  graph: graphProp = null,
  storyId = null,
  variant = "default",
  busy = false,
  workflowError = "",
  onDecision,
  onOutlineEdit,
  onStateInjection,
  onDraftEdit,
  onDirectorPatch = asyncNoop,
  onExtractionRemap = asyncNoop,
  onAnchorResolution = asyncNoop,
  onContextPrune = asyncNoop,
}: Props) {
  const { t } = useI18n();
  const [remapMissingIds, setRemapMissingIds] = useState<string[]>([]);
  const [localGraph, setLocalGraph] = useState<GraphSnapshot | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [selectedSolution, setSelectedSolution] = useState<HitlSolutionId | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const remapInitSigRef = useRef<string>("");
  const form = useForm<HitlFormValues>({
    resolver: zodResolver(formSchema) as never,
    mode: "onChange",
    defaultValues: {
      narrativeScript: "",
      outlineEvents: [{ event_id: "event_01", description: "", caused_by_event_id: "" }],
      draftText: "",
      draftResumeFrom: "reader",
      chapterType: "",
      bStoryDirective: "",
      bStoryType: "",
      newElementsLines: "",
      narrativeDirective: "",
      bResolved: [],
      bEvidence: [],
      bAnalysis: "",
      pruneProductTier: 0,
      alignmentRulesInput: "",
      pacingLimitInput: "",
      futureAnchorTitle: "",
      futureAnchorDesc: "",
      futureAnchorDelay: "",
      remaps: [{ from_node_id: "ghost_01", to_node_id: "planned_01" }],
      injectionJson:
        '[{"action":"CREATE_NODE","node_id":"item_backup_relic","node_type":"ITEM","properties":{"canonical_name":"backup_item","description":"HITL injected"}}]',
      advancedInjectAck: false,
      directorNotes: "",
    },
  });
  const { register, watch, setValue, getValues, formState } = form;
  const outlineArray = useFieldArray({ control: form.control, name: "outlineEvents" });
  const remapArray = useFieldArray({ control: form.control, name: "remaps" });

  const hitlActive = isHitlActive(workflow);
  const controlsLocked = !hitlActive || busy;
  const hitlContext = (workflow?.run.hitl_context ?? null) as HitlContextPayload | null;
  const rawOptions = (workflow?.state.pending_hitl_options as Array<{ id: string; label: string }> | undefined) ?? [];
  const options = useMemo(
    () => rawOptions.filter((o) => o.id !== "b_story_wait_judgement"),
    [rawOptions],
  );
  const reason = String(workflow?.run.hitl_reason ?? workflow?.state.hitl_reason ?? "");
  const resumeHint = String(workflow?.state.resume_from ?? "");
  const compact = variant === "compact";
  const primaryNarrative = useMemo(() => {
    if (!workflow?.state) return { headline: t("hitl.title"), extraLine: null as string | null };
    return buildHitlPrimaryHeadline(reason, workflow.state as Record<string, unknown>, hitlContext, t);
  }, [reason, workflow?.state, hitlContext, t]);
  const feedbackLines = useMemo(() => {
    if (!workflow?.state) return [];
    if (reason === HITL_REASON.PLAN_LOOP && primaryNarrative.extraLine) return [];
    return buildFeedbackSummary(workflow.state as Record<string, unknown>, reason);
  }, [workflow?.state, reason, primaryNarrative.extraLine]);
  const solutionList = useMemo(() => solutionsForReason(reason), [reason]);
  const effectiveGraph = graphProp && graphProp.nodes.length > 0 ? graphProp : localGraph;
  const extractionModels = useMemo(
    () => parseExtractionRemapHints(workflow?.state?.hitl_extraction_remap_hints),
    [workflow?.state?.hitl_extraction_remap_hints],
  );

  useEffect(() => {
    if (!hitlActive || reason !== HITL_REASON.EXTRACTION_GATE || !storyId?.trim()) return;
    if (graphProp && graphProp.nodes.length > 0) return;
    if (localGraph && localGraph.nodes.length > 0) return;
    let cancelled = false;
    setGraphLoading(true);
    void fetchGraph(storyId.trim())
      .then((g) => {
        if (!cancelled) setLocalGraph(g);
      })
      .catch(() => {
        if (!cancelled) setLocalGraph(null);
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hitlActive, reason, storyId, graphProp, localGraph]);

  useEffect(() => {
    if (!hitlActive) return;
    const list = solutionsForReason(reason);
    setSelectedSolution(list.length ? defaultSolutionForReason(reason) : null);
  }, [hitlActive, reason, workflow?.run.run_id]);

  useEffect(() => {
    if (hitlActive && workflow?.state.current_draft != null) {
      setValue("draftText", String(workflow.state.current_draft));
    }
  }, [hitlActive, workflow?.run.run_id, workflow?.state.current_draft]);

  useEffect(() => {
    if (!hitlActive || !workflow?.state) return;
    const st = workflow.state as Record<string, unknown>;
    if (isPlanFamilyReason(reason)) {
      const gt = st.ground_truth_events;
      if (Array.isArray(gt) && gt.length > 0) {
        const mapped = (gt as Array<Record<string, unknown>>).map((row, i) => ({
          event_id: String(row.event_id ?? "").trim() || `event_${i + 1}`,
          description: String(row.description ?? "").trim(),
          caused_by_event_id: row.caused_by_event_id != null ? String(row.caused_by_event_id).trim() : "",
        }));
        const currentOutline = (getValues("outlineEvents") ?? []).map((row) => ({
          event_id: String(row.event_id ?? "").trim(),
          description: String(row.description ?? "").trim(),
          caused_by_event_id: String(row.caused_by_event_id ?? "").trim(),
        }));
        if (JSON.stringify(currentOutline) !== JSON.stringify(mapped)) {
          outlineArray.replace(mapped);
        }
      }
      const nextNarrativeScript = String(st.narrative_script ?? "");
      if (getValues("narrativeScript") !== nextNarrativeScript) {
        setValue("narrativeScript", nextNarrativeScript);
      }
    }
    if (isDirectorPatchReason(reason)) {
      const nextDirectorNotes =
        reason === HITL_REASON.B_STORY_COOLDOWN
          ? String(st.b_story_directive ?? "")
          : String(st.narrative_directive ?? "");
      if (getValues("directorNotes") !== nextDirectorNotes) {
        setValue("directorNotes", nextDirectorNotes);
      }
    }
    if (reason === HITL_REASON.EXTRACTION_GATE) {
      const h = st.hitl_extraction_remap_hints;
      const models = parseExtractionRemapHints(h);
      const sig = `${workflow?.run?.run_id ?? ""}::${JSON.stringify(models.map((m) => [m.missing_planned_node_id, m.fromOptions.map((x) => x.node_id)]))}`;
      if (remapInitSigRef.current === sig) {
        return;
      }
      remapInitSigRef.current = sig;
      setRemapMissingIds(models.map((m) => m.missing_planned_node_id));
      const rows = models.map((m) => ({ from_node_id: m.defaultFromId, to_node_id: "" }));
      if (rows.length) {
        remapArray.replace(rows);
      } else {
        setRemapMissingIds([]);
        remapArray.replace([{ from_node_id: "", to_node_id: "" }]);
      }
    }
  if (reason === HITL_REASON.ANCHOR_RESOLVE || reason === HITL_REASON.B_STORY) {
      const cand = st.anchor_resolution_hitl_candidate ?? st.b_story_resolution_hitl_candidate;
      if (cand && typeof cand === "object") {
        setValue("bAnalysis", JSON.stringify(cand, null, 2));
        const c = cand as Record<string, unknown>;
        const suggestedB = Array.isArray(c.resolved_anchor_ids) ? c.resolved_anchor_ids : [];
        const evidenceRows = Array.isArray(c.evidence_summary) ? c.evidence_summary : [];
        const suggestedE = evidenceRows
          .map((row) => {
            if (!row || typeof row !== "object") return "";
            const r = row as Record<string, unknown>;
            const aid = String(r.anchor_id ?? "").trim();
            const reasonTxt = String(r.decision_reason ?? "").trim();
            return [aid, reasonTxt].filter(Boolean).join(": ");
          })
          .filter(Boolean);
        setValue(
          "bResolved",
          suggestedB.map((x) => String(x).trim()).filter(Boolean),
        );
        setValue(
          "bEvidence",
          suggestedE.map((x) => String(x).trim()).filter(Boolean),
        );
      }
    }
    if (reason === HITL_REASON.CONTEXT) {
      const meta = workflow?.run.hitl_context?.context_metadata;
      const suggested = meta?.graph_rag_context_tier;
      if (typeof suggested === "number" && suggested >= 0 && suggested <= 2) {
        setValue("pruneProductTier", suggested);
      } else {
        setValue("pruneProductTier", 0);
      }
    }
    if (reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED) {
      const nextRules = String(st.chapter_hard_rules ?? "");
      if (getValues("alignmentRulesInput") !== nextRules) {
        setValue("alignmentRulesInput", nextRules);
      }
    }
  }, [hitlActive, reason, workflow?.run.run_id, workflow?.run.hitl_context, workflow?.state, remapArray, outlineArray, getValues, setValue]);
  const shell = compact
    ? "glass-panel rounded-xl border border-outline-variant/15 p-4 shadow-glow"
    : "rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow";
  const inputClass = compact ? "auteur-input mt-1 text-xs" : "auteur-input mt-1 text-sm";
  const btnClass = "btn-secondary mt-2 w-full text-xs";
  const taRows = (n: number) => (compact ? Math.max(3, n - 2) : n);

  const autoWaiveMissingPlannedIds = (): string[] => {
    const rows = getValues("remaps") ?? [];
    const waive: string[] = [];
    for (let i = 0; i < rows.length; i++) {
      const to = String(rows[i]?.to_node_id ?? "").trim();
      if (to && to !== "__NEW_NODE__") continue;
      const mid = String(remapMissingIds[i] ?? "").trim();
      if (mid) waive.push(mid);
    }
    return Array.from(new Set(waive));
  };

  const decisionMode = String(workflow?.run.hitl_decision_mode ?? "");

  return (
    <section className={shell} aria-labelledby="hitl-panel-heading">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="hitl-panel-heading" className="font-headline text-sm font-bold uppercase tracking-wider text-tertiary">
          {t("hitl.title")}
        </h2>
        {hitlActive ? (
          <button
            type="button"
            className="shrink-0 rounded-md border border-error/50 bg-error/15 px-2 py-1 font-label text-[11px] font-semibold text-error hover:bg-error/25 disabled:opacity-40"
            disabled={controlsLocked}
            onClick={() => onDecision("ABORT_AND_RESTART")}
          >
            {t("hitl.abortChapter")}
          </button>
        ) : null}
      </div>
      <p className="mb-3 font-body text-sm text-on-surface-variant">
        {hitlActive ? (
          <>
            <strong className="text-tertiary">{t("hitl.workflowPaused")}</strong>
            <span className="text-on-surface-variant">
              {" "}
              · {hitlDecisionModeLabel(decisionMode)}
            </span>
          </>
        ) : (
          t("hitl.noPending")
        )}
      </p>
      {hitlActive ? <HitlFlowStrip reason={reason} resumeFrom={resumeHint} compact={compact} /> : null}

      {hitlActive && reason === HITL_REASON.CHAPTER_DRAFT_REVIEW ? (
        <div className="rounded-lg border border-tertiary/40 bg-tertiary/10 px-3 py-3 font-body text-sm text-on-surface">
          {t("hitl.chapterReview.panelStub")}
        </div>
      ) : null}

      {hitlActive && reason !== HITL_REASON.CHAPTER_DRAFT_REVIEW ? (
        <>
          {workflowError.trim() ? (
            <div className="mb-3 rounded-lg border border-error/40 bg-error/10 px-3 py-2 font-body text-sm text-error">{workflowError.trim()}</div>
          ) : null}
          <div className="mb-4 rounded-lg border border-tertiary/20 bg-tertiary/5 px-3 py-3">
            <h3 className="font-headline text-sm font-bold text-on-surface">{primaryNarrative.headline}</h3>
            {primaryNarrative.extraLine ? (
              <p className="mt-2 font-body text-sm leading-relaxed text-on-surface">{primaryNarrative.extraLine}</p>
            ) : null}
            {hitlContext?.primary_issue && reason !== HITL_REASON.ALIGNMENT_RULES_REQUIRED ? (
              <p className="mt-2 rounded-md bg-surface-container-highest/60 px-2 py-2 font-body text-xs text-on-surface">{hitlContext.primary_issue}</p>
            ) : null}
            {reason === HITL_REASON.B_STORY && String(hitlContext?.problematic_draft_snippet ?? "").trim() ? (
              <div className="mt-3 rounded-md border border-outline-variant/20 bg-surface-container-low/70 px-2 py-2">
                <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.draft.title")}</p>
                <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-body text-xs text-on-surface">
                  {String(hitlContext?.problematic_draft_snippet ?? "").trim()}
                </pre>
              </div>
            ) : null}
            {hitlContext?.context_metadata?.payload_type === "output_language" &&
            hitlContext.context_metadata.expected_output_language ? (
              <p className="mt-2 font-label text-xs text-on-surface-variant">
                {t("hitl.outputLanguage.projectLang")}
                <span className="text-on-surface">{String(hitlContext.context_metadata.expected_output_language)}</span>
              </p>
            ) : null}
            {hitlContext?.context_metadata?.language_detection_summary ? (
              <p className="mt-1 font-body text-xs text-on-surface-variant">{hitlContext.context_metadata.language_detection_summary}</p>
            ) : null}
            {reason !== HITL_REASON.ANCHOR_RESOLVE ? (
              <p className="mt-2 font-label text-xs text-on-surface-variant">
                {t("hitl.resumeNear", "", { step: resumeNodeUserLabel(resumeHint) })}
              </p>
            ) : null}
          </div>

          {feedbackLines.length > 0 ? (
            <div className="mb-4 rounded-lg bg-surface-container-highest/50 px-3 py-2">
              <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.systemFeedback")}</p>
              <ul className="mt-1 list-inside list-disc font-body text-sm text-on-surface">
                {feedbackLines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED ? (
            <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 px-3 py-3" aria-live="polite">
              <p className="mb-2 font-body text-xs text-on-surface">
                {t("hitl.alignment.explain")}
              </p>
              <textarea
                className={inputClass}
                rows={taRows(8)}
                disabled={controlsLocked}
                placeholder={t("hitl.alignment.placeholder")}
                {...register("alignmentRulesInput")}
              />
              {!watch("alignmentRulesInput").trim() ? (
                <p className="mt-1 font-body text-xs text-error">{t("hitl.alignment.required")}</p>
              ) : null}
              <button
                type="button"
                className={btnClass}
                disabled={controlsLocked || !watch("alignmentRulesInput").trim()}
                onClick={() => {
                  if (!watch("alignmentRulesInput").trim()) return;
                  onStateInjection({
                    mutations: [],
                    chapter_hard_rules: watch("alignmentRulesInput"),
                    resume_from: "logic_alignment",
                    reason: "alignment_rules_patch",
                    this_chapter_pacing_limit: "",
                    future_anchor_title: "",
                    future_anchor_description: "",
                    chapters_to_delay: null,
                  });
                }}
              >
                {t("hitl.alignment.submit")}
              </button>
            </div>
          ) : null}

          {options.length > 0 ? (
            <div className="mb-4">
              <p className="mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.quickActions")}</p>
              <div className="flex flex-col gap-2">
                {options.map((option) => (
                  <div key={option.id} className="rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 p-2">
                    <button
                      type="button"
                      disabled={controlsLocked}
                      onClick={() => {
                        if (option.id === "force_approve_plan") {
                          setPreview({
                            title: t("hitl.preview.forceApproveTitle"),
                            bullets: [t("hitl.preview.forceApproveBullet1"), t("hitl.preview.forceApproveBullet2")],
                            confirmLabel: t("hitl.preview.forceApproveConfirm"),
                            onConfirm: () => void onDecision(option.id),
                          });
                          return;
                        }
                        void onDecision(option.id);
                      }}
                      className="w-full rounded-md bg-primary/15 px-3 py-2 text-left font-label text-sm font-medium text-primary transition-colors hover:bg-primary/25 disabled:opacity-40"
                    >
                      {mapHitlQuickActionLabel(option.id, option.label, t)}
                    </button>
                    {mapHitlOptionHint(option.id, t).trim() ? (
                      <p className="mt-1.5 px-1 font-body text-xs text-on-surface-variant">{mapHitlOptionHint(option.id, t)}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {solutionList.length > 0 ? (
            <div className="mb-3">
              <p className="mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.chooseSolution")}</p>
              <div className={`flex flex-wrap gap-2 ${compact ? "" : "gap-3"}`}>
                {solutionList.map((sol) => (
                  <button
                    key={sol.id}
                    type="button"
                    disabled={controlsLocked}
                    onClick={() => setSelectedSolution(sol.id)}
                    className={`max-w-full rounded-xl border px-3 py-2 text-left transition-colors ${
                      selectedSolution === sol.id
                        ? "border-tertiary bg-tertiary/15 ring-1 ring-tertiary/30"
                        : "border-outline-variant/20 bg-surface-container-highest/40 hover:border-outline-variant/40"
                    } disabled:opacity-40`}
                  >
                    <span className="block font-label text-sm font-semibold text-on-surface">{sol.title}</span>
                    <span className="mt-0.5 block font-body text-xs text-on-surface-variant">{sol.blurb}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4">
            {selectedSolution === "outline" && isPlanFamilyReason(reason) ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("hitl.outline.title")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">{t("hitl.outline.hint")}</p>
                <div className="space-y-2">
                  {outlineArray.fields.map((field, idx) => (
                    <div
                      key={field.id}
                      className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-2"
                      draggable={!controlsLocked}
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(idx))}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        const src = Number.parseInt(e.dataTransfer.getData("text/plain"), 10);
                        if (Number.isFinite(src) && src !== idx) outlineArray.move(src, idx);
                      }}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-label text-[10px] text-on-surface-variant">
                          {t("hitl.outline.eventN", "", { n: idx + 1 })}
                        </span>
                        <button type="button" className="btn-secondary ml-auto text-[10px]" disabled={controlsLocked || outlineArray.fields.length <= 1} onClick={() => outlineArray.remove(idx)}>
                          {t("hitl.delete")}
                        </button>
                      </div>
                      <label className="auteur-label mt-1 text-[10px] text-on-surface-variant">{t("hitl.outline.eventId")}</label>
                      <input className={`${inputClass} font-mono text-xs`} disabled={controlsLocked} {...register(`outlineEvents.${idx}.event_id`)} />
                      <label className="auteur-label mt-1">{t("hitl.outline.description")}</label>
                      <textarea className={inputClass} rows={taRows(4)} disabled={controlsLocked} {...register(`outlineEvents.${idx}.description`)} />
                      <label className="auteur-label mt-1 text-[10px] text-on-surface-variant">{t("hitl.outline.causedBy")}</label>
                      <input className={inputClass} disabled={controlsLocked} {...register(`outlineEvents.${idx}.caused_by_event_id`)} />
                    </div>
                  ))}
                </div>
                <button type="button" className={btnClass} disabled={controlsLocked} onClick={() => outlineArray.append({ event_id: "", description: "", caused_by_event_id: "" })}>
                  {t("hitl.outline.addCard")}
                </button>
                <label className="auteur-label mt-2">{t("hitl.outline.narrativeScript")}</label>
                <textarea className={inputClass} rows={taRows(3)} disabled={controlsLocked} {...register("narrativeScript")} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked || !formState.isValid}
                  onClick={() => {
                    const nextEvents = getValues("outlineEvents");
                    const current = Array.isArray(workflow?.state?.ground_truth_events)
                      ? (workflow?.state?.ground_truth_events as Array<Record<string, unknown>>)
                      : [];
                    const removed = current.filter((row) => !nextEvents.some((e) => e.event_id === String(row.event_id ?? "")));
                    const added = nextEvents.filter((row) => !current.some((e) => String(e.event_id ?? "") === row.event_id));
                    setPreview({
                      title: t("hitl.outline.previewTitle"),
                      bullets: [
                        t("hitl.outline.previewStats", "", {
                          added: added.length,
                          removed: removed.length,
                          total: nextEvents.length,
                        }),
                      ],
                      confirmLabel: t("hitl.outline.previewConfirm"),
                      onConfirm: () =>
                        void onOutlineEdit({
                          ground_truth_events: nextEvents as Array<Record<string, unknown>>,
                          narrative_script: getValues("narrativeScript"),
                        }),
                    });
                  }}
                >
                  {t("hitl.outline.previewApply")}
                </button>
              </>
            ) : null}

            {selectedSolution === "director" && isDirectorPatchReason(reason) ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">
                  {reason === HITL_REASON.B_STORY_COOLDOWN ? t("hitl.director.titleBStory") : t("hitl.director.titlePlan")}
                </h3>
                <textarea className={inputClass} rows={taRows(6)} disabled={controlsLocked} placeholder={t("hitl.director.placeholder")} {...register("directorNotes")} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() => {
                    const notes = getValues("directorNotes").trim();
                    if (reason === HITL_REASON.B_STORY_COOLDOWN) {
                      void onDirectorPatch({ b_story_directive: notes || undefined });
                    } else {
                      void onDirectorPatch({ narrative_directive: notes || undefined });
                    }
                  }}
                >
                  {t("hitl.director.apply")}
                </button>
              </>
            ) : null}

            {selectedSolution === "draft" && reason === HITL_REASON.DRAFT_LOOP ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("hitl.draft.title")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">{t("hitl.draft.hint")}</p>
                <label className="auteur-label">{t("hitl.draft.resumeLabel")}</label>
                <select className={inputClass} disabled={controlsLocked} {...register("draftResumeFrom")}>
                  {DRAFT_RESUME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(`hitl.draft.resume.${o.value}`, o.label)}
                    </option>
                  ))}
                </select>
                <textarea className={inputClass} rows={taRows(10)} disabled={controlsLocked} {...register("draftText")} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() =>
                    onDraftEdit({
                      chapter_content: getValues("draftText"),
                      resume_from: getValues("draftResumeFrom"),
                      merge_extraction_hints: true,
                    })
                  }
                >
                  {t("hitl.draft.submit")}
                </button>
              </>
            ) : null}

            {selectedSolution === "remap" && reason === HITL_REASON.EXTRACTION_GATE ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("hitl.remap.title")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">{t("hitl.remap.hint")}</p>
                {graphLoading ? <p className="mb-2 font-body text-xs text-on-surface-variant">{t("hitl.remap.graphLoading")}</p> : null}
                {!graphLoading && (!effectiveGraph || effectiveGraph.nodes.length === 0) ? (
                  <p className="mb-2 font-body text-xs text-warning">{t("hitl.remap.graphEmpty")}</p>
                ) : null}
                {extractionModels.length === 0 ? (
                  <p className="mb-2 font-body text-xs text-on-surface-variant">{t("hitl.remap.noHints")}</p>
                ) : null}
                <div className="space-y-2">
                  {remapArray.fields.map((field, idx) => {
                    const stObj = workflow?.state as Record<string, unknown> | undefined;
                    const missingId = String(remapMissingIds[idx] ?? "").trim();
                    const expectedType = stObj ? getRemapExpectedNodeType(missingId, stObj) : null;
                    let rightNodes = filterGraphNodesByType((effectiveGraph?.nodes ?? []) as GraphNodeLite[], expectedType);
                    if (expectedType && rightNodes.length === 0) {
                      rightNodes = (effectiveGraph?.nodes ?? []) as GraphNodeLite[];
                    }
                    const leftOpts = extractionModels[idx]?.fromOptions ?? [];
                    return (
                      <div key={field.id} className="grid grid-cols-1 gap-2 rounded-lg border border-outline-variant/15 p-2 md:grid-cols-[1fr_1fr_auto]">
                        <select className={inputClass} disabled={controlsLocked} {...register(`remaps.${idx}.from_node_id`)}>
                          <option value="">{t("hitl.remap.leftPlaceholder")}</option>
                          {leftOpts.map((opt) => (
                            <option key={opt.node_id} value={opt.node_id}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                        <select className={inputClass} disabled={controlsLocked} {...register(`remaps.${idx}.to_node_id`)}>
                          <option value="">{t("hitl.remap.rightPlaceholder")}</option>
                          <option value="__NEW_NODE__">{t("hitl.remap.newNodeOption")}</option>
                          {rightNodes.map((n) => {
                            const nid = String(n.node_id ?? "").trim();
                            const cn = String(n.canonical_name ?? "").trim();
                            const lab = cn ? `${cn} (${nid})` : nid;
                            return (
                              <option key={nid} value={nid}>
                                {lab}
                              </option>
                            );
                          })}
                        </select>
                        <button
                          type="button"
                          className="btn-secondary"
                          disabled={controlsLocked || remapArray.fields.length <= 1}
                          onClick={() => {
                            remapArray.remove(idx);
                            setRemapMissingIds((prev) => prev.filter((_, i) => i !== idx));
                          }}
                        >
                          {t("hitl.delete")}
                        </button>
                      </div>
                    );
                  })}
                </div>
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() => {
                    const rows = getValues("remaps")
                      .map((r) => ({
                        from_node_id: r.from_node_id.trim(),
                        to_node_id: r.to_node_id.trim(),
                      }))
                      .filter((r) => r.from_node_id && r.to_node_id && r.to_node_id !== "__NEW_NODE__");
                    setPreview({
                      title: t("hitl.remap.previewTitle"),
                      bullets: rows
                        .slice(0, 6)
                        .map((r) => `${r.from_node_id} → ${r.to_node_id}`)
                        .concat(rows.length > 6 ? [`… +${rows.length - 6}`] : []),
                      confirmLabel: t("hitl.remap.previewConfirm"),
                      onConfirm: () =>
                        void onExtractionRemap({
                          entity_remaps: rows,
                          waive_mandatory_node_ids: autoWaiveMissingPlannedIds(),
                        }),
                    });
                  }}
                >
                  {t("hitl.remap.previewApply")}
                </button>
              </>
            ) : null}

            {selectedSolution === "b_story" && reason === HITL_REASON.ANCHOR_RESOLVE ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("hitl.anchorResolve.title")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">{t("hitl.anchorResolve.hint")}</p>

                {String(hitlContext?.problematic_draft_snippet ?? "").trim() ? (
                  <div className="mb-3 rounded-md border border-outline-variant/20 bg-surface-container-low/70 px-2 py-2">
                    <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.draft.title")}</p>
                    <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-body text-xs text-on-surface">
                      {String(hitlContext?.problematic_draft_snippet ?? "").trim()}
                    </pre>
                  </div>
                ) : null}

                <div className="rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 px-3 py-2">
                  <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.anchorResolve.details")}</p>
                  <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-on-surface">
                    {watch("bAnalysis").trim() || "—"}
                  </pre>
                </div>

                <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    className="rounded-xl border border-tertiary/40 bg-tertiary/15 px-4 py-4 text-left font-label text-sm font-semibold text-tertiary transition-colors hover:bg-tertiary/25 disabled:opacity-40"
                    disabled={controlsLocked}
                    onClick={() =>
                      onAnchorResolution({
                        action: "force_resolve",
                        resolved_anchor_ids: watch("bResolved"),
                        reason: watch("bAnalysis"),
                      })
                    }
                  >
                    {t("hitl.anchorResolve.confirm")}
                  </button>
                  <button
                    type="button"
                    className="rounded-xl border border-outline-variant/30 bg-surface-container-highest/50 px-4 py-4 text-left font-label text-sm font-semibold text-on-surface transition-colors hover:border-outline-variant/50 disabled:opacity-40"
                    disabled={controlsLocked}
                    onClick={() =>
                      onAnchorResolution({
                        action: "rewrite",
                        reject_resume_from: "planner",
                        reason: watch("bAnalysis").slice(0, 800),
                      })
                    }
                  >
                    {t("hitl.anchorResolve.reject")}
                  </button>
                </div>
              </>
            ) : null}

            {selectedSolution === "prune" && reason === HITL_REASON.CONTEXT ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("hitl.prune.title")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">{t("hitl.prune.hint")}</p>
                <div className="flex flex-col gap-2">
                  {(
                    [
                      { v: 0, label: t("hitl.prune.tier0") },
                      { v: 1, label: t("hitl.prune.tier1") },
                      { v: 2, label: t("hitl.prune.tier2") },
                    ] as const
                  ).map((row) => (
                    <label key={row.v} className="flex cursor-pointer items-center gap-2 font-body text-sm text-on-surface">
                      <input
                        type="radio"
                        name="prune-tier"
                        checked={watch("pruneProductTier") === row.v}
                        onChange={() => setValue("pruneProductTier", row.v)}
                        disabled={controlsLocked}
                      />
                      {row.label}
                    </label>
                  ))}
                </div>
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() => onContextPrune?.({ graph_rag_context_tier: watch("pruneProductTier"), reason: "author_context_prune" })}
                >
                  {t("hitl.prune.apply")}
                </button>
              </>
            ) : null}

            {selectedSolution === "draft" && reason === HITL_REASON.OUTPUT_LANGUAGE ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("hitl.outputLanguage.editTitle")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">{t("hitl.outputLanguage.editHint")}</p>
                <textarea className={inputClass} rows={taRows(10)} disabled={controlsLocked} {...register("draftText")} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() =>
                    onDraftEdit({
                      chapter_content: getValues("draftText"),
                      resume_from: "output_language_gate",
                      merge_extraction_hints: true,
                    })
                  }
                >
                  {t("hitl.outputLanguage.editApply")}
                </button>
              </>
            ) : null}

            {hitlActive && solutionList.length === 0 ? (
              <p className="font-body text-sm text-on-surface-variant">{t("hitl.noDedicatedForm")}</p>
            ) : null}
            {hitlActive && solutionList.length > 0 && selectedSolution == null ? (
              <p className="font-body text-sm text-on-surface-variant">{t("hitl.chooseSolutionAbove")}</p>
            ) : null}
          </div>

          <details
            className="mt-4 rounded-xl border border-outline-variant/15 bg-surface-container-highest/20 p-3"
            open={advancedOpen}
            onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}
          >
            <summary className="cursor-pointer font-label text-sm font-semibold text-on-surface-variant">
              {t("hitl.advancedSummary")}
            </summary>
            <div className="mt-3 space-y-3 border-t border-outline-variant/10 pt-3">
              <p className="font-mono text-[10px] text-on-surface-variant">
                {t("hitl.reasonCode")}：{reason || "—"} · resume：{resumeHint || "—"}
              </p>
              <div>
                <h4 className="font-label text-xs font-bold text-on-surface">{t("hitl.directMutation")}</h4>
                <p className="mb-1 font-body text-[10px] text-on-surface-variant">{t("hitl.directMutationWarn")}</p>
                <textarea className={inputClass} rows={taRows(6)} disabled={controlsLocked} {...register("injectionJson")} />
                <label className="mt-2 flex cursor-pointer items-start gap-2 font-body text-xs text-on-surface">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    {...register("advancedInjectAck")}
                    disabled={controlsLocked}
                  />
                  <span>{t("hitl.directMutationAck")}</span>
                </label>
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked || !watch("advancedInjectAck")}
                  onClick={() => {
                    if (!watch("advancedInjectAck")) return;
                    let parsed: unknown;
                    try {
                      parsed = JSON.parse(getValues("injectionJson")) as unknown;
                    } catch {
                      return;
                    }
                    if (!Array.isArray(parsed)) {
                      return;
                    }
                    const rows = parsed as Array<Record<string, unknown>>;
                    setPreview({
                      title: t("hitl.previewMutationTitle"),
                      bullets: [t("hitl.previewMutationBullets", "", { count: rows.length })],
                      confirmLabel: t("hitl.confirmWrite"),
                      onConfirm: () =>
                        void onStateInjection({
                          mutations: rows,
                        }),
                    });
                  }}
                >
                  {t("hitl.writeAndContinue")}
                </button>
              </div>
            </div>
          </details>
          {preview ? (
            <div className="mt-4 rounded-xl border border-secondary/30 bg-secondary/10 p-3" role="dialog" aria-live="polite">
              <p className="font-headline text-sm font-bold text-on-surface">{preview.title}</p>
              <ul className="mt-2 list-disc list-inside font-body text-sm text-on-surface">
                {preview.bullets.map((line, idx) => (
                  <li key={idx}>{line}</li>
                ))}
              </ul>
              <div className="mt-3 flex gap-2">
                <button type="button" className="btn-secondary" onClick={() => setPreview(null)}>
                  {t("hitl.backEdit")}
                </button>
                <button
                  type="button"
                  className="btn-primary-gradient"
                  onClick={() => {
                    preview.onConfirm();
                    setPreview(null);
                  }}
                >
                  {preview.confirmLabel}
                </button>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function TokenEditor({
  values,
  onAdd,
  onRemove,
  input,
  onInput,
  disabled,
}: {
  values: string[];
  onAdd: (v: string) => void;
  onRemove: (v: string) => void;
  input: string;
  onInput: (v: string) => void;
  disabled: boolean;
}) {
  return null;
}
