import { describe, expect, it } from "vitest";
import type { MacroCompileData, MacroPlanPutBody } from "../types";
import {
  buildMacroPutBody,
  buildMacroPutBodyForExport,
  idUnderStoryPrefix,
  mergeMacroPlan,
  namespaceMacroPlanIdsForStory,
  parseMacroImportJson,
  resetAnchorNodesForProjectExport,
} from "./macroPlanBundle";

const sampleMacroData: MacroCompileData = {
  story_id: "story_x",
  bible: { story_genre: "奇幻" },
  volumes: [{ volume_id: "story_x_vol1", title: "V1", summary: "s", chapter_start: 1, chapter_end: 3 }],
  cast: [{ node_id: "story_x_mc", canonical_name: "Hero", role: "protagonist" }],
  protagonist_character_id: "story_x_mc",
  storylines: [
    {
      id: "story_x_main",
      type: "MAIN",
      title: "主線",
      overall_goal: "抵達終點",
      involved_entities: ["story_x_mc"],
    },
  ],
  anchor_nodes: [
    {
      id: "story_x_anchor_01",
      storyline_ids: ["story_x_main"],
      volume_id: "story_x_vol1",
      node_kind: "NORMAL",
      title: "開端",
      description: "d",
      depends_on: [],
      status: "UNLOCKED",
      estimated_chapter: 1,
    },
  ],
};

describe("macroPlanBundle", () => {
  it("buildMacroPutBody includes storylines for round-trip", () => {
    const body = buildMacroPutBody(sampleMacroData);
    expect(body.storylines).toHaveLength(1);
    expect(body.storylines?.[0].id).toBe("story_x_main");
    expect(body.anchor_nodes).toHaveLength(1);
    const json = JSON.stringify({ kind: "macro_compile", version: 1, macro_plan: body });
    const parsed = parseMacroImportJson(json);
    expect(parsed.storylines).toEqual(body.storylines);
    expect(parsed.anchor_nodes[0].id).toBe("story_x_anchor_01");
  });

  it("mergeMacroPlan merges storylines by id", () => {
    const base = buildMacroPutBody(sampleMacroData);
    const current: MacroPlanPutBody = {
      ...base,
      storylines: [...(base.storylines ?? []), { id: "keep", type: "B_TIER", title: "B", overall_goal: "g", involved_entities: [] }],
    };
    const incoming: MacroPlanPutBody = {
      ...base,
      storylines: [
        { id: "keep", type: "B_TIER", title: "B2", overall_goal: "g2", involved_entities: [] },
        { id: "new_sl", type: "S_TIER", title: "S", overall_goal: "sg", involved_entities: [] },
      ],
    };
    const merged = mergeMacroPlan(current, incoming);
    expect(merged.storylines?.map((s) => s.id).sort()).toEqual(["keep", "new_sl", "story_x_main"].sort());
    const keep = merged.storylines?.find((s) => s.id === "keep");
    expect(keep?.title).toBe("B");
  });

  it("resetAnchorNodesForProjectExport clears RESOLVED and restores post-compile LOCKED/UNLOCKED", () => {
    const nodes = [
      {
        id: "a1",
        storyline_ids: [],
        volume_id: "v1",
        node_kind: "NORMAL" as const,
        title: "root",
        description: "d",
        depends_on: [] as string[],
        status: "RESOLVED" as const,
      },
      {
        id: "a2",
        storyline_ids: [],
        volume_id: "v1",
        node_kind: "NORMAL" as const,
        title: "child",
        description: "d2",
        depends_on: ["a1"],
        status: "RESOLVED" as const,
      },
    ];
    const out = resetAnchorNodesForProjectExport(nodes);
    expect(out.find((n) => n.id === "a1")?.status).toBe("UNLOCKED");
    expect(out.find((n) => n.id === "a2")?.status).toBe("LOCKED");
  });

  it("buildMacroPutBodyForExport never emits RESOLVED statuses", () => {
    const data: MacroCompileData = {
      ...sampleMacroData,
      anchor_nodes: [
        {
          ...sampleMacroData.anchor_nodes![0],
          status: "RESOLVED",
        },
      ],
    };
    const body = buildMacroPutBodyForExport(data);
    expect(body.anchor_nodes.every((n) => n.status !== "RESOLVED")).toBe(true);
  });

  it("namespaceMacroPlanIdsForStory remaps storyline, anchor, depends_on, involved_entities", () => {
    const body: MacroPlanPutBody = {
      bible: {},
      volumes: [{ volume_id: "other_vol1", title: "V1", summary: "s", chapter_start: 1, chapter_end: 3 }],
      anchors: [],
      storylines: [
        {
          id: "other_main",
          type: "MAIN",
          title: "M",
          overall_goal: "g",
          involved_entities: ["other_mc"],
        },
      ],
      anchor_nodes: [
        {
          id: "other_anchor_1",
          storyline_ids: ["other_main"],
          volume_id: "other_vol1",
          node_kind: "NORMAL",
          title: "a",
          description: "d",
          depends_on: [],
          status: "UNLOCKED",
        },
        {
          id: "other_anchor_2",
          storyline_ids: ["other_main"],
          volume_id: "other_vol1",
          node_kind: "NORMAL",
          title: "b",
          description: "d2",
          depends_on: ["other_anchor_1"],
          status: "LOCKED",
        },
      ],
      cast: [{ node_id: "other_mc", canonical_name: "X", role: "protagonist" }],
      protagonist_character_id: "other_mc",
    };
    const target = "myStory";
    const out = namespaceMacroPlanIdsForStory(body, target);
    expect(out.storylines?.[0].id).toBe(idUnderStoryPrefix(target, "other_main"));
    expect(out.cast[0].node_id).toBe(idUnderStoryPrefix(target, "other_mc"));
    expect(out.storylines?.[0].involved_entities?.[0]).toBe(out.cast[0].node_id);
    const n1 = out.anchor_nodes.find((n) => n.id.endsWith("other_anchor_1"));
    const n2 = out.anchor_nodes.find((n) => n.id.endsWith("other_anchor_2"));
    expect(n1).toBeDefined();
    expect(n2?.depends_on?.[0]).toBe(n1?.id);
  });
});
