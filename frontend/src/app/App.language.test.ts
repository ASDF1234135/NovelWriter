import { describe, expect, it } from "vitest";

import { isStoryConfigDirty, normalizeOutputLanguage, storyDetailToInput } from "./App";
import type { StoryDetailResponse } from "../types";

function buildDetail(overrides: Partial<StoryDetailResponse> = {}): StoryDetailResponse {
  return {
    story_id: "story_x",
    title: "Title",
    premise: "Premise",
    bible: {},
    target_total_words: 1000,
    plan_retry_limit: 3,
    draft_loop_retry_limit: 3,
    macro_author_notes: "",
    cast_seed: [],
    output_language: "zh-Hant",
    configuration_locked: false,
    ...overrides,
  };
}

describe("normalizeOutputLanguage", () => {
  it("maps common aliases to canonical values", () => {
    expect(normalizeOutputLanguage("zh-CN")).toBe("zh-Hans");
    expect(normalizeOutputLanguage("zh-TW")).toBe("zh-Hant");
    expect(normalizeOutputLanguage("en-us")).toBe("en");
  });
});

describe("storyDetailToInput", () => {
  it("keeps canonical output language from response", () => {
    const input = storyDetailToInput(buildDetail({ output_language: "zh-Hans" }));
    expect(input.output_language).toBe("zh-Hans");
  });

  it("uses fallback language when output_language is missing", () => {
    const detail = buildDetail();
    delete (detail as StoryDetailResponse & { output_language?: unknown }).output_language;
    const input = storyDetailToInput(detail, "zh-Hans");
    expect(input.output_language).toBe("zh-Hans");
  });
});

describe("isStoryConfigDirty", () => {
  it("returns true when output language changed but not persisted", () => {
    const persisted = storyDetailToInput(buildDetail({ output_language: "zh-Hant" }));
    const current = storyDetailToInput(buildDetail({ output_language: "zh-Hans" }));
    expect(isStoryConfigDirty(current, persisted)).toBe(true);
  });

  it("returns false for equivalent payloads", () => {
    const persisted = storyDetailToInput(buildDetail({ output_language: "zh-Hans" }));
    const current = storyDetailToInput(buildDetail({ output_language: "zh-Hans" }));
    expect(isStoryConfigDirty(current, persisted)).toBe(false);
  });
});
