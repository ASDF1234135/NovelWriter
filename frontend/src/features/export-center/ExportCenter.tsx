import { useMemo, useState } from "react";
import type { ChapterSummary } from "../../types";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  storyId: string;
  chapters: ChapterSummary[];
  busy: boolean;
  onExportProject: () => void;
  onExportChapter: (chapterId: number) => Promise<void>;
  uxMetrics: {
    navCount: number;
    elapsedMinutes: number | null;
    stageVisitCount: Record<"projectSetup" | "planStructure" | "writeChapter" | "reviewFix" | "export", number>;
  };
};

export function ExportCenter({ storyId, chapters, busy, onExportProject, onExportChapter, uxMetrics }: Props) {
  const { t } = useI18n();
  const latestChapter = chapters.length > 0 ? Math.max(...chapters.map((c) => c.chapter_id)) : null;
  const sortedChapters = useMemo(
    () => [...chapters].sort((a, b) => a.chapter_id - b.chapter_id),
    [chapters],
  );
  const [pickedChapterId, setPickedChapterId] = useState<number | null>(null);
  const fallbackChapterId = sortedChapters.length > 0 ? sortedChapters[sortedChapters.length - 1]!.chapter_id : null;
  const exportChapterId = pickedChapterId ?? fallbackChapterId;

  const chapterDesc =
    latestChapter != null
      ? t("export.center.chapterTextDescThrough", undefined, { n: latestChapter })
      : t("export.center.chapterTextDescEmpty");

  const elapsedDisplay =
    uxMetrics.elapsedMinutes == null
      ? t("export.center.elapsedNotStarted")
      : t("export.center.elapsedMinutes", undefined, { n: uxMetrics.elapsedMinutes });

  return (
    <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low p-6 shadow-glow">
      <p className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">{t("export.center.kicker")}</p>
      <h2 className="mt-1 font-headline text-2xl text-on-surface">{t("export.center.title")}</h2>
      <p className="mt-2 font-body text-sm text-on-surface-variant">{t("export.center.intro")}</p>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <article className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/50 p-4">
          <h3 className="font-headline text-lg text-on-surface">{t("export.center.projectBackup")}</h3>
          <p className="mt-1 font-body text-sm text-on-surface-variant">
            {t("export.center.projectBackupDesc", undefined, {
              storyId: storyId.trim() ? storyId : t("app.setup.storyIdMissing"),
            })}
          </p>
          <button type="button" className="btn-secondary mt-3" onClick={onExportProject} disabled={!storyId || busy}>
            {t("setup.exportProjectJson")}
          </button>
        </article>

        <article className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/50 p-4">
          <h3 className="font-headline text-lg text-on-surface">{t("export.center.chapterText")}</h3>
          <p className="mt-1 font-body text-sm text-on-surface-variant">{chapterDesc}</p>
          {chapters.length === 0 ? (
            <span className="mt-3 inline-block rounded-lg border border-outline-variant/20 px-3 py-2 text-xs text-on-surface-variant">
              {t("export.center.needChapterFirst")}
            </span>
          ) : (
            <div className="mt-3 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end">
              <label className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="font-label text-[10px] uppercase tracking-wider text-outline">{t("export.center.chapterLabel")}</span>
                <select
                  className="auteur-input max-w-full text-sm"
                  value={exportChapterId ?? 0}
                  onChange={(e) => setPickedChapterId(Number(e.target.value))}
                  disabled={busy}
                >
                  {sortedChapters.map((chapter) => (
                    <option key={chapter.chapter_id} value={chapter.chapter_id}>
                      {t("export.center.chapterOption", undefined, {
                        id: chapter.chapter_id,
                        title: chapter.title?.trim() ? chapter.title : t("export.center.chapterUntitled"),
                      })}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="btn-secondary shrink-0"
                disabled={busy || exportChapterId == null}
                onClick={() => {
                  if (exportChapterId != null) void onExportChapter(exportChapterId);
                }}
              >
                {t("export.center.downloadTxt")}
              </button>
            </div>
          )}
        </article>
      </div>
      <article className="mt-4 rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4">
        <h3 className="font-headline text-lg text-on-surface">{t("export.center.metricsTitle")}</h3>
        <p className="mt-1 font-body text-sm text-on-surface-variant">{t("export.center.metricsIntro")}</p>
        <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">
            {t("export.center.navSwitches")}
            {uxMetrics.navCount}
          </div>
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">
            {t("export.center.elapsed")}
            {elapsedDisplay}
          </div>
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">
            {t("export.center.stageCoverage")}
            {Object.values(uxMetrics.stageVisitCount).filter((v) => v > 0).length}/5
          </div>
        </div>
      </article>
    </section>
  );
}
