import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n/I18nProvider";
import { HitlPanel } from "./HitlPanel";

const noopAsync = vi.fn().mockResolvedValue(undefined);

vi.mock("../chapter-review/ChapterReviewEditor", () => ({
  default: ({
    initialDoc,
    busy,
    onChange,
  }: {
    initialDoc: string;
    busy?: boolean;
    onChange: (text: string) => void;
  }) => (
    <textarea
      data-testid="mock-editor"
      defaultValue={initialDoc}
      disabled={busy}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));

function renderPanel(node: ReactElement) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

function renderPanelWithRouter(node: ReactNode) {
  const router = createMemoryRouter([{ path: "*", element: <I18nProvider>{node}</I18nProvider> }], {
    initialEntries: ["/write"],
  });
  return render(<RouterProvider router={router} />);
}

function sectionRoot(sectionId: string): HTMLElement {
  const el = document.getElementById(sectionId);
  if (!el) throw new Error(`Missing section #${sectionId}`);
  return el;
}

/** Clicks a quick-action label, then confirms the preview dialog. */
async function confirmQuickAction(
  user: ReturnType<typeof userEvent.setup>,
  actionLabel: string | RegExp,
  confirmLabel: string | RegExp,
) {
  const quick = within(sectionRoot("hitl-section-quick"));
  await user.click(quick.getByRole("button", { name: actionLabel }));
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: confirmLabel }));
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
            pending_hitl_options: [
              { id: "keep_current_logic", label: "維持現有草稿（強制通過）" },
              { id: "relax_word_count", label: "退回重寫並放寬字數限制" },
            ],
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

    const reasonSection = within(sectionRoot("hitl-section-reason"));
    expect(reasonSection.getByText("AI 產出的正文反覆修改仍未達標（字數不足或偏離大綱）。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /手動調整事件大綱/ })).not.toBeInTheDocument();

    const manual = within(sectionRoot("hitl-section-manual"));
    expect(manual.getByRole("heading", { level: 3, name: "修改章節正文" })).toBeInTheDocument();

    const resumeSelect = manual.getByDisplayValue("從閱讀檢查再跑");
    const resumeValues = Array.from(resumeSelect.querySelectorAll("option")).map((o) => (o as HTMLOptionElement).value);
    expect(resumeValues).toEqual(expect.arrayContaining(["reader", "draft_supervisor", "author"]));
    expect(resumeValues).not.toContain("extraction_gate");

    await confirmQuickAction(user, "退回重寫並放寬字數限制", "確認並繼續");
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

    const reasonSection = within(sectionRoot("hitl-section-reason"));
    expect(reasonSection.getByText("大綱規劃觸發安全限制，AI 無法產出符合邏輯的劇情。")).toBeInTheDocument();
    expect(reasonSection.getByText(/無法通過原因：大綱與錨點衝突/)).toBeInTheDocument();

    const manual = within(sectionRoot("hitl-section-manual"));
    await user.click(manual.getByRole("button", { name: /手動調整事件大綱/ }));
    expect(manual.getByRole("button", { name: "新增事件卡片" })).toBeInTheDocument();
  });

  it("resolution tactic cooldown: shows director solution like plan family", () => {
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

    const reasonSection = within(sectionRoot("hitl-section-reason"));
    expect(reasonSection.getByText(/目前「此收尾套路」已連續多章重複使用。/)).toBeInTheDocument();
    const manual = within(sectionRoot("hitl-section-manual"));
    expect(manual.getByRole("button", { name: /^微調章節方向/ })).toBeInTheDocument();
  });

  it("chapter draft review without chapterReview: shows redirect stub", () => {
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

    expect(screen.getByText("此次審核請至閱讀區進行（不在此面板操作）。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /通過（可修改）/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /保留劇情節點重跑/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /放棄此次生成/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "修改章節正文" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /手動調整事件大綱/ })).not.toBeInTheDocument();
    expect(document.getElementById("hitl-section-quick")).toBeNull();
    expect(document.getElementById("hitl-section-manual")).toBeNull();

    expect(onDecision).not.toHaveBeenCalled();
    expect(onDraftEdit).not.toHaveBeenCalled();
  });

  it("chapter draft review with chapterReview: embeds ChapterReviewGate in the panel", () => {
    renderPanelWithRouter(
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
            workflow_status: "WAITING_HITL",
          },
          steps: [],
        }}
        chapterReview={{
          draft: "draft body…",
          readerScore: 88,
          onApprove: noopAsync,
          onAbandon: noopAsync,
          onRerun: noopAsync,
        }}
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );

    expect(screen.getByText("人類章節審核")).toBeInTheDocument();
    expect(screen.getByTestId("chapter-review-abandon")).toBeInTheDocument();
    expect(screen.queryByText("此次審核請至閱讀區進行（不在此面板操作）。")).not.toBeInTheDocument();
    expect(document.getElementById("hitl-section-quick")).toBeNull();
    expect(document.getElementById("hitl-section-manual")).toBeNull();
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

    const reasonSection = within(sectionRoot("hitl-section-reason"));
    expect(reasonSection.getByText("AI 產出的語言與專案設定不符（例如中文混雜了大量外文）。")).toBeInTheDocument();

    const content = within(sectionRoot("hitl-section-content"));
    expect(content.getByText(/Story is set to English/)).toBeInTheDocument();
    expect(content.getByText("en", { selector: "span.text-on-surface" })).toBeInTheDocument();

    await confirmQuickAction(user, "強制繼續（這是我故意的）", "確認並繼續");
    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("language_force_continue"));
  });

  it("anchor resolve: quick actions require confirm and support continue unresolved", async () => {
    const user = userEvent.setup();
    const onAnchorResolution = vi.fn().mockResolvedValue(undefined);
    renderPanel(
      <HitlPanel
        workflow={{
          run: {
            run_id: "run-anchor",
            story_id: "story-1",
            chapter_id: 1,
            status: "WAITING_HITL",
            requires_hitl: true,
            hitl_reason: "Anchor_Resolution_Failed",
            hitl_decision_mode: "MANUAL_EDIT",
            hitl_context: {
              primary_issue: "Uncertain milestone.",
              supervisor_feedbacks: [],
              conflict_notes: [],
              problematic_draft_snippet: "林默找到短刃但沒帶走。",
              context_metadata: { payload_type: "generic" },
            },
          },
          state: {
            pending_hitl_options: [],
            resume_from: "anchor_resolve",
            anchor_nodes: [
              {
                id: "anchor_get_obsidian_dagger",
                title: "取得黑曜短刃",
                description: "主角應在本章確實取得黑曜短刃。",
              },
            ],
            anchor_resolution_hitl_candidate: {
              unresolved_anchor_ids: ["anchor_get_obsidian_dagger"],
              resolution_analysis: "系統無法判定是否達成。",
            },
          },
          steps: [],
        }}
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
        onAnchorResolution={onAnchorResolution}
      />,
    );

    const reasonSection = within(sectionRoot("hitl-section-reason"));
    expect(reasonSection.getByText(/AI 無法確定里程碑「取得黑曜短刃」/)).toBeInTheDocument();

    const content = within(sectionRoot("hitl-section-content"));
    expect(content.getByText("取得黑曜短刃")).toBeInTheDocument();
    expect(content.getByText("主角應在本章確實取得黑曜短刃。")).toBeInTheDocument();
    expect(content.queryByText(/\{[\s\S]*"unresolved_anchor_ids"/)).not.toBeInTheDocument();

    expect(sectionRoot("hitl-section-quick")).toBeTruthy();
    expect(document.getElementById("hitl-section-manual")).toBeNull();

    const quick = within(sectionRoot("hitl-section-quick"));
    expect(quick.getByRole("button", { name: "未達成，保持劇情未完成狀態繼續" })).toBeInTheDocument();

    await confirmQuickAction(user, "未達成，保持劇情未完成狀態繼續", "確認繼續");
    await waitFor(() =>
      expect(onAnchorResolution).toHaveBeenCalledWith(
        expect.objectContaining({ action: "continue_unresolved" }),
      ),
    );
  });
});
