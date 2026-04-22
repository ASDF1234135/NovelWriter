import { beforeEach, describe, expect, it, vi } from "vitest";

async function loadModule() {
  vi.resetModules();
  return import("./workflowDisplay");
}

describe("workflowDisplay", () => {
  beforeEach(() => {
    window.localStorage.setItem("nb.ui.locale", "zh-Hant");
  });

  it("maps run status", async () => {
    const { workflowRunStatusLabel } = await loadModule();
    expect(workflowRunStatusLabel("WAITING_HITL")).toBe("等待您處理");
    expect(workflowRunStatusLabel("RUNNING")).toBe("進行中");
    expect(workflowRunStatusLabel("UNKNOWN_X")).toBe("狀態：UNKNOWN_X");
  });

  it("maps agent nodes", async () => {
    const { workflowAgentStepLabel } = await loadModule();
    expect(workflowAgentStepLabel("planner")).toBe("劇情規劃");
    expect(workflowAgentStepLabel("hitl")).toBe("等待您協助");
  });

  it("maps chapter status", async () => {
    const { chapterStatusLabel } = await loadModule();
    expect(chapterStatusLabel("completed")).toBe("已完成");
  });

  it("maps hitl reason to title", async () => {
    const { hitlReasonTitle } = await loadModule();
    expect(hitlReasonTitle("Draft_Loop_Exceeded")).toBe("內文審核多次未過");
  });

  it("maps decision mode", async () => {
    const { hitlDecisionModeLabel } = await loadModule();
    expect(hitlDecisionModeLabel("DASHBOARD")).toBe("可一鍵選擇");
  });

  it("maps route decision", async () => {
    const { routeDecisionLabel } = await loadModule();
    expect(routeDecisionLabel("author")).toBe("回到撰寫");
  });
});
