import { useState } from "react";
import type { WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { workflowAgentStepLabel, workflowRunStatusLabel } from "../ui-copy/workflowDisplay";

type Props = {
  workflow: WorkflowPayload | null;
  variant?: "default" | "compact";
};

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
  const planWarnings = asStringArray(state.plan_warnings);
  const conflictNotes = asStringArray(state.human_outline_conflict_notes);
  const alignmentLog = String(state.alignment_log ?? "").trim();
  const directorBrief = String(state.director_state_brief ?? "").trim();

  return (
    <section className={shell}>
      <h2 className="mb-4 flex items-center gap-2 font-headline text-sm font-bold uppercase tracking-wider text-primary">
        <span className="material-symbols-outlined text-base">monitoring</span>
        {compact ? (locale === "en" ? "Current Run" : locale === "zh-Hans" ? "本次执行" : "本次執行") : locale === "en" ? "Chapter Progress" : locale === "zh-Hans" ? "章节撰写进度" : "章節撰寫進度"}
      </h2>
      <div className={`grid gap-3 ${compact ? "grid-cols-1 text-xs" : "grid-cols-2 md:grid-cols-3"}`}>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">{locale === "en" ? "Chapter" : locale === "zh-Hans" ? "章节" : "章節"}</div>
          <div className="text-on-surface">{locale === "en" ? `Chapter ${workflow.run.chapter_id}` : `第 ${workflow.run.chapter_id} 章`}</div>
        </div>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">{locale === "en" ? "Current Step" : locale === "zh-Hans" ? "当前步骤" : "目前步驟"}</div>
          <div className="text-on-surface">{workflowAgentStepLabel(agentRaw)}</div>
        </div>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">{locale === "en" ? "Status" : locale === "zh-Hans" ? "状态" : "狀態"}</div>
          <div className="text-on-surface">{workflowRunStatusLabel(workflow.run.status)}</div>
        </div>
      </div>
      {!compact && directorBrief ? (
        <div className="mt-4 rounded-lg border border-outline-variant/15 bg-surface-container-highest/40 px-3 py-2">
          <p className="font-label text-[10px] uppercase tracking-wider text-outline">
            {locale === "en" ? "Chapter direction summary" : locale === "zh-Hans" ? "本章走向摘要" : "本章走向摘要"}
          </p>
          <p className="mt-1 whitespace-pre-wrap font-body text-xs text-on-surface">{directorBrief.slice(0, 1200)}{directorBrief.length > 1200 ? "…" : ""}</p>
        </div>
      ) : null}
      {!compact && planWarnings.length > 0 ? (
        <div className="mt-3 rounded-lg border border-secondary/20 bg-secondary/5 px-3 py-2">
          <p className="font-label text-[10px] uppercase tracking-wider text-secondary">{t("workflow.monitor.planWarningsLabel")}</p>
          <ul className="mt-1 list-inside list-disc font-body text-xs text-on-surface">
            {planWarnings.slice(0, 12).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {!compact && conflictNotes.length > 0 ? (
        <div className="mt-3 rounded-lg border border-tertiary/25 bg-tertiary/5 px-3 py-2">
          <p className="font-label text-[10px] uppercase tracking-wider text-tertiary">{t("workflow.monitor.conflictNotesLabel")}</p>
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
