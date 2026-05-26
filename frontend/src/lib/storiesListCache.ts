import type { QueryClient } from "@tanstack/react-query";
import type { StoryDetailResponse, StoryListItem } from "../types";

/** Keep GET /stories list cache aligned with a freshly saved story row. */
export function upsertStoriesListCacheItem(
  queryClient: QueryClient,
  detail: Pick<StoryDetailResponse, "story_id" | "title" | "premise" | "target_total_words">,
) {
  queryClient.setQueryData<StoryListItem[]>(["stories-list"], (prev) => {
    const list = prev ?? [];
    const idx = list.findIndex((x) => x.story_id === detail.story_id);
    const created_at = idx >= 0 ? list[idx].created_at : new Date().toISOString();
    const nextItem: StoryListItem = {
      story_id: detail.story_id,
      title: detail.title,
      premise: detail.premise,
      target_total_words: detail.target_total_words,
      created_at,
    };
    if (idx >= 0) {
      const next = [...list];
      next[idx] = nextItem;
      return next;
    }
    return [nextItem, ...list];
  });
}

export async function refreshStoriesListCache(queryClient: QueryClient) {
  await queryClient.refetchQueries({ queryKey: ["stories-list"] });
}
