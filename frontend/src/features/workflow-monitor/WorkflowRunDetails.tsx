import type { WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { resumeNodeUserLabel as resumeLabelFromHitl } from "../hitl-panel/hitlCopy";
import { hitlReasonTitle, workflowInternalStatusLabel } from "../ui-copy/workflowDisplay";

type Props = {
  workflow: WorkflowPayload | null;
};

function resumeDisplay(resumeFrom: string): string {
  const raw = String(resumeFrom ?? "").trim();
  if (!raw) return "—";
  return resumeLabelFromHitl(raw);
}

/**
 * Always-visible "technical details" panel surfaced on the Workflow Metrics page.
 * Mirrors the data previously hidden behind WorkflowMonitor's <details> disclosure.
 */
export function WorkflowRunDetails({ workflow }: Props) {
  const { locale, t } = useI18n();

  if (!workflow) {
    return (
      <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low/70 p-5 shadow-glow">
        <h2 className="mb-2 font-headline text-sm font-bold uppercase tracking-wider text-primary">
          {t("workflow.runDetails.title")}
        </h2>
        <p className="font-body text-sm text-on-surface-variant">{t("workflow.runDetails.empty")}</p>
      </section>
    );
  }

  const state = workflow.state;
  const hitlReasonRaw = String(state.hitl_reason ?? workflow.run.hitl_reason ?? "").trim();
  const failureType = String(state.failure_type ?? "");
  const timeoutBucket = String(state.timeout_bucket ?? "");
  const threadResetDone = state.thread_reset_done === true;
  const commitExecuted = state.commit_executed === true;
  const failed = String(state.workflow_status ?? "") === "FAILED";

  const entries: Array<{ label: string; value: string; mono?: boolean }> = [
    { label: locale === "en" ? "Run ID" : locale === "zh-Hans" ? "执行编号" : "執行編號", value: workflow.run.run_id, mono: true },
    {
      label: locale === "en" ? "Engine status" : locale === "zh-Hans" ? "引擎状态" : "引擎狀態",
      value: workflowInternalStatusLabel(String(state.workflow_status ?? "-")),
    },
    {
      label: locale === "en" ? "Viewpoint" : locale === "zh-Hans" ? "叙事视角" : "敘事視角",
      value: String(state.pov_character_id ?? "-"),
    },
    {
      label: locale === "en" ? "Timeframe" : locale === "zh-Hans" ? "叙事时段" : "敘事時段",
      value: String(state.active_epoch_id ?? "-"),
    },
    {
      label: locale === "en" ? "Focus milestone" : locale === "zh-Hans" ? "进行中里程碑" : "進行中里程碑",
      value: String(state.target_anchor_id ?? "-"),
    },
    {
      label: locale === "en" ? "AI freedom" : locale === "zh-Hans" ? "创作自由度" : "創作自由度",
      value: String(state.ai_freedom_level ?? "—"),
    },
    {
      label: locale === "en" ? "Outline binding" : locale === "zh-Hans" ? "大纲约束强度" : "大綱約束強度",
      value: String(state.outline_binding_mode ?? "—"),
    },
    {
      label: locale === "en" ? "Reference score" : locale === "zh-Hans" ? "阅读评分" : "閱讀評分",
      value: String(state.last_reader_score ?? "-"),
    },
    {
      label: locale === "en" ? "Pause reason" : locale === "zh-Hans" ? "暂停原因" : "暫停原因",
      value: hitlReasonRaw ? hitlReasonTitle(hitlReasonRaw) : "—",
    },
    {
      label: locale === "en" ? "Resume from" : locale === "zh-Hans" ? "接续位置" : "接續位置",
      value: resumeDisplay(String(state.resume_from ?? "")),
    },
  ];

  if (failed) {
    entries.push(
      { label: t("workflow.monitor.failureType"), value: failureType || "ERROR" },
      { label: t("workflow.monitor.timeoutTier"), value: timeoutBucket || "—" },
      {
        label: t("workflow.monitor.dataCommit"),
        value: commitExecuted ? t("workflow.monitor.committedYes") : t("workflow.monitor.committedNo"),
      },
      {
        label: t("workflow.monitor.threadReset"),
        value: threadResetDone ? t("workflow.monitor.resetDone") : t("workflow.monitor.resetPending"),
      },
    );
  }

  return (
    <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low/70 p-5 shadow-glow">
      <header className="mb-4 flex items-center gap-2">
        <span className="material-symbols-outlined text-base text-primary">monitoring</span>
        <h2 className="font-headline text-sm font-bold uppercase tracking-wider text-primary">
          {t("workflow.runDetails.title")}
        </h2>
      </header>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map((entry) => (
          <div key={entry.label} className="min-w-0">
            <dt className="font-label text-[10px] uppercase tracking-wider text-outline">{entry.label}</dt>
            <dd
              className={
                entry.mono
                  ? "mt-0.5 break-all font-mono text-xs text-on-surface"
                  : "mt-0.5 break-words font-body text-sm text-on-surface"
              }
            >
              {entry.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
