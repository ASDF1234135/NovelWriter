import type { ChapterSummary } from "../../types";

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
  const latestChapter = chapters.length > 0 ? Math.max(...chapters.map((c) => c.chapter_id)) : null;

  return (
    <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low p-6 shadow-glow">
      <p className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">Export Center</p>
      <h2 className="mt-1 font-headline text-2xl text-on-surface">輸出與備份</h2>
      <p className="mt-2 font-body text-sm text-on-surface-variant">
        你可以在這裡統一匯出專案設定備份與章節文字稿，方便交付、封存與跨環境遷移。
      </p>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <article className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/50 p-4">
          <h3 className="font-headline text-lg text-on-surface">專案備份</h3>
          <p className="mt-1 font-body text-sm text-on-surface-variant">
            匯出目前故事設定與宏觀規劃為 JSON。故事編號：{storyId || "未建立"}。
          </p>
          <button type="button" className="btn-secondary mt-3" onClick={onExportProject} disabled={!storyId || busy}>
            匯出專案 JSON
          </button>
        </article>

        <article className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/50 p-4">
          <h3 className="font-headline text-lg text-on-surface">章節文本</h3>
          <p className="mt-1 font-body text-sm text-on-surface-variant">
            單章下載為 TXT。{latestChapter ? `目前可下載至第 ${latestChapter} 章。` : "尚未有可下載章節。"}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {chapters.length === 0 ? (
              <span className="rounded-lg border border-outline-variant/20 px-3 py-2 text-xs text-on-surface-variant">請先完成至少一章</span>
            ) : (
              chapters.map((chapter) => (
                <button
                  key={chapter.chapter_id}
                  type="button"
                  className="btn-secondary"
                  disabled={busy}
                  onClick={() => void onExportChapter(chapter.chapter_id)}
                >
                  匯出第 {chapter.chapter_id} 章
                </button>
              ))
            )}
          </div>
        </article>
      </div>
      <article className="mt-4 rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4">
        <h3 className="font-headline text-lg text-on-surface">流程驗收指標</h3>
        <p className="mt-1 font-body text-sm text-on-surface-variant">用於快速驗證使用流程優化是否生效（本次操作會話）。</p>
        <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">導航切換次數：{uxMetrics.navCount}</div>
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">
            完成流程耗時：{uxMetrics.elapsedMinutes == null ? "尚未開始" : `${uxMetrics.elapsedMinutes} 分鐘`}
          </div>
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">
            階段覆蓋：{Object.values(uxMetrics.stageVisitCount).filter((v) => v > 0).length}/5
          </div>
        </div>
      </article>
    </section>
  );
}
