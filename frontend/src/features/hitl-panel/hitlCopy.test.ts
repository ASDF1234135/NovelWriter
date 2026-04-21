import { describe, expect, it } from "vitest";
import {
  defaultSolutionForReason,
  getSituationCopy,
  HITL_REASON,
  HITL_REASON_MATRIX,
  solutionsForReason,
} from "./hitlCopy";

describe("HITL reason matrix baseline", () => {
  it("keeps one row for each known reason", () => {
    expect(HITL_REASON_MATRIX).toHaveLength(Object.keys(HITL_REASON).length);
  });

  it("matches title and solution mapping functions", () => {
    for (const row of HITL_REASON_MATRIX) {
      expect(row.title).toBe(getSituationCopy(row.reason).title);
      expect(row.solutionIds).toEqual(solutionsForReason(row.reason).map((x) => x.id));
      if (row.defaultSolution) {
        expect(row.defaultSolution).toBe(defaultSolutionForReason(row.reason));
      } else {
        expect(row.solutionIds).toHaveLength(0);
      }
    }
  });
});
