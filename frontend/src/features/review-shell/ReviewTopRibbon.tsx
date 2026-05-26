import type { WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { workflowRunStatusLabel } from "../ui-copy/workflowDisplay";
import { WorkflowProgressTrack } from "../workflow-monitor/WorkflowProgressTrack";

type Props = {
  workflow: WorkflowPayload | null;
  storyId: string | null;
  workflowHitlActive: boolean;
  logsOpen: boolean;
  onToggleLogs: () => void;
  /** Optional shortcut back to chapter run while keeping DAG leave-edit confirmations in App's handler. */
  onBackToChapterRun?: () => void;
};

/**
 * Slim sticky top strip for the review shell. Replaces the boxed
 * progress + tabs that used to live in the right rail.
 *
 * Layout (left to right):
 *  - Story / run identification chip (mono, short)
 *  - Run status pill
 *  - {@link WorkflowProgressTrack} ribbon (brass ruler with 4 stage dots)
 *  - HITL beacon (idle / awaiting / blocked) — clicking it scrolls the dock
 *    into view, but actual expand/collapse is owned by the dock itself.
 *  - Logs drawer toggle
 *
 * The strip is intentionally thin (~h-12) so the manuscript stage below it
 * keeps almost the full viewport height.
 */
export function ReviewTopRibbon({
  workflow,
  storyId,
  workflowHitlActive,
  logsOpen,
  onToggleLogs,
  onBackToChapterRun,
}: Props) {
  const { t } = useI18n();
  const runFailed =
    workflow != null &&
    (String(workflow.state.workflow_status ?? workflow.run.status ?? "").toUpperCase() === "FAILED" ||
      String(workflow.run.status ?? "").toUpperCase() === "FAILED");
  const beaconState: "idle" | "awaiting" | "blocked" = runFailed
    ? "blocked"
    : workflowHitlActive
      ? "awaiting"
      : "idle";
  const beaconLabel = t(`reviewShell.ribbon.hitlBeacon.${beaconState}`);
  const beaconTone =
    beaconState === "blocked"
      ? "border-semantic-danger/45 bg-semantic-danger/10 text-semantic-danger"
      : beaconState === "awaiting"
        ? "border-tertiary/55 bg-tertiary/10 text-tertiary atelier-candle-strong"
        : "border-secondary/30 bg-secondary/5 text-secondary/80";

  const compactStoryId = storyId ? `${storyId.slice(0, 8)}…` : "—";
  const runStatus = workflow ? workflowRunStatusLabel(workflow.run.status) : "—";

  return (
    <header
      className="atelier-ribbon sticky top-0 z-30 flex min-h-12 w-full shrink-0 flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2 sm:flex-nowrap sm:items-center sm:px-5"
      role="banner"
    >
      <div className="hidden min-w-0 shrink-0 items-center gap-2 sm:flex">
        <span className="font-label text-[9px] font-bold uppercase tracking-[0.32em] text-secondary/70">
          {t("reviewShell.ribbon.runId")}
        </span>
        <span className="font-mono text-[11px] text-on-surface" title={storyId ?? undefined}>
          {compactStoryId}
        </span>
        <span aria-hidden className="text-on-surface-variant">·</span>
        <span className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">
          {runStatus}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <WorkflowProgressTrack workflow={workflow} layout="ribbon" />
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-label text-[10px] font-bold uppercase tracking-[0.2em] ${beaconTone}`}
          aria-label={beaconLabel}
          data-testid="hitl-beacon"
          data-state={beaconState}
        >
          <span
            className="material-symbols-outlined text-sm"
            aria-hidden
            style={
              beaconState === "awaiting"
                ? { filter: "drop-shadow(0 0 6px rgba(255,183,131,0.7))" }
                : undefined
            }
          >
            {beaconState === "blocked"
              ? "report"
              : beaconState === "awaiting"
                ? "local_fire_department"
                : "task_alt"}
          </span>
          <span className="hidden sm:inline">{beaconLabel}</span>
        </span>

        {storyId && onBackToChapterRun ? (
          <button
            type="button"
            onClick={onBackToChapterRun}
            className="inline-flex items-center gap-1 rounded-full border border-outline-variant/30 bg-surface-container-high/60 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant transition-colors hover:border-secondary/40 hover:text-secondary"
            title={t("reviewShell.ribbon.backWrite")}
          >
            <span className="material-symbols-outlined text-sm" aria-hidden>
              play_circle
            </span>
            <span className="hidden sm:inline">{t("reviewShell.ribbon.backWrite")}</span>
          </button>
        ) : null}

        <button
          type="button"
          onClick={onToggleLogs}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-label text-[10px] font-bold uppercase tracking-[0.2em] transition-colors ${
            logsOpen
              ? "border-primary/55 bg-primary/15 text-primary"
              : "border-outline-variant/30 bg-surface-container-high/60 text-on-surface-variant hover:bg-surface-container-high"
          }`}
          aria-pressed={logsOpen}
          aria-label={logsOpen ? t("reviewShell.ribbon.closeLogs") : t("reviewShell.ribbon.openLogs")}
          data-testid="review-ribbon-logs-toggle"
        >
          <span className="material-symbols-outlined text-sm" aria-hidden>
            menu_book
          </span>
          <span className="hidden sm:inline">{t("reviewShell.ribbon.openLogs")}</span>
        </button>
      </div>
    </header>
  );
}
