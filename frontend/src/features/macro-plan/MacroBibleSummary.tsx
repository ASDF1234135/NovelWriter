import { useMemo } from "react";
import { useI18n } from "../../i18n/useI18n";
import type { MacroCompileData } from "../../types";
import { isObjectRecord, splitBibleForForm } from "./macroPlanHelpers";

type Props = {
  macroData: MacroCompileData | null;
  /** Optional: cap visible lines of the world-lore Markdown blurb. */
  loreClampLines?: number;
};

/**
 * Read-only Bible preview used in the chapter-run right rail.
 *
 * Renders three count badges (volumes / cast / storylines), the genre tag,
 * and a clamped excerpt of `general_world_lore`. Editing happens through
 * the full `MacroPlanPanel` drawer opened from the rail.
 */
export function MacroBibleSummary({ macroData, loreClampLines = 6 }: Props) {
  const { locale, t } = useI18n();

  const { genre, lore } = useMemo(() => {
    const bibleRaw = macroData?.bible;
    const bible = isObjectRecord(bibleRaw) ? bibleRaw : {};
    const split = splitBibleForForm(bible as Record<string, unknown>);
    const genreVal = String(bible.story_genre ?? bible.genre ?? "").trim();
    return {
      genre: genreVal,
      lore: split.generalWorldLore.trim(),
    };
  }, [macroData]);

  const volumeCount = macroData?.volumes?.length ?? 0;
  const castCount = macroData?.cast?.length ?? 0;
  const storylineCount = macroData?.storylines?.length ?? 0;
  const anchorCount = macroData?.anchor_nodes?.length ?? 0;

  const genrePlaceholder =
    locale === "en" ? "No genre set" : locale === "zh-Hans" ? "尚未设定类型" : "尚未設定類型";

  if (!macroData) {
    return (
      <div className="rounded-lg border border-outline-variant/15 bg-surface-container-low/60 px-3 py-4 text-center font-body text-xs text-on-surface-variant">
        {t("app.write.compileResultEmpty")}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <dl className="grid grid-cols-4 gap-1.5">
        <StatBadge label={t("macroSummary.stat.volumes")} value={volumeCount} />
        <StatBadge label={t("macroSummary.stat.anchors")} value={anchorCount} />
        <StatBadge label={t("macroSummary.stat.cast")} value={castCount} />
        <StatBadge label={t("macroSummary.stat.storylines")} value={storylineCount} />
      </dl>

      <div className="rounded-lg border border-outline-variant/15 bg-surface-container-low/50 px-3 py-2.5">
        <p className="mb-1 font-label text-[9px] font-bold uppercase tracking-[0.25em] text-secondary/80">
          {t("macroSummary.genreLabel")}
        </p>
        <p
          className={
            genre
              ? "font-body text-sm font-semibold text-on-surface"
              : "font-body text-sm italic text-on-surface-variant/70"
          }
        >
          {genre || genrePlaceholder}
        </p>
      </div>

      <div className="rounded-lg border border-outline-variant/15 bg-surface-container-low/50 px-3 py-2.5">
        <p className="mb-1.5 font-label text-[9px] font-bold uppercase tracking-[0.25em] text-secondary/80">
          {t("macroSummary.loreLabel")}
        </p>
        {lore ? (
          <p
            className="whitespace-pre-wrap font-body text-xs leading-relaxed text-on-surface-variant"
            style={{
              display: "-webkit-box",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: loreClampLines,
              overflow: "hidden",
            }}
          >
            {lore}
          </p>
        ) : (
          <p className="font-body text-xs italic text-on-surface-variant/70">
            {t("macroSummary.loreEmpty")}
          </p>
        )}
      </div>
    </div>
  );
}

function StatBadge({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-outline-variant/15 bg-surface-container/80 px-1 py-2">
      <span className="font-headline text-lg font-bold leading-none tabular-nums text-on-surface">
        {value}
      </span>
      <span className="mt-1 font-label text-[9px] font-semibold uppercase tracking-[0.18em] text-on-surface-variant">
        {label}
      </span>
    </div>
  );
}
