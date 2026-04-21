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
  const { locale } = useI18n();
  const latestChapter = chapters.length > 0 ? Math.max(...chapters.map((c) => c.chapter_id)) : null;

  return (
    <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low p-6 shadow-glow">
      <p className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">Export Center</p>
      <h2 className="mt-1 font-headline text-2xl text-on-surface">
        {locale === "en" ? "Export & Backup" : locale === "zh-Hans" ? "导出与备份" : "輸出與備份"}
      </h2>
      <p className="mt-2 font-body text-sm text-on-surface-variant">
        {locale === "en"
          ? "Export project settings and chapter text here for delivery, archiving, and migration."
          : locale === "zh-Hans"
            ? "你可以在这里统一导出项目设置备份与章节文本，方便交付、封存与跨环境迁移。"
            : "你可以在這裡統一匯出專案設定備份與章節文字稿，方便交付、封存與跨環境遷移。"}
      </p>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <article className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/50 p-4">
          <h3 className="font-headline text-lg text-on-surface">{locale === "en" ? "Project Backup" : locale === "zh-Hans" ? "项目备份" : "專案備份"}</h3>
          <p className="mt-1 font-body text-sm text-on-surface-variant">
            {locale === "en"
              ? `Export story settings and macro plan as JSON. Story ID: ${storyId || "N/A"}.`
              : locale === "zh-Hans"
                ? `导出当前故事设置与宏观规划为 JSON。故事编号：${storyId || "未建立"}。`
                : `匯出目前故事設定與宏觀規劃為 JSON。故事編號：${storyId || "未建立"}。`}
          </p>
          <button type="button" className="btn-secondary mt-3" onClick={onExportProject} disabled={!storyId || busy}>
            {locale === "en" ? "Export Project JSON" : locale === "zh-Hans" ? "导出项目 JSON" : "匯出專案 JSON"}
          </button>
        </article>

        <article className="rounded-xl border border-outline-variant/15 bg-surface-container-highest/50 p-4">
          <h3 className="font-headline text-lg text-on-surface">{locale === "en" ? "Chapter Text" : locale === "zh-Hans" ? "章节文本" : "章節文本"}</h3>
          <p className="mt-1 font-body text-sm text-on-surface-variant">
            {locale === "en"
              ? `Download each chapter as TXT. ${latestChapter ? `Available through chapter ${latestChapter}.` : "No downloadable chapters yet."}`
              : locale === "zh-Hans"
                ? `单章下载为 TXT。${latestChapter ? `当前可下载至第 ${latestChapter} 章。` : "尚未有可下载章节。"}`
                : `單章下載為 TXT。${latestChapter ? `目前可下載至第 ${latestChapter} 章。` : "尚未有可下載章節。"}`
            }
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {chapters.length === 0 ? (
              <span className="rounded-lg border border-outline-variant/20 px-3 py-2 text-xs text-on-surface-variant">
                {locale === "en" ? "Complete at least one chapter first" : locale === "zh-Hans" ? "请先完成至少一章" : "請先完成至少一章"}
              </span>
            ) : (
              chapters.map((chapter) => (
                <button
                  key={chapter.chapter_id}
                  type="button"
                  className="btn-secondary"
                  disabled={busy}
                  onClick={() => void onExportChapter(chapter.chapter_id)}
                >
                  {locale === "en" ? `Export Ch. ${chapter.chapter_id}` : locale === "zh-Hans" ? `导出第 ${chapter.chapter_id} 章` : `匯出第 ${chapter.chapter_id} 章`}
                </button>
              ))
            )}
          </div>
        </article>
      </div>
      <article className="mt-4 rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4">
        <h3 className="font-headline text-lg text-on-surface">{locale === "en" ? "Flow Validation Metrics" : locale === "zh-Hans" ? "流程验收指标" : "流程驗收指標"}</h3>
        <p className="mt-1 font-body text-sm text-on-surface-variant">
          {locale === "en"
            ? "Quick checks for whether workflow UX optimizations are effective in this session."
            : locale === "zh-Hans"
              ? "用于快速验证流程优化是否在本次会话生效。"
              : "用於快速驗證使用流程優化是否生效（本次操作會話）。"}
        </p>
        <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">
            {locale === "en" ? "Navigation switches: " : locale === "zh-Hans" ? "导航切换次数：" : "導航切換次數："}
            {uxMetrics.navCount}
          </div>
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">
            {locale === "en" ? "Elapsed: " : locale === "zh-Hans" ? "流程耗时：" : "完成流程耗時："}
            {uxMetrics.elapsedMinutes == null
              ? locale === "en"
                ? "not started"
                : locale === "zh-Hans"
                  ? "尚未开始"
                  : "尚未開始"
              : locale === "en"
                ? `${uxMetrics.elapsedMinutes} min`
                : `${uxMetrics.elapsedMinutes} 分鐘`}
          </div>
          <div className="rounded-lg border border-outline-variant/20 px-3 py-2">
            {locale === "en" ? "Stage coverage: " : locale === "zh-Hans" ? "阶段覆盖：" : "階段覆蓋："}
            {Object.values(uxMetrics.stageVisitCount).filter((v) => v > 0).length}/5
          </div>
        </div>
      </article>
    </section>
  );
}
