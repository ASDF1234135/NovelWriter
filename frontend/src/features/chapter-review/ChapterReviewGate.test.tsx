import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { I18nProvider } from "../../i18n/I18nProvider";
import { ChapterReviewGate } from "./ChapterReviewGate";

// Replace the lazy-loaded TipTap-backed editor with a light contenteditable
// surrogate so jsdom does not have to evaluate ProseMirror.
vi.mock("./ChapterReviewEditor", () => ({
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

function mountWithDataRouter(node: ReactNode) {
  const router = createMemoryRouter([{ path: "*", element: <>{node}</> }], {
    initialEntries: ["/review"],
  });
  return render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
}

const DRAFT = "第一段。\n\n第二段。\n\n第三段。";

beforeEach(() => {
  window.localStorage.setItem("nb.ui.locale", "zh-Hant");
});

describe("ChapterReviewGate", () => {
  it("renders the draft notice, abandon hint, and reader score", async () => {
    const noop = vi.fn().mockResolvedValue(undefined);
    mountWithDataRouter(
      <ChapterReviewGate
        draft={DRAFT}
        readerScore={87}
        busy={false}
        onApprove={noop}
        onAbandon={noop}
        onRerun={noop}
      />,
    );

    expect(await screen.findByText(/此版本為草稿/)).toBeInTheDocument();
    expect(screen.getByText(/建議放棄並回到設定畫面/)).toBeInTheDocument();
    expect(screen.getByText("讀者評分：87")).toBeInTheDocument();
    // Suspense fallback yields its own pre while the lazy chunk resolves; once
    // resolved, the mocked editor is rendered.
    expect(await screen.findByTestId("mock-editor")).toBeInTheDocument();
  });

  it("approve button label is 通過 until the user edits, then becomes 修改後通過", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn().mockResolvedValue(undefined);
    mountWithDataRouter(
      <ChapterReviewGate
        draft={DRAFT}
        busy={false}
        onApprove={onApprove}
        onAbandon={vi.fn().mockResolvedValue(undefined)}
        onRerun={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const approveBtn = await screen.findByTestId("chapter-review-approve");
    expect(approveBtn).toHaveTextContent("通過");
    expect(approveBtn).not.toHaveTextContent("修改後通過");

    const editor = await screen.findByTestId("mock-editor");
    await user.clear(editor);
    await user.type(editor, "改寫後內容");

    await waitFor(() =>
      expect(screen.getByTestId("chapter-review-approve")).toHaveTextContent("修改後通過"),
    );
  });

  it("clicking approve without edits calls onApprove(draft, false)", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn().mockResolvedValue(undefined);
    mountWithDataRouter(
      <ChapterReviewGate
        draft={DRAFT}
        busy={false}
        onApprove={onApprove}
        onAbandon={vi.fn().mockResolvedValue(undefined)}
        onRerun={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await screen.findByTestId("mock-editor");
    await user.click(screen.getByTestId("chapter-review-approve"));

    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1));
    expect(onApprove).toHaveBeenCalledWith(DRAFT, false);
  });

  it("clicking approve after edits calls onApprove(newContent, true)", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn().mockResolvedValue(undefined);
    mountWithDataRouter(
      <ChapterReviewGate
        draft={DRAFT}
        busy={false}
        onApprove={onApprove}
        onAbandon={vi.fn().mockResolvedValue(undefined)}
        onRerun={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const editor = await screen.findByTestId("mock-editor");
    await user.clear(editor);
    await user.type(editor, "改寫後內容");
    await user.click(screen.getByTestId("chapter-review-approve"));

    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1));
    const [content, edited] = onApprove.mock.calls[0];
    expect(edited).toBe(true);
    expect(String(content)).toBe("改寫後內容");
  });

  it("rerun button opens a confirm modal before calling onRerun", async () => {
    const user = userEvent.setup();
    const onRerun = vi.fn().mockResolvedValue(undefined);
    mountWithDataRouter(
      <ChapterReviewGate
        draft={DRAFT}
        busy={false}
        onApprove={vi.fn().mockResolvedValue(undefined)}
        onAbandon={vi.fn().mockResolvedValue(undefined)}
        onRerun={onRerun}
      />,
    );

    await user.click(await screen.findByTestId("chapter-review-rerun"));

    // Confirm modal text comes from chapterReview.rerunConfirm.
    expect(await screen.findByText(/將清空目前草稿並從 planner 重新生成/)).toBeInTheDocument();
    expect(onRerun).not.toHaveBeenCalled();

    // Click the modal's confirm action ("保留劇情節點重跑").
    const confirms = screen.getAllByRole("button", { name: "保留劇情節點重跑" });
    // The first match is the sticky-bar trigger (still visible); the second is
    // the modal's confirm button. Pick the one inside the dialog.
    const dialog = screen.getByRole("dialog");
    const modalConfirm = confirms.find((btn) => dialog.contains(btn));
    expect(modalConfirm).toBeTruthy();
    await user.click(modalConfirm!);

    await waitFor(() => expect(onRerun).toHaveBeenCalledTimes(1));
  });

  it("abandon button opens a confirm modal before calling onAbandon", async () => {
    const user = userEvent.setup();
    const onAbandon = vi.fn().mockResolvedValue(undefined);
    mountWithDataRouter(
      <ChapterReviewGate
        draft={DRAFT}
        busy={false}
        onApprove={vi.fn().mockResolvedValue(undefined)}
        onAbandon={onAbandon}
        onRerun={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await user.click(await screen.findByTestId("chapter-review-abandon"));

    expect(await screen.findByText(/此次生成將被取消/)).toBeInTheDocument();
    expect(onAbandon).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    const confirms = screen.getAllByRole("button", { name: "放棄此次生成" });
    const modalConfirm = confirms.find((btn) => dialog.contains(btn));
    expect(modalConfirm).toBeTruthy();
    await user.click(modalConfirm!);

    await waitFor(() => expect(onAbandon).toHaveBeenCalledTimes(1));
  });

  it("cancelling the confirm modal does not invoke handlers", async () => {
    const user = userEvent.setup();
    const onAbandon = vi.fn().mockResolvedValue(undefined);
    const onRerun = vi.fn().mockResolvedValue(undefined);
    mountWithDataRouter(
      <ChapterReviewGate
        draft={DRAFT}
        busy={false}
        onApprove={vi.fn().mockResolvedValue(undefined)}
        onAbandon={onAbandon}
        onRerun={onRerun}
      />,
    );

    await user.click(await screen.findByTestId("chapter-review-abandon"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /取消|Cancel/ }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onAbandon).not.toHaveBeenCalled();
    expect(onRerun).not.toHaveBeenCalled();
  });

  it("busy disables every action button", async () => {
    const noop = vi.fn().mockResolvedValue(undefined);
    mountWithDataRouter(
      <ChapterReviewGate
        draft={DRAFT}
        busy
        onApprove={noop}
        onAbandon={noop}
        onRerun={noop}
      />,
    );

    expect(await screen.findByTestId("chapter-review-approve")).toBeDisabled();
    expect(screen.getByTestId("chapter-review-rerun")).toBeDisabled();
    expect(screen.getByTestId("chapter-review-abandon")).toBeDisabled();
  });
});
