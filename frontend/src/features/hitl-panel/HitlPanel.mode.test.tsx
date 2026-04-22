import { render, screen } from "@testing-library/react";
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

  it("switches to expert mode tab", async () => {
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
    await user.click(screen.getByRole("tab", { name: "專家模式" }));
    expect(screen.getByRole("tab", { name: "專家模式" })).toHaveAttribute("aria-selected", "true");
  });
});
