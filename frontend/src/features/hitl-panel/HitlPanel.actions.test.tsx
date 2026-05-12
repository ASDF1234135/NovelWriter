import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n/I18nProvider";
import { HitlPanel } from "./HitlPanel";

const makeNoop = () => vi.fn().mockResolvedValue(undefined);

function renderPanel(node: ReactElement) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

describe("HitlPanel actions", () => {
  beforeEach(() => {
    window.localStorage.setItem("nb.ui.locale", "zh-Hant");
  });

  it("alignment rules required: shows dedicated block and submits state injection patch", async () => {
    const user = userEvent.setup();
    const onStateInjection = vi.fn().mockResolvedValue(undefined);
    renderPanel(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-4",
            story_id: "story-1",
            chapter_id: 3,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Alignment_Rules_Required",
            hitl_decision_mode: "MANUAL_EDIT",
          },
          state: {
            pending_hitl_options: [],
            resume_from: "logic_alignment",
            chapter_hard_rules: "舊規則",
            alignment_log: "[HITL_REQUEST] 請補充勝負條件與回合判定。",
          },
          steps: [],
        }}
        onDecision={makeNoop()}
        onOutlineEdit={makeNoop()}
        onStateInjection={onStateInjection}
        onDraftEdit={makeNoop()}
      />,
    );

    expect(screen.getByText(/系統遇到「.*請補充勝負條件與回合判定/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "送出並繼續" }));
    await waitFor(() =>
      expect(onStateInjection).toHaveBeenCalledWith(
        expect.objectContaining({
          mutations: [],
          chapter_hard_rules: "舊規則",
          resume_from: "logic_alignment",
          this_chapter_pacing_limit: "",
          future_anchor_title: "",
          future_anchor_description: "",
          chapters_to_delay: null,
        }),
      ),
    );
  });

  it("plan loop: outline submit goes through preview gate before calling onOutlineEdit", async () => {
    const user = userEvent.setup();
    const onOutlineEdit = vi.fn().mockResolvedValue(undefined);
    renderPanel(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-json",
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
            // Provide a valid outline so formState.isValid becomes true after the
            // useEffect populates outlineEvents via outlineArray.replace().
            ground_truth_events: [
              { event_id: "event_01", description: "主角入山" },
              { event_id: "event_02", description: "遇到對手", caused_by_event_id: "event_01" },
            ],
          },
          steps: [],
        }}
        onDecision={makeNoop()}
        onOutlineEdit={onOutlineEdit}
        onStateInjection={makeNoop()}
        onDraftEdit={makeNoop()}
      />,
    );

    // Plan_Loop's default solution is "director"; switch to the outline panel first.
    await user.click(screen.getByRole("button", { name: /手動調整事件大綱/ }));
    const previewBtn = await screen.findByRole("button", { name: "預覽並套用大綱" });
    await waitFor(() => expect(previewBtn).not.toBeDisabled());
    await user.click(previewBtn);
    expect(await screen.findByText("送出前預覽：事件大綱變更")).toBeInTheDocument();
    expect(onOutlineEdit).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "確認套用大綱" }));
    await waitFor(() => expect(onOutlineEdit).toHaveBeenCalledTimes(1));
  });

  it("panic button sends ABORT_AND_RESTART decision", async () => {
    const user = userEvent.setup();
    const onDecision = vi.fn().mockResolvedValue(undefined);
    renderPanel(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-panic",
            story_id: "story-1",
            chapter_id: 1,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Plan_Loop_Exceeded",
            hitl_decision_mode: "MANUAL_EDIT",
          },
          state: { pending_hitl_options: [], resume_from: "planner" },
          steps: [],
        }}
        onDecision={onDecision}
        onOutlineEdit={makeNoop()}
        onStateInjection={makeNoop()}
        onDraftEdit={makeNoop()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "放棄本章草稿，打掉重練" }));
    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("ABORT_AND_RESTART"));
  });

  it("busy disables quick-action decision buttons", () => {
    renderPanel(
      <HitlPanel
        busy
        workflow={{
          run: {
            run_id: "run-busy",
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
        onDecision={makeNoop()}
        onOutlineEdit={makeNoop()}
        onStateInjection={makeNoop()}
        onDraftEdit={makeNoop()}
      />,
    );
    expect(screen.getByRole("button", { name: "維持現有草稿（強制通過）" })).toBeDisabled();
  });
});
