import { describe, expect, it } from "vitest";
import { buildExtraObject, extractAnchorGoal, findOverlappingVolumes, mergeMacroBibles, normalizeAnchors, splitBibleForForm } from "./macroPlanHelpers";

describe("splitBibleForForm", () => {
  it("migrates top-level tags into extra rows and preserves active_b_stories", () => {
    const { extraRows, activeBStories } = splitBibleForForm({
      genre: "科幻",
      tags: ["A", "B"],
      active_b_stories: [{ id: "x1", desc: "副線", type: "UNKNOWN", resolution_condition: "" }],
    });
    expect(extraRows.some((r) => r.key === "tags" && r.isList)).toBe(true);
    expect(activeBStories).toHaveLength(1);
    expect(activeBStories[0]?.id).toBe("x1");
  });

  it("reads nested extra object", () => {
    const { extraRows } = splitBibleForForm({
      extra: { magic: "低魔" },
    });
    expect(extraRows.some((r) => r.key === "magic" && r.value === "低魔")).toBe(true);
  });

  it("ignores primary optional keys from extra", () => {
    const { extraRows } = splitBibleForForm({
      theme: "信任與背叛",
      narrative_pov: "第一人稱",
      writing_style: "短句直敘",
      extra: {
        theme: "不應出現",
        narrative_pov: "不應出現",
        writing_style: "不應出現",
        magic: "低魔",
      },
    });
    expect(extraRows.some((r) => r.key === "magic")).toBe(true);
    expect(extraRows.some((r) => r.key === "theme")).toBe(false);
    expect(extraRows.some((r) => r.key === "narrative_pov")).toBe(false);
    expect(extraRows.some((r) => r.key === "writing_style")).toBe(false);
  });
});

describe("buildExtraObject", () => {
  it("skips optional primary keys to avoid duplication", () => {
    const out = buildExtraObject([
      { key: "theme", value: "不應寫入 extra", isList: false },
      { key: "narrative_pov", value: "不應寫入 extra", isList: false },
      { key: "writing_style", value: "不應寫入 extra", isList: false },
      { key: "magic", value: "低魔", isList: false },
    ]);
    expect(out).toEqual({ magic: "低魔" });
  });
});

describe("mergeMacroBibles", () => {
  it("merges extra objects with current winning key collisions", () => {
    const out = mergeMacroBibles({ extra: { a: 1, b: 2 } }, { extra: { b: 3, c: 4 } });
    expect((out.extra as Record<string, number>).b).toBe(2);
    expect((out.extra as Record<string, number>).c).toBe(4);
  });

  it("dedupes active_b_stories by id with current winning", () => {
    const out = mergeMacroBibles(
      { active_b_stories: [{ id: "s1", desc: "cur" }] },
      { active_b_stories: [{ id: "s1", desc: "inc" }, { id: "s2", desc: "b" }] },
    );
    const stories = out.active_b_stories as Array<{ id: string; desc: string }>;
    expect(stories.find((s) => s.id === "s1")?.desc).toBe("cur");
    expect(stories.find((s) => s.id === "s2")?.desc).toBe("b");
  });
});

describe("normalizeAnchors", () => {
  it("sorts by chapter target and reassigns priority", () => {
    const out = normalizeAnchors([
      { anchor_id: "a2", chapter_target: 3, priority: 9 },
      { anchor_id: "a1", chapter_target: 2, priority: 4 },
      { anchor_id: "a3", chapter_target: 3, priority: 5 },
    ]);
    expect(out.map((x) => x.anchor_id)).toEqual(["a1", "a2", "a3"]);
    expect(out.map((x) => x.priority)).toEqual([1, 2, 3]);
  });
});

describe("findOverlappingVolumes", () => {
  it("finds overlapping chapter ranges", () => {
    const out = findOverlappingVolumes([
      { volume_id: "v1", title: "卷一", chapter_start: 1, chapter_end: 3 },
      { volume_id: "v2", title: "卷二", chapter_start: 3, chapter_end: 5 },
      { volume_id: "v3", title: "卷三", chapter_start: 6, chapter_end: 8 },
    ]);
    expect(out).toEqual([["v1", "v2"]]);
  });
});

describe("extractAnchorGoal", () => {
  it("prefers chapter_goal key", () => {
    expect(extractAnchorGoal({ chapter_goal: "完成救援" })).toBe("完成救援");
  });
});
