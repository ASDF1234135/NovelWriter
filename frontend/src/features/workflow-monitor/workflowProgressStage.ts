import type { WorkflowPayload } from "../../types";
import { FLOW_STEPS, getStuckFlowStepIndex } from "../hitl-panel/hitlCopy";

/**
 * Step index along {@link FLOW_STEPS} for stage ribbon / grid.
 * Uses `FLOW_STEPS.length` when the run has successfully finished so every
 * four macro-stages can show "done" (`activeIndex > groupMax` for the last group).
 */
export function computeWorkflowStageStepIndex(workflow: WorkflowPayload | null): number {
  if (!workflow) return -1;

  const wfState = String(workflow.state.workflow_status ?? "").toUpperCase();
  const runStatus = String(workflow.run.status ?? "").toUpperCase();

  if (wfState === "COMPLETED") {
    return FLOW_STEPS.length;
  }

  const hitlWait =
    workflow.run.requires_hitl === true || runStatus === "WAITING_HITL" || wfState === "WAITING_HITL";

  if (hitlWait) {
    const reason = String(workflow.state.hitl_reason ?? workflow.run.hitl_reason ?? "");
    const resumeFrom = String(
      (workflow.state as { resume_from?: string }).resume_from ?? "",
    );
    return getStuckFlowStepIndex(reason, resumeFrom);
  }

  const currentAgent = String(workflow.run.current_agent ?? workflow.state.last_agent ?? "").trim();
  if (currentAgent) {
    const idx = FLOW_STEPS.findIndex((s) => s.id === currentAgent);
    if (idx >= 0) return idx;
  }

  if (wfState === "FAILED" || runStatus === "FAILED") {
    return Math.max(FLOW_STEPS.length - 2, 0);
  }

  return 0;
}
