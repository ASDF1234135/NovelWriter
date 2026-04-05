import { describe, expect, it } from "vitest";
import {
  chapterStatusLabel,
  hitlDecisionModeLabel,
  hitlReasonTitle,
  routeDecisionLabel,
  workflowAgentStepLabel,
  workflowRunStatusLabel,
} from "./workflowDisplay";

describe("workflowDisplay", () => {
  it("maps run status", () => {
    expect(workflowRunStatusLabel("WAITING_HITL")).toBe("等待您處理");
    expect(workflowRunStatusLabel("RUNNING")).toBe("進行中");
    expect(workflowRunStatusLabel("UNKNOWN_X")).toBe("狀態：UNKNOWN_X");
  });

  it("maps agent nodes", () => {
    expect(workflowAgentStepLabel("planner")).toBe("劇情規劃");
    expect(workflowAgentStepLabel("hitl")).toBe("等待您協助");
  });

  it("maps chapter status", () => {
    expect(chapterStatusLabel("completed")).toBe("已完成");
  });

  it("maps hitl reason to title", () => {
    expect(hitlReasonTitle("Draft_Loop_Exceeded")).toBe("內文審核多次未過");
  });

  it("maps decision mode", () => {
    expect(hitlDecisionModeLabel("DASHBOARD")).toBe("可一鍵選擇");
  });

  it("maps route decision", () => {
    expect(routeDecisionLabel("author")).toBe("回到撰寫");
  });
});
