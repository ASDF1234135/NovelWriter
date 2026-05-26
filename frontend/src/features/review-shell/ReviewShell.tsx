import { useState, type Dispatch, type SetStateAction } from "react";
import type {
  ChapterContent,
  ChapterSummary,
  StoryOutputLanguage,
  WorkflowPayload,
} from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { AgentLogsDrawer } from "../agent-output/AgentLogsDrawer";
import { ChapterReader } from "../chapter-reader/ChapterReader";
import { ReviewTopRibbon } from "./ReviewTopRibbon";

export type ReviewShellProps = {
  storyId: string;
  chapterId: number;
  chapters: ChapterSummary[];
  selectedChapter: ChapterContent | null;
  outputLanguage: StoryOutputLanguage;
  busy: boolean;

  workflow: WorkflowPayload | null;
  setWorkflow: Dispatch<SetStateAction<WorkflowPayload | null>>;
  workflowHitlActive: boolean;

  onSelectChapter: (chapterId: number) => Promise<void>;
  onDownloadChapter: (chapterId: number) => Promise<void>;
  /** Batch-export all completed chapters; omitted hides the ZIP control. */
  onDownloadAllCompletedZip?: () => Promise<void>;
  /** Number of chapters with status `completed` (ZIP disabled when zero). */
  completedChaptersZipCount: number;

  onBackToChapterRun?: () => void;
};

/**
 * Orchestrates the review-view layout: top brass ribbon, atelier manuscript
 * stage, floating HITL dock, and bottom logs drawer.
 *
 * This component replaces the in-line JSX that used to live in `App.tsx`
 * around line 1905–2033, including the legacy progress/logs tabs and the
 * compact HITL panel crammed into the 320px right rail.
 *
 * Human-in-the-loop UI is anchored from `App.tsx` so setup/write/graph/review
 * share one floating dock instance.
 */
export function ReviewShell(props: ReviewShellProps) {
  const {
    storyId,
    chapterId,
    chapters,
    selectedChapter,
    outputLanguage,
    busy,
    workflow,
    setWorkflow,
    workflowHitlActive,
    onSelectChapter,
    onDownloadChapter,
    onDownloadAllCompletedZip,
    completedChaptersZipCount,
    onBackToChapterRun,
  } = props;
  const { t } = useI18n();
  const [logsOpen, setLogsOpen] = useState(false);

  return (
    <div
      className="atelier-stage flex min-h-[calc(100vh-12rem)] flex-col"
      aria-label={t("reviewShell.aria.stage")}
    >
      <ReviewTopRibbon
        workflow={workflow}
        storyId={storyId || null}
        workflowHitlActive={workflowHitlActive}
        logsOpen={logsOpen}
        onToggleLogs={() => setLogsOpen((v) => !v)}
        onBackToChapterRun={onBackToChapterRun}
      />

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <ChapterReader
          storyId={storyId}
          currentChapterId={selectedChapter?.chapter_id ?? chapterId}
          chapters={chapters}
          chapter={selectedChapter}
          outputLanguage={outputLanguage}
          busy={busy}
          onSelectChapter={onSelectChapter}
          onDownloadChapter={onDownloadChapter}
          onDownloadAllCompletedZip={onDownloadAllCompletedZip}
          completedChaptersZipCount={completedChaptersZipCount}
        />
      </div>

      <AgentLogsDrawer open={logsOpen} onClose={() => setLogsOpen(false)} workflow={workflow} />

    </div>
  );
}
