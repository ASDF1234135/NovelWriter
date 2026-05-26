import { describe, expect, it } from "vitest";
import {
  buildAnchorMilestoneRows,
  filterGraphNodesByType,
  getRemapExpectedNodeType,
  mapHitlQuickActionLabel,
  type GraphNodeLite,
} from "./hitlNarrative";

const tZh: (key: string, fallback?: string, params?: Record<string, string | number>) => string = (key, fallback = "", params) => {
  if (key === "hitl.option.keep_current_logic") return "維持現有草稿（強制通過）";
  if (key === "hitl.option.missing") return "";
  return fallback || key;
};

describe("hitlNarrative", () => {
  it("mapHitlQuickActionLabel prefers i18n then server label", () => {
    expect(mapHitlQuickActionLabel("keep_current_logic", "伺服器舊字", tZh)).toBe("維持現有草稿（強制通過）");
    expect(mapHitlQuickActionLabel("unknown_opt", "後端標籤", tZh)).toBe("後端標籤");
    expect(mapHitlQuickActionLabel("unknown_opt", "", tZh)).toBe("unknown_opt");
  });

  it("getRemapExpectedNodeType reads planned_graph_nodes", () => {
    const state = {
      planned_graph_nodes: [{ node_id: "p1", node_type: "CHARACTER" }],
    };
    expect(getRemapExpectedNodeType("p1", state)).toBe("CHARACTER");
    expect(getRemapExpectedNodeType("", state)).toBe(null);
    expect(getRemapExpectedNodeType("missing", state)).toBe(null);
  });

  it("filterGraphNodesByType returns all nodes when type is null", () => {
    const nodes: GraphNodeLite[] = [
      { node_id: "a", node_type: "ITEM" },
      { node_id: "b", node_type: "CHARACTER" },
    ];
    expect(filterGraphNodesByType(nodes, null)).toEqual(nodes);
  });

  it("buildAnchorMilestoneRows uses anchor_nodes title and description", () => {
    const rows = buildAnchorMilestoneRows({
      anchor_nodes: [{ id: "a1", title: "取得黑曜短刃", description: "應確實取得道具。" }],
      anchor_resolution_hitl_candidate: {
        unresolved_anchor_ids: ["a1"],
        resolution_analysis: "系統無法自動判定。",
      },
    });
    expect(rows).toHaveLength(1);
    expect(rows[0]?.title).toBe("取得黑曜短刃");
    expect(rows[0]?.description).toBe("應確實取得道具。");
  });

  it("filterGraphNodesByType matches node_type case-insensitively", () => {
    const nodes: GraphNodeLite[] = [
      { node_id: "a", node_type: "item" },
      { node_id: "b", node_type: "CHARACTER" },
    ];
    expect(filterGraphNodesByType(nodes, "ITEM").map((n) => n.node_id)).toEqual(["a"]);
  });
});
