import { useEffect, useMemo, useState } from "react";
import type { WorkflowPayload } from "../../types";
import { HitlFlowStrip } from "./HitlFlowStrip";
import { hitlDecisionModeLabel } from "../ui-copy/workflowDisplay";
import {
  B_STORY_REJECT_RESUME_OPTIONS,
  buildFeedbackSummary,
  DRAFT_RESUME_OPTIONS,
  defaultSolutionForReason,
  formatBStoryCandidateForDisplay,
  getSituationCopy,
  HINTS_RESUME_OPTIONS,
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
  onDecision: (optionId: string) => Promise<void>;
  onOutlineEdit: (payload: { ground_truth_events: Array<Record<string, unknown>>; narrative_script?: string }) => Promise<void>;
  onStateInjection: (payload: { mutations: Array<Record<string, unknown>> }) => Promise<void>;
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
  onExtractionHints?: (payload: {
    entries: Array<{ node_id: string; surface_forms: string[] }>;
    resume_from?: string;
    waive_mandatory_node_ids?: string[];
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
  onContextPrune?: (payload: {
    bible_context?: string;
    graph_context?: string;
    vector_context?: string;
    recent_chapter_context?: string;
    previous_chapter_summary?: string;
    graph_rag_context_tier?: number;
    reason?: string;
  }) => Promise<void>;
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

export function HitlPanel({
  workflow,
  variant = "default",
  onDecision,
  onOutlineEdit,
  onStateInjection,
  onDraftEdit,
  onDirectorPatch = asyncNoop,
  onExtractionHints = asyncNoop,
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
  const [draftText, setDraftText] = useState("");
  const [resumeFrom, setResumeFrom] = useState("reader");
  const [mergeHintsOnDraft, setMergeHintsOnDraft] = useState(false);
  const [chapterType, setChapterType] = useState("");
  const [bStoryDirective, setBStoryDirective] = useState("");
  const [bStoryType, setBStoryType] = useState("");
  const [newElementsLines, setNewElementsLines] = useState("");
  const [narrativeDirective, setNarrativeDirective] = useState("");
  const [anchorId, setAnchorId] = useState("");
  const [anchorNewChapter, setAnchorNewChapter] = useState(1);
  const [hintsJson, setHintsJson] = useState('[{"node_id":"char_x","surface_forms":["精確子字串"]}]');
  const [hintsResume, setHintsResume] = useState("draft_supervisor");
  const [waiveIdsComma, setWaiveIdsComma] = useState("");
  const [remapJson, setRemapJson] = useState('[{"from_node_id":"ghost_01","to_node_id":"planned_01"}]');
  const [remapHintsView, setRemapHintsView] = useState("[]");
  const [bResolvedCsv, setBResolvedCsv] = useState("");
  const [bEvidenceCsv, setBEvidenceCsv] = useState("");
  const [bAnalysis, setBAnalysis] = useState("");
  const [bRejectResume, setBRejectResume] = useState("extraction_gate");
  const [pruneBible, setPruneBible] = useState("");
  const [pruneGraph, setPruneGraph] = useState("");
  const [pruneVector, setPruneVector] = useState("");
  const [pruneRecent, setPruneRecent] = useState("");
  const [prunePrevSummary, setPrunePrevSummary] = useState("");
  const [pruneTier, setPruneTier] = useState(1);
  const [selectedSolution, setSelectedSolution] = useState<HitlSolutionId | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [contextFieldNamesOpen, setContextFieldNamesOpen] = useState(false);

  const hitlActive = isHitlActive(workflow);
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
      setAnchorNewChapter(cid + 1);
    }
    if (reason === HITL_REASON.DRAFT_LOOP) {
      const hints = st.author_extraction_surface_hints;
      if (Array.isArray(hints) && hints.length > 0) {
        setHintsJson(JSON.stringify(hints, null, 2));
      }
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
      setPruneBible(String(st.bible_context ?? ""));
      setPruneGraph(String(st.graph_context ?? ""));
      setPruneVector(String(st.vector_context ?? ""));
      setPruneRecent(String(st.recent_chapter_context ?? ""));
      setPrunePrevSummary(String(st.previous_chapter_summary ?? ""));
      setPruneTier(Number(st.graph_rag_context_tier ?? 1));
    }
  }, [hitlActive, reason, workflow?.run.run_id, workflow?.state]);

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
      <h2 className="mb-1 font-headline text-sm font-bold uppercase tracking-wider text-tertiary">需要您協助</h2>
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
        <>
          <div className="mb-4 rounded-lg border border-tertiary/20 bg-tertiary/5 px-3 py-3">
            <h3 className="font-headline text-sm font-bold text-on-surface">{situation.title}</h3>
            <p className="mt-2 font-body text-sm leading-relaxed text-on-surface-variant">{situation.why}</p>
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

          {options.length > 0 ? (
            <div className="mb-4">
              <p className="mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant">可先一鍵處理</p>
              <div className="flex flex-col gap-2">
                {options.map((option) => (
                  <div key={option.id} className="rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 p-2">
                    <button
                      type="button"
                      disabled={!hitlActive}
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
                    disabled={!hitlActive}
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
                  onChange={(e) => setOutlineJson(e.target.value)}
                  disabled={!hitlActive}
                />
                <textarea
                  className={inputClass}
                  value={narrativeScript}
                  rows={taRows(3)}
                  onChange={(e) => setNarrativeScript(e.target.value)}
                  disabled={!hitlActive}
                />
                <button
                  type="button"
                  className={btnClass}
                  disabled={!hitlActive}
                  onClick={() =>
                    onOutlineEdit({
                      ground_truth_events: JSON.parse(outlineJson) as Array<Record<string, unknown>>,
                      narrative_script: narrativeScript,
                    })
                  }
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
                <input className={inputClass} value={anchorId} onChange={(e) => setAnchorId(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">改到第幾章</label>
                <input
                  type="number"
                  min={1}
                  className={inputClass}
                  value={anchorNewChapter}
                  onChange={(e) => setAnchorNewChapter(Number(e.target.value))}
                  disabled={!hitlActive}
                />
                <button
                  type="button"
                  className={btnClass}
                  disabled={!hitlActive || !anchorId.trim()}
                  onClick={() => onAnchorDelay({ anchor_id: anchorId.trim(), new_chapter_target: anchorNewChapter })}
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
                <input className={inputClass} value={chapterType} onChange={(e) => setChapterType(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">副線指示</label>
                <input className={inputClass} value={bStoryDirective} onChange={(e) => setBStoryDirective(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">副線類型標籤</label>
                <input className={inputClass} value={bStoryType} onChange={(e) => setBStoryType(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">想新登場的元素（每行一項）</label>
                <textarea className={inputClass} value={newElementsLines} rows={taRows(3)} onChange={(e) => setNewElementsLines(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">主線／敘事指示</label>
                <input className={inputClass} value={narrativeDirective} onChange={(e) => setNarrativeDirective(e.target.value)} disabled={!hitlActive} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={!hitlActive}
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
                <label className="flex items-center gap-2 font-label text-xs text-on-surface-variant">
                  <input type="checkbox" checked={mergeHintsOnDraft} onChange={(e) => setMergeHintsOnDraft(e.target.checked)} disabled={!hitlActive} />
                  保留已蒐集的專名線索
                </label>
                <label className="auteur-label">接下來從哪一步再檢查</label>
                <select className={inputClass} value={resumeFrom} onChange={(e) => setResumeFrom(e.target.value)} disabled={!hitlActive}>
                  {DRAFT_RESUME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <textarea className={inputClass} value={draftText} rows={taRows(10)} onChange={(e) => setDraftText(e.target.value)} disabled={!hitlActive} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={!hitlActive}
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

            {selectedSolution === "hints" && reason === HITL_REASON.DRAFT_LOOP ? (
              <>
                <h3 className="mb-2 font-headline text-xs font-bold text-on-surface">補上稱呼與專名線索</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  以結構化清單列出設定代號與文中應出現的說法；若不熟悉格式，可先略過並改以「修改內文」處理。
                </p>
                <textarea className={inputClass} value={hintsJson} rows={taRows(6)} onChange={(e) => setHintsJson(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">送交哪一步驗證</label>
                <select className={inputClass} value={hintsResume} onChange={(e) => setHintsResume(e.target.value)} disabled={!hitlActive}>
                  {HINTS_RESUME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <label className="auteur-label mt-2">可略過的必填項目代號（逗號分隔，進階）</label>
                <input className={inputClass} value={waiveIdsComma} onChange={(e) => setWaiveIdsComma(e.target.value)} disabled={!hitlActive} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={!hitlActive}
                  onClick={() =>
                    onExtractionHints({
                      entries: JSON.parse(hintsJson) as Array<{ node_id: string; surface_forms: string[] }>,
                      resume_from: hintsResume,
                      waive_mandatory_node_ids: waiveList(),
                    })
                  }
                >
                  套用線索並繼續
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
                <label className="auteur-label">手動對照（結構化，進階）</label>
                <textarea className={inputClass} value={remapJson} rows={taRows(4)} onChange={(e) => setRemapJson(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">可略過的必填項目代號（逗號分隔，進階）</label>
                <input className={inputClass} value={waiveIdsComma} onChange={(e) => setWaiveIdsComma(e.target.value)} disabled={!hitlActive} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={!hitlActive}
                  onClick={() =>
                    onExtractionRemap({
                      entity_remaps: JSON.parse(remapJson) as Array<{ from_node_id: string; to_node_id: string }>,
                      waive_mandatory_node_ids: waiveList(),
                    })
                  }
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
                <textarea className={inputClass} value={bAnalysis} rows={taRows(4)} onChange={(e) => setBAnalysis(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">視為已收尾的副線名稱代號（逗號分隔）</label>
                <input className={inputClass} value={bResolvedCsv} onChange={(e) => setBResolvedCsv(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">當作證據的情節事件代號（逗號分隔）</label>
                <input className={inputClass} value={bEvidenceCsv} onChange={(e) => setBEvidenceCsv(e.target.value)} disabled={!hitlActive} />
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={btnClass + " flex-1"}
                    disabled={!hitlActive}
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
                    disabled={!hitlActive}
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
                <select className={inputClass} value={bRejectResume} onChange={(e) => setBRejectResume(e.target.value)} disabled={!hitlActive}>
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
                <p className="mb-2 font-body text-xs text-on-surface-variant">請刪短各區文字；不必全清空，重點是降低總量。</p>
                <div className="grid gap-2 lg:grid-cols-2">
                  <div>
                    <label className="auteur-label">世界觀摘要</label>
                    <textarea className={inputClass} value={pruneBible} rows={taRows(4)} onChange={(e) => setPruneBible(e.target.value)} disabled={!hitlActive} />
                  </div>
                  <div>
                    <label className="auteur-label">人物與事件關係摘要</label>
                    <textarea className={inputClass} value={pruneGraph} rows={taRows(4)} onChange={(e) => setPruneGraph(e.target.value)} disabled={!hitlActive} />
                  </div>
                  <div>
                    <label className="auteur-label">相關段落摘錄</label>
                    <textarea className={inputClass} value={pruneVector} rows={taRows(4)} onChange={(e) => setPruneVector(e.target.value)} disabled={!hitlActive} />
                  </div>
                  <div>
                    <label className="auteur-label">近期章節摘要</label>
                    <textarea className={inputClass} value={pruneRecent} rows={taRows(4)} onChange={(e) => setPruneRecent(e.target.value)} disabled={!hitlActive} />
                  </div>
                </div>
                <label className="auteur-label mt-2">上一章精簡回顧</label>
                <textarea className={inputClass} value={prunePrevSummary} rows={taRows(2)} onChange={(e) => setPrunePrevSummary(e.target.value)} disabled={!hitlActive} />
                <label className="auteur-label mt-2">關係網詳盡度（0 最精簡—2 最細）</label>
                <input
                  type="number"
                  min={0}
                  max={2}
                  className={inputClass}
                  value={pruneTier}
                  onChange={(e) => setPruneTier(Number(e.target.value))}
                  disabled={!hitlActive}
                />
                <button
                  type="button"
                  className={btnClass}
                  disabled={!hitlActive}
                  onClick={() =>
                    onContextPrune({
                      bible_context: pruneBible,
                      graph_context: pruneGraph,
                      vector_context: pruneVector,
                      recent_chapter_context: pruneRecent,
                      previous_chapter_summary: prunePrevSummary,
                      graph_rag_context_tier: pruneTier,
                    })
                  }
                >
                  套用精簡並重新整理背景
                </button>
                <details className="mt-3" open={contextFieldNamesOpen} onToggle={(e) => setContextFieldNamesOpen((e.target as HTMLDetailsElement).open)}>
                  <summary className="cursor-pointer font-label text-xs text-on-surface-variant">進階：對應系統欄位名稱</summary>
                  <p className="mt-1 font-mono text-[10px] text-on-surface-variant">
                    bible_context · graph_context · vector_context · recent_chapter_context · previous_chapter_summary · graph_rag_context_tier
                  </p>
                </details>
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
                <textarea className={inputClass} value={injectionJson} rows={taRows(6)} onChange={(e) => setInjectionJson(e.target.value)} disabled={!hitlActive} />
                <button
                  type="button"
                  className={btnClass}
                  disabled={!hitlActive}
                  onClick={() =>
                    onStateInjection({
                      mutations: JSON.parse(injectionJson) as Array<Record<string, unknown>>,
                    })
                  }
                >
                  執行寫入並繼續
                </button>
              </div>
            </div>
          </details>
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
