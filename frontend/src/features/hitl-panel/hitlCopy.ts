/** Mirrors backend HitlReason (schema.py) */
export const HITL_REASON = {
  PLAN_LOOP: "Plan_Loop_Exceeded",
  DRAFT_LOOP: "Draft_Loop_Exceeded",
  EXTRACTION_GATE: "Extraction_Gate_Failed",
  B_STORY: "B_Story_Resolution_Failed",
  B_STORY_COOLDOWN: "B_Story_Cooldown_Violation",
  RESOLUTION_TACTIC: "Resolution_Tactic_Cooldown_Violation",
  ENDING_VIBE: "Ending_Vibe_Cooldown_Violation",
  CONTEXT: "Context_Length_Exceeded",
} as const;

export type HitlReasonValue = (typeof HITL_REASON)[keyof typeof HITL_REASON];

export const FLOW_STEPS = [
  { id: "director", userLabel: "章節方向" },
  { id: "graph_rag", userLabel: "背景整理" },
  { id: "planner", userLabel: "劇情規劃" },
  { id: "plan_supervisor", userLabel: "大綱審核" },
  { id: "author", userLabel: "撰寫內文" },
  { id: "draft_supervisor", userLabel: "內文審核" },
  { id: "reader", userLabel: "閱讀檢查" },
  { id: "extraction_gate", userLabel: "設定歸檔" },
  { id: "b_story_resolve", userLabel: "副線收尾" },
  { id: "state_updater", userLabel: "完稿更新" },
] as const;

const RESUME_TO_STEP_INDEX: Record<string, number> = {
  director: 0,
  graph_rag: 1,
  planner: 2,
  plan_supervisor: 3,
  author: 4,
  draft_supervisor: 5,
  reader: 6,
  extraction_gate: 7,
  chapter_summarizer: 8,
  b_story_resolve: 8,
  state_updater: 9,
};

const REASON_TO_STEP_INDEX: Partial<Record<string, number>> = {
  [HITL_REASON.PLAN_LOOP]: 3,
  [HITL_REASON.RESOLUTION_TACTIC]: 3,
  [HITL_REASON.ENDING_VIBE]: 3,
  [HITL_REASON.B_STORY_COOLDOWN]: 0,
  [HITL_REASON.CONTEXT]: 1,
  [HITL_REASON.DRAFT_LOOP]: 5,
  [HITL_REASON.EXTRACTION_GATE]: 7,
  [HITL_REASON.B_STORY]: 8,
};

export function getStuckFlowStepIndex(reason: string, resumeFrom: string): number {
  const r = REASON_TO_STEP_INDEX[reason];
  if (typeof r === "number") return r;
  const rf = resumeFrom.trim();
  if (rf && RESUME_TO_STEP_INDEX[rf] !== undefined) return RESUME_TO_STEP_INDEX[rf];
  return 0;
}

export function resumeNodeUserLabel(resumeFrom: string): string {
  const idx = RESUME_TO_STEP_INDEX[resumeFrom.trim()];
  if (typeof idx === "number" && FLOW_STEPS[idx]) return FLOW_STEPS[idx].userLabel;
  return resumeFrom.trim() || "—";
}

const HITL_SITUATION_COPY: Record<string, { title: string; why: string }> = {
  [HITL_REASON.PLAN_LOOP]: {
    title: "大綱反覆未過審",
    why: "這一章的劇情規劃多次調整後，仍不符合系統的規則或您的故事設定。需要您選擇下一步：放寬某個條件、手動改大綱，或調整章節方向。",
  },
  [HITL_REASON.DRAFT_LOOP]: {
    title: "內文審核多次未過",
    why: "章節內文已重寫多次，仍與目標（長度、節奏或一致性）有落差。您可以放寬字數、直接修改內文，或補上文中應出現的稱呼與專名線索。",
  },
  [HITL_REASON.EXTRACTION_GATE]: {
    title: "設定與內文對不起來",
    why: "系統要把本章出現的人、事、物記進故事設定時，發現名稱或對應關係對不上。請協助對照、修正映射，或先回去改內文再試一次。",
  },
  [HITL_REASON.B_STORY]: {
    title: "副線收尾需要您拍板",
    why: "系統無法自動判定某條副線是否已合理收束。請依您的創作意圖，決定是否視為已收尾，或要求回到前段流程修改。",
  },
  [HITL_REASON.B_STORY_COOLDOWN]: {
    title: "副線類型撞期",
    why: "本章想走的副線類型，與近期章節用過的太接近。請微調章節方向或副線指示，讓故事節奏更有變化。",
  },
  [HITL_REASON.RESOLUTION_TACTIC]: {
    title: "收尾方式與近期重複",
    why: "大綱裡的收尾方式（例如特定戲劇手段）與系統的「冷卻」規則衝突。請調整大綱敘事或章節方向後再繼續。",
  },
  [HITL_REASON.ENDING_VIBE]: {
    title: "結尾氛圍與近期重複",
    why: "本章結尾的氛圍或場景類型，與近期章節太像。請調整大綱或敘事走向，避免讀者感到重複。",
  },
  [HITL_REASON.CONTEXT]: {
    title: "參考資料量過大",
    why: "系統準備寫作背景時，一次載入的內容超過上限。請刪減或精簡各段參考文字後再繼續。",
  },
};

export function getSituationCopy(reason: string): { title: string; why: string } {
  return (
    HITL_SITUATION_COPY[reason] ?? {
      title: "流程需要您協助",
      why: "系統在此步驟暫停，請依下方選項或表單處理後再繼續。",
    }
  );
}

/** Extra plain-language lines for dashboard option buttons */
export const OPTION_DECISION_HINTS: Record<string, string> = {
  allow_adjust_anchor: "先選這個後，再到下方用「延後里程碑」指定要延到哪一章。",
  force_rewrite_plan: "清空大綱重試計次，並以您手動編輯後的大綱重新規劃。",
  force_approve_plan: "接受目前大綱，直接進入撰寫（請確認您願意承擔後續風險）。",
  keep_current_logic: "維持劇情邏輯，重置內文重試次數，請接著修改正文或補線索。",
  relax_word_count: "放寬字數目標約四成，讓內文審核較易通過。",
  extraction_return_author: "先不對照設定表，回到撰寫階段修改內文用詞與指涉。",
};

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

const PLAN_VIOLATION_HINTS: Record<string, string> = {
  ANCHOR: "與故事里程碑不一致",
  LENGTH: "長度目標不符",
  COOLDOWN: "與近期章節節奏規則衝突",
  B_STORY: "副線相關",
  RESOLUTION_COOLDOWN_HARD_VIOLATION: "收尾方式與冷卻規則衝突",
  ENDING_VIBE_COOLDOWN_HARD_VIOLATION: "結尾氛圍與冷卻規則衝突",
};

function planViolationFriendly(code: string): string {
  const c = code.trim();
  if (!c) return "";
  const hint = PLAN_VIOLATION_HINTS[c];
  if (hint) return `${hint}（${c}）`;
  if (/^[A-Z0-9_]+$/.test(c)) return `系統代碼：${c}`;
  return c;
}

export function buildFeedbackSummary(state: Record<string, unknown>, reason: string): string[] {
  const lines: string[] = [];

  if (
    reason === HITL_REASON.PLAN_LOOP ||
    reason === HITL_REASON.RESOLUTION_TACTIC ||
    reason === HITL_REASON.ENDING_VIBE
  ) {
    const pf = state.plan_feedback;
    if (Array.isArray(pf) && pf.length > 0) {
      const last = pf[pf.length - 1];
      const row = asRecord(last);
      if (row) {
        const msg = String(row.message ?? "").trim();
        const viol = String(row.violation ?? "").trim();
        if (msg) lines.push(`審核意見：${msg}`);
        else if (viol) lines.push(`問題類型：${planViolationFriendly(viol)}`);
      }
    }
    const pw = state.plan_warnings;
    if (Array.isArray(pw) && pw.length > 0) {
      const tail = pw.slice(-3).map((w) => String(w).trim()).filter(Boolean);
      if (tail.length) lines.push(`提醒：${tail.join("；")}`);
    }
  }

  if (reason === HITL_REASON.DRAFT_LOOP || reason === HITL_REASON.EXTRACTION_GATE) {
    const df = state.draft_feedback;
    if (Array.isArray(df) && df.length > 0) {
      const last = df[df.length - 1];
      const row = asRecord(last);
      if (row) {
        const msg = String(row.message ?? "").trim();
        if (msg) lines.push(`審稿回饋：${msg}`);
      }
    }
  }

  return lines.slice(0, 6);
}

export type RemapHintRow = Record<string, unknown>;

export function parseRemapHintsJson(jsonStr: string): RemapHintRow[] {
  try {
    const v = JSON.parse(jsonStr) as unknown;
    return Array.isArray(v) ? (v as RemapHintRow[]) : [];
  } catch {
    return [];
  }
}

export function formatBStoryCandidateForDisplay(raw: string): { bullets: string[]; rawJson: string } {
  try {
    const v = JSON.parse(raw) as unknown;
    const o = asRecord(v);
    if (!o) return { bullets: [], rawJson: raw };
    const bullets: string[] = [];
    for (const [k, val] of Object.entries(o)) {
      if (val == null || val === "") continue;
      const s = typeof val === "object" ? JSON.stringify(val) : String(val);
      if (s.length > 200) bullets.push(`${k}：${s.slice(0, 200)}…`);
      else bullets.push(`${k}：${s}`);
    }
    return { bullets: bullets.slice(0, 12), rawJson: raw };
  } catch {
    return { bullets: [], rawJson: raw };
  }
}

export const DRAFT_RESUME_OPTIONS: { value: string; label: string }[] = [
  { value: "reader", label: "從閱讀檢查再跑" },
  { value: "draft_supervisor", label: "從內文審核再跑" },
  { value: "author", label: "從撰寫再跑" },
];

export const HINTS_RESUME_OPTIONS: { value: string; label: string }[] = [
  { value: "draft_supervisor", label: "先給內文審核看" },
  { value: "extraction_gate", label: "快到歸檔時再驗證" },
  { value: "author", label: "直接回到撰寫" },
];

export const B_STORY_REJECT_RESUME_OPTIONS: { value: string; label: string }[] = [
  { value: "extraction_gate", label: "設定歸檔" },
  { value: "author", label: "撰寫內文" },
  { value: "b_story_resolve", label: "副線收尾" },
];

export function isPlanFamilyReason(reason: string): boolean {
  return (
    reason === HITL_REASON.PLAN_LOOP ||
    reason === HITL_REASON.RESOLUTION_TACTIC ||
    reason === HITL_REASON.ENDING_VIBE
  );
}

export function isDirectorPatchReason(reason: string): boolean {
  return (
    isPlanFamilyReason(reason) ||
    reason === HITL_REASON.B_STORY_COOLDOWN
  );
}

export type HitlSolutionId = "outline" | "anchor" | "director" | "draft" | "hints" | "remap" | "b_story" | "prune";

export function solutionsForReason(reason: string): { id: HitlSolutionId; title: string; blurb: string }[] {
  if (reason === HITL_REASON.PLAN_LOOP) {
    return [
      { id: "outline", title: "手動調整事件大綱", blurb: "直接編輯事件表與表層敘事，交給系統重新規劃細節。" },
      { id: "anchor", title: "延後故事里程碑", blurb: "把某個關鍵節點改到較晚的章再達成。" },
      { id: "director", title: "微調章節方向", blurb: "調整本章類型、主線指示、想新登場的元素等。" },
    ];
  }
  if (isPlanFamilyReason(reason) && reason !== HITL_REASON.PLAN_LOOP) {
    return [
      { id: "outline", title: "調整大綱與敘事", blurb: "修改事件與敘事走向，避開重複的收尾或氛圍。" },
      { id: "director", title: "微調章節方向", blurb: "從章節定位與副線指示下手，讓規劃更容易過審。" },
    ];
  }
  if (reason === HITL_REASON.B_STORY_COOLDOWN) {
    return [{ id: "director", title: "調整副線與章節方向", blurb: "換一種副線類型或寫法，避免與前幾章撞題。" }];
  }
  if (reason === HITL_REASON.DRAFT_LOOP) {
    return [
      { id: "draft", title: "直接修改章節內文", blurb: "在下方編輯正文，再從適當步驟續跑。" },
      { id: "hints", title: "補上稱呼與專名線索", blurb: "告訴系統文中應出現哪些用詞，協助後續審核與歸檔。" },
    ];
  }
  if (reason === HITL_REASON.EXTRACTION_GATE) {
    return [{ id: "remap", title: "對照角色與道具名稱", blurb: "依系統猜測修正「文中說法」對應到「設定表」的哪一筆。" }];
  }
  if (reason === HITL_REASON.B_STORY) {
    return [{ id: "b_story", title: "副線是否已收尾", blurb: "決定核銷副線或打回前段流程。" }];
  }
  if (reason === HITL_REASON.CONTEXT) {
    return [{ id: "prune", title: "精簡參考資料", blurb: "刪短各段背景文字，降低一次載入量。" }];
  }
  return [];
}

export function defaultSolutionForReason(reason: string): HitlSolutionId {
  const list = solutionsForReason(reason);
  return list[0]?.id ?? "outline";
}
