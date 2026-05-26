import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { I18nProvider } from "../../i18n/I18nProvider";
import { HitlDevPanel } from "./HitlDevPanel";
import { HITL_REASON } from "./hitlCopy";

describe("HitlDevPanel", () => {
  const env = import.meta.env;

  beforeEach(() => {
    window.localStorage.setItem("nb.ui.locale", "zh-Hant");
    import.meta.env.VITE_ENABLE_DEV_TOOLS = "1";
  });

  afterEach(() => {
    import.meta.env.VITE_ENABLE_DEV_TOOLS = env.VITE_ENABLE_DEV_TOOLS;
  });

  it("hidden when dev tools flag is off", () => {
    import.meta.env.VITE_ENABLE_DEV_TOOLS = "0";
    const { container } = render(
      <I18nProvider>
        <HitlDevPanel workflow={null} setWorkflow={vi.fn()} />
      </I18nProvider>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("injects plan loop mock with quick actions", async () => {
    const user = userEvent.setup();
    const setWorkflow = vi.fn();
    render(
      <I18nProvider>
        <HitlDevPanel workflow={null} setWorkflow={setWorkflow} />
      </I18nProvider>,
    );

    const select = screen.getByTestId("hitl-dev-reason-select");
    await user.selectOptions(select, HITL_REASON.PLAN_LOOP);

    await waitFor(() => expect(setWorkflow).toHaveBeenCalled());
    const wf = setWorkflow.mock.calls.at(-1)?.[0];
    expect(wf.run.hitl_reason).toBe(HITL_REASON.PLAN_LOOP);
    expect((wf.state.pending_hitl_options as Array<{ id: string }>).map((o) => o.id)).toEqual([
      "force_rewrite_plan",
      "force_approve_plan",
    ]);
  });
});
