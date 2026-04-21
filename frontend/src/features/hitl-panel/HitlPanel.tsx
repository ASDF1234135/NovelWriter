import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import type { HitlContextPayload, WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { hitlDecisionModeLabel } from "../ui-copy/workflowDisplay";
import {
  B_STORY_REJECT_RESUME_OPTIONS,
  buildFeedbackSummary,
  DRAFT_RESUME_OPTIONS,
  defaultSolutionForReason,
  formatBStoryCandidateForDisplay,
  getSituationCopy,
  HITL_REASON,
  type HitlSolutionId,
  isDirectorPatchReason,
  isPlanFamilyReason,
  OPTION_DECISION_HINTS,
  parseRemapHintsJson,
  resumeNodeUserLabel,
  solutionsForReason,
} from "./hitlCopy";

export { HITL_REASON } from "./hitlCopy";

type Props = {
  workflow: WorkflowPayload | null;
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
  onBStoryJudgement?: (payload: {
    action: "force_resolve" | "reject";
    resolved_b_stories?: string[];
    resolution_evidence_event_ids?: string[];
    resolution_analysis?: string;
    reject_resume_from?: string;
    reason?: string;
  }) => Promise<void>;
  onAnchorDelay?: (payload: { anchor_id: string; new_chapter_target: number; reason?: string }) => Promise<void>;
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
  mergeHintsOnDraft: z.boolean().default(false),
  chapterType: z.string().default(""),
  bStoryDirective: z.string().default(""),
  bStoryType: z.string().default(""),
  newElementsLines: z.string().default(""),
  narrativeDirective: z.string().default(""),
  anchorId: z.string().default(""),
  anchorChapterInput: z.string().default("1"),
  bResolved: z.array(z.string()).default([]),
  bEvidence: z.array(z.string()).default([]),
  bAnalysis: z.string().default(""),
  bRejectResume: z.string().default("extraction_gate"),
  pruneProductTier: z.number().min(0).max(2).default(0),
  alignmentRulesInput: z.string().default(""),
  pacingLimitInput: z.string().default(""),
  futureAnchorTitle: z.string().default(""),
  futureAnchorDesc: z.string().default(""),
  futureAnchorDelay: z.string().default(""),
  remaps: z
    .array(
      z.object({
        from_node_id: z.string().trim().min(1, "source required"),
        to_node_id: z.string().trim().min(1, "target required"),
      }),
    )
    .default([]),
  waiveIdsComma: z.string().default(""),
  injectionJson: z.string().default("[]"),
  advancedInjectAck: z.boolean().default(false),
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
  variant = "default",
  busy = false,
  workflowError = "",
  onDecision,
  onOutlineEdit,
  onStateInjection,
  onDraftEdit,
  onDirectorPatch = asyncNoop,
  onExtractionRemap = asyncNoop,
  onBStoryJudgement = asyncNoop,
  onAnchorDelay = asyncNoop,
  onContextPrune = asyncNoop,
}: Props) {
  const { locale } = useI18n();
  const t = (zhHant: string, zhHans: string, en: string) => {
    if (locale === "en") return en;
    if (locale === "zh-Hans") return zhHans;
    return zhHant;
  };
  const [remapHintsView, setRemapHintsView] = useState("[]");
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [selectedSolution, setSelectedSolution] = useState<HitlSolutionId | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [uiMode, setUiMode] = useState<"recommended" | "expert">("recommended");
  const [tokenInput, setTokenInput] = useState("");
  const [tokenInputEvidence, setTokenInputEvidence] = useState("");
  const form = useForm<HitlFormValues>({
    resolver: zodResolver(formSchema) as never,
    mode: "onChange",
    defaultValues: {
      narrativeScript: "Manual narrative script from author.",
      outlineEvents: [{ event_id: "event_manual_01", description: "Manually adjusted event", caused_by_event_id: "" }],
      draftText: "",
      draftResumeFrom: "reader",
      mergeHintsOnDraft: false,
      chapterType: "",
      bStoryDirective: "",
      bStoryType: "",
      newElementsLines: "",
      narrativeDirective: "",
      anchorId: "",
      anchorChapterInput: "1",
      bResolved: [],
      bEvidence: [],
      bAnalysis: "",
      bRejectResume: "extraction_gate",
      pruneProductTier: 0,
      alignmentRulesInput: "",
      pacingLimitInput: "",
      futureAnchorTitle: "",
      futureAnchorDesc: "",
      futureAnchorDelay: "",
      remaps: [{ from_node_id: "ghost_01", to_node_id: "planned_01" }],
      waiveIdsComma: "",
      injectionJson:
        '[{"action":"CREATE_NODE","node_id":"item_backup_relic","node_type":"ITEM","properties":{"canonical_name":"backup_item","description":"HITL injected"}}]',
      advancedInjectAck: false,
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
  const situation = getSituationCopy(reason);
  const feedbackLines = useMemo(
    () => (workflow?.state ? buildFeedbackSummary(workflow.state as Record<string, unknown>, reason) : []),
    [workflow?.state, reason],
  );
  const solutionList = useMemo(() => solutionsForReason(reason), [reason]);
  const remapHintRows = useMemo(() => parseRemapHintsJson(remapHintsView), [remapHintsView]);
  const bStoryDisplay = useMemo(() => formatBStoryCandidateForDisplay(watch("bAnalysis")), [watch("bAnalysis")]);
  const remapCandidateIds = useMemo(() => {
    const from = new Set<string>();
    const to = new Set<string>();
    for (const row of remapHintRows) {
      const fromId = String(
        row.from_node_id ?? row.unknown_node_id ?? row.unknown_entity_id ?? row.extracted_node_id ?? "",
      ).trim();
      const toId = String(row.to_node_id ?? row.target_node_id ?? row.candidate_node_id ?? row.matched_node_id ?? "").trim();
      if (fromId) from.add(fromId);
      if (toId) to.add(toId);
    }
    return {
      from: Array.from(from),
      to: Array.from(to),
    };
  }, [remapHintRows]);

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
    const st = workflow.state;
    if (isDirectorPatchReason(reason)) {
      setValue("chapterType", String(st.chapter_type ?? ""));
      setValue("bStoryDirective", st.b_story_directive != null ? String(st.b_story_directive) : "");
      setValue("bStoryType", st.b_story_type != null ? String(st.b_story_type) : "");
      const ne = st.new_elements_to_introduce;
      setValue("newElementsLines", Array.isArray(ne) ? (ne as string[]).map((x) => String(x)).join("\n") : "");
      setValue("narrativeDirective", String(st.narrative_directive ?? ""));
      const anchors = (st.unachieved_anchors as Array<{ anchor_id?: string }> | undefined) ?? [];
      const first = anchors[0]?.anchor_id;
      if (first) setValue("anchorId", String(first));
      const cid = Number(st.chapter_id ?? 1);
      setValue("anchorChapterInput", String(cid + 1));
    }
    if (reason === HITL_REASON.EXTRACTION_GATE) {
      const h = st.hitl_extraction_remap_hints;
      setRemapHintsView(JSON.stringify(h ?? [], null, 2));
      const rows = Array.isArray(h)
        ? h
            .map((row) => {
              const r = row as Record<string, unknown>;
              const fromId = String(
                r.from_node_id ?? r.unknown_node_id ?? r.unknown_entity_id ?? r.extracted_node_id ?? "",
              ).trim();
              const toId = String(r.to_node_id ?? r.target_node_id ?? r.candidate_node_id ?? r.matched_node_id ?? "").trim();
              return fromId || toId ? { from_node_id: fromId, to_node_id: toId } : null;
            })
            .filter(Boolean) as Array<{ from_node_id: string; to_node_id: string }>
        : [];
      if (rows.length) {
        remapArray.replace(rows);
      }
    }
    if (reason === HITL_REASON.B_STORY) {
      const cand = st.b_story_resolution_hitl_candidate;
      if (cand && typeof cand === "object") {
        setValue("bAnalysis", JSON.stringify(cand, null, 2));
        const c = cand as Record<string, unknown>;
        const suggestedB = Array.isArray(c.suggested_resolved_b_stories) ? c.suggested_resolved_b_stories : [];
        const suggestedE = Array.isArray(c.suggested_resolution_evidence_event_ids) ? c.suggested_resolution_evidence_event_ids : [];
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
      setValue("alignmentRulesInput", String(st.chapter_hard_rules ?? ""));
    }
  }, [hitlActive, reason, workflow?.run.run_id, workflow?.run.hitl_context, workflow?.state, remapArray, setValue]);

  useEffect(() => {
    if (!hitlActive) {
      setUiMode("recommended");
    }
  }, [hitlActive, workflow?.run.run_id]);

  const shell = compact
    ? "glass-panel rounded-xl border border-outline-variant/15 p-4 shadow-glow"
    : "rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow";
  const inputClass = compact ? "auteur-input mt-1 text-xs" : "auteur-input mt-1 text-sm";
  const btnClass = "btn-secondary mt-2 w-full text-xs";
  const taRows = (n: number) => (compact ? Math.max(3, n - 2) : n);

  const waiveList = (): string[] =>
    String(getValues("waiveIdsComma") ?? "")
      .split(/[,，\s]+/)
      .map((s: string) => s.trim())
      .filter(Boolean);

  const decisionMode = String(workflow?.run.hitl_decision_mode ?? "");

  return (
    <section className={shell}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-headline text-sm font-bold uppercase tracking-wider text-tertiary">
          {locale === "en" ? "Need Your Input" : locale === "zh-Hans" ? "需要你协助" : "需要您協助"}
        </h2>
        {hitlActive ? (
          <button
            type="button"
            className="shrink-0 rounded-md border border-error/50 bg-error/15 px-2 py-1 font-label text-[11px] font-semibold text-error hover:bg-error/25 disabled:opacity-40"
            disabled={controlsLocked}
            onClick={() => onDecision("ABORT_AND_RESTART")}
          >
            {locale === "en" ? "Abort this draft and restart" : locale === "zh-Hans" ? "放弃本章草稿并重跑" : "放棄本章草稿，打掉重練"}
          </button>
        ) : null}
      </div>
      <p className="mb-3 font-body text-sm text-on-surface-variant">
        {hitlActive ? (
          <>
            <strong className="text-tertiary">{t("流程已暫停", "流程已暂停", "Workflow Paused")}</strong>
            <span className="text-on-surface-variant">
              {" "}
              · {hitlDecisionModeLabel(decisionMode)}
            </span>
          </>
        ) : (
          locale === "en" ? "No pending HITL step." : locale === "zh-Hans" ? "目前没有等待你处理的步骤。" : "目前沒有等待您處理的步驟。"
        )}
      </p>
      {hitlActive ? (
        <div
          className="mb-3 inline-flex rounded-lg border border-outline-variant/25 bg-surface-container-highest/30 p-1"
          role="tablist"
          aria-label={t("HITL 模式切換", "HITL 模式切换", "HITL Mode Switch")}
        >
          <button
            type="button"
            id="hitl-mode-recommended"
            role="tab"
            aria-controls="hitl-mode-panel"
            aria-selected={uiMode === "recommended"}
            className={`rounded-md px-3 py-1 text-xs ${uiMode === "recommended" ? "bg-primary/20 text-primary" : "text-on-surface-variant"}`}
            disabled={controlsLocked}
            onClick={() => setUiMode("recommended")}
          >
            {locale === "en" ? "Recommended" : locale === "zh-Hans" ? "建议模式" : "建議模式"}
          </button>
          <button
            type="button"
            id="hitl-mode-expert"
            role="tab"
            aria-controls="hitl-mode-panel"
            aria-selected={uiMode === "expert"}
            className={`rounded-md px-3 py-1 text-xs ${uiMode === "expert" ? "bg-secondary/20 text-secondary" : "text-on-surface-variant"}`}
            disabled={controlsLocked}
            onClick={() => setUiMode("expert")}
          >
            {locale === "en" ? "Expert" : locale === "zh-Hans" ? "专家模式" : "專家模式"}
          </button>
        </div>
      ) : null}

      {hitlActive ? (
        <>
          {workflowError.trim() ? (
            <div className="mb-3 rounded-lg border border-error/40 bg-error/10 px-3 py-2 font-body text-sm text-error">{workflowError.trim()}</div>
          ) : null}
          <div className="mb-4 rounded-lg border border-tertiary/20 bg-tertiary/5 px-3 py-3">
            <h3 className="font-headline text-sm font-bold text-on-surface">{situation.title}</h3>
            <p className="mt-2 font-body text-sm leading-relaxed text-on-surface-variant">{situation.why}</p>
            {hitlContext?.primary_issue ? (
                  <p className="mt-2 rounded-md bg-surface-container-highest/60 px-2 py-2 font-body text-xs text-on-surface">{hitlContext.primary_issue}</p>
            ) : null}
            {hitlContext?.context_metadata?.payload_type === "output_language" &&
            hitlContext.context_metadata.expected_output_language ? (
              <p className="mt-2 font-label text-xs text-on-surface-variant">
                {locale === "en" ? "Project output language: " : locale === "zh-Hans" ? "项目输出语言：" : "專案輸出語言："}
                <span className="text-on-surface">{String(hitlContext.context_metadata.expected_output_language)}</span>
              </p>
            ) : null}
            {hitlContext?.context_metadata?.language_detection_summary ? (
              <p className="mt-1 font-body text-xs text-on-surface-variant">{hitlContext.context_metadata.language_detection_summary}</p>
            ) : null}
            {reason === HITL_REASON.CONTEXT ? (
              <p className="mt-2 font-label text-xs text-on-surface-variant">
                {locale === "en"
                  ? `Estimated context size is ${String(workflow?.state.context_overflow_char_estimate ?? "—")} chars; please trim as needed.`
                  : locale === "zh-Hans"
                    ? `当前估算参考内容约 ${String(workflow?.state.context_overflow_char_estimate ?? "—")} 字，请按需删减。`
                    : `目前估算參考內容約 ${String(workflow?.state.context_overflow_char_estimate ?? "—")} 字，請視情況刪減。`}
              </p>
            ) : null}
            <p className="mt-2 font-label text-xs text-on-surface-variant">
              {locale === "en"
                ? `Resume point is near "${resumeNodeUserLabel(resumeHint)}" (may change by your decision).`
                : locale === "zh-Hans"
                  ? `暂停后会从「${resumeNodeUserLabel(resumeHint)}」附近接续（会随你的选择改变）。`
                  : `暫停後會從「${resumeNodeUserLabel(resumeHint)}」附近接續（依您選擇可能變更）。`}
            </p>
          </div>

          {feedbackLines.length > 0 ? (
            <div className="mb-4 rounded-lg bg-surface-container-highest/50 px-3 py-2">
              <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">
                {t("系統剛才的說明", "系统刚才的说明", "System Feedback")}
              </p>
              <ul className="mt-1 list-inside list-disc font-body text-sm text-on-surface">
                {feedbackLines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {reason === HITL_REASON.B_STORY && rawOptions.some((o) => o.id === "b_story_wait_judgement") ? (
            <p className="mb-3 rounded-lg bg-primary/10 px-3 py-2 font-body text-sm text-on-surface">
              {locale === "en"
                ? "Choose an action and fill the form below to resolve subplot status."
                : locale === "zh-Hans"
                  ? "请在下方选择做法并填写表单，决定副线是否已收尾；无需使用其他按钮。"
                  : "請在下方選擇做法並填寫表單，決定副線是否已收尾；無需使用其他按鈕。"}
            </p>
          ) : null}
          {reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED ? (
            <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 px-3 py-3" aria-live="polite">
              <p className="font-label text-xs font-semibold text-on-surface">
                {t("Alignment 需要你補充章節硬性規則", "Alignment 需要你补充章节硬性规则", "Alignment requires hard rules for this chapter")}
              </p>
              <blockquote className="mt-2 border-l-2 border-warning/60 pl-3 font-body text-xs text-on-surface-variant">
                {String(workflow?.state.alignment_log ?? "").trim() ||
                  t("請補充可執行的勝負條件與判定流程。", "请补充可执行的胜负条件与判定流程。", "Please provide executable win conditions and judging flow.")}
              </blockquote>
              <textarea
                className={inputClass}
                rows={taRows(4)}
                disabled={controlsLocked}
                placeholder={t("補充本章硬性規則：勝負條件、回合流程、籌碼/代價、可用策略邊界", "补充本章硬性规则：胜负条件、回合流程、筹码/代价、可用策略边界", "Add hard rules: win conditions, turns, costs, strategy boundaries")}
                {...register("alignmentRulesInput")}
              />
              {!watch("alignmentRulesInput").trim() ? (
                <p className="mt-1 font-body text-xs text-error">{t("請填寫硬性規則後再繼續。", "请填写硬性规则后继续。", "Please fill hard rules before continuing.")}</p>
              ) : null}
              <label className="auteur-label mt-2">{t("本章節奏煞車（可選；禁止本章寫出最終結局）", "本章节节奏刹车（可选；禁止本章写出最终结局）", "Pacing brake (optional; block final ending this chapter)")}</label>
              <textarea className={inputClass} rows={2} disabled={controlsLocked} placeholder={t("例：本章只允許試探與懸念，不得揭露真凶身分。", "例：本章只允许试探与悬念，不得揭露真凶身份。", "e.g. only probing/suspense, no true culprit reveal")} {...register("pacingLimitInput")} />
              <p className="mt-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("未來結局錨點（可選）", "未来结局锚点（可选）", "Future Ending Anchor (optional)")}</p>
              <input className={inputClass} disabled={controlsLocked} placeholder={t("錨點標題", "锚点标题", "Anchor title")} {...register("futureAnchorTitle")} />
              <textarea className={inputClass} rows={2} disabled={controlsLocked} placeholder={t("錨點描述（可空）", "锚点描述（可空）", "Anchor description (optional)")} {...register("futureAnchorDesc")} />
              <label className="auteur-label mt-1">{t("延遲幾章後觸發（空白表示 0）", "延迟几章后触发（空白表示 0）", "Delay chapters before trigger (blank=0)")}</label>
              <input type="number" min={0} className={inputClass} disabled={controlsLocked} placeholder="0" {...register("futureAnchorDelay")} />
              <button
                type="button"
                className={btnClass}
                disabled={controlsLocked || !watch("alignmentRulesInput").trim()}
                onClick={() => {
                  if (!watch("alignmentRulesInput").trim()) return;
                  const raw = watch("futureAnchorDelay").trim();
                  const parsed = raw === "" ? null : Number.parseInt(raw, 10);
                  const chapters_to_delay = parsed != null && Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
                  onStateInjection({
                    mutations: [],
                    chapter_hard_rules: watch("alignmentRulesInput"),
                    resume_from: "logic_alignment",
                    reason: "alignment_rules_patch",
                    this_chapter_pacing_limit: watch("pacingLimitInput").trim(),
                    future_anchor_title: watch("futureAnchorTitle").trim(),
                    future_anchor_description: watch("futureAnchorDesc").trim(),
                    chapters_to_delay,
                  });
                }}
              >
                {t("套用硬性規則並繼續", "应用硬性规则并继续", "Apply Rules and Continue")}
              </button>
            </div>
          ) : null}

          {options.length > 0 ? (
            <div className="mb-4">
              <p className="mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("可先一鍵處理", "可先一键处理", "Quick Actions")}</p>
              <div className="flex flex-col gap-2">
                {options.map((option) => (
                  <div key={option.id} className="rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 p-2">
                    <button
                      type="button"
                      disabled={controlsLocked}
                      onClick={() => {
                        if (option.id === "force_approve_plan") {
                          setPreview({
                            title: t("送出前預覽：強制放行大綱", "提交前预览：强制放行大纲", "Preview: Force Approve Outline"),
                            bullets: [
                              t("此操作會直接以目前大綱進入 Author。", "此操作会直接以当前大纲进入 Author。", "This goes directly to Author with current outline."),
                              t("後續若邏輯不足，可能增加草稿重寫成本。", "后续若逻辑不足，可能增加草稿重写成本。", "Weak logic may increase rewrite cost later."),
                            ],
                            confirmLabel: t("確認強制放行", "确认强制放行", "Confirm Force Approve"),
                            onConfirm: () => void onDecision(option.id),
                          });
                          return;
                        }
                        void onDecision(option.id);
                      }}
                      className="w-full rounded-md bg-primary/15 px-3 py-2 text-left font-label text-sm font-medium text-primary transition-colors hover:bg-primary/25 disabled:opacity-40"
                    >
                      {option.label}
                    </button>
                    {OPTION_DECISION_HINTS[option.id] ? (
                      <p className="mt-1.5 px-1 font-body text-xs text-on-surface-variant">{OPTION_DECISION_HINTS[option.id]}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {solutionList.length > 0 ? (
            <div className="mb-3">
              <p className="mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("選擇做法", "选择做法", "Choose a Solution")}</p>
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

          <div id="hitl-mode-panel" role="tabpanel" aria-labelledby={uiMode === "recommended" ? "hitl-mode-recommended" : "hitl-mode-expert"} className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4">
            {selectedSolution === "outline" && isPlanFamilyReason(reason) ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("手動調整事件大綱", "手动调整事件大纲", "Manually Edit Event Outline")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  {t("以卡片直接調整事件（可拖曳排序），不需要手寫 JSON。", "以卡片直接调整事件（可拖拽排序），不需要手写 JSON。", "Adjust events with cards (drag-sort), no raw JSON needed.")}
                </p>
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
                        <span className="font-label text-[10px] text-on-surface-variant">{t("事件", "事件", "Event")} {idx + 1}</span>
                        <button type="button" className="btn-secondary ml-auto text-[10px]" disabled={controlsLocked || outlineArray.fields.length <= 1} onClick={() => outlineArray.remove(idx)}>
                          {t("刪除", "删除", "Delete")}
                        </button>
                      </div>
                      <input className={inputClass} placeholder="event_id" disabled={controlsLocked} {...register(`outlineEvents.${idx}.event_id`)} />
                      <textarea className={inputClass} rows={taRows(2)} placeholder={t("事件描述", "事件描述", "Event description")} disabled={controlsLocked} {...register(`outlineEvents.${idx}.description`)} />
                      <input className={inputClass} placeholder={t("caused_by_event_id（可空）", "caused_by_event_id（可空）", "caused_by_event_id (optional)")} disabled={controlsLocked} {...register(`outlineEvents.${idx}.caused_by_event_id`)} />
                    </div>
                  ))}
                </div>
                <button type="button" className={btnClass} disabled={controlsLocked} onClick={() => outlineArray.append({ event_id: "", description: "", caused_by_event_id: "" })}>
                  {t("新增事件卡片", "新增事件卡片", "Add Event Card")}
                </button>
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
                      title: t("送出前預覽：事件大綱變更", "提交前预览：事件大纲变更", "Preview: Outline Changes"),
                      bullets: [
                        t(`新增事件 ${added.length} 筆`, `新增事件 ${added.length} 笔`, `Added events: ${added.length}`),
                        t(`刪除事件 ${removed.length} 筆`, `删除事件 ${removed.length} 笔`, `Removed events: ${removed.length}`),
                        t(`最終事件總數 ${nextEvents.length} 筆`, `最终事件总数 ${nextEvents.length} 笔`, `Final event count: ${nextEvents.length}`),
                      ],
                      confirmLabel: t("確認套用大綱", "确认套用大纲", "Confirm Apply Outline"),
                      onConfirm: () =>
                        void onOutlineEdit({
                          ground_truth_events: nextEvents as Array<Record<string, unknown>>,
                          narrative_script: getValues("narrativeScript"),
                        }),
                    });
                  }}
                >
                  {t("預覽並套用大綱", "预览并套用大纲", "Preview and Apply Outline")}
                </button>
              </>
            ) : null}

            {selectedSolution === "anchor" && reason === HITL_REASON.PLAN_LOOP ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("延後故事里程碑", "延后故事里程碑", "Delay Story Milestone")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  {t("指定要延後的節點代號，以及希望改到哪一章再達成。", "指定要延后的节点代号，以及希望改到哪一章达成。", "Choose milestone ID and target chapter to delay to.")}
                </p>
                <label className="auteur-label">{t("里程碑代號", "里程碑代号", "Milestone ID")}</label>
                <input className={inputClass} disabled={controlsLocked} {...register("anchorId")} />
                <label className="auteur-label mt-2">{t("改到第幾章", "改到第几章", "Move to Chapter")}</label>
                <input type="number" min={1} className={inputClass} disabled={controlsLocked} {...register("anchorChapterInput")} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked || !watch("anchorId").trim()}
                  onClick={() => {
                    const n = Number.parseInt(getValues("anchorChapterInput").trim(), 10);
                    if (!Number.isFinite(n) || n < 1) return;
                    void onAnchorDelay({ anchor_id: getValues("anchorId").trim(), new_chapter_target: n });
                  }}
                >
                  {t("儲存並回到劇情規劃", "保存并回到剧情规划", "Save and Return to Planning")}
                </button>
              </>
            ) : null}

            {selectedSolution === "director" && isDirectorPatchReason(reason) ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("微調章節方向與副線", "微调章节方向与副线", "Tune Chapter Direction & Subplot")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  {t("這些欄位會影響本章定位與副線走向，請用簡短中文填寫即可。", "这些栏位会影响本章定位与副线走向，请简短填写。", "These fields affect chapter direction and subplot routing. Keep it concise.")}
                </p>
                <label className="auteur-label">{t("章節類型（例：過渡／高潮）", "章节类型（例：过渡/高潮）", "Chapter type (e.g. transition/climax)")}</label>
                <input className={inputClass} disabled={controlsLocked} {...register("chapterType")} />
                <label className="auteur-label mt-2">{t("副線指示", "副线指示", "Subplot directive")}</label>
                <input className={inputClass} disabled={controlsLocked} {...register("bStoryDirective")} />
                <label className="auteur-label mt-2">{t("副線類型標籤", "副线类型标签", "Subplot type tag")}</label>
                <input className={inputClass} disabled={controlsLocked} {...register("bStoryType")} />
                <label className="auteur-label mt-2">{t("想新登場的元素（每行一項）", "想新登场的元素（每行一项）", "New elements to introduce (one per line)")}</label>
                <textarea className={inputClass} rows={taRows(3)} disabled={controlsLocked} {...register("newElementsLines")} />
                <label className="auteur-label mt-2">{t("主線／敘事指示", "主线/叙事指示", "Main plot / narrative directive")}</label>
                <input className={inputClass} disabled={controlsLocked} {...register("narrativeDirective")} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() =>
                    onDirectorPatch({
                      chapter_type: getValues("chapterType") || undefined,
                      b_story_directive: getValues("bStoryDirective"),
                      b_story_type: getValues("bStoryType") || null,
                      new_elements_to_introduce: getValues("newElementsLines")
                        .split("\n")
                        .map((s) => s.trim())
                        .filter(Boolean),
                      narrative_directive: getValues("narrativeDirective") || undefined,
                    })
                  }
                >
                  {t("套用並繼續", "套用并继续", "Apply and Continue")}
                </button>
              </>
            ) : null}

            {selectedSolution === "draft" && reason === HITL_REASON.DRAFT_LOOP ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("修改章節內文", "修改章节正文", "Edit Chapter Draft")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  {t("專名對照線索請在下次「開始撰寫本章」時，於章節執行請求一併送出（無法在此 HITL 面板補送）。", "专名对照线索请在下次“开始撰写本章”时于执行请求一并送出（无法在此面板补送）。", "Naming hints must be submitted with the next chapter run request (not from this panel).")}
                </p>
                <label className="flex items-center gap-2 font-label text-xs text-on-surface-variant">
                  <input type="checkbox" disabled={controlsLocked} {...register("mergeHintsOnDraft")} />
                  {t("保留已蒐集的專名線索", "保留已收集的专名线索", "Keep collected naming hints")}
                </label>
                <label className="auteur-label">{t("接下來從哪一步再檢查", "接下来从哪一步再检查", "Resume from step")}</label>
                <select className={inputClass} disabled={controlsLocked} {...register("draftResumeFrom")}>
                  {DRAFT_RESUME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
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
                      merge_extraction_hints: getValues("mergeHintsOnDraft"),
                    })
                  }
                >
                  {t("提交內文並繼續", "提交正文并继续", "Submit Draft and Continue")}
                </button>
              </>
            ) : null}

            {selectedSolution === "remap" && reason === HITL_REASON.EXTRACTION_GATE ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("對照角色與道具", "对照角色与道具", "Map Characters and Items")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  {t("系統猜測如下，請核對；手動對照請編輯下方結構化對照表。", "系统猜测如下，请核对；手动对照请编辑下方结构化表。", "Review guessed mappings below, or edit structured mappings manually.")}
                </p>
                {remapHintRows.length > 0 ? (
                  <div className="mb-3 max-h-40 overflow-auto rounded-lg border border-outline-variant/15 text-xs">
                    <table className="w-full border-collapse font-body text-on-surface">
                      <thead className="sticky top-0 bg-surface-container-highest font-label text-[10px] uppercase text-on-surface-variant">
                        <tr>
                          {Object.keys(remapHintRows[0] ?? {})
                            .slice(0, 6)
                            .map((k) => (
                              <th key={k} className="border-b border-outline-variant/20 px-2 py-1 text-left font-medium">
                                {k}
                              </th>
                            ))}
                        </tr>
                      </thead>
                      <tbody>
                        {remapHintRows.map((row, ri) => (
                          <tr key={ri} className="border-b border-outline-variant/10">
                            {Object.keys(remapHintRows[0] ?? {})
                              .slice(0, 6)
                              .map((k) => (
                                <td key={k} className="px-2 py-1 align-top text-on-surface-variant">
                                  {formatCell(row[k])}
                                </td>
                              ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="mb-2 font-body text-xs text-on-surface-variant">{t("目前沒有表格化猜測，請依內文自行填寫對照。", "目前没有表格化猜测，请按内文自行填写映射。", "No tabular hints available; fill mappings manually.")}</p>
                )}
                <div className="space-y-2">
                  {remapArray.fields.map((field, idx) => (
                    <div key={field.id} className="grid grid-cols-1 gap-2 rounded-lg border border-outline-variant/15 p-2 md:grid-cols-[1fr_1fr_auto]">
                      <select className={inputClass} disabled={controlsLocked} {...register(`remaps.${idx}.from_node_id`)}>
                        <option value="">{t("選擇文中節點", "选择文中节点", "Select source node")}</option>
                        {remapCandidateIds.from.map((id) => (
                          <option key={id} value={id}>
                            {id}
                          </option>
                        ))}
                      </select>
                      <select className={inputClass} disabled={controlsLocked} {...register(`remaps.${idx}.to_node_id`)}>
                        <option value="">{t("選擇設定節點", "选择设定节点", "Select target node")}</option>
                        {remapCandidateIds.to.map((id) => (
                          <option key={id} value={id}>
                            {id}
                          </option>
                        ))}
                      </select>
                      <button type="button" className="btn-secondary" disabled={controlsLocked || remapArray.fields.length <= 1} onClick={() => remapArray.remove(idx)}>
                        {t("刪除", "删除", "Delete")}
                      </button>
                    </div>
                  ))}
                </div>
                <button type="button" className={btnClass} disabled={controlsLocked} onClick={() => remapArray.append({ from_node_id: "", to_node_id: "" })}>
                  {t("新增對照列", "新增对照行", "Add Mapping Row")}
                </button>
                {uiMode === "expert" ? (
                  <>
                    <label className="auteur-label mt-2">{t("可略過的必填項目代號（逗號分隔，進階）", "可略过的必填项代号（逗号分隔，进阶）", "Skippable required IDs (advanced)")}</label>
                    <input className={inputClass} disabled={controlsLocked} {...register("waiveIdsComma")} />
                  </>
                ) : null}
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() => {
                    const rows = getValues("remaps").map((r) => ({
                      from_node_id: r.from_node_id.trim(),
                      to_node_id: r.to_node_id.trim(),
                    })).filter((r) => r.from_node_id && r.to_node_id);
                    setPreview({
                      title: t("送出前預覽：角色/道具對照", "提交前预览：角色/道具对照", "Preview: Character/Item Mapping"),
                      bullets: rows
                        .slice(0, 6)
                        .map((r) => `${r.from_node_id} -> ${r.to_node_id}`)
                        .concat(
                          rows.length > 6
                            ? [
                                t(
                                  `... 另 ${rows.length - 6} 筆`,
                                  `... 另 ${rows.length - 6} 笔`,
                                  `... and ${rows.length - 6} more`,
                                ),
                              ]
                            : [],
                        ),
                      confirmLabel: t("確認套用對照", "确认套用对照", "Confirm Apply Mapping"),
                      onConfirm: () =>
                        void onExtractionRemap({
                          entity_remaps: uiMode === "expert" ? rows : rows.slice(0, Math.max(1, rows.length)),
                          waive_mandatory_node_ids: uiMode === "expert" ? waiveList() : [],
                        }),
                    });
                  }}
                >
                  {t("預覽並套用對照", "预览并套用对照", "Preview and Apply Mapping")}
                </button>
              </>
            ) : null}

            {selectedSolution === "b_story" && reason === HITL_REASON.B_STORY ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("副線收尾判定", "副线收尾判定", "Subplot Resolution Decision")}</h3>
                {bStoryDisplay.bullets.length > 0 ? (
                  <ul className="mb-2 list-inside list-disc font-body text-sm text-on-surface">
                    {bStoryDisplay.bullets.map((b, i) => (
                      <li key={i}>{b}</li>
                    ))}
                  </ul>
                ) : null}
                <label className="auteur-label">{t("補充說明（會一併存檔）", "补充说明（会一并存档）", "Additional notes (saved)")}</label>
                <textarea className={inputClass} rows={taRows(4)} disabled={controlsLocked} {...register("bAnalysis")} />
                <label className="auteur-label mt-2">{t("視為已收尾的副線名稱代號（逗號分隔）", "视为已收尾的副线名称代号（逗号分隔）", "Resolved subplot IDs (comma-separated)")}</label>
                <TokenEditor
                  values={watch("bResolved")}
                  onAdd={(v) => setValue("bResolved", Array.from(new Set([...watch("bResolved"), v])))}
                  onRemove={(v) => setValue("bResolved", watch("bResolved").filter((x) => x !== v))}
                  input={tokenInput}
                  onInput={setTokenInput}
                  disabled={controlsLocked}
                />
                <label className="auteur-label mt-2">{t("當作證據的情節事件代號（逗號分隔）", "作为证据的情节事件代号（逗号分隔）", "Evidence event IDs (comma-separated)")}</label>
                <TokenEditor
                  values={watch("bEvidence")}
                  onAdd={(v) => setValue("bEvidence", Array.from(new Set([...watch("bEvidence"), v])))}
                  onRemove={(v) => setValue("bEvidence", watch("bEvidence").filter((x) => x !== v))}
                  input={tokenInputEvidence}
                  onInput={setTokenInputEvidence}
                  disabled={controlsLocked}
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={btnClass + " flex-1"}
                    disabled={controlsLocked}
                    onClick={() =>
                      onBStoryJudgement({
                        action: "force_resolve",
                        resolved_b_stories: watch("bResolved"),
                        resolution_evidence_event_ids: watch("bEvidence"),
                        resolution_analysis: watch("bAnalysis"),
                      })
                    }
                  >
                    {t("確認已收尾", "确认已收尾", "Confirm Resolved")}
                  </button>
                  <button
                    type="button"
                    className={btnClass + " flex-1"}
                    disabled={controlsLocked}
                    onClick={() =>
                      onBStoryJudgement({
                        action: "reject",
                        reject_resume_from: watch("bRejectResume"),
                        reason: watch("bAnalysis").slice(0, 500),
                      })
                    }
                  >
                    {t("打回、回到前段", "打回、回到前段", "Reject and Return")}
                  </button>
                </div>
                <label className="auteur-label mt-2">{t("打回後從哪一步重來", "打回后从哪一步重来", "Resume step after reject")}</label>
                <select className={inputClass} disabled={controlsLocked} {...register("bRejectResume")}>
                  {B_STORY_REJECT_RESUME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </>
            ) : null}

            {selectedSolution === "prune" && reason === HITL_REASON.CONTEXT ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">{t("精簡參考資料", "精简参考资料", "Prune Context")}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  {t("選擇組裝層級：後端會依層級自動縮減圖譜與向量脈絡（0=最完整，2=最精簡）。", "选择组装层级：后端会依层级自动缩减图谱与向量脉络（0=最完整，2=最精简）。", "Choose assembly level: backend auto-prunes graph/vector context (0 fullest, 2 leanest).")}
                </p>
                <div className="flex flex-col gap-2">
                  {(
                    [
                      { v: 0, label: t("層級 0 — 盡量完整", "层级 0 — 尽量完整", "Tier 0 — fullest") },
                      { v: 1, label: t("層級 1 — 中度瘦身", "层级 1 — 中度瘦身", "Tier 1 — moderate") },
                      { v: 2, label: t("層級 2 — 積極瘦身", "层级 2 — 积极瘦身", "Tier 2 — aggressive") },
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
                  {t("套用並重新整理背景", "套用并重新整理背景", "Apply and Refresh Context")}
                </button>
              </>
            ) : null}

            {hitlActive && solutionList.length === 0 ? (
              <p className="font-body text-sm text-on-surface-variant">
                {t("此暫停沒有專用表單。若上方有「一鍵處理」請優先使用；否則請展開下方進階選項。", "此暂停没有专用表单。若上方有“一键处理”请优先使用；否则请展开下方进阶选项。", "No dedicated form for this pause. Use quick action first or open advanced options.")}
              </p>
            ) : null}
            {hitlActive && solutionList.length > 0 && selectedSolution == null ? (
              <p className="font-body text-sm text-on-surface-variant">{t("請選擇上方做法。", "请选择上方做法。", "Choose a solution above.")}</p>
            ) : null}
          </div>

          {uiMode === "expert" ? (
            <details className="mt-4 rounded-xl border border-outline-variant/15 bg-surface-container-highest/20 p-3" open={advancedOpen} onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}>
            <summary className="cursor-pointer font-label text-sm font-semibold text-on-surface-variant">
              {t("進階：僅在熟悉系統時使用", "进阶：仅在熟悉系统时使用", "Advanced: for experienced users only")}
            </summary>
            <div className="mt-3 space-y-3 border-t border-outline-variant/10 pt-3">
              <p className="font-mono text-[10px] text-on-surface-variant">
                {t("內部原因碼", "内部原因码", "Reason code")}：{reason || "—"} · resume：{resumeHint || "—"}
              </p>
              <div>
                <h4 className="font-label text-xs font-bold text-on-surface">{t("直接寫入故事資料（進階結構化）", "直接写入故事资料（进阶结构化）", "Direct story mutation (advanced)")}</h4>
                <p className="mb-1 font-body text-[10px] text-on-surface-variant">{t("錯誤操作可能破壞資料，請謹慎。", "错误操作可能破坏资料，请谨慎。", "Wrong operations may corrupt data. Proceed carefully.")}</p>
                <textarea className={inputClass} rows={taRows(6)} disabled={controlsLocked} {...register("injectionJson")} />
                <label className="mt-2 flex cursor-pointer items-start gap-2 font-body text-xs text-on-surface">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    {...register("advancedInjectAck")}
                    disabled={controlsLocked}
                  />
                  <span>{t("我已了解此操作會直接變更故事圖譜資料，且可能無法還原。", "我已了解此操作会直接变更故事图谱资料，且可能无法还原。", "I understand this directly mutates story graph data and may be irreversible.")}</span>
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
                      title: t("送出前預覽：直接寫入故事資料", "提交前预览：直接写入故事资料", "Preview: Direct Story Mutation"),
                      bullets: [
                        t(`即將寫入 ${rows.length} 筆 mutation`, `即将写入 ${rows.length} 条 mutation`, `About to write ${rows.length} mutations`),
                        t("此操作可能無法還原，請確認。", "此操作可能无法还原，请确认。", "This may be irreversible. Confirm to proceed."),
                      ],
                      confirmLabel: t("確認執行寫入", "确认执行写入", "Confirm Write"),
                      onConfirm: () => void onStateInjection({
                        mutations: rows,
                      }),
                    });
                  }}
                >
                  {t("執行寫入並繼續", "执行写入并继续", "Write and Continue")}
                </button>
              </div>
            </div>
            </details>
          ) : null}
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
                  {t("返回編輯", "返回编辑", "Back to Edit")}
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

function formatCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v).slice(0, 120);
  const s = String(v);
  return s.length > 120 ? `${s.slice(0, 120)}…` : s;
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
  return (
    <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-2">
      <div className="mb-2 flex flex-wrap gap-2">
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs text-primary">
            {v}
            <button
              type="button"
              className="text-primary/70"
              onClick={() => onRemove(v)}
              disabled={disabled}
              aria-label={`Remove ${v}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          className="auteur-input text-sm"
          value={input}
          disabled={disabled}
          onChange={(e) => onInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            const next = input.trim();
            if (!next) return;
            onAdd(next);
            onInput("");
          }}
          placeholder="Type and press Enter to add"
        />
      </div>
    </div>
  );
}
