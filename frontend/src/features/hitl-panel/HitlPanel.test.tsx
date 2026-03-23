import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HitlPanel } from "./HitlPanel";

describe("HitlPanel", () => {
  it("renders options and triggers dashboard decision", async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined);
    const onOutlineEdit = vi.fn().mockResolvedValue(undefined);
    const onStateInjection = vi.fn().mockResolvedValue(undefined);
    const onDraftEdit = vi.fn().mockResolvedValue(undefined);

    render(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-1",
            story_id: "story-1",
            chapter_id: 1,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Draft_Loop_Exceeded",
            hitl_decision_mode: "DASHBOARD",
          },
          state: {
            pending_hitl_options: [{ id: "force_rewrite_plan", label: "強制重寫大綱" }],
          },
          steps: [],
        }}
        onDecision={onDecision}
        onOutlineEdit={onOutlineEdit}
        onStateInjection={onStateInjection}
        onDraftEdit={onDraftEdit}
      />,
    );

    fireEvent.click(screen.getByText("強制重寫大綱"));

    expect(onDecision).toHaveBeenCalledWith("force_rewrite_plan");
  });
});
