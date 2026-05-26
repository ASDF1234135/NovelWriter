import { Fragment, type ReactNode } from "react";
import { FLOW_STEPS } from "../hitl-panel/hitlCopy";
import type { WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { computeWorkflowStageStepIndex } from "./workflowProgressStage";

type Props = {
  workflow: WorkflowPayload | null;
  /** True while the run request is in flight before the first workflow snapshot arrives. */
  starting?: boolean;
  compact?: boolean;
  /**
   * Top-level layout flavor.
   *  - "default" / "compact": the boxed grid card used in side rails (legacy behavior).
   *  - "ribbon": horizontal stage timeline in the review-shell top strip: four
   *    equal stations with labels above and numbered nodes (or checkmarks),
   *    joined by connector segments — no overlay dots on a gradient bar.
   * When `layout="ribbon"`, the `compact` prop is ignored.
   */
  layout?: "default" | "compact" | "ribbon";
  /** Optional actions shown in the header next to the status pill (e.g. next-step buttons). */
  headerActions?: ReactNode;
};

const STAGE_GROUPS = [
  {
    id: "planning",
    label: { "zh-Hant": "本章規劃", "zh-Hans": "本章规划", en: "Planning this chapter" },
    stepIds: ["director", "graph_rag", "planner", "plan_supervisor", "logic_alignment"],
  },
  {
    id: "writing",
    label: { "zh-Hant": "正文撰寫", "zh-Hans": "正文撰写", en: "Drafting prose" },
    stepIds: ["author", "draft_supervisor", "reader"],
  },
  {
    id: "archive",
    label: { "zh-Hant": "章末整理", "zh-Hans": "章末整理", en: "Chapter wrap-up" },
    stepIds: ["extraction_gate", "copyeditor", "output_language_gate", "chapter_summarizer"],
  },
  {
    id: "finish",
    label: { "zh-Hant": "確認並儲存", "zh-Hans": "确认并保存", en: "Confirm & save" },
    stepIds: ["anchor_resolve", "profile_expander", "state_updater", "commit_to_databases"],
  },
] as const;

function getDisplayedStepLabel(workflow: WorkflowPayload | null, activeIndex: number): string {
  if (!workflow || activeIndex < 0) return "";
  const labelIndex = Math.min(activeIndex, FLOW_STEPS.length - 1);
  const agent = String(workflow.run.current_agent ?? "").trim();
  if (agent) {
    const found = FLOW_STEPS.find((s) => s.id === agent);
    if (found) return found.userLabel;
  }
  const step = FLOW_STEPS[labelIndex];
  return step?.userLabel ?? "";
}

function getActiveStepIndex(workflow: WorkflowPayload | null): number {
  return computeWorkflowStageStepIndex(workflow);
}

export function WorkflowProgressTrack({
  workflow,
  starting = false,
  compact = false,
  layout,
  headerActions,
}: Props) {
  const { locale, t } = useI18n();
  const activeIndex = getActiveStepIndex(workflow);
  const resolvedLayout: "default" | "compact" | "ribbon" =
    layout ?? (compact ? "compact" : "default");
  const isRibbon = resolvedLayout === "ribbon";
  const isCompact = resolvedLayout === "compact";
  const runFailed =
    workflow != null &&
    (String(workflow.state.workflow_status ?? workflow.run.status ?? "").toUpperCase() === "FAILED" ||
      String(workflow.run.status ?? "").toUpperCase() === "FAILED");
  const hitlWait =
    workflow != null &&
    (workflow.run.requires_hitl === true ||
      String(workflow.run.status ?? "").toUpperCase() === "WAITING_HITL" ||
      String(workflow.state.workflow_status ?? "").toUpperCase() === "WAITING_HITL");
  const wfStatus = workflow
    ? String(workflow.state.workflow_status ?? workflow.run.status ?? "").toUpperCase()
    : "";
  const workflowTerminal =
    wfStatus === "COMPLETED" || wfStatus === "CANCELLED" || wfStatus === "FAILED";
  const pipelineRunning =
    Boolean(workflow) && !runFailed && !hitlWait && !workflowTerminal;
  const showConnecting = Boolean(starting && !workflow);
  const showLivePipeline = pipelineRunning;
  const liveStepLabel = showLivePipeline ? getDisplayedStepLabel(workflow, activeIndex) : "";
  const groups = STAGE_GROUPS.map((group) => {
    const indexes = group.stepIds
      .map((id) => FLOW_STEPS.findIndex((step) => step.id === id))
      .filter((idx) => idx >= 0);
    const groupStart = Math.min(...indexes);
    const done = activeIndex > Math.max(...indexes);
    const active = activeIndex >= groupStart && activeIndex <= Math.max(...indexes);
    return { ...group, done, active };
  });

  if (isRibbon) {
    return (
      <div
        className="flex w-full min-w-0 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3"
        role="group"
        aria-label={locale === "en" ? "Writing stages" : locale === "zh-Hans" ? "撰写阶段" : "撰寫階段"}
      >
        <span className="hidden shrink-0 font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary/80 sm:inline">
          {locale === "en" ? "Stages" : locale === "zh-Hans" ? "阶段" : "階段"}
        </span>

        <div className="flex w-full min-w-0 flex-row items-stretch justify-between gap-0 px-0.5 sm:flex-1" role="list">
          {groups.map((group, index) => {
            const failedHere = runFailed && group.active;
            const prev = index > 0 ? groups[index - 1] : null;
            const connectorClass =
              index === 0
                ? "hidden"
                : runFailed && prev && (prev.active || group.active)
                  ? "bg-semantic-danger/55"
                  : prev?.done
                    ? "bg-semantic-success/45"
                    : hitlWait && group.active
                      ? "bg-semantic-warning/50"
                      : prev?.active || group.active
                        ? "bg-secondary/45"
                        : "bg-outline-variant/35";

            const nodeRing = failedHere
              ? "border-semantic-danger/60 bg-semantic-danger/20 text-semantic-danger ring-2 ring-semantic-danger/35"
              : group.done && !failedHere
                ? "border-semantic-success/45 bg-semantic-success/15 text-semantic-success ring-2 ring-semantic-success/25"
                : group.active && hitlWait
                  ? "border-semantic-warning/55 bg-semantic-warning/15 text-semantic-warning ring-2 ring-semantic-warning/35 atelier-candle-strong"
                  : group.active
                    ? "border-secondary/55 bg-secondary/15 text-secondary ring-2 ring-secondary/30 atelier-candle-pulse"
                    : "border-outline-variant/40 bg-surface-container-highest/40 text-on-surface-variant/80 ring-1 ring-outline-variant/25";

            const labelColor = failedHere
              ? "text-semantic-danger"
              : group.done && !failedHere
                ? "text-semantic-success"
                : group.active && hitlWait
                  ? "text-semantic-warning"
                  : group.active
                    ? "text-secondary"
                    : "text-on-surface-variant/75";

            return (
              <Fragment key={group.id}>
                {index > 0 ? (
                  <div aria-hidden className="flex min-w-[6px] max-w-[48px] flex-1 items-center self-center px-0">
                    <div className={`h-[3px] w-full min-w-[4px] rounded-full ${connectorClass}`} />
                  </div>
                ) : null}
                <div role="listitem" className="flex w-[4.25rem] shrink-0 flex-col items-center gap-1 sm:w-[5.25rem] md:w-28">
                  <span
                    className={`max-w-full truncate px-0.5 text-center font-label text-[8px] font-bold uppercase leading-tight tracking-[0.14em] sm:text-[9px] sm:tracking-[0.18em] ${labelColor}`}
                    title={group.label[locale]}
                  >
                    {group.done && !failedHere ? "✓ " : ""}
                    {group.label[locale]}
                  </span>
                  <div className="flex w-full flex-col items-center">
                    <span
                      className={`flex h-7 w-7 items-center justify-center rounded-full border text-[10px] font-bold shadow-sm sm:h-8 sm:w-9 ${nodeRing}`}
                      aria-current={group.active ? "step" : undefined}
                    >
                      {group.done && !failedHere ? (
                        <span className="material-symbols-outlined text-base leading-none" aria-hidden>
                          check
                        </span>
                      ) : (
                        <span className="font-mono text-[11px] leading-none sm:text-xs">{index + 1}</span>
                      )}
                    </span>
                  </div>
                </div>
              </Fragment>
            );
          })}
        </div>

        {headerActions ? <div className="flex shrink-0 items-center gap-2 sm:ml-1">{headerActions}</div> : null}
      </div>
    );
  }

  const liveActivityBar =
    showConnecting || showLivePipeline ? (
      <div
        className={`mb-3 overflow-hidden rounded-lg border border-secondary/25 bg-secondary/10 ${
          showLivePipeline ? "shadow-[inset_0_0_0_1px_rgba(255,255,255,0.04)]" : ""
        }`}
        role="status"
        aria-live="polite"
      >
        {showLivePipeline ? (
          <div className="h-0.5 w-full bg-outline-variant/25">
            <div className="h-full w-[38%] animate-[workflowLiveBar_1.1s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-transparent via-secondary to-transparent" />
          </div>
        ) : (
          <div className="h-0.5 w-full overflow-hidden bg-outline-variant/20">
            <div className="h-full w-1/3 animate-[workflowLiveBar_0.9s_ease-in-out_infinite] rounded-full bg-secondary/70" />
          </div>
        )}
        <div className="flex items-start gap-3 px-3 py-2.5">
          <span className="relative mt-0.5 flex h-2.5 w-2.5 shrink-0">
            <span
              className={`absolute inline-flex h-full w-full rounded-full opacity-40 ${
                showLivePipeline ? "animate-ping bg-secondary" : "animate-pulse bg-secondary/80"
              }`}
            />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-secondary" />
          </span>
          <p className="min-w-0 flex-1 font-body text-sm leading-snug text-on-surface">
            {showConnecting ? (
              <span className="font-medium text-secondary">{t("workflowProgress.connecting")}</span>
            ) : (
              <>
                <span className="font-semibold text-secondary">{t("workflowProgress.runningLabel")}</span>
                {liveStepLabel ? (
                  <span className="text-on-surface-variant">
                    {" "}
                    {t("workflowProgress.runningStep", undefined, { step: liveStepLabel })}
                  </span>
                ) : (
                  <span className="text-on-surface-variant"> {t("workflowProgress.runningFallback")}</span>
                )}
              </>
            )}
          </p>
        </div>
      </div>
    ) : null;

  return (
    <section className={`rounded-xl border border-outline-variant/15 bg-surface-container-low/60 ${isCompact ? "p-3" : "p-4"}`}>
      {liveActivityBar}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
          {locale === "en" ? "Writing stages" : locale === "zh-Hans" ? "撰写阶段" : "撰寫階段"}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {runFailed ? (
            <span className="rounded border border-semantic-danger/40 bg-semantic-danger/10 px-2 py-0.5 font-label text-[9px] font-bold uppercase tracking-wide text-semantic-danger">
              {locale === "en" ? "Failed" : locale === "zh-Hans" ? "失败" : "失敗"}
            </span>
          ) : hitlWait ? (
            <span className="rounded border border-semantic-warning/40 bg-semantic-warning/10 px-2 py-0.5 font-label text-[9px] font-bold uppercase tracking-wide text-semantic-warning">
              {locale === "en" ? "HITL" : locale === "zh-Hans" ? "待人工" : "待人工"}
            </span>
          ) : null}
          {headerActions}
        </div>
      </div>
      <ol className={`grid ${isCompact ? "grid-cols-2 gap-2" : "grid-cols-2 gap-3 md:grid-cols-4"}`}>
        {groups.map((group) => {
          const failedHere = runFailed && group.active;
          return (
            <li
              key={group.id}
              className={`rounded-lg border px-3 py-2 text-xs font-medium ${
                failedHere
                  ? "border-semantic-danger/50 bg-semantic-danger/15 text-semantic-danger"
                  : group.active
                    ? hitlWait
                      ? "border-semantic-warning/45 bg-semantic-warning/10 text-semantic-warning"
                      : "border-primary bg-primary/15 text-primary"
                    : group.done
                      ? "border-semantic-success/35 bg-semantic-success/10 text-semantic-success"
                      : "border-outline-variant/20 text-on-surface-variant"
              }`}
            >
              {group.done && !failedHere ? "✓ " : ""}
              {group.label[locale]}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
