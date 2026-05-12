import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n/I18nProvider";
import { HitlPanel } from "./HitlPanel";

const noopAsync = vi.fn().mockResolvedValue(undefined);

function renderPanel(node: ReactElement) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

describe("HitlPanel reason rendering", () => {
  beforeEach(() => {
    window.localStorage.setItem("nb.ui.locale", "zh-Hant");
  });

  it("draft loop: dashboard decision calls onDecision and does not show plan-outline panel by default", async () => {
    const user = userEvent.setup();
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
            pending_hitl_options: [{ id: "relax_word_count", label: "放寬字數要求" }],
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

    expect(screen.getByText("AI 產出的正文反覆修改仍未達標（字數不足或偏離大綱）。")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "手動調整事件大綱" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "修改章節正文" })).toBeInTheDocument();

    const resumeSelect = screen.getByDisplayValue("從閱讀檢查再跑");
    const resumeValues = Array.from(resumeSelect.querySelectorAll("option")).map((o) => (o as HTMLOptionElement).value);
    expect(resumeValues).toEqual(expect.arrayContaining(["reader", "draft_supervisor", "author"]));
    expect(resumeValues).not.toContain("extraction_gate");

    await user.click(screen.getByText("放寬字數限制"));
    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("relax_word_count"));
  });

  it("plan loop: shows situation copy and outline panel when selected", async () => {
    const user = userEvent.setup();
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

    expect(screen.getByText("大綱規劃觸發安全限制，AI 無法產出符合邏輯的劇情。")).toBeInTheDocument();
    expect(screen.getByText(/無法通過原因：大綱與錨點衝突/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /手動調整事件大綱/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /手動調整事件大綱/ }));
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

    expect(screen.getByText(/目前「此收尾套路」已連續多章重複使用。/)).toBeInTheDocument();
    expect(screen.getAllByText("微調章節方向").length).toBeGreaterThan(0);
  });

  it("chapter draft review: panel renders the redirect stub instead of solution panels", async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined);
    const onDraftEdit = vi.fn().mockResolvedValue(undefined);
    renderPanel(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-cr",
            story_id: "story-1",
            chapter_id: 1,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Chapter_Draft_Review",
            hitl_decision_mode: "MANUAL_EDIT",
            hitl_context: {
              primary_issue: "Awaiting human review of the chapter draft.",
              supervisor_feedbacks: [],
              conflict_notes: [],
              problematic_draft_snippet: "draft snippet…",
              context_metadata: { payload_type: "chapter_review", reader_score: 88 },
            },
          },
          state: {
            pending_hitl_options: [
              { id: "APPROVE_DRAFT", label: "通過（可修改）" },
              { id: "RERUN_KEEP_DIRECTOR", label: "保留劇情節點重跑" },
              { id: "ABANDON_CHAPTER", label: "放棄此次生成" },
            ],
            resume_from: "chunker",
            current_draft: "draft body…",
          },
          steps: [],
        }}
        onDecision={onDecision}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={onDraftEdit}
      />,
    );

    // The redirect stub points the user at the reading area.
    expect(
      screen.getByText("此次審核請至閱讀區進行（不在此面板操作）。"),
    ).toBeInTheDocument();

    // None of the option-id buttons should be wired up inside the panel,
    // because chapter-review actions live in the reading area.
    expect(screen.queryByRole("button", { name: /通過（可修改）/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /保留劇情節點重跑/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /放棄此次生成/ })).not.toBeInTheDocument();

    // And the panel's heavyweight solution surfaces stay hidden.
    expect(screen.queryByRole("heading", { name: "修改章節正文" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "手動調整事件大綱" })).not.toBeInTheDocument();

    expect(onDecision).not.toHaveBeenCalled();
    expect(onDraftEdit).not.toHaveBeenCalled();
  });

  it("output language mismatch: shows situation and dashboard options", async () => {
    const user = userEvent.setup();
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

    expect(screen.getByText("AI 產出的語言與專案設定不符（例如中文混雜了大量外文）。")).toBeInTheDocument();
    expect(screen.getByText(/Story is set to English/)).toBeInTheDocument();
    expect(screen.getByText("en", { selector: "span.text-on-surface" })).toBeInTheDocument();
    expect(screen.getByText(/^專案輸出語言：$/, { selector: "p" })).toBeInTheDocument();
    await user.click(screen.getByText("強制繼續（這是我故意的）"));
    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("language_force_continue"));
  });
});
