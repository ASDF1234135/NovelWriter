import { useState } from "react";
import type { WorkflowPayload } from "../../types";
import { resumeNodeUserLabel as resumeLabelFromHitl } from "../hitl-panel/hitlCopy";
import { useI18n } from "../../i18n/useI18n";
import {
  hitlReasonTitle,
  workflowAgentStepLabel,
  workflowInternalStatusLabel,
  workflowRunStatusLabel,
} from "../ui-copy/workflowDisplay";

type Props = {
  workflow: WorkflowPayload | null;
  variant?: "default" | "compact";
};

function resumeDisplay(resumeFrom: string): string {
  const raw = String(resumeFrom ?? "").trim();
  if (!raw) return "—";
  return resumeLabelFromHitl(raw);
}

function asStringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.map((x) => String(x).trim()).filter(Boolean);
}

export function WorkflowMonitor({ workflow, variant = "default" }: Props) {
  const { locale, t } = useI18n();
  const [alignmentOpen, setAlignmentOpen] = useState(false);
  const compact = variant === "compact";
  const shell = compact
    ? "glass-panel rounded-xl border border-outline-variant/15 p-4 shadow-glow"
    : "rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow";

  if (!workflow) {
    return (
      <section className={shell}>
        <h2 className="mb-2 font-headline text-sm font-bold uppercase tracking-wider text-primary">
          {locale === "en" ? "Chapter Progress" : locale === "zh-Hans" ? "章节撰写进度" : "章節撰寫進度"}
        </h2>
        <p className="font-body text-sm text-on-surface-variant">
          {locale === "en"
            ? "Chapter workflow has not started."
            : locale === "zh-Hans"
              ? "尚未开始本章的自动撰写流程。"
              : "尚未開始本章的自動撰寫流程。"}
        </p>
      </section>
    );
  }

  const state = workflow.state;
  const agentRaw =
    workflow.run.current_agent ?? (typeof state.last_agent === "string" ? state.last_agent : null) ?? "";
  const hitlReasonRaw = String(state.hitl_reason ?? workflow.run.hitl_reason ?? "").trim();
  const planWarnings = asStringArray(state.plan_warnings);
  const conflictNotes = asStringArray(state.human_outline_conflict_notes);
  const alignmentLog = String(state.alignment_log ?? "").trim();
  const directorBrief = String(state.director_state_brief ?? "").trim();
  const failureType = String(state.failure_type ?? "");
  const timeoutBucket = String(state.timeout_bucket ?? "");
  const threadResetDone = state.thread_reset_done === true;
  const commitExecuted = state.commit_executed === true;

  return (
    <section className={shell}>
      <h2 className="mb-4 flex items-center gap-2 font-headline text-sm font-bold uppercase tracking-wider text-primary">
        <span className="material-symbols-outlined text-base">monitoring</span>
        {compact ? (locale === "en" ? "Current Run" : locale === "zh-Hans" ? "本次执行" : "本次執行") : locale === "en" ? "Chapter Progress" : locale === "zh-Hans" ? "章节撰写进度" : "章節撰寫進度"}
      </h2>
      <div className={`grid gap-3 ${compact ? "grid-cols-1 text-xs" : "grid-cols-2 md:grid-cols-4"}`}>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">{locale === "en" ? "Run ID" : locale === "zh-Hans" ? "执行编号" : "執行編號"}</div>
          <div className="break-all font-mono text-on-surface">{workflow.run.run_id}</div>
        </div>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">{locale === "en" ? "Current Step" : locale === "zh-Hans" ? "当前步骤" : "目前步驟"}</div>
          <div className="text-on-surface">{workflowAgentStepLabel(agentRaw)}</div>
        </div>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">{locale === "en" ? "Status" : locale === "zh-Hans" ? "状态" : "狀態"}</div>
          <div className="text-on-surface">{workflowRunStatusLabel(workflow.run.status)}</div>
          {!compact ? (
            <div className="text-xs text-on-surface-variant">
              {locale === "en" ? "Internal: " : locale === "zh-Hans" ? "内部状态：" : "內部狀態："}
              {workflowInternalStatusLabel(String(state.workflow_status ?? "-"))}
            </div>
          ) : null}
        </div>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">{locale === "en" ? "Chapter" : locale === "zh-Hans" ? "章节" : "章節"}</div>
          <div className="text-on-surface">{workflow.run.chapter_id}</div>
        </div>
      </div>
      {!compact ? (
        <div className="mt-4 flex flex-wrap gap-3 border-t border-outline-variant/10 pt-4 font-label text-xs text-on-surface-variant">
          <span>{locale === "en" ? "POV Character" : locale === "zh-Hans" ? "视角角色" : "視角角色"}：{String(state.pov_character_id ?? "-")}</span>
          <span>{locale === "en" ? "Epoch" : locale === "zh-Hans" ? "时间段" : "時間段"}：{String(state.active_epoch_id ?? "-")}</span>
          <span>{locale === "en" ? "Target Anchor" : locale === "zh-Hans" ? "目标里程碑" : "目標里程碑"}：{String(state.target_anchor_id ?? "-")}</span>
          <span>{locale === "en" ? "AI Freedom" : locale === "zh-Hans" ? "创作自由度" : "創作自由度"}：{String(state.ai_freedom_level ?? "—")}</span>
          <span>{locale === "en" ? "Outline Binding" : locale === "zh-Hans" ? "大纲绑定" : "大綱綁定"}：{String(state.outline_binding_mode ?? "—")}</span>
          <span>{locale === "en" ? "Reader Score" : locale === "zh-Hans" ? "阅读评分" : "閱讀評分"}：{String(state.last_reader_score ?? "-")}</span>
          <span>{locale === "en" ? "Pause Reason" : locale === "zh-Hans" ? "暂停原因" : "暫停原因"}：{hitlReasonRaw ? hitlReasonTitle(hitlReasonRaw) : "—"}</span>
          <span>{locale === "en" ? "Resume From" : locale === "zh-Hans" ? "接续位置" : "接續位置"}：{resumeDisplay(String(state.resume_from ?? ""))}</span>
          {String(state.workflow_status ?? "") === "FAILED" ? (
            <>
              <span>
                {t("workflow.monitor.failureType")}：{failureType || "ERROR"}
              </span>
              <span>
                {t("workflow.monitor.timeoutTier")}：{timeoutBucket || "—"}
              </span>
              <span>
                {t("workflow.monitor.dataCommit")}：{commitExecuted ? t("workflow.monitor.committedYes") : t("workflow.monitor.committedNo")}
              </span>
              <span>
                {t("workflow.monitor.threadReset")}：{threadResetDone ? t("workflow.monitor.resetDone") : t("workflow.monitor.resetPending")}
              </span>
            </>
          ) : null}
        </div>
      ) : null}
      {!compact && directorBrief ? (
        <div className="mt-4 rounded-lg border border-outline-variant/15 bg-surface-container-highest/40 px-3 py-2">
          <p className="font-label text-[10px] uppercase tracking-wider text-outline">
            {locale === "en" ? "Director Brief" : locale === "zh-Hans" ? "Director 状态简报" : "Director 狀態簡報"}
          </p>
          <p className="mt-1 whitespace-pre-wrap font-body text-xs text-on-surface">{directorBrief.slice(0, 1200)}{directorBrief.length > 1200 ? "…" : ""}</p>
        </div>
      ) : null}
      {!compact && planWarnings.length > 0 ? (
        <div className="mt-3 rounded-lg border border-secondary/20 bg-secondary/5 px-3 py-2">
          <p className="font-label text-[10px] uppercase tracking-wider text-secondary">
            {t("workflow.monitor.planWarningsLabel")} / plan_warnings
          </p>
          <ul className="mt-1 list-inside list-disc font-body text-xs text-on-surface">
            {planWarnings.slice(0, 12).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {!compact && conflictNotes.length > 0 ? (
        <div className="mt-3 rounded-lg border border-tertiary/25 bg-tertiary/5 px-3 py-2">
          <p className="font-label text-[10px] uppercase tracking-wider text-tertiary">
            {t("workflow.monitor.conflictNotesLabel")}（human_outline_conflict_notes）
          </p>
          <ul className="mt-1 list-inside list-disc font-body text-xs text-on-surface">
            {conflictNotes.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {!compact && alignmentLog ? (
        <div className="mt-3">
          <button
            type="button"
            className="font-label text-xs text-primary underline-offset-2 hover:underline"
            onClick={() => setAlignmentOpen((o) => !o)}
          >
            {alignmentOpen ? t("workflow.monitor.alignmentToggleCollapse") : t("workflow.monitor.alignmentToggleExpand")}{" "}
            {t("workflow.monitor.alignmentLogAria")}
          </button>
          {alignmentOpen ? (
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-outline-variant/15 bg-surface-container-highest/50 p-2 font-mono text-[11px] text-on-surface">
              {alignmentLog}
            </pre>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
