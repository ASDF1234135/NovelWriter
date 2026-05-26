import { useEffect, useState, type ReactNode } from "react";
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
  /** When set, bulk-download all completed chapters as ZIP. Hidden when reviewing against `articleOverride`. */
  onDownloadAllCompletedZip?: () => Promise<void>;
  /** Number of `completed` chapters; ZIP control disabled when zero. Defaults to `0`. */
  completedChaptersZipCount?: number;
  /**
   * When provided, replaces the default article body (drafted chapter content). Used by the
   * post-reader human-review HITL to render an editable review surface within the reading area.
   * In the review shell this is shown beside a read-only "saved chapter" reference column on
   * large screens, or behind a tab on narrow viewports so the draft UI does not fully replace
   * access to the on-disk chapter text.
   */
  articleOverride?: ReactNode;
  /**
   * Disable the chapter-list buttons (left rail) so the user cannot navigate away mid-review.
   * Pairs with `articleOverride` for the post-reader chapter-review gate.
   */
  disableChapterSelection?: boolean;
  /** Title shown above the article when `articleOverride` is rendered. */
  reviewModeTitle?: string;
};

/**
 * Reading surface for the review shell.
 *
 * Layout changes vs. the old version:
 *  - The chapter list (left rail) is now a "book spine" — `lg:w-14` collapsed,
 *    hover/focus-within expands to `lg:w-64`. On small screens it becomes a
 *    horizontal chip strip pinned at the top so it never eats reading space.
 *  - The old `rightRail` (Actions header + side panel) is gone. The Download
 *    button moves to an inline "desk-clip" at the top of the manuscript so it
 *    feels like a brass clamp pinning the page down. Everything else (HITL,
 *    workflow progress, run logs) now lives in the review shell's top ribbon
 *    and floating dock.
 *  - The manuscript page itself uses the `.atelier-paper` token — a warm
 *    cream surface with subtle paper grain — to create a "manuscript on a
 *    dark desk" contrast with the surrounding stage.
 */
export function ChapterReader({
  storyId,
  currentChapterId,
  chapters,
  chapter,
  outputLanguage = "zh-Hant",
  busy,
  onSelectChapter,
  onDownloadChapter,
  onDownloadAllCompletedZip,
  completedChaptersZipCount = 0,
  articleOverride,
  disableChapterSelection,
  reviewModeTitle,
}: Props) {
  const { locale, t } = useI18n();
  /** Narrow viewports: toggle between saved chapter text and the review gate. */
  const [reviewMobilePane, setReviewMobilePane] = useState<"saved" | "draft">("draft");

  useEffect(() => {
    if (!articleOverride) return;
    setReviewMobilePane("draft");
  }, [articleOverride, chapter?.chapter_id]);

  const content = chapter?.content ?? "";
  const isEn = outputLanguage === "en";
  const lengthStat = isEn ? englishWordCount(content) : content.replace(/\s/g, "").length;
  const lengthLabel = isEn
    ? "Words"
    : locale === "en"
      ? "Characters (approx.)"
      : locale === "zh-Hans"
        ? "字数（近似）"
        : "字元量（近似）";

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
          {/* Mobile / narrow: horizontal chip strip pinned at the top. */}
          <nav
            aria-label={t("reviewShell.spine.chapters")}
            className="block w-full shrink-0 overflow-x-auto border-b border-secondary/15 bg-surface-container-low/40 px-3 py-2 no-scrollbar lg:hidden"
          >
            <ul className="flex w-max items-center gap-1.5">
              {chapters.length === 0 ? (
                <li className="font-body text-xs italic text-on-surface-variant">
                  {locale === "en"
                    ? "No chapters yet."
                    : locale === "zh-Hans"
                      ? "尚无章节。"
                      : "尚無章節。"}
                </li>
              ) : (
                chapters.map((item) => {
                  const active = item.chapter_id === currentChapterId;
                  return (
                    <li key={item.chapter_key}>
                      <button
                        type="button"
                        onClick={() => onSelectChapter(item.chapter_id)}
                        disabled={busy || disableChapterSelection}
                        title={disableChapterSelection ? reviewModeTitle ?? "" : item.title}
                        className={`whitespace-nowrap rounded-full border px-3 py-1 font-label text-[11px] uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                          active
                            ? "border-secondary/60 bg-secondary/15 text-secondary"
                            : "border-outline-variant/30 bg-surface-container-highest/40 text-on-surface-variant hover:bg-surface-container-high"
                        }`}
                      >
                        {locale === "en"
                          ? `Ch ${item.chapter_id}`
                          : `第${item.chapter_id}章`}
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          </nav>

          {/* Desktop: slim "book spine" rail that hover-expands. */}
          <aside
            aria-label={t("reviewShell.spine.chapters")}
            className="group/spine hidden shrink-0 border-r border-secondary/15 bg-surface-container-low/30 transition-[width] duration-300 ease-out hover:w-64 focus-within:w-64 lg:flex lg:w-14 lg:flex-col"
          >
            <div className="border-b border-secondary/15 px-3 py-3">
              <p className="truncate font-label text-[9px] font-bold uppercase tracking-[0.32em] text-secondary/70">
                {t("reviewShell.spine.chapters")}
              </p>
              <p className="mt-1 hidden truncate font-body text-[11px] italic text-on-surface-variant/80 group-hover/spine:block group-focus-within/spine:block">
                {t("reviewShell.spine.expandHint")}
              </p>
            </div>
            {chapters.length === 0 ? (
              <p className="hidden p-3 font-body text-xs italic text-on-surface-variant/80 group-hover/spine:block group-focus-within/spine:block">
                {locale === "en"
                  ? "No chapters available yet."
                  : locale === "zh-Hans"
                    ? "尚无已落盘章节。"
                    : "尚無已落盤章節。"}
              </p>
            ) : (
              <ol className="flex max-h-[calc(100vh-12rem)] flex-col gap-0 overflow-y-auto no-scrollbar">
                {chapters.map((item) => {
                  const active = item.chapter_id === currentChapterId;
                  return (
                    <li key={item.chapter_key}>
                      <button
                        type="button"
                        onClick={() => onSelectChapter(item.chapter_id)}
                        disabled={busy || disableChapterSelection}
                        title={disableChapterSelection ? reviewModeTitle ?? "" : item.title}
                        data-active={active ? "true" : "false"}
                        className="atelier-bookmark w-full disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <span className="font-mono text-[11px] tracking-widest">
                          {String(item.chapter_id).padStart(2, "0")}
                        </span>
                        <span className="hidden min-w-0 max-w-[12rem] truncate text-left font-body text-[12px] normal-case tracking-normal text-on-surface group-hover/spine:block group-focus-within/spine:block">
                          {item.title}
                        </span>
                        <span className="hidden font-label text-[9px] uppercase tracking-wider text-on-surface-variant/70 group-hover/spine:block group-focus-within/spine:block">
                          {chapterStatusLabel(item.status)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            )}
          </aside>

          <section className="atelier-stage relative min-w-0 flex-1 overflow-y-auto px-4 py-8 sm:px-8 md:px-12 lg:px-16">
            <div
              className={`mx-auto w-full max-w-[760px] ${articleOverride ? "lg:max-w-[min(1152px,calc(100vw-2rem))]" : ""}`}
            >
              <div className="atelier-paper relative rounded-[14px] px-6 py-10 sm:px-10 md:px-14 lg:px-16">
                {chapter && !articleOverride ? (
                  <div className="absolute right-6 top-[-14px] z-10 flex flex-wrap items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => onDownloadChapter(chapter.chapter_id)}
                      disabled={busy}
                      className="atelier-desk-clip"
                      aria-label={t("reviewShell.downloadSingleAria")}
                    >
                      <span className="material-symbols-outlined text-base" aria-hidden>
                        attachment
                      </span>
                      {t("reviewShell.downloadSingle")}
                    </button>
                    {onDownloadAllCompletedZip ? (
                      <button
                        type="button"
                        onClick={() => void onDownloadAllCompletedZip()}
                        disabled={busy || completedChaptersZipCount < 1}
                        title={
                          completedChaptersZipCount < 1 ? t("reviewShell.downloadZipNoCompleted") : t("reviewShell.downloadAllZipAria")
                        }
                        className="atelier-desk-clip"
                        aria-label={t("reviewShell.downloadAllZipAria")}
                      >
                        <span className="material-symbols-outlined text-base" aria-hidden>
                          folder_zip
                        </span>
                        {t("reviewShell.downloadAllZip")}
                      </button>
                    ) : null}
                  </div>
                ) : null}

                <header className="mb-10">
                  <span
                    className="font-label text-[11px] font-bold uppercase tracking-[0.32em]"
                    style={{ color: "#9a7a2a" }}
                  >
                    {chapter
                      ? locale === "en"
                        ? `Chapter ${chapter.chapter_id}`
                        : `第 ${chapter.chapter_id} 章`
                      : "—"}
                  </span>
                  <h1
                    className="mt-3 font-body text-3xl italic leading-tight md:text-4xl"
                    style={{ color: "#2a221a" }}
                  >
                    {chapter?.title ??
                      (locale === "en"
                        ? "No chapter selected"
                        : locale === "zh-Hans"
                          ? "尚未选择章节"
                          : "尚未選擇章節")}
                  </h1>
                  {chapter ? (
                    <div
                      className="mt-6 flex flex-wrap items-center gap-4 font-label text-[10px] uppercase tracking-[0.22em]"
                      style={{ color: "#6b5630" }}
                    >
                      <span>
                        {lengthLabel} {lengthStat.toLocaleString()}
                      </span>
                      <span
                        className="h-1 w-1 rounded-full"
                        style={{ backgroundColor: "rgba(107,86,48,0.4)" }}
                      />
                      <span>{chapterStatusLabel(chapter.status)}</span>
                    </div>
                  ) : null}
                </header>

                {articleOverride ? (
                  <div className="review-dual-root w-full">
                    <div
                      className="mb-6 flex rounded-xl border border-[rgba(122,90,40,0.2)] bg-[rgba(255,250,235,0.45)] p-1 lg:hidden"
                      role="tablist"
                      aria-label={t("reviewShell.dual.ariaTabs")}
                    >
                      <button
                        type="button"
                        id="review-tab-saved"
                        role="tab"
                        aria-controls="review-panel-saved"
                        aria-selected={reviewMobilePane === "saved"}
                        className={`flex-1 rounded-lg px-3 py-2 font-label text-[11px] font-bold uppercase tracking-[0.18em] transition-colors ${
                          reviewMobilePane === "saved"
                            ? "bg-[#fff9ed] text-[#5c4218] shadow-sm ring-1 ring-[rgba(180,140,60,0.35)]"
                            : "text-[#6b5630]/80 hover:bg-[rgba(255,255,255,0.35)]"
                        }`}
                        onClick={() => setReviewMobilePane("saved")}
                      >
                        {t("reviewShell.dual.tabSaved")}
                      </button>
                      <button
                        type="button"
                        id="review-tab-draft"
                        role="tab"
                        aria-controls="review-panel-draft"
                        aria-selected={reviewMobilePane === "draft"}
                        className={`flex-1 rounded-lg px-3 py-2 font-label text-[11px] font-bold uppercase tracking-[0.18em] transition-colors ${
                          reviewMobilePane === "draft"
                            ? "bg-[#fff9ed] text-[#5c4218] shadow-sm ring-1 ring-[rgba(180,140,60,0.35)]"
                            : "text-[#6b5630]/80 hover:bg-[rgba(255,255,255,0.35)]"
                        }`}
                        onClick={() => setReviewMobilePane("draft")}
                      >
                        {t("reviewShell.dual.tabDraft")}
                      </button>
                    </div>

                    <div className="flex flex-col gap-8 lg:grid lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)] lg:items-start lg:gap-10">
                      <section
                        id="review-panel-saved"
                        role="tabpanel"
                        aria-labelledby="review-tab-saved"
                        className={`min-w-0 ${reviewMobilePane === "saved" ? "block" : "hidden"} lg:block`}
                      >
                        <div className="atelier-review-reference atelier-review-reference--sticky p-4 sm:p-5">
                          <p className="font-label text-[9px] font-bold uppercase tracking-[0.32em] text-[#8a6a38]">
                            {t("reviewShell.dual.referenceKicker")}
                          </p>
                          <h2 className="mt-1 font-headline text-sm font-bold tracking-tight text-[#3d2f1f]">
                            {t("reviewShell.dual.referenceTitle")}
                          </h2>
                          <p className="mt-2 font-body text-xs leading-relaxed text-[#5c4a32]/90">
                            {t("reviewShell.dual.referenceIntro")}
                          </p>
                          {content.trim() ? (
                            <article
                              className="prose-manuscript mt-4 max-h-[min(52vh,420px)] overflow-y-auto rounded-lg border border-[rgba(90,70,45,0.1)] bg-[rgba(255,255,252,0.65)] px-3 py-3 sm:max-h-[min(60vh,520px)] lg:max-h-[min(68vh,640px)]"
                              style={{ color: "rgba(42,34,26,0.9)" }}
                            >
                              <pre className="whitespace-pre-wrap font-body text-[15px] leading-[1.82] sm:text-base">
                                {content}
                              </pre>
                            </article>
                          ) : (
                            <p className="mt-4 rounded-lg border border-dashed border-[rgba(122,90,40,0.25)] bg-[rgba(255,252,244,0.5)] px-3 py-4 font-body text-sm italic leading-relaxed text-[#6b5630]/85">
                              {t("reviewShell.dual.referenceEmpty")}
                            </p>
                          )}
                        </div>
                      </section>

                      <section
                        id="review-panel-draft"
                        role="tabpanel"
                        aria-labelledby="review-tab-draft"
                        className={`min-w-0 ${reviewMobilePane === "draft" ? "block" : "hidden"} lg:block`}
                      >
                        <div className="review-article-override w-full">{articleOverride}</div>
                      </section>
                    </div>
                  </div>
                ) : chapter ? (
                  <article
                    className="prose-manuscript font-body text-lg leading-[1.85]"
                    style={{ color: "rgba(42,34,26,0.92)" }}
                  >
                    <pre className="whitespace-pre-wrap font-body text-lg leading-[1.85] first-letter:float-left first-letter:mr-3 first-letter:font-bold first-letter:text-7xl first-letter:text-[#7a5a28]">
                      {chapter.content}
                    </pre>
                  </article>
                ) : (
                  <p
                    className="font-body italic"
                    style={{ color: "rgba(74,58,24,0.7)" }}
                  >
                    {locale === "en"
                      ? "Choose a chapter from the spine."
                      : locale === "zh-Hans"
                        ? "请从左侧书脊选择章节。"
                        : "請從左側書脊選擇章節。"}
                  </p>
                )}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
