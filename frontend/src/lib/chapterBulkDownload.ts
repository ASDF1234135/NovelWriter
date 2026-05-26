import { strToU8, zipSync } from "fflate";
import { fetchChapter } from "../api";
import type { ChapterSummary } from "../types";

/**
 * Downloads all chapters whose status is `completed` as a single ZIP (UTF-8 .txt bodies).
 */
export async function downloadCompletedChaptersZip(
  storyId: string,
  chapters: ChapterSummary[],
): Promise<void> {
  const completed = chapters.filter((c) => String(c.status ?? "").toLowerCase() === "completed");
  if (!completed.length) return;

  const entries: Record<string, Uint8Array> = {};
  for (const c of completed) {
    const row = await fetchChapter(storyId, c.chapter_id);
    const title = String(row.title ?? "").trim();
    const body = String(row.content ?? "");
    const txt = title ? `${title}\n\n${body}` : body;
    entries[`chapter-${row.chapter_id}.txt`] = strToU8(txt);
  }

  const zipped = zipSync(entries, { level: 6 });
  const safePrefix = storyId.replace(/[^\w.-]+/g, "_").slice(0, 32) || "story";
  const blob = new Blob([new Uint8Array(zipped)], { type: "application/zip" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${safePrefix}-chapters.zip`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
