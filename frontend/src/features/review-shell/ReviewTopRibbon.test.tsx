import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { WorkflowPayload } from "../../types";
import { I18nProvider } from "../../i18n/I18nProvider";
import { ReviewTopRibbon } from "./ReviewTopRibbon";

function makeWorkflow(status: string, hitl = false): WorkflowPayload {
  return {
    run: {
      run_id: "run-x",
      story_id: "story-x",
      chapter_id: 2,
      status,
      requires_hitl: hitl,
      hitl_reason: hitl ? "Plan_Loop_Exceeded" : "",
      hitl_decision_mode: hitl ? "CHOICE" : "NONE",
    },
    state: { workflow_status: status },
    steps: [],
  } as unknown as WorkflowPayload;
}

function renderRibbon(node: React.ReactElement) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

describe("ReviewTopRibbon", () => {
  it("renders the HITL beacon as 'idle' when nothing is waiting", () => {
    renderRibbon(
      <ReviewTopRibbon
        workflow={makeWorkflow("RUNNING")}
        storyId="story-x"
        workflowHitlActive={false}
        logsOpen={false}
        onToggleLogs={vi.fn()}
      />,
    );
    const beacon = screen.getByTestId("hitl-beacon");
    expect(beacon.getAttribute("data-state")).toBe("idle");
  });

  it("renders the HITL beacon as 'awaiting' when HITL is active", () => {
    renderRibbon(
      <ReviewTopRibbon
        workflow={makeWorkflow("WAITING_HITL", true)}
        storyId="story-x"
        workflowHitlActive
        logsOpen={false}
        onToggleLogs={vi.fn()}
      />,
    );
    const beacon = screen.getByTestId("hitl-beacon");
    expect(beacon.getAttribute("data-state")).toBe("awaiting");
  });

  it("renders the HITL beacon as 'blocked' when the run has failed", () => {
    renderRibbon(
      <ReviewTopRibbon
        workflow={makeWorkflow("FAILED")}
        storyId="story-x"
        workflowHitlActive={false}
        logsOpen={false}
        onToggleLogs={vi.fn()}
      />,
    );
    const beacon = screen.getByTestId("hitl-beacon");
    expect(beacon.getAttribute("data-state")).toBe("blocked");
  });

  it("logs toggle invokes the callback", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    renderRibbon(
      <ReviewTopRibbon
        workflow={makeWorkflow("RUNNING")}
        storyId="story-x"
        workflowHitlActive={false}
        logsOpen={false}
        onToggleLogs={onToggle}
      />,
    );
    await user.click(screen.getByTestId("review-ribbon-logs-toggle"));
    expect(onToggle).toHaveBeenCalled();
  });
});
