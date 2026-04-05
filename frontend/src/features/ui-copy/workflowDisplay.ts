import { FLOW_STEPS, getSituationCopy } from "../hitl-panel/hitlCopy";

const RUN_STATUS_LABELS: Record<string, string> = {
  IDLE: "待開始",
  RUNNING: "進行中",
  WAITING_HITL: "等待您處理",
  COMPLETED: "已完成",
  FAILED: "失敗",
};

/** 後端 WorkflowRun / 章節工作狀態顯示 */
export function workflowRunStatusLabel(status: string): string {
  const s = status.trim();
  if (!s) return "—";
  return RUN_STATUS_LABELS[s] ?? `狀態：${s}`;
}

/** 與 workflowRunStatusLabel 相同語意，內部狀態欄位用 */
export function workflowInternalStatusLabel(status: string): string {
  return workflowRunStatusLabel(status);
}

const AGENT_EXTRA: Record<string, string> = {
  hitl: "等待您協助",
  chapter_summarizer: "整理章節摘要",
  end: "結束",
  END: "結束",
};

export function workflowAgentStepLabel(agentName: string): string {
  const key = agentName.trim();
  if (!key) return "—";
  const fromFlow = FLOW_STEPS.find((s) => s.id === key);
  if (fromFlow) return fromFlow.userLabel;
  return AGENT_EXTRA[key] ?? key;
}

const CHAPTER_STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  draft: "草稿",
  in_progress: "撰寫中",
  pending: "待處理",
  published: "已發佈",
};

export function chapterStatusLabel(status: string): string {
  const s = status.trim().toLowerCase();
  if (!s) return "—";
  return CHAPTER_STATUS_LABELS[s] ?? status;
}

export function hitlReasonTitle(reason: string): string {
  return getSituationCopy(reason).title;
}

const DECISION_MODE_LABELS: Record<string, string> = {
  NONE: "無",
  DASHBOARD: "可一鍵選擇",
  MANUAL_EDIT: "需填寫表單",
  STATE_INJECTION: "進階寫入",
};

export function hitlDecisionModeLabel(mode: string): string {
  const m = mode.trim();
  if (!m) return "—";
  return DECISION_MODE_LABELS[m] ?? `模式：${m}`;
}

const ROUTE_DECISION_LABELS: Record<string, string> = {
  pause: "暫停",
  hitl: "等待協助",
  planner: "回到劇情規劃",
  author: "回到撰寫",
  reader: "閱讀檢查",
  extraction_gate: "設定歸檔",
  resolve_subplots: "副線收尾",
  state_updater: "完稿更新",
  graph_rag: "背景整理",
  draft_supervisor: "內文審核",
  plan_supervisor: "大綱審核",
  director: "章節方向",
  b_story_resolve: "副線收尾",
  "": "—",
};

export function routeDecisionLabel(decision: string): string {
  const d = decision.trim();
  if (!d) return "—";
  return ROUTE_DECISION_LABELS[d] ?? d;
}

