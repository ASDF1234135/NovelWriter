import { describe, expect, it } from "vitest";
import { HITL_REASON, HITL_REASON_MATRIX } from "../features/hitl-panel/hitlCopy";
import { buildHitlDevPayload, HITL_DEV_MOCK_SLUGS, HITL_DEV_SCENARIOS } from "./hitlDevMocks";

describe("hitlDevMocks", () => {
  it("covers every HITL_REASON_MATRIX row", () => {
    const scenarioReasons = new Set(HITL_DEV_SCENARIOS.map((s) => s.reason));
    for (const row of HITL_REASON_MATRIX) {
      expect(scenarioReasons.has(row.reason)).toBe(true);
    }
  });

  it("buildHitlDevPayload mirrors backend option ids per reason", () => {
    for (const row of HITL_REASON_MATRIX) {
      const { workflow } = buildHitlDevPayload(row.reason as (typeof HITL_REASON)[keyof typeof HITL_REASON], null);
      expect(workflow.run.status).toBe("WAITING_HITL");
      expect(workflow.run.requires_hitl).toBe(true);
      expect(workflow.run.hitl_reason).toBe(row.reason);
      expect(workflow.state.hitl_reason).toBe(row.reason);
      const pending = (workflow.state.pending_hitl_options as Array<{ id: string }>) ?? [];
      expect(pending.map((o) => o.id)).toEqual(row.optionIds);
      expect(workflow.run.hitl_context).toBeTruthy();
    }
  });

  it("extraction gate includes remap hints and graph", () => {
    const { workflow, graph } = buildHitlDevPayload(HITL_REASON.EXTRACTION_GATE, null);
    expect(graph?.nodes.length).toBeGreaterThan(0);
    expect(Array.isArray(workflow.state.hitl_extraction_remap_hints)).toBe(true);
    expect((workflow.state.hitl_extraction_remap_hints as unknown[]).length).toBeGreaterThan(0);
  });

  it("slug map resolves all console mock keys", () => {
    expect(Object.keys(HITL_DEV_MOCK_SLUGS).length).toBe(Object.values(HITL_REASON).length);
  });
});
