import { describe, expect, it } from "vitest";
import {
  countWeaklyConnectedComponents,
  detectCycle,
  formatAnchorDagValidationIssue,
  validateAnchorDagComprehensive,
  validateAnchorDagForPut,
} from "./anchorDagValidate";

describe("anchorDagValidate", () => {
  it("detects cycle", () => {
    const nodes = [
      { id: "a", depends_on: [] as string[] },
      { id: "b", depends_on: ["a"] },
      { id: "c", depends_on: ["b"] },
    ];
    expect(detectCycle(nodes)).toBe(false);
    const cycle = [
      { id: "a", depends_on: ["c"] },
      { id: "b", depends_on: ["a"] },
      { id: "c", depends_on: ["b"] },
    ];
    expect(detectCycle(cycle)).toBe(true);
  });

  it("counts weakly connected components", () => {
    expect(countWeaklyConnectedComponents([{ id: "a", depends_on: [] }])).toBe(1);
    const twoIslands = [
      { id: "a", depends_on: [] as string[] },
      { id: "b", depends_on: [] },
    ];
    expect(countWeaklyConnectedComponents(twoIslands)).toBe(2);
    const bridged = [
      { id: "a", depends_on: [] as string[] },
      { id: "b", depends_on: ["a"] },
    ];
    expect(countWeaklyConnectedComponents(bridged)).toBe(1);
  });

  it("validateAnchorDagComprehensive: USER_EDIT without forward CHECKPOINT is warning only", () => {
    const storylines = [
      { id: "s_main", type: "MAIN" },
      { id: "ue", type: "USER_EDIT" },
    ];
    const nodes = [
      { id: "m", storyline_ids: ["s_main"], depends_on: [] as string[] },
      { id: "u1", storyline_ids: ["ue"], depends_on: ["m"] },
    ];
    const r = validateAnchorDagComprehensive(nodes, storylines);
    expect(r.blocking).toBeNull();
    const w = r.warnings.find((x) => x.code === "USER_EDIT_NO_CHECKPOINT");
    expect(w).toBeDefined();
    expect(formatAnchorDagValidationIssue(w!, "zh-Hant")).toContain("checkpoint");
    expect(formatAnchorDagValidationIssue(w!, "en")).toMatch(/checkpoint/i);
  });

  it("validateAnchorDagForPut returns blocking only", () => {
    const storylines = [{ id: "m", type: "MAIN" }];
    const disconnected = [
      { id: "a", storyline_ids: ["m"], depends_on: [] as string[] },
      { id: "b", storyline_ids: ["m"], depends_on: [] },
    ];
    const err = validateAnchorDagForPut(disconnected, storylines);
    expect(err?.code).toBe("DAG_ISLANDS");
  });
});
