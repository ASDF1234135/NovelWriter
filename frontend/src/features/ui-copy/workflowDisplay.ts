import { FLOW_STEPS, getSituationCopy } from "../hitl-panel/hitlCopy";
import { getRuntimeLocale } from "../../i18n/runtimeLocale";

function pick(zhHant: string, zhHans: string, en: string): string {
  const locale = getRuntimeLocale();
  if (locale === "en") return en;
  if (locale === "zh-Hans") return zhHans;
  return zhHant;
}

const RUN_STATUS_LABELS: Record<string, string> = {
  IDLE: pick("待開始", "待开始", "Idle"),
  RUNNING: pick("進行中", "进行中", "Running"),
  WAITING_HITL: pick("等待您處理", "等待你处理", "Waiting for you"),
  COMPLETED: pick("已完成", "已完成", "Completed"),
  FAILED: pick("失敗", "失败", "Failed"),
};

/** 後端 WorkflowRun / 章節工作狀態顯示 */
export function workflowRunStatusLabel(status: string): string {
  const s = status.trim();
  if (!s) return "—";
  return RUN_STATUS_LABELS[s] ?? pick(`狀態：${s}`, `状态：${s}`, `Status: ${s}`);
}

/** 與 workflowRunStatusLabel 相同語意，內部狀態欄位用 */
export function workflowInternalStatusLabel(status: string): string {
  return workflowRunStatusLabel(status);
}

const AGENT_EXTRA: Record<string, string> = {
  hitl: pick("等待您協助", "等待你协助", "Waiting for your input"),
  chapter_summarizer: pick("整理章節摘要", "整理章节摘要", "Summarizing chapter"),
  end: pick("結束", "结束", "End"),
  END: pick("結束", "结束", "End"),
};

export function workflowAgentStepLabel(agentName: string): string {
  const key = agentName.trim();
  if (!key) return "—";
  const fromFlow = FLOW_STEPS.find((s) => s.id === key);
  if (fromFlow) return fromFlow.userLabel;
  return AGENT_EXTRA[key] ?? key;
}

const CHAPTER_STATUS_LABELS: Record<string, string> = {
  completed: pick("已完成", "已完成", "Completed"),
  draft: pick("草稿", "草稿", "Draft"),
  in_progress: pick("撰寫中", "撰写中", "In Progress"),
  pending: pick("待處理", "待处理", "Pending"),
  published: pick("已發佈", "已发布", "Published"),
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
  NONE: pick("無", "无", "None"),
  DASHBOARD: pick("可一鍵選擇", "可一键选择", "One-click options"),
  MANUAL_EDIT: pick("需填寫表單", "需填写表单", "Manual form"),
  STATE_INJECTION: pick("進階寫入", "进阶写入", "Advanced injection"),
};

export function hitlDecisionModeLabel(mode: string): string {
  const m = mode.trim();
  if (!m) return "—";
  return DECISION_MODE_LABELS[m] ?? pick(`模式：${m}`, `模式：${m}`, `Mode: ${m}`);
}

const ROUTE_DECISION_LABELS: Record<string, string> = {
  pause: pick("暫停", "暂停", "Pause"),
  hitl: pick("等待協助", "等待协助", "Await help"),
  planner: pick("回到劇情規劃", "回到剧情规划", "Back to planning"),
  author: pick("回到撰寫", "回到撰写", "Back to writing"),
  reader: pick("閱讀檢查", "阅读检查", "Reader check"),
  extraction_gate: pick("設定歸檔", "设定归档", "Extraction gate"),
  resolve_subplots: pick("副線收尾", "副线收尾", "Resolve subplot"),
  state_updater: pick("完稿更新", "完稿更新", "State update"),
  graph_rag: pick("背景整理", "背景整理", "Context prep"),
  draft_supervisor: pick("內文審核", "正文审核", "Draft review"),
  plan_supervisor: pick("大綱審核", "大纲审核", "Plan review"),
  director: pick("章節方向", "章节方向", "Chapter direction"),
  b_story_resolve: pick("副線收尾", "副线收尾", "Resolve subplot"),
  "": "—",
};

export function routeDecisionLabel(decision: string): string {
  const d = decision.trim();
  if (!d) return "—";
  return ROUTE_DECISION_LABELS[d] ?? d;
}

