import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HitlPanel } from "./HitlPanel";

const noopAsync = vi.fn().mockResolvedValue(undefined);

describe("HitlPanel", () => {
  it("draft loop: dashboard decision calls onDecision and does not show plan-outline panel by default", async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined);

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
            pending_hitl_options: [{ id: "keep_current_logic", label: "保持邏輯並重寫" }],
            resume_from: "author",
          },
          steps: [],
        }}
        onDecision={onDecision}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );

    expect(screen.getByText("內文審核多次未過")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "手動調整事件大綱" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "修改章節內文" })).toBeInTheDocument();

    fireEvent.click(screen.getByText("保持邏輯並重寫"));
    expect(onDecision).toHaveBeenCalledWith("keep_current_logic");
  });

  it("plan loop: shows situation copy and outline panel when selected", async () => {
    render(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-2",
            story_id: "story-1",
            chapter_id: 1,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Plan_Loop_Exceeded",
            hitl_decision_mode: "MANUAL_EDIT",
          },
          state: {
            pending_hitl_options: [],
            resume_from: "planner",
            plan_feedback: [{ message: "大綱與錨點衝突", violation: "ANCHOR" }],
          },
          steps: [],
        }}
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );

    expect(screen.getByText("大綱反覆未過審")).toBeInTheDocument();
    expect(screen.getByText(/審核意見：大綱與錨點衝突/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "手動調整事件大綱" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "修改章節內文" })).not.toBeInTheDocument();
  });

  it("resolution tactic cooldown: shows director solution like plan family", async () => {
    render(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-3",
            story_id: "story-1",
            chapter_id: 1,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Resolution_Tactic_Cooldown_Violation",
            hitl_decision_mode: "MANUAL_EDIT",
          },
          state: { pending_hitl_options: [], resume_from: "planner" },
          steps: [],
        }}
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
        onDirectorPatch={noopAsync}
      />,
    );

    expect(screen.getByText("收尾方式與近期重複")).toBeInTheDocument();
    expect(screen.getByText("微調章節方向")).toBeInTheDocument();
  });
});
