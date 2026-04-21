import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HitlPanel } from "./HitlPanel";
import { I18nProvider } from "../../i18n/I18nProvider";

const noopAsync = vi.fn().mockResolvedValue(undefined);

function renderPanel(node: ReactElement) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

describe("HitlPanel", () => {
  beforeEach(() => {
    window.localStorage.setItem("nb.ui.locale", "zh-Hant");
  });

  it("draft loop: dashboard decision calls onDecision and does not show plan-outline panel by default", async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined);

    renderPanel(
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
    renderPanel(
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
    expect(screen.getByRole("button", { name: "新增事件卡片" })).toBeInTheDocument();
  });

  it("resolution tactic cooldown: shows director solution like plan family", async () => {
    renderPanel(
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

  it("alignment rules required: shows dedicated block and submits state injection patch", async () => {
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
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={onStateInjection}
        onDraftEdit={noopAsync}
      />,
    );

    expect(screen.getByText("偵測到複雜智鬥，需補充規則")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "套用硬性規則並繼續" }));
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
    );
  });

  it("output language mismatch: shows situation and dashboard options", async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined);
    renderPanel(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-ol",
            story_id: "story-1",
            chapter_id: 1,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Output_Language_Mismatch",
            hitl_decision_mode: "DASHBOARD",
            hitl_context: {
              primary_issue: "Story is set to English, but the draft has many CJK letters.",
              supervisor_feedbacks: [],
              conflict_notes: [],
              problematic_draft_snippet: "…",
              context_metadata: { payload_type: "output_language", expected_output_language: "en" },
            },
          },
          state: {
            pending_hitl_options: [
              { id: "language_return_author", label: "退回 Author 依設定語言重寫" },
              { id: "language_force_continue", label: "略過檢查並繼續彙總" },
            ],
            resume_from: "output_language_gate",
          },
          steps: [],
        }}
        onDecision={onDecision}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );

    expect(screen.getByText("輸出語言與專案設定不一致")).toBeInTheDocument();
    expect(screen.getByText(/Story is set to English/)).toBeInTheDocument();
    expect(screen.getByText("en", { selector: "span.text-on-surface" })).toBeInTheDocument();
    expect(screen.getByText(/專案輸出語言/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("略過檢查並繼續彙總"));
    expect(onDecision).toHaveBeenCalledWith("language_force_continue");
  });

  it("outline submit uses preview gate before calling onOutlineEdit", async () => {
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
          state: { pending_hitl_options: [], resume_from: "planner" },
          steps: [],
        }}
        onDecision={noopAsync}
        onOutlineEdit={onOutlineEdit}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "預覽並套用大綱" }));
    expect(await screen.findByText("送出前預覽：事件大綱變更")).toBeInTheDocument();
    expect(onOutlineEdit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "確認套用大綱" }));
    expect(onOutlineEdit).toHaveBeenCalledTimes(1);
  });

  it("switches to expert mode tab", () => {
    renderPanel(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-mode",
            story_id: "story-1",
            chapter_id: 1,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Extraction_Gate_Failed",
            hitl_decision_mode: "MANUAL_EDIT",
          },
          state: { pending_hitl_options: [], resume_from: "extraction_gate" },
          steps: [],
        }}
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "專家模式" }));
    expect(screen.getByRole("tab", { name: "專家模式" })).toHaveAttribute("aria-selected", "true");
  });

  it("busy disables one-click decision buttons", () => {
    const onDecision = vi.fn();
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
        onDecision={onDecision}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    expect(screen.getByRole("button", { name: "保持邏輯並重寫" })).toBeDisabled();
  });

  it("panic button sends ABORT_AND_RESTART decision", async () => {
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
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "放棄本章草稿，打掉重練" }));
    expect(onDecision).toHaveBeenCalledWith("ABORT_AND_RESTART");
  });
});
