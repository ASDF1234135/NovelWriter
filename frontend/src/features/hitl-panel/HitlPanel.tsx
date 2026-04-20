import { useEffect, useMemo, useState } from "react";
import type { HitlContextPayload, WorkflowPayload } from "../../types";
import { HitlFlowStrip } from "./HitlFlowStrip";
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

function parseJsonField(raw: string, label: string): { ok: true; value: unknown } | { ok: false; message: string } {
  try {
    return { ok: true, value: JSON.parse(raw) as unknown };
  } catch {
    return { ok: false, message: `${label}：JSON 格式不正確` };
  }
}

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
  const [outlineJson, setOutlineJson] = useState('[{"event_id":"event_manual_01","description":"人類手動修正事件","caused_by_event_id":null}]');
  const [narrativeScript, setNarrativeScript] = useState("人類手動指定的表層敘事劇本。");
  const [injectionJson, setInjectionJson] = useState(
    '[{"action":"CREATE_NODE","node_id":"item_backup_relic","node_type":"ITEM","properties":{"canonical_name":"備用道具","description":"HITL 強制注入"}}]',
  );
  const [alignmentRulesInput, setAlignmentRulesInput] = useState("");
  const [pacingLimitInput, setPacingLimitInput] = useState("");
  const [futureAnchorTitle, setFutureAnchorTitle] = useState("");
  const [futureAnchorDesc, setFutureAnchorDesc] = useState("");
  const [futureAnchorDelay, setFutureAnchorDelay] = useState("");
  const [draftText, setDraftText] = useState("");
  const [resumeFrom, setResumeFrom] = useState("reader");
  const [mergeHintsOnDraft, setMergeHintsOnDraft] = useState(false);
  const [chapterType, setChapterType] = useState("");
  const [bStoryDirective, setBStoryDirective] = useState("");
  const [bStoryType, setBStoryType] = useState("");
  const [newElementsLines, setNewElementsLines] = useState("");
  const [narrativeDirective, setNarrativeDirective] = useState("");
  const [anchorId, setAnchorId] = useState("");
  const [anchorChapterInput, setAnchorChapterInput] = useState("1");
  const [waiveIdsComma, setWaiveIdsComma] = useState("");
  const [remapJson, setRemapJson] = useState('[{"from_node_id":"ghost_01","to_node_id":"planned_01"}]');
  const [remapHintsView, setRemapHintsView] = useState("[]");
  const [bResolvedCsv, setBResolvedCsv] = useState("");
  const [bEvidenceCsv, setBEvidenceCsv] = useState("");
  const [bAnalysis, setBAnalysis] = useState("");
  const [bRejectResume, setBRejectResume] = useState("extraction_gate");
  const [pruneProductTier, setPruneProductTier] = useState(0);
  const [selectedSolution, setSelectedSolution] = useState<HitlSolutionId | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [outlineJsonError, setOutlineJsonError] = useState("");
  const [remapJsonError, setRemapJsonError] = useState("");
  const [injectionJsonError, setInjectionJsonError] = useState("");
  const [anchorChapterError, setAnchorChapterError] = useState("");
  const [advancedInjectAck, setAdvancedInjectAck] = useState(false);
  const [uiMode, setUiMode] = useState<"simple" | "advanced">("simple");

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
  const bStoryDisplay = useMemo(() => formatBStoryCandidateForDisplay(bAnalysis), [bAnalysis]);

  useEffect(() => {
    if (!hitlActive) return;
    const list = solutionsForReason(reason);
    setSelectedSolution(list.length ? defaultSolutionForReason(reason) : null);
  }, [hitlActive, reason, workflow?.run.run_id]);

  useEffect(() => {
    if (hitlActive && workflow?.state.current_draft != null) {
      setDraftText(String(workflow.state.current_draft));
    }
  }, [hitlActive, workflow?.run.run_id, workflow?.state.current_draft]);

  useEffect(() => {
    if (!hitlActive || !workflow?.state) return;
    const st = workflow.state;
    if (isDirectorPatchReason(reason)) {
      setChapterType(String(st.chapter_type ?? ""));
      setBStoryDirective(st.b_story_directive != null ? String(st.b_story_directive) : "");
      setBStoryType(st.b_story_type != null ? String(st.b_story_type) : "");
      const ne = st.new_elements_to_introduce;
      setNewElementsLines(Array.isArray(ne) ? (ne as string[]).map((x) => String(x)).join("\n") : "");
      setNarrativeDirective(String(st.narrative_directive ?? ""));
      const anchors = (st.unachieved_anchors as Array<{ anchor_id?: string }> | undefined) ?? [];
      const first = anchors[0]?.anchor_id;
      if (first) setAnchorId(String(first));
      const cid = Number(st.chapter_id ?? 1);
      setAnchorChapterInput(String(cid + 1));
    }
    if (reason === HITL_REASON.EXTRACTION_GATE) {
      const h = st.hitl_extraction_remap_hints;
      setRemapHintsView(JSON.stringify(h ?? [], null, 2));
    }
    if (reason === HITL_REASON.B_STORY) {
      const cand = st.b_story_resolution_hitl_candidate;
      if (cand && typeof cand === "object") {
        setBAnalysis(JSON.stringify(cand, null, 2));
      }
    }
    if (reason === HITL_REASON.CONTEXT) {
      const meta = workflow?.run.hitl_context?.context_metadata;
      const suggested = meta?.graph_rag_context_tier;
      if (typeof suggested === "number" && suggested >= 0 && suggested <= 2) {
        setPruneProductTier(suggested);
      } else {
        setPruneProductTier(0);
      }
    }
    if (reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED) {
      setAlignmentRulesInput(String(st.chapter_hard_rules ?? ""));
    }
  }, [hitlActive, reason, workflow?.run.run_id, workflow?.run.hitl_context, workflow?.state]);

  useEffect(() => {
    if (!hitlActive) {
      setUiMode("simple");
    }
  }, [hitlActive, workflow?.run.run_id]);

  const shell = compact
    ? "glass-panel rounded-xl border border-outline-variant/15 p-4 shadow-glow"
    : "rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow";
  const inputClass = compact ? "auteur-input mt-1 text-xs" : "auteur-input mt-1 text-sm";
  const btnClass = "btn-secondary mt-2 w-full text-xs";
  const taRows = (n: number) => (compact ? Math.max(3, n - 2) : n);

  const waiveList = (): string[] =>
    waiveIdsComma
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);

  const decisionMode = String(workflow?.run.hitl_decision_mode ?? "");

  return (
    <section className={shell}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-headline text-sm font-bold uppercase tracking-wider text-tertiary">需要您協助</h2>
        {hitlActive ? (
          <button
            type="button"
            className="shrink-0 rounded-md border border-error/50 bg-error/15 px-2 py-1 font-label text-[11px] font-semibold text-error hover:bg-error/25 disabled:opacity-40"
            disabled={controlsLocked}
            onClick={() => onDecision("ABORT_AND_RESTART")}
          >
            放棄本章草稿，打掉重練
          </button>
        ) : null}
      </div>
      <p className="mb-3 font-body text-sm text-on-surface-variant">
        {hitlActive ? (
          <>
            <strong className="text-tertiary">流程已暫停</strong>
            <span className="text-on-surface-variant">
              {" "}
              · {hitlDecisionModeLabel(decisionMode)}
            </span>
          </>
        ) : (
          "目前沒有等待您處理的步驟。"
        )}
      </p>
      {hitlActive ? (
        <div className="mb-3 inline-flex rounded-lg border border-outline-variant/25 bg-surface-container-highest/30 p-1">
          <button
            type="button"
            className={`rounded-md px-3 py-1 text-xs ${uiMode === "simple" ? "bg-primary/20 text-primary" : "text-on-surface-variant"}`}
            disabled={controlsLocked}
            onClick={() => setUiMode("simple")}
          >
            簡化模式
          </button>
          <button
            type="button"
            className={`rounded-md px-3 py-1 text-xs ${uiMode === "advanced" ? "bg-secondary/20 text-secondary" : "text-on-surface-variant"}`}
            disabled={controlsLocked}
            onClick={() => setUiMode("advanced")}
          >
            進階模式
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
                專案輸出語言：<span className="text-on-surface">{String(hitlContext.context_metadata.expected_output_language)}</span>
              </p>
            ) : null}
            {hitlContext?.context_metadata?.language_detection_summary ? (
              <p className="mt-1 font-body text-xs text-on-surface-variant">{hitlContext.context_metadata.language_detection_summary}</p>
            ) : null}
            {reason === HITL_REASON.CONTEXT ? (
              <p className="mt-2 font-label text-xs text-on-surface-variant">
                目前估算參考內容約 {String(workflow?.state.context_overflow_char_estimate ?? "—")} 字，請視情況刪減。
              </p>
            ) : null}
            <p className="mt-2 font-label text-xs text-on-surface-variant">
              暫停後會從「{resumeNodeUserLabel(resumeHint)}」附近接續（依您選擇可能變更）。
            </p>
          </div>

          <div className="mb-4">
            <p className="mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">章節流程</p>
            <HitlFlowStrip reason={reason} resumeFrom={resumeHint} compact={compact} />
          </div>

          {feedbackLines.length > 0 ? (
            <div className="mb-4 rounded-lg bg-surface-container-highest/50 px-3 py-2">
              <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">系統剛才的說明</p>
              <ul className="mt-1 list-inside list-disc font-body text-sm text-on-surface">
                {feedbackLines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {reason === HITL_REASON.B_STORY && rawOptions.some((o) => o.id === "b_story_wait_judgement") ? (
            <p className="mb-3 rounded-lg bg-primary/10 px-3 py-2 font-body text-sm text-on-surface">
              請在下方選擇做法並填寫表單，決定副線是否已收尾；無需使用其他按鈕。
            </p>
          ) : null}
          {reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED ? (
            <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 px-3 py-3">
              <p className="font-label text-xs font-semibold text-on-surface">Alignment 需要你補充章節硬性規則</p>
              <blockquote className="mt-2 border-l-2 border-warning/60 pl-3 font-body text-xs text-on-surface-variant">
                {String(workflow?.state.alignment_log ?? "").trim() || "請補充可執行的勝負條件與判定流程。"}
              </blockquote>
              <textarea
                className={inputClass}
                value={alignmentRulesInput}
                rows={taRows(4)}
                onChange={(e) => {
                  setAlignmentRulesInput(e.target.value);
                }}
                disabled={controlsLocked}
                placeholder="補充本章硬性規則：勝負條件、回合流程、籌碼/代價、可用策略邊界"
              />
              {!alignmentRulesInput.trim() ? (
                <p className="mt-1 font-body text-xs text-error">請填寫硬性規則後再繼續。</p>
              ) : null}
              <label className="auteur-label mt-2">本章節奏煞車（可選；禁止本章寫出最終結局）</label>
              <textarea
                className={inputClass}
                value={pacingLimitInput}
                rows={2}
                onChange={(e) => setPacingLimitInput(e.target.value)}
                disabled={controlsLocked}
                placeholder="例：本章只允許試探與懸念，不得揭露真凶身分。"
              />
              <p className="mt-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">未來結局錨點（可選）</p>
              <input
                className={inputClass}
                value={futureAnchorTitle}
                onChange={(e) => setFutureAnchorTitle(e.target.value)}
                disabled={controlsLocked}
                placeholder="錨點標題"
              />
              <textarea
                className={inputClass}
                value={futureAnchorDesc}
                rows={2}
                onChange={(e) => setFutureAnchorDesc(e.target.value)}
                disabled={controlsLocked}
                placeholder="錨點描述（可空）"
              />
              <label className="auteur-label mt-1">延遲幾章後觸發（空白表示 0）</label>
              <input
                type="number"
                min={0}
                className={inputClass}
                value={futureAnchorDelay}
                onChange={(e) => setFutureAnchorDelay(e.target.value)}
                disabled={controlsLocked}
                placeholder="0"
              />
              <button
                type="button"
                className={btnClass}
                disabled={controlsLocked || !alignmentRulesInput.trim()}
                onClick={() => {
                  if (!alignmentRulesInput.trim()) return;
                  const raw = futureAnchorDelay.trim();
                  const parsed = raw === "" ? null : Number.parseInt(raw, 10);
                  const chapters_to_delay = parsed != null && Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
                  onStateInjection({
                    mutations: [],
                    chapter_hard_rules: alignmentRulesInput,
                    resume_from: "logic_alignment",
                    reason: "alignment_rules_patch",
                    this_chapter_pacing_limit: pacingLimitInput.trim(),
                    future_anchor_title: futureAnchorTitle.trim(),
                    future_anchor_description: futureAnchorDesc.trim(),
                    chapters_to_delay,
                  });
                }}
              >
                套用硬性規則並繼續
              </button>
            </div>
          ) : null}

          {options.length > 0 ? (
            <div className="mb-4">
              <p className="mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">可先一鍵處理</p>
              <div className="flex flex-col gap-2">
                {options.map((option) => (
                  <div key={option.id} className="rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 p-2">
                    <button
                      type="button"
                      disabled={controlsLocked}
                      onClick={() => onDecision(option.id)}
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
              <p className="mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">選擇做法</p>
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
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">手動調整事件大綱</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  左側為事件結構（進階結構化格式，與備份相容），右側為本章的表層敘事說明。
                </p>
                <textarea
                  className={inputClass}
                  value={outlineJson}
                  rows={taRows(6)}
                  onChange={(e) => {
                    setOutlineJson(e.target.value);
                    setOutlineJsonError("");
                  }}
                  disabled={controlsLocked}
                />
                {outlineJsonError ? <p className="mt-1 font-body text-xs text-error">{outlineJsonError}</p> : null}
                <textarea
                  className={inputClass}
                  value={narrativeScript}
                  rows={taRows(3)}
                  onChange={(e) => setNarrativeScript(e.target.value)}
                  disabled={controlsLocked}
                />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() => {
                    const parsed = parseJsonField(outlineJson, "事件大綱 JSON");
                    if (!parsed.ok) {
                      setOutlineJsonError(parsed.message);
                      return;
                    }
                    if (!Array.isArray(parsed.value)) {
                      setOutlineJsonError("事件大綱必須是 JSON 陣列。");
                      return;
                    }
                    setOutlineJsonError("");
                    void onOutlineEdit({
                      ground_truth_events: parsed.value as Array<Record<string, unknown>>,
                      narrative_script: narrativeScript,
                    });
                  }}
                >
                  套用大綱並繼續
                </button>
              </>
            ) : null}

            {selectedSolution === "anchor" && reason === HITL_REASON.PLAN_LOOP ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">延後故事里程碑</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  指定要延後的節點代號，以及希望改到哪一章再達成。
                </p>
                <label className="auteur-label">里程碑代號</label>
                <input className={inputClass} value={anchorId} onChange={(e) => setAnchorId(e.target.value)} disabled={controlsLocked} />
                <label className="auteur-label mt-2">改到第幾章</label>
                <input
                  type="number"
                  min={1}
                  className={inputClass}
                  value={anchorChapterInput}
                  onChange={(e) => {
                    setAnchorChapterInput(e.target.value);
                    setAnchorChapterError("");
                  }}
                  disabled={controlsLocked}
                />
                {anchorChapterError ? <p className="mt-1 font-body text-xs text-error">{anchorChapterError}</p> : null}
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked || !anchorId.trim()}
                  onClick={() => {
                    const n = Number.parseInt(anchorChapterInput.trim(), 10);
                    if (!Number.isFinite(n) || n < 1) {
                      setAnchorChapterError("請輸入有效的章節編號（≥ 1）。");
                      return;
                    }
                    setAnchorChapterError("");
                    void onAnchorDelay({ anchor_id: anchorId.trim(), new_chapter_target: n });
                  }}
                >
                  儲存並回到劇情規劃
                </button>
              </>
            ) : null}

            {selectedSolution === "director" && isDirectorPatchReason(reason) ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">微調章節方向與副線</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  這些欄位會影響本章定位與副線走向，請用簡短中文填寫即可。
                </p>
                <label className="auteur-label">章節類型（例：過渡／高潮）</label>
                <input className={inputClass} value={chapterType} onChange={(e) => setChapterType(e.target.value)} disabled={controlsLocked} />
                <label className="auteur-label mt-2">副線指示</label>
                <input className={inputClass} value={bStoryDirective} onChange={(e) => setBStoryDirective(e.target.value)} disabled={controlsLocked} />
                <label className="auteur-label mt-2">副線類型標籤</label>
                <input className={inputClass} value={bStoryType} onChange={(e) => setBStoryType(e.target.value)} disabled={controlsLocked} />
                <label className="auteur-label mt-2">想新登場的元素（每行一項）</label>
                <textarea className={inputClass} value={newElementsLines} rows={taRows(3)} onChange={(e) => setNewElementsLines(e.target.value)} disabled={controlsLocked} />
                <label className="auteur-label mt-2">主線／敘事指示</label>
                <input className={inputClass} value={narrativeDirective} onChange={(e) => setNarrativeDirective(e.target.value)} disabled={controlsLocked} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() =>
                    onDirectorPatch({
                      chapter_type: chapterType || undefined,
                      b_story_directive: bStoryDirective,
                      b_story_type: bStoryType || null,
                      new_elements_to_introduce: newElementsLines
                        .split("\n")
                        .map((s) => s.trim())
                        .filter(Boolean),
                      narrative_directive: narrativeDirective || undefined,
                    })
                  }
                >
                  套用並繼續
                </button>
              </>
            ) : null}

            {selectedSolution === "draft" && reason === HITL_REASON.DRAFT_LOOP ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">修改章節內文</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  專名對照線索請在下次「開始撰寫本章」時，於章節執行請求一併送出（無法在此 HITL 面板補送）。
                </p>
                <label className="flex items-center gap-2 font-label text-xs text-on-surface-variant">
                  <input type="checkbox" checked={mergeHintsOnDraft} onChange={(e) => setMergeHintsOnDraft(e.target.checked)} disabled={controlsLocked} />
                  保留已蒐集的專名線索
                </label>
                <label className="auteur-label">接下來從哪一步再檢查</label>
                <select className={inputClass} value={resumeFrom} onChange={(e) => setResumeFrom(e.target.value)} disabled={controlsLocked}>
                  {DRAFT_RESUME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <textarea className={inputClass} value={draftText} rows={taRows(10)} onChange={(e) => setDraftText(e.target.value)} disabled={controlsLocked} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() =>
                    onDraftEdit({
                      chapter_content: draftText,
                      resume_from: resumeFrom,
                      merge_extraction_hints: mergeHintsOnDraft,
                    })
                  }
                >
                  提交內文並繼續
                </button>
              </>
            ) : null}

            {selectedSolution === "remap" && reason === HITL_REASON.EXTRACTION_GATE ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">對照角色與道具</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  系統猜測如下，請核對；手動對照請編輯下方結構化對照表。
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
                  <p className="mb-2 font-body text-xs text-on-surface-variant">目前沒有表格化猜測，請依內文自行填寫對照。</p>
                )}
                {uiMode === "advanced" ? <label className="auteur-label">手動對照（結構化，進階）</label> : null}
                <textarea
                  className={inputClass}
                  value={remapJson}
                  rows={taRows(4)}
                  onChange={(e) => {
                    setRemapJson(e.target.value);
                    setRemapJsonError("");
                  }}
                  disabled={controlsLocked}
                />
                {remapJsonError ? <p className="mt-1 font-body text-xs text-error">{remapJsonError}</p> : null}
                {uiMode === "advanced" ? (
                  <>
                    <label className="auteur-label mt-2">可略過的必填項目代號（逗號分隔，進階）</label>
                    <input className={inputClass} value={waiveIdsComma} onChange={(e) => setWaiveIdsComma(e.target.value)} disabled={controlsLocked} />
                  </>
                ) : null}
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked}
                  onClick={() => {
                    const parsed = parseJsonField(remapJson, "對照表 JSON");
                    if (!parsed.ok) {
                      setRemapJsonError(parsed.message);
                      return;
                    }
                    if (!Array.isArray(parsed.value)) {
                      setRemapJsonError("對照表必須是 JSON 陣列。");
                      return;
                    }
                    const rows: Array<{ from_node_id: string; to_node_id: string }> = [];
                    for (const item of parsed.value) {
                      if (!item || typeof item !== "object") {
                        setRemapJsonError("對照表每一列必須是物件，且含 from_node_id、to_node_id。");
                        return;
                      }
                      const rec = item as Record<string, unknown>;
                      const fromId = String(rec.from_node_id ?? "").trim();
                      const toId = String(rec.to_node_id ?? "").trim();
                      if (!fromId || !toId) {
                        setRemapJsonError("對照表每一列都需有非空的 from_node_id 與 to_node_id。");
                        return;
                      }
                      rows.push({ from_node_id: fromId, to_node_id: toId });
                    }
                    setRemapJsonError("");
                    void onExtractionRemap({
                      entity_remaps: uiMode === "advanced" ? rows : rows.slice(0, Math.max(1, rows.length)),
                      waive_mandatory_node_ids: uiMode === "advanced" ? waiveList() : [],
                    });
                  }}
                >
                  套用對照並重新歸檔
                </button>
              </>
            ) : null}

            {selectedSolution === "b_story" && reason === HITL_REASON.B_STORY ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">副線收尾判定</h3>
                {bStoryDisplay.bullets.length > 0 ? (
                  <ul className="mb-2 list-inside list-disc font-body text-sm text-on-surface">
                    {bStoryDisplay.bullets.map((b, i) => (
                      <li key={i}>{b}</li>
                    ))}
                  </ul>
                ) : null}
                <label className="auteur-label">補充說明（會一併存檔）</label>
                <textarea className={inputClass} value={bAnalysis} rows={taRows(4)} onChange={(e) => setBAnalysis(e.target.value)} disabled={controlsLocked} />
                <label className="auteur-label mt-2">視為已收尾的副線名稱代號（逗號分隔）</label>
                <input className={inputClass} value={bResolvedCsv} onChange={(e) => setBResolvedCsv(e.target.value)} disabled={controlsLocked} />
                <label className="auteur-label mt-2">當作證據的情節事件代號（逗號分隔）</label>
                <input className={inputClass} value={bEvidenceCsv} onChange={(e) => setBEvidenceCsv(e.target.value)} disabled={controlsLocked} />
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={btnClass + " flex-1"}
                    disabled={controlsLocked}
                    onClick={() =>
                      onBStoryJudgement({
                        action: "force_resolve",
                        resolved_b_stories: bResolvedCsv
                          .split(/[,，\s]+/)
                          .map((s) => s.trim())
                          .filter(Boolean),
                        resolution_evidence_event_ids: bEvidenceCsv
                          .split(/[,，\s]+/)
                          .map((s) => s.trim())
                          .filter(Boolean),
                        resolution_analysis: bAnalysis,
                      })
                    }
                  >
                    確認已收尾
                  </button>
                  <button
                    type="button"
                    className={btnClass + " flex-1"}
                    disabled={controlsLocked}
                    onClick={() =>
                      onBStoryJudgement({
                        action: "reject",
                        reject_resume_from: bRejectResume,
                        reason: bAnalysis.slice(0, 500),
                      })
                    }
                  >
                    打回、回到前段
                  </button>
                </div>
                <label className="auteur-label mt-2">打回後從哪一步重來</label>
                <select className={inputClass} value={bRejectResume} onChange={(e) => setBRejectResume(e.target.value)} disabled={controlsLocked}>
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
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">精簡參考資料</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  選擇組裝層級：後端會依層級自動縮減圖譜與向量脈絡（0=最完整，2=最精簡）。
                </p>
                <div className="flex flex-col gap-2">
                  {(
                    [
                      { v: 0, label: "層級 0 — 盡量完整" },
                      { v: 1, label: "層級 1 — 中度瘦身" },
                      { v: 2, label: "層級 2 — 積極瘦身" },
                    ] as const
                  ).map((row) => (
                    <label key={row.v} className="flex cursor-pointer items-center gap-2 font-body text-sm text-on-surface">
                      <input
                        type="radio"
                        name="prune-tier"
                        checked={pruneProductTier === row.v}
                        onChange={() => setPruneProductTier(row.v)}
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
                  onClick={() => onContextPrune?.({ graph_rag_context_tier: pruneProductTier, reason: "author_context_prune" })}
                >
                  套用並重新整理背景
                </button>
              </>
            ) : null}

            {hitlActive && solutionList.length === 0 ? (
              <p className="font-body text-sm text-on-surface-variant">
                此暫停沒有專用表單。若上方有「一鍵處理」請優先使用；否則請展開下方進階選項。
              </p>
            ) : null}
            {hitlActive && solutionList.length > 0 && selectedSolution == null ? (
              <p className="font-body text-sm text-on-surface-variant">請選擇上方做法。</p>
            ) : null}
          </div>

          {uiMode === "advanced" ? (
            <details className="mt-4 rounded-xl border border-outline-variant/15 bg-surface-container-highest/20 p-3" open={advancedOpen} onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}>
            <summary className="cursor-pointer font-label text-sm font-semibold text-on-surface-variant">
              進階：僅在熟悉系統時使用
            </summary>
            <div className="mt-3 space-y-3 border-t border-outline-variant/10 pt-3">
              <p className="font-mono text-[10px] text-on-surface-variant">
                內部原因碼：{reason || "—"} · resume：{resumeHint || "—"}
              </p>
              <div>
                <h4 className="font-label text-xs font-bold text-on-surface">直接寫入故事資料（進階結構化）</h4>
                <p className="mb-1 font-body text-[10px] text-on-surface-variant">錯誤操作可能破壞資料，請謹慎。</p>
                <textarea
                  className={inputClass}
                  value={injectionJson}
                  rows={taRows(6)}
                  onChange={(e) => {
                    setInjectionJson(e.target.value);
                    setInjectionJsonError("");
                    setAdvancedInjectAck(false);
                  }}
                  disabled={controlsLocked}
                />
                {injectionJsonError ? <p className="mt-1 font-body text-xs text-error">{injectionJsonError}</p> : null}
                <label className="mt-2 flex cursor-pointer items-start gap-2 font-body text-xs text-on-surface">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={advancedInjectAck}
                    onChange={(e) => setAdvancedInjectAck(e.target.checked)}
                    disabled={controlsLocked}
                  />
                  <span>我已了解此操作會直接變更故事圖譜資料，且可能無法還原。</span>
                </label>
                <button
                  type="button"
                  className={btnClass}
                  disabled={controlsLocked || !advancedInjectAck}
                  onClick={() => {
                    if (!advancedInjectAck) return;
                    const parsed = parseJsonField(injectionJson, "mutations JSON");
                    if (!parsed.ok) {
                      setInjectionJsonError(parsed.message);
                      return;
                    }
                    if (!Array.isArray(parsed.value)) {
                      setInjectionJsonError("mutations 必須是 JSON 陣列。");
                      return;
                    }
                    setInjectionJsonError("");
                    void onStateInjection({
                      mutations: parsed.value as Array<Record<string, unknown>>,
                    });
                  }}
                >
                  執行寫入並繼續
                </button>
              </div>
            </div>
            </details>
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
