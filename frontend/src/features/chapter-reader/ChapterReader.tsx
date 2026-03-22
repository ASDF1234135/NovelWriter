import type { ChapterContent, ChapterSummary } from "../../types";

type Props = {
  storyId: string;
  currentChapterId: number;
  chapters: ChapterSummary[];
  chapter: ChapterContent | null;
  busy?: boolean;
  onSelectChapter: (chapterId: number) => Promise<void>;
  onDownloadChapter: (chapterId: number) => Promise<void>;
};

export function ChapterReader({
  storyId,
  currentChapterId,
  chapters,
  chapter,
  busy,
  onSelectChapter,
  onDownloadChapter,
}: Props) {
  return (
    <section className="panel">
      <h2>章節閱讀區</h2>
      {!storyId ? (
        <p>請先建立故事並生成章節。</p>
      ) : (
        <div className="output-grid chapter-reader-grid">
          <article>
            <h3>已生成章節</h3>
            {chapters.length === 0 ? (
              <p>目前尚未有已落盤的章節。</p>
            ) : (
              <div className="chapter-list">
                {chapters.map((item) => (
                  <button
                    key={item.chapter_key}
                    className={`chapter-list-item${item.chapter_id === currentChapterId ? " active" : ""}`}
                    onClick={() => onSelectChapter(item.chapter_id)}
                    disabled={busy}
                  >
                    {item.title} | {item.status}
                  </button>
                ))}
              </div>
            )}
          </article>
          <article className="chapter-reader-content">
            <div className="chapter-reader-header">
              <h3>{chapter ? chapter.title : "尚未選擇章節"}</h3>
              {chapter ? (
                <button onClick={() => onDownloadChapter(chapter.chapter_id)} disabled={busy}>
                  下載 TXT
                </button>
              ) : null}
            </div>
            {chapter ? <pre>{chapter.content}</pre> : <p>選擇左側章節後可在此閱讀內容。</p>}
          </article>
        </div>
      )}
    </section>
  );
}
