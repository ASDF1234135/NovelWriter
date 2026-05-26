import { createPortal } from "react-dom";
import type { ChapterSummary, WorkflowPayload } from "../../types";
import { WorkflowMetricsDashboard } from "../workflow-metrics/WorkflowMetricsDashboard";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  open: boolean;
  onClose: () => void;
  storyId: string;
  chapters: ChapterSummary[];
  workflow: WorkflowPayload | null;
};

/** Right-side drawer with workflow metrics & run details; opened from the workspace header. */
export function StoryWorkflowDetailsDrawer({ open, onClose, storyId, chapters, workflow }: Props) {
  const { t } = useI18n();

  if (!open) return null;
  const mount = typeof document !== "undefined" ? document.body : null;
  if (!mount) return null;

  return createPortal(
    <div className="fixed inset-0 z-[85] flex justify-end" role="dialog" aria-modal="true" aria-label={t("workspace.details.title")}>
      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-black/50 backdrop-blur-[2px]"
      />
      <aside className="nb-panel relative z-[86] flex h-full w-full max-w-xl flex-col border-l border-outline-variant/20 shadow-[0_0_48px_rgba(0,0,0,0.45)]">
        <header className="nb-panel-header flex shrink-0 items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">{t("workspace.details.kicker")}</p>
            <h2 className="font-headline text-lg font-bold tracking-tight text-on-surface">{t("workspace.details.title")}</h2>
          </div>
          <button type="button" className="btn-secondary shrink-0 text-[11px]" onClick={onClose}>
            {t("graphDrawer.close")}
          </button>
        </header>
        <div className="nb-panel-body min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
          <WorkflowMetricsDashboard storyId={storyId} chapters={chapters} workflow={workflow} embedded />
        </div>
      </aside>
    </div>,
    mount,
  );
}
