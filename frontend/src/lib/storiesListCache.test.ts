import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import type { StoryListItem } from "../types";
import { upsertStoriesListCacheItem } from "./storiesListCache";

describe("upsertStoriesListCacheItem", () => {
  it("updates an existing story row in the list cache", () => {
    const qc = new QueryClient();
    const initial: StoryListItem[] = [
      {
        story_id: "s1",
        title: "Old",
        premise: "old premise",
        target_total_words: 1000,
        created_at: "2020-01-01T00:00:00Z",
      },
    ];
    qc.setQueryData(["stories-list"], initial);

    upsertStoriesListCacheItem(qc, {
      story_id: "s1",
      title: "New title",
      premise: "new premise",
      target_total_words: 200000,
    });

    const next = qc.getQueryData<StoryListItem[]>(["stories-list"]);
    expect(next).toHaveLength(1);
    expect(next?.[0].title).toBe("New title");
    expect(next?.[0].premise).toBe("new premise");
    expect(next?.[0].target_total_words).toBe(200000);
    expect(next?.[0].created_at).toBe("2020-01-01T00:00:00Z");
  });
});
