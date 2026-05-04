import { describe, expect, it } from "vitest";
import { buildExtraObject, extractAnchorGoal, findOverlappingVolumes, mergeMacroBibles, normalizeAnchors, splitBibleForForm } from "./macroPlanHelpers";

describe("splitBibleForForm", () => {
  it("migrates top-level tags into extra rows and synthesizes lore when general_world_lore is missing", () => {
    const { extraRows, generalWorldLore } = splitBibleForForm({
      genre: "科幻",
      tags: ["A", "B"],
      active_b_stories: [{ id: "x1", desc: "ignored", type: "UNKNOWN", resolution_condition: "" }],
    });
    expect(extraRows.some((r) => r.key === "tags" && r.isList)).toBe(true);
    expect(generalWorldLore).toContain("Genre");
    expect(generalWorldLore).toContain("科幻");
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

  it("uses existing general_world_lore when set", () => {
    const { generalWorldLore } = splitBibleForForm({
      genre: "X",
      general_world_lore: "## Custom\n\nbody",
      tone: "should not duplicate into lore string when lore exists",
    });
    expect(generalWorldLore).toBe("## Custom\n\nbody");
  });

  it("omits compile/runtime debug keys from extra rows (top-level and nested extra)", () => {
    const { extraRows } = splitBibleForForm({
      genre: "G",
      tags: ["ok"],
      branch_count_final: 3,
      llm_weave_debug: { x: 1 },
      resolved_anchors: ["a1"],
      anchor_candidates: ["a2"],
      extra: {
        branch_count_final: 9,
        llm_weave_debug: {},
        resolved_anchors: [],
        anchor_candidates: [],
        note: "visible",
      },
    });
    const keys = extraRows.map((r) => r.key);
    expect(keys).toContain("tags");
    expect(keys).toContain("note");
    expect(keys.some((k) => k === "branch_count_final")).toBe(false);
    expect(keys.some((k) => k === "llm_weave_debug")).toBe(false);
    expect(keys.some((k) => k === "resolved_anchors")).toBe(false);
    expect(keys.some((k) => k === "anchor_candidates")).toBe(false);
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

  it("prefers current (first arg) general_world_lore when non-empty", () => {
    const out = mergeMacroBibles(
      { general_world_lore: "## Form\n\nedited" },
      { general_world_lore: "## Stored\n\nold" },
    );
    expect(out.general_world_lore).toBe("## Form\n\nedited");
  });

  it("falls back to incoming lore when current is blank", () => {
    const out = mergeMacroBibles({ general_world_lore: "   " }, { general_world_lore: "from-stored" });
    expect(out.general_world_lore).toBe("from-stored");
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
