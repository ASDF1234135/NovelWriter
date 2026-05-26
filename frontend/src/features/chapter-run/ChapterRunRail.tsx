import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  bibleSlot: ReactNode;
  dagSlot: ReactNode;
  /** Optional: total anchor-node count, shown inside DAG window. */
  anchorNodeCount?: number;
  /** Disable the buttons (e.g. before a story is selected). */
  disabled?: boolean;
  /** When true, show “compiled result” badge copy for Setup page. */
  showCompiledBadge?: boolean;
};

/**
 * Two-button reference launcher:
 * - “Story settings” opens a window with the world overview (read-only).
 * - “Plot DAG” opens a window with the anchor topology (fullscreen + edit mode for changes).
 */
export function ChapterRunRail({
  bibleSlot,
  dagSlot,
  anchorNodeCount,
  disabled = false,
  showCompiledBadge = false,
}: Props) {
  const { t } = useI18n();
  const [windowOpen, setWindowOpen] = useState<null | "bible" | "dag">(null);
  const dialogMount = typeof document !== "undefined" ? document.body : null;
  const hasDag = (anchorNodeCount ?? 0) > 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-2"
          onClick={() => setWindowOpen("bible")}
          disabled={disabled}
        >
          <span className="material-symbols-outlined text-base" aria-hidden>
            auto_stories
          </span>
          {t("chapterRail.openStorySettings")}
          {showCompiledBadge ? (
            <span className="ml-1 rounded-full border border-outline-variant/25 bg-surface-container-high px-2 py-0.5 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
              {t("chapterRail.compiledBadge")}
            </span>
          ) : null}
        </button>
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-2"
          onClick={() => setWindowOpen("dag")}
          disabled={disabled || !hasDag}
          title={!hasDag ? t("chapterRail.dagEmpty") : undefined}
        >
          <span className="material-symbols-outlined text-base" aria-hidden>
            account_tree
          </span>
          {t("chapterRail.openPlotDag")}
          {anchorNodeCount != null ? (
            <span className="ml-1 rounded-full border border-outline-variant/25 bg-surface-container-high px-2 py-0.5 font-label text-[10px] font-semibold tabular-nums text-on-surface-variant">
              {t("chapterRail.dagNodeCount", undefined, { n: anchorNodeCount })}
            </span>
          ) : null}
        </button>
      </div>

      {dialogMount && windowOpen
        ? createPortal(
            <div
              className="fixed inset-0 z-[65000] flex items-center justify-center bg-black/55 px-4 py-8 backdrop-blur-[2px] md:px-10"
              role="dialog"
              aria-modal="true"
              aria-label={windowOpen === "bible" ? t("chapterRail.window.bibleTitle") : t("chapterRail.window.dagTitle")}
              onClick={(e) => {
                if (e.target === e.currentTarget) setWindowOpen(null);
              }}
            >
              <div
                className="nb-panel relative flex max-h-[min(960px,92vh)] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-outline-variant/20 bg-surface-container-high shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
                onClick={(e) => e.stopPropagation()}
              >
                <header className="flex items-start justify-between gap-3 border-b border-outline-variant/10 px-5 py-4">
                  <div className="min-w-0">
                    <p className="font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary/80">
                      {t("chapterRail.window.kicker")}
                    </p>
                    <h3 className="mt-1 font-headline text-xl font-bold tracking-tight text-on-surface">
                      {windowOpen === "bible" ? t("chapterRail.window.bibleTitle") : t("chapterRail.window.dagTitle")}
                    </h3>
                  </div>
                  <button
                    type="button"
                    className="rounded-xl border border-outline-variant/30 bg-surface-container px-3 py-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-container-high"
                    onClick={() => setWindowOpen(null)}
                  >
                    {t("common.close")}
                  </button>
                </header>
                <div className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
                  {windowOpen === "bible" ? bibleSlot : dagSlot}
                </div>
              </div>
            </div>,
            dialogMount,
          )
        : null}
    </div>
  );
}
