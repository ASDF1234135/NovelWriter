import type { ReactNode } from "react";
import type { ChapterContent, ChapterSummary, StoryOutputLanguage } from "../../types";
import { chapterStatusLabel } from "../ui-copy/workflowDisplay";
import { useI18n } from "../../i18n/useI18n";

/** Whitespace-separated tokens; aligns with backend English chapter length for typical prose. */
function englishWordCount(text: string): number {
  const t = text.trim();
  if (!t) return 0;
  return t.split(/\s+/).length;
}

type Props = {
  storyId: string;
  currentChapterId: number;
  chapters: ChapterSummary[];
  chapter: ChapterContent | null;
  /** When `en`, header shows word count; otherwise approximate non-whitespace character count. */
  outputLanguage?: StoryOutputLanguage;
  busy?: boolean;
  onSelectChapter: (chapterId: number) => Promise<void>;
  onDownloadChapter: (chapterId: number) => Promise<void>;
  rightRail?: ReactNode;
};

export function ChapterReader({
  storyId,
  currentChapterId,
  chapters,
  chapter,
  outputLanguage = "zh-Hant",
  busy,
  onSelectChapter,
  onDownloadChapter,
  rightRail,
}: Props) {
  const { locale } = useI18n();
  const content = chapter?.content ?? "";
  const isEn = outputLanguage === "en";
  const lengthStat = isEn ? englishWordCount(content) : content.replace(/\s/g, "").length;
  const lengthLabel = isEn ? "Words" : locale === "en" ? "Characters (approx.)" : locale === "zh-Hans" ? "字数（近似）" : "字元量（近似）";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
      {!storyId ? (
        <div className="flex flex-1 items-center justify-center p-12 font-body text-on-surface-variant">
          {locale === "en"
            ? "Create a story in Setup first, then generate chapters."
            : locale === "zh-Hans"
              ? "请先到“故事设置”建立故事并生成章节。"
              : "請先到「故事設定」建立故事並產生章節。"}
        </div>
      ) : (
        <>
          <aside className="w-full shrink-0 border-b border-outline-variant/10 bg-surface-container-low lg:w-56 lg:border-b-0 lg:border-r">
            <div className="p-4">
              <h3 className="mb-3 font-headline text-xs font-bold uppercase tracking-wider text-primary">
                {locale === "en" ? "Chapters" : locale === "zh-Hans" ? "章节列表" : "章節列表"}
              </h3>
              {chapters.length === 0 ? (
                <p className="font-body text-sm text-on-surface-variant">
                  {locale === "en" ? "No chapters available yet." : locale === "zh-Hans" ? "尚无已落盘章节。" : "尚無已落盤章節。"}
                </p>
              ) : (
                <div className="flex max-h-48 flex-col gap-2 overflow-y-auto no-scrollbar lg:max-h-[calc(100vh-12rem)]">
                  {chapters.map((item) => (
                    <button
                      key={item.chapter_key}
                      type="button"
                      onClick={() => onSelectChapter(item.chapter_id)}
                      disabled={busy}
                      className={`w-full rounded-lg px-3 py-2 text-left font-label text-sm transition-colors ${
                        item.chapter_id === currentChapterId
                          ? "bg-primary/20 text-primary"
                          : "bg-surface-container-highest/60 text-on-surface hover:bg-surface-container-high"
                      }`}
                    >
                      {item.title}
                      <span className="mt-0.5 block text-[10px] tracking-wide text-on-surface-variant">
                        {chapterStatusLabel(item.status)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </aside>

          <section className="min-w-0 flex-1 overflow-y-auto px-6 py-10 md:px-16 lg:px-20">
            <div className="mx-auto max-w-read">
              <header className="mb-12">
                <span className="font-label text-sm font-bold uppercase tracking-[0.2em] text-secondary">
                  {chapter
                    ? locale === "en"
                      ? `Chapter ${chapter.chapter_id}`
                      : `第 ${chapter.chapter_id} 章`
                    : "—"}
                </span>
                <h1 className="mt-4 font-body text-4xl italic leading-tight text-on-surface md:text-5xl">
                  {chapter?.title ?? (locale === "en" ? "No chapter selected" : locale === "zh-Hans" ? "尚未选择章节" : "尚未選擇章節")}
                </h1>
                {chapter ? (
                  <div className="mt-8 flex flex-wrap items-center gap-4 font-label text-xs uppercase tracking-widest text-on-surface-variant">
                    <span>
                      {lengthLabel} {lengthStat.toLocaleString()}
                    </span>
                    <span className="h-1 w-1 rounded-full bg-outline-variant" />
                    <span>{chapterStatusLabel(chapter.status)}</span>
                  </div>
                ) : null}
              </header>
              {chapter ? (
                <article className="prose-manuscript font-body text-lg leading-[1.8] text-on-surface/90 first-letter:float-left first-letter:mr-3 first-letter:font-bold first-letter:text-7xl first-letter:text-primary">
                  <pre className="whitespace-pre-wrap font-body text-lg leading-[1.8]">{chapter.content}</pre>
                </article>
              ) : (
                <p className="font-body text-on-surface-variant">
                  {locale === "en" ? "Choose a chapter from the left." : locale === "zh-Hans" ? "选择左侧章节以阅读内容。" : "選擇左側章節以閱讀內容。"}
                </p>
              )}
            </div>
          </section>

          <div className="flex w-full flex-col border-t border-outline-variant/10 bg-surface-container-low lg:w-80 lg:border-l lg:border-t-0">
            <div className="flex items-center justify-between border-b border-outline-variant/10 p-4">
              <h2 className="font-label text-xs font-extrabold uppercase tracking-[0.2em] text-primary">
                {locale === "en" ? "Actions" : locale === "zh-Hans" ? "操作" : "操作"}
              </h2>
              {chapter ? (
                <button
                  type="button"
                  onClick={() => onDownloadChapter(chapter.chapter_id)}
                  disabled={busy}
                  className="btn-primary-gradient flex items-center gap-2 py-2 pl-4 pr-5 text-xs"
                >
                  <span className="material-symbols-outlined text-base">download</span>
                  {locale === "en" ? "Download TXT" : locale === "zh-Hans" ? "下载纯文本" : "下載純文字"}
                </button>
              ) : null}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">{rightRail}</div>
          </div>
        </>
      )}
    </div>
  );
}
