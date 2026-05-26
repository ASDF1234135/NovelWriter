import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkflowPayload } from "../../types";
import { I18nProvider } from "../../i18n/I18nProvider";
import { HitlFloatingDock, __HITL_DOCK_TEST_HOOKS__ } from "./HitlFloatingDock";

const { STORAGE_KEY, SESSION_DISMISSED_KEY } = __HITL_DOCK_TEST_HOOKS__;

const noopAsync = () => Promise.resolve(undefined);

function makeWorkflow(overrides: Partial<WorkflowPayload["run"]> = {}, hitl = true): WorkflowPayload {
  return {
    run: {
      run_id: overrides.run_id ?? "run-1",
      story_id: "story-1",
      chapter_id: 1,
      status: hitl ? "WAITING_HITL" : "RUNNING",
      requires_hitl: hitl,
      hitl_reason: "Plan_Loop_Exceeded",
      hitl_decision_mode: "CHOICE",
      ...overrides,
    },
    state: {
      pending_hitl_options: [{ id: "opt_a", label: "Option A" }],
      resume_from: "planner",
    },
    steps: [],
  } as unknown as WorkflowPayload;
}

function renderDock(node: React.ReactElement) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

describe("HitlFloatingDock", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem("nb.ui.locale", "zh-Hant");
  });

  it("auto-expands when HITL fires for a new run_id (pill not visible, dialog visible)", async () => {
    const workflow = makeWorkflow();
    renderDock(
      <HitlFloatingDock
        workflow={workflow}
        workflowHitlActive
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("hitl-floating-dock")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("hitl-dock-pill")).not.toBeInTheDocument();
  });

  it("stays minimized when the user has already dismissed the dock for that run_id", async () => {
    // Pre-seed sessionStorage so the dock treats run-1 as already dismissed.
    window.sessionStorage.setItem(
      SESSION_DISMISSED_KEY,
      JSON.stringify(["run-1"]),
    );
    // Pre-seed localStorage geom so the dock starts minimized.
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        width: 520,
        height: 640,
        right: 24,
        bottom: 24,
        minimized: true,
      }),
    );

    const workflow = makeWorkflow();
    renderDock(
      <HitlFloatingDock
        workflow={workflow}
        workflowHitlActive
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    expect(screen.getByTestId("hitl-dock-pill")).toBeInTheDocument();
    expect(screen.queryByTestId("hitl-floating-dock")).not.toBeInTheDocument();
  });

  it("minimize button collapses the dock to a candle pill and records the run_id as dismissed", async () => {
    const user = userEvent.setup();
    const workflow = makeWorkflow();
    renderDock(
      <HitlFloatingDock
        workflow={workflow}
        workflowHitlActive
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    await user.click(screen.getByTestId("hitl-dock-minimize"));
    expect(screen.getByTestId("hitl-dock-pill")).toBeInTheDocument();
    expect(screen.queryByTestId("hitl-floating-dock")).not.toBeInTheDocument();
    const dismissed = JSON.parse(
      window.sessionStorage.getItem(SESSION_DISMISSED_KEY) ?? "[]",
    ) as string[];
    expect(dismissed).toContain("run-1");
  });

  it("a new run_id pops the dock open again even if a previous run was dismissed", async () => {
    window.sessionStorage.setItem(
      SESSION_DISMISSED_KEY,
      JSON.stringify(["run-1"]),
    );
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        width: 520,
        height: 640,
        right: 24,
        bottom: 24,
        minimized: true,
      }),
    );

    const { rerender } = renderDock(
      <HitlFloatingDock
        workflow={makeWorkflow({ run_id: "run-1" })}
        workflowHitlActive
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    expect(screen.getByTestId("hitl-dock-pill")).toBeInTheDocument();

    rerender(
      <I18nProvider>
        <HitlFloatingDock
          workflow={makeWorkflow({ run_id: "run-2" })}
          workflowHitlActive
          onDecision={noopAsync}
          onOutlineEdit={noopAsync}
          onStateInjection={noopAsync}
          onDraftEdit={noopAsync}
        />
      </I18nProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("hitl-floating-dock")).toBeInTheDocument(),
    );
  });

  it("persists geometry to localStorage when geom changes (e.g. on initial mount)", async () => {
    renderDock(
      <HitlFloatingDock
        workflow={makeWorkflow()}
        workflowHitlActive
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    await waitFor(() => {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      expect(raw).toBeTruthy();
      const parsed = JSON.parse(raw ?? "{}") as { width: number; height: number };
      expect(parsed.width).toBeGreaterThanOrEqual(380);
      expect(parsed.height).toBeGreaterThanOrEqual(320);
    });
  });

  it("clicking the candle pill expands the dock", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        width: 520,
        height: 640,
        right: 24,
        bottom: 24,
        minimized: true,
      }),
    );
    window.sessionStorage.setItem(
      SESSION_DISMISSED_KEY,
      JSON.stringify(["run-1"]),
    );
    renderDock(
      <HitlFloatingDock
        workflow={makeWorkflow()}
        workflowHitlActive
        onDecision={noopAsync}
        onOutlineEdit={noopAsync}
        onStateInjection={noopAsync}
        onDraftEdit={noopAsync}
      />,
    );
    await user.click(screen.getByTestId("hitl-dock-pill"));
    await waitFor(() =>
      expect(screen.getByTestId("hitl-floating-dock")).toBeInTheDocument(),
    );
  });
});
