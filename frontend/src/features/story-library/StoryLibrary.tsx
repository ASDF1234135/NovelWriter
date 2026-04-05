import { useEffect, useState } from "react";
import { deleteStory, fetchStories } from "../../api";
import type { StoryListItem } from "../../types";

type Props = {
  onSelectStory: (storyId: string, title?: string) => void;
  onNewStory: () => void;
  /** Called after successful API delete (e.g. clear App state if current story). */
  onStoryDeleted?: (storyId: string) => void;
  /** Short async operations (create story, load list selection, etc.). */
  busy?: boolean;
  /** While a chapter workflow is auto-running, block switching stories or starting a new one. */
  blockSelectingStories?: boolean;
};

function formatCreatedAt(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function truncate(text: string, max: number): string {
  const t = text.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

export function StoryLibrary({
  onSelectStory,
  onNewStory,
  onStoryDeleted,
  busy = false,
  blockSelectingStories = false,
}: Props) {
  const [stories, setStories] = useState<StoryListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setLoadError("");
      try {
        const rows = await fetchStories();
        if (!cancelled) setStories(rows);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "無法載入故事列表");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="px-4 pb-16 pt-8 md:px-10 lg:px-12">
      <div className="mb-10 flex max-w-7xl flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span className="mb-2 block font-label text-xs font-semibold uppercase tracking-[0.3em] text-secondary">故事庫</span>
          <h1 className="font-headline text-4xl font-black tracking-tighter text-on-surface">你的故事</h1>
          <p className="mt-3 max-w-xl font-body text-lg italic text-on-surface-variant">
            選擇既有專案繼續編輯，或開始一則新故事。
          </p>
        </div>
        <button
          type="button"
          onClick={onNewStory}
          disabled={busy || blockSelectingStories}
          className="btn-primary-gradient flex shrink-0 items-center justify-center gap-2 self-start px-6 py-3 font-headline text-sm font-bold sm:self-auto"
        >
          <span className="material-symbols-outlined text-lg">add_circle</span>
          新故事
        </button>
      </div>

      {loadError ? (
        <div className="mb-8 max-w-2xl rounded-xl bg-error/10 px-4 py-3 font-label text-sm text-error">{loadError}</div>
      ) : null}

      {loading ? (
        <p className="font-label text-sm text-on-surface-variant">載入中…</p>
      ) : stories.length === 0 ? (
        <div className="max-w-xl rounded-md bg-surface-container-low px-8 py-12 text-center transition-all">
          <p className="font-body text-on-surface-variant">尚無故事。點「新故事」建立第一個專案。</p>
        </div>
      ) : (
        <ul className="mx-auto grid max-w-7xl grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
          {stories.map((s) => (
            <li key={s.story_id}>
              <div className="group relative flex w-full flex-col gap-4 rounded-md bg-surface-container-low p-6 text-left transition-all duration-200 hover:rounded-lg hover:bg-surface-container-high">
                <button
                  type="button"
                  disabled={busy || deletingId !== null || blockSelectingStories}
                  onClick={() => onSelectStory(s.story_id, s.title)}
                  className="flex w-full flex-col gap-4 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary/40"
                >
                  <h2 className="font-body text-2xl font-semibold leading-tight text-on-surface">{s.title}</h2>
                  <p className="font-body text-sm leading-relaxed text-on-surface-variant">{truncate(s.premise, 180)}</p>
                  <div className="flex flex-col gap-1 font-label text-xs uppercase tracking-wider text-on-surface-variant">
                    <span>
                      目標字數 <span className="text-secondary">{s.target_total_words.toLocaleString()}</span>
                    </span>
                    <span className="normal-case tracking-normal text-on-surface/60">{formatCreatedAt(s.created_at)}</span>
                    <span className="font-mono text-[10px] tracking-tight text-outline">故事編號 {s.story_id}</span>
                  </div>
                </button>
                <button
                  type="button"
                  disabled={busy || deletingId !== null || blockSelectingStories}
                  onClick={async (e) => {
                    e.stopPropagation();
                    if (!window.confirm(`確定刪除「${s.title}」？此動作無法復原。`)) return;
                    setDeletingId(s.story_id);
                    setLoadError("");
                    try {
                      await deleteStory(s.story_id);
                      setStories((prev) => prev.filter((x) => x.story_id !== s.story_id));
                      onStoryDeleted?.(s.story_id);
                    } catch (err) {
                      setLoadError(err instanceof Error ? err.message : "刪除失敗");
                    } finally {
                      setDeletingId(null);
                    }
                  }}
                  className="absolute right-4 top-4 rounded-lg border border-error/30 bg-error/10 px-2 py-1 font-label text-[10px] font-bold uppercase tracking-wider text-error opacity-100 transition-opacity hover:bg-error/20 sm:opacity-0 sm:group-hover:opacity-100"
                >
                  {deletingId === s.story_id ? "…" : "刪除"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
