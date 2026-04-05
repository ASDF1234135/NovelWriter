import type { ReactNode } from "react";
import type { ChapterContent, ChapterSummary } from "../../types";
import { chapterStatusLabel } from "../ui-copy/workflowDisplay";

type Props = {
  storyId: string;
  currentChapterId: number;
  chapters: ChapterSummary[];
  chapter: ChapterContent | null;
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
  busy,
  onSelectChapter,
  onDownloadChapter,
  rightRail,
}: Props) {
  const wc = chapter?.content ? chapter.content.replace(/\s/g, "").length : 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
      {!storyId ? (
        <div className="flex flex-1 items-center justify-center p-12 font-body text-on-surface-variant">
          請先到「故事設定」建立故事並產生章節。
        </div>
      ) : (
        <>
          <aside className="w-full shrink-0 border-b border-outline-variant/10 bg-surface-container-low lg:w-56 lg:border-b-0 lg:border-r">
            <div className="p-4">
              <h3 className="mb-3 font-headline text-xs font-bold uppercase tracking-wider text-primary">章節列表</h3>
              {chapters.length === 0 ? (
                <p className="font-body text-sm text-on-surface-variant">尚無已落盤章節。</p>
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
                  {chapter ? `第 ${chapter.chapter_id} 章` : "—"}
                </span>
                <h1 className="mt-4 font-body text-4xl italic leading-tight text-on-surface md:text-5xl">
                  {chapter?.title ?? "尚未選擇章節"}
                </h1>
                {chapter ? (
                  <div className="mt-8 flex flex-wrap items-center gap-4 font-label text-xs uppercase tracking-widest text-on-surface-variant">
                    <span>字元量（近似） {wc.toLocaleString()}</span>
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
                <p className="font-body text-on-surface-variant">選擇左側章節以閱讀內容。</p>
              )}
            </div>
          </section>

          <div className="flex w-full flex-col border-t border-outline-variant/10 bg-surface-container-low lg:w-80 lg:border-l lg:border-t-0">
            <div className="flex items-center justify-between border-b border-outline-variant/10 p-4">
              <h2 className="font-label text-xs font-extrabold uppercase tracking-[0.2em] text-primary">操作</h2>
              {chapter ? (
                <button
                  type="button"
                  onClick={() => onDownloadChapter(chapter.chapter_id)}
                  disabled={busy}
                  className="btn-primary-gradient flex items-center gap-2 py-2 pl-4 pr-5 text-xs"
                >
                  <span className="material-symbols-outlined text-base">download</span>
                  下載純文字
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
