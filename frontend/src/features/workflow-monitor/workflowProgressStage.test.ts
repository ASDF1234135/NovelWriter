import { describe, expect, it } from "vitest";
import { HITL_REASON } from "../hitl-panel/hitlCopy";
import { FLOW_STEPS } from "../hitl-panel/hitlCopy";
import { computeWorkflowStageStepIndex } from "./workflowProgressStage";
import type { WorkflowPayload } from "../../types";

function wf(partial: {
  workflow_status?: string;
  runStatus?: string;
  requires_hitl?: boolean;
  hitl_reason?: string;
  resume_from?: string;
  current_agent?: string;
  last_agent?: string;
}): WorkflowPayload {
  return {
    run: {
      run_id: "r",
      story_id: "s",
      chapter_id: 1,
      status: partial.runStatus ?? "RUNNING",
      requires_hitl: partial.requires_hitl ?? false,
      hitl_reason: partial.hitl_reason ?? "",
      hitl_decision_mode: "NONE",
      current_agent: partial.current_agent ?? "",
    },
    state: {
      workflow_status: partial.workflow_status ?? "RUNNING",
      last_agent: partial.last_agent,
      resume_from: partial.resume_from,
      hitl_reason: partial.hitl_reason,
    },
    steps: [],
  } as WorkflowPayload;
}

describe("computeWorkflowStageStepIndex", () => {
  it("returns FLOW_STEPS.length when workflow_status is COMPLETED", () => {
    expect(
      computeWorkflowStageStepIndex(
        wf({ workflow_status: "COMPLETED", runStatus: "COMPLETED", requires_hitl: false }),
      ),
    ).toBe(FLOW_STEPS.length);
  });

  it("uses getStuckFlowStepIndex when WAITING_HITL and agents empty", () => {
    expect(
      computeWorkflowStageStepIndex(
        wf({
          workflow_status: "WAITING_HITL",
          runStatus: "WAITING_HITL",
          requires_hitl: true,
          hitl_reason: HITL_REASON.PLAN_LOOP,
          resume_from: "",
          current_agent: "",
          last_agent: "",
        }),
      ),
    ).toBe(3);
  });

  it("chapter draft review maps to reader stage via reason index", () => {
    expect(
      computeWorkflowStageStepIndex(
        wf({
          workflow_status: "WAITING_HITL",
          runStatus: "WAITING_HITL",
          requires_hitl: true,
          hitl_reason: HITL_REASON.CHAPTER_DRAFT_REVIEW,
          resume_from: "",
        }),
      ),
    ).toBe(7);
  });

  it("prefers current_agent when pipeline running without HITL", () => {
    expect(
      computeWorkflowStageStepIndex(
        wf({
          workflow_status: "RUNNING",
          runStatus: "RUNNING",
          current_agent: "chapter_summarizer",
        }),
      ),
    ).toBe(FLOW_STEPS.findIndex((s) => s.id === "chapter_summarizer"));
  });
});
