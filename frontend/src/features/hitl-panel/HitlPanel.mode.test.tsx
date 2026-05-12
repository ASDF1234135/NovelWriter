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

describe("HitlPanel mode switching", () => {
  beforeEach(() => {
    window.localStorage.setItem("nb.ui.locale", "zh-Hant");
  });

  it("expands the advanced (expert) section when its summary is clicked", async () => {
    // The panel used to expose a tablist; it now hides advanced controls
    // behind a native <details> element keyed by hitl.advancedSummary.
    const user = userEvent.setup();
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

    const summary = screen.getByText("進階：僅在熟悉系統時使用");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");

    await user.click(summary);

    await waitFor(() => expect(details).toHaveAttribute("open"));
    // Once expanded, the inner JSON-injection controls become visible.
    expect(screen.getByText("直接寫入故事資料（進階結構化）")).toBeInTheDocument();
  });
});
