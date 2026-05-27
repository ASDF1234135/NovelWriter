/** Mirrors backend HitlReason (schema.py) */
import { getRuntimeLocale } from "../../i18n/runtimeLocale";

function pick(zhHant: string, zhHans: string, en: string): string {
  const locale = getRuntimeLocale();
  if (locale === "en") return en;
  if (locale === "zh-Hans") return zhHans;
  return zhHant;
}

export const HITL_REASON = {
  PLAN_LOOP: "Plan_Loop_Exceeded",
  DRAFT_LOOP: "Draft_Loop_Exceeded",
  EXTRACTION_GATE: "Extraction_Gate_Failed",
  /** Legacy: subplot/B-story HITL; kept for backward compatibility. */
  B_STORY: "B_Story_Resolution_Failed",
  B_STORY_COOLDOWN: "B_Story_Cooldown_Violation",
  RESOLUTION_TACTIC: "Resolution_Tactic_Cooldown_Violation",
  ENDING_VIBE: "Ending_Vibe_Cooldown_Violation",
  CONTEXT: "Context_Length_Exceeded",
  ALIGNMENT_RULES_REQUIRED: "Alignment_Rules_Required",
  OUTPUT_LANGUAGE: "Output_Language_Mismatch",
  /** Post-run milestone adjudication (anchor_resolve node). */
  ANCHOR_RESOLVE: "Anchor_Resolution_Failed",
  /**
   * Post-reader human review checkpoint. Handled in the reading area (not this panel);
   * solutionsForReason returns [] so HitlPanel renders a redirect stub.
   */
  CHAPTER_DRAFT_REVIEW: "Chapter_Draft_Review",
} as const;

export type HitlReasonValue = (typeof HITL_REASON)[keyof typeof HITL_REASON];

/** Matches backend `graph.py` chapter pipeline order (copyeditor may be skipped when disabled). */
export const FLOW_STEPS = [
  { id: "director", userLabel: pick("章節方向", "章节方向", "Chapter direction") },
  { id: "graph_rag", userLabel: pick("背景整理", "背景整理", "Context prep") },
  { id: "planner", userLabel: pick("劇情規劃", "剧情规划", "Story planning") },
  { id: "plan_supervisor", userLabel: pick("大綱審核", "大纲审核", "Outline review") },
  { id: "logic_alignment", userLabel: pick("規則對齊", "规则对齐", "Rules alignment") },
  { id: "author", userLabel: pick("撰寫內文", "撰写正文", "Writing draft") },
  { id: "draft_supervisor", userLabel: pick("內文審核", "正文审核", "Draft review") },
  { id: "reader", userLabel: pick("閱讀檢查", "阅读检查", "Reader check") },
  { id: "extraction_gate", userLabel: pick("章末設定整理", "章末设定整理", "Chapter settings wrap-up") },
  { id: "copyeditor", userLabel: pick("文稿潤飾", "文稿润饰", "Line editing") },
  { id: "output_language_gate", userLabel: pick("語言一致檢查", "语言一致检查", "Language check") },
  { id: "chapter_summarizer", userLabel: pick("章節摘要整理", "章节摘要整理", "Chapter summary") },
  { id: "anchor_resolve", userLabel: pick("里程碑達成確認", "里程碑达成确认", "Milestone check") },
  { id: "profile_expander", userLabel: pick("角色資料補齊", "角色资料补齐", "Character profiles") },
  { id: "state_updater", userLabel: pick("章節進度儲存", "章节进度保存", "Preparing save") },
  { id: "commit_to_databases", userLabel: pick("寫入作品庫", "写入作品库", "Saving to library") },
] as const;

const RESUME_TO_STEP_INDEX: Record<string, number> = {
  director: 0,
  graph_rag: 1,
  planner: 2,
  plan_supervisor: 3,
  logic_alignment: 4,
  author: 5,
  draft_supervisor: 6,
  reader: 7,
  extraction_gate: 8,
  copyeditor: 9,
  output_language_gate: 10,
  chapter_summarizer: 11,
  anchor_resolve: 12,
  profile_expander: 13,
  state_updater: 14,
  commit_to_databases: 15,
};

const REASON_TO_STEP_INDEX: Partial<Record<string, number>> = {
  [HITL_REASON.PLAN_LOOP]: 3,
  [HITL_REASON.RESOLUTION_TACTIC]: 3,
  [HITL_REASON.ENDING_VIBE]: 3,
  [HITL_REASON.B_STORY_COOLDOWN]: 0,
  [HITL_REASON.CONTEXT]: 1,
  [HITL_REASON.ALIGNMENT_RULES_REQUIRED]: 4,
  [HITL_REASON.DRAFT_LOOP]: 5,
  [HITL_REASON.EXTRACTION_GATE]: 8,
  [HITL_REASON.B_STORY]: 12,
  [HITL_REASON.ANCHOR_RESOLVE]: 12,
  [HITL_REASON.OUTPUT_LANGUAGE]: 10,
  /** Post-reader human review — pipeline paused after reader; show writing-stage emphasis. */
  [HITL_REASON.CHAPTER_DRAFT_REVIEW]: 7,
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
    title: pick("大綱反覆未過審", "大纲反复未过审", "Outline Repeatedly Rejected"),
    why: pick(
      "這一章的劇情規劃多次調整後，仍不符合系統的規則或您的故事設定。需要您選擇下一步：放寬某個條件、手動改大綱，或調整章節方向。",
      "这一章的剧情规划多次调整后，仍不符合系统规则或你的故事设定。请决定下一步：放宽条件、手动改大纲，或调整章节方向。",
      "This chapter plan still fails system rules or your story settings after multiple revisions. Choose a next step: relax constraints, edit outline manually, or tune chapter direction.",
    ),
  },
  [HITL_REASON.DRAFT_LOOP]: {
    title: pick("內文審核多次未過", "正文审核多次未过", "Draft Rejected Multiple Times"),
    why: pick(
      "章節內文已重寫多次，仍與目標（長度、節奏或一致性）有落差。您可以放寬字數、直接修改內文，或補上文中應出現的稱呼與專名線索。",
      "章节正文已重写多次，仍与目标（长度、节奏或一致性）有落差。你可以放宽字数、直接修改正文，或补上应出现的称呼与专名线索。",
      "The chapter draft has been rewritten multiple times but still misses targets (length, pacing, or consistency). You can relax word count, edit draft directly, or add naming hints.",
    ),
  },
  [HITL_REASON.EXTRACTION_GATE]: {
    title: pick("設定與內文對不起來", "设定与正文对不上", "Canon and Draft Mismatch"),
    why: pick(
      "系統要把本章出現的人、事、物記進故事設定時，發現名稱或對應關係對不上。請協助對照、修正映射，或先回去改內文再試一次。",
      "系统在把本章人物/事件/物件写回设定时，发现名称或映射关系不一致。请协助对照修正，或先回去修改正文再试。",
      "When archiving people/events/items from this chapter into canon, the system found naming or mapping mismatches. Please fix mappings, or revise draft first and retry.",
    ),
  },
  [HITL_REASON.B_STORY]: {
    title: pick("副線收尾需要您拍板", "副线收尾需要你拍板", "Subplot Resolution Needs Decision"),
    why: pick(
      "系統無法自動判定某條副線是否已合理收束。請依您的創作意圖，決定是否視為已收尾，或要求回到前段流程修改。",
      "系统无法自动判定某条副线是否已合理收束。请按你的创作意图决定是否视为已收尾，或打回前段流程修改。",
      "The system cannot confidently decide whether a subplot is properly resolved. Decide whether to mark it resolved or send the flow back for revision.",
    ),
  },
  [HITL_REASON.B_STORY_COOLDOWN]: {
    title: pick("副線類型撞期", "副线类型撞期", "Subplot Type Cooldown Conflict"),
    why: pick(
      "本章想走的副線類型，與近期章節用過的太接近。請微調章節方向或副線指示，讓故事節奏更有變化。",
      "本章想走的副线类型，与近期章节用过的太接近。请微调章节方向或副线指示，让节奏更有变化。",
      "The subplot type planned for this chapter is too similar to recent chapters. Tune chapter direction or subplot directive to add variation.",
    ),
  },
  [HITL_REASON.ANCHOR_RESOLVE]: {
    title: pick("里程碑達成需要您拍板", "里程碑达成需要你拍板", "Milestone Resolution Needs Decision"),
    why: pick(
      "系統無法自動判定本章是否確實達成（或未達成）某個里程碑。請依您的創作意圖，決定要視為已達成、要求改寫，或延後目標到之後章節再完成。",
      "系统无法自动判定本章是否确实达成（或未达成）某个里程碑。请按你的创作意图决定要视为已达成、要求改写，或延后目标到后续章节再完成。",
      "The system cannot confidently decide whether this chapter achieves the planned milestone. Decide whether to mark it achieved, request a rewrite, or delay the milestone to a later chapter.",
    ),
  },
  [HITL_REASON.RESOLUTION_TACTIC]: {
    title: pick("收尾方式與近期重複", "收尾方式与近期重复", "Ending Tactic Repeats Recent Chapters"),
    why: pick(
      "大綱裡的收尾方式（例如特定戲劇手段）與系統的「冷卻」規則衝突。請調整大綱敘事或章節方向後再繼續。",
      "大纲里的收尾方式（例如特定戏剧手段）与系统“冷却”规则冲突。请调整大纲叙事或章节方向后继续。",
      "The ending tactic in your outline conflicts with cooldown rules. Adjust narrative approach or chapter direction before continuing.",
    ),
  },
  [HITL_REASON.ENDING_VIBE]: {
    title: pick("結尾氛圍與近期重複", "结尾氛围与近期重复", "Ending Vibe Repeats Recent Chapters"),
    why: pick(
      "本章結尾的氛圍或場景類型，與近期章節太像。請調整大綱或敘事走向，避免讀者感到重複。",
      "本章结尾氛围或场景类型与近期章节太像。请调整大纲或叙事走向，避免读者感觉重复。",
      "The ending vibe or scene type is too similar to recent chapters. Adjust outline or narrative direction to avoid repetition.",
    ),
  },
  [HITL_REASON.CONTEXT]: {
    title: pick("參考資料量過大", "参考资料量过大", "Context Too Large"),
    why: pick(
      "系統準備寫作背景時，一次載入的內容超過上限。請刪減或精簡各段參考文字後再繼續。",
      "系统准备写作背景时，单次载入内容超过上限。请删减或精简各段参考文字后继续。",
      "Loaded context exceeded limits during background assembly. Trim reference sections and continue.",
    ),
  },
  [HITL_REASON.ALIGNMENT_RULES_REQUIRED]: {
    title: pick("偵測到複雜智鬥，需補充規則", "检测到复杂智斗，需补充规则", "Complex Mind-Game Detected"),
    why: pick(
      "草稿包含高複雜智鬥元素，但缺少可執行的硬性規則。請補充勝負條件、回合/判定流程與籌碼代價，系統才能安全對齊後續正文。",
      "草稿包含高复杂智斗元素，但缺少可执行硬性规则。请补充胜负条件、回合/判定流程与筹码代价，系统才能安全对齐后续正文。",
      "Draft contains complex strategy conflicts but lacks executable hard rules. Add win conditions, round/judging flow, and stakes so later drafting can align safely.",
    ),
  },
  [HITL_REASON.OUTPUT_LANGUAGE]: {
    title: pick("輸出語言與專案設定不一致", "输出语言与项目设定不一致", "Output Language Mismatch"),
    why: pick(
      "系統用簡單規則檢查本章正文的主要字母類型，發現可能與故事「輸出語言」設定不符。您可以退回撰寫依設定語言重寫，或確認後略過檢查繼續彙總。",
      "系统用简单规则检查本章正文的主要字符类型，发现可能与故事“输出语言”设定不符。你可以回到撰写按设定重写，或确认后略过检查继续汇总。",
      "Simple language detection suggests this chapter may not match the project's output language setting. You can return to rewrite in target language, or confirm and continue.",
    ),
  },
  [HITL_REASON.CHAPTER_DRAFT_REVIEW]: {
    title: pick("章節草稿待您審核", "章节草稿待你审核", "Chapter Draft Awaiting Review"),
    why: pick(
      "Reader 已通過本章草稿；此次工作流設定為需要人工審核。請在右下角 HITL 浮動面板審閱、編輯或放棄。",
      "Reader 已通过本章草稿；此次工作流设定为需要人工审核。请在右下角 HITL 浮动面板审阅、编辑或放弃。",
      "Reader has approved the draft, but this run requires a human checkpoint. Use the HITL floating panel (bottom-right) to review, edit, or abandon.",
    ),
  },
};

export function getSituationCopy(reason: string): { title: string; why: string } {
  return (
    HITL_SITUATION_COPY[reason] ?? {
      title: pick("流程需要您協助", "流程需要你协助", "Your input is required"),
      why: pick("系統在此步驟暫停，請依下方選項或表單處理後再繼續。", "系统在此步骤暂停，请根据下方选项或表单处理后继续。", "The workflow is paused at this step. Use the options or form below to continue."),
    }
  );
}

/** Extra plain-language lines for dashboard option buttons */
export const OPTION_DECISION_HINTS: Record<string, string> = {
  allow_adjust_anchor: pick(
    "先選這個後，再到下方用「延後里程碑」指定要延到哪一章。",
    "先选这个，再到下方用“延后里程碑”指定要延到哪一章。",
    "Choose this first, then set the target chapter in Delay Milestone below.",
  ),
  force_rewrite_plan: pick(
    "清空大綱重試計次，並以您手動編輯後的大綱重新規劃。",
    "清空大纲重试计次，并以你手动编辑后的大纲重新规划。",
    "Reset outline retry count and re-plan from your edited outline.",
  ),
  force_approve_plan: pick(
    "接受目前大綱，直接進入撰寫（請確認您願意承擔後續風險）。",
    "接受当前大纲，直接进入撰写（请确认你愿意承担后续风险）。",
    "Accept current outline and move to writing (with downstream risk).",
  ),
  keep_current_logic: pick(
    "維持劇情邏輯，重置內文重試次數，請接著修改正文或補線索。",
    "维持剧情逻辑，重置正文重试次数，请继续修改正文或补线索。",
    "Keep current logic, reset draft retries, then revise draft or add hints.",
  ),
  relax_word_count: pick(
    "放寬字數目標約四成，讓內文審核較易通過。",
    "放宽字数目标约四成，让正文审核更容易通过。",
    "Relax word-count target by around 40% for easier draft validation.",
  ),
  extraction_return_author: pick(
    "先不對照設定表，回到撰寫階段修改內文用詞與指涉。",
    "先不对照设定表，回到撰写阶段修改正文用词与指涉。",
    "Skip mapping for now and return to writing to revise wording/references.",
  ),
  language_return_author: pick(
    "回到撰寫，依專案設定的輸出語言重寫本章正文。",
    "回到撰写，按项目设定的输出语言重写本章正文。",
    "Return to writing and rewrite this chapter in project output language.",
  ),
  language_force_continue: pick(
    "接受目前正文並略過語言檢查，繼續進入章節彙總與收尾流程。",
    "接受当前正文并略过语言检查，继续进入章节汇总与收尾流程。",
    "Accept current draft, skip language check, and continue to wrap-up.",
  ),
};

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

const PLAN_VIOLATION_HINTS: Record<string, string> = {
  ANCHOR: pick("與故事里程碑不一致", "与故事里程碑不一致", "Conflicts with story milestone"),
  LENGTH: pick("長度目標不符", "长度目标不符", "Length target mismatch"),
  COOLDOWN: pick("與近期章節節奏規則衝突", "与近期章节节奏规则冲突", "Conflicts with recent chapter cooldown rules"),
  B_STORY: pick("副線相關", "副线相关", "Subplot-related"),
  RESOLUTION_COOLDOWN_HARD_VIOLATION: pick(
    "收尾方式與冷卻規則衝突",
    "收尾方式与冷却规则冲突",
    "Ending tactic conflicts with cooldown rules",
  ),
  ENDING_VIBE_COOLDOWN_HARD_VIOLATION: pick(
    "結尾氛圍與冷卻規則衝突",
    "结尾氛围与冷却规则冲突",
    "Ending vibe conflicts with cooldown rules",
  ),
};

function planViolationFriendly(code: string): string {
  const c = code.trim();
  if (!c) return "";
  const hint = PLAN_VIOLATION_HINTS[c];
  if (hint) return `${hint}（${c}）`;
  if (/^[A-Z0-9_]+$/.test(c)) {
    return pick(`系統代碼：${c}`, `系统代码：${c}`, `System code: ${c}`);
  }
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
        if (msg) lines.push(pick(`審核意見：${msg}`, `审核意见：${msg}`, `Review note: ${msg}`));
        else if (viol) {
          lines.push(
            pick(
              `問題類型：${planViolationFriendly(viol)}`,
              `问题类型：${planViolationFriendly(viol)}`,
              `Issue type: ${planViolationFriendly(viol)}`,
            ),
          );
        }
      }
    }
    const pw = state.plan_warnings;
    if (Array.isArray(pw) && pw.length > 0) {
      const tail = pw.slice(-3).map((w) => String(w).trim()).filter(Boolean);
      if (tail.length) {
        lines.push(
          pick(`提醒：${tail.join("；")}`, `提醒：${tail.join("；")}`, `Reminder: ${tail.join("; ")}`),
        );
      }
    }
  }

  if (reason === HITL_REASON.DRAFT_LOOP || reason === HITL_REASON.EXTRACTION_GATE) {
    const df = state.draft_feedback;
    if (Array.isArray(df) && df.length > 0) {
      const last = df[df.length - 1];
      const row = asRecord(last);
      if (row) {
        const msg = String(row.message ?? "").trim();
        if (msg) lines.push(pick(`審稿回饋：${msg}`, `审稿反馈：${msg}`, `Draft feedback: ${msg}`));
      }
    }
  }

  if (reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED) {
    const al = String(state.alignment_log ?? "").trim();
    if (al) {
      const clipped = al.length > 420 ? `${al.slice(0, 420)}…` : al;
      lines.push(pick(`對齊日誌：${clipped}`, `对齐日志：${clipped}`, `Alignment log: ${clipped}`));
    }
    const cn = state.human_outline_conflict_notes;
    if (Array.isArray(cn)) {
      for (const x of cn.slice(0, 5)) {
        const s = String(x).trim();
        if (s) lines.push(pick(`設定衝突：${s}`, `设定冲突：${s}`, `Setting conflict: ${s}`));
      }
    }
    const co = String(state.chapter_outline ?? "").trim();
    if (co) {
      const clipped = co.length > 180 ? `${co.slice(0, 180)}…` : co;
      lines.push(
        pick(
          `你的人類大綱（節錄）：${clipped}`,
          `你的人类大纲（节录）：${clipped}`,
          `Your outline (excerpt): ${clipped}`,
        ),
      );
    }
  }

  return lines.slice(0, 8);
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
  { value: "reader", label: pick("從閱讀檢查再跑", "从阅读检查再跑", "Resume from Reader Check") },
  { value: "draft_supervisor", label: pick("從內文審核再跑", "从正文审核再跑", "Resume from Draft Review") },
  { value: "author", label: pick("從撰寫再跑", "从撰写再跑", "Resume from Writing") },
];

export const HINTS_RESUME_OPTIONS: { value: string; label: string }[] = [
  { value: "draft_supervisor", label: pick("先給內文審核看", "先给正文审核看", "Send to Draft Review first") },
  { value: "extraction_gate", label: pick("快到歸檔時再驗證", "到归档前再验证", "Validate near extraction step") },
  { value: "author", label: pick("直接回到撰寫", "直接回到撰写", "Return to Writing directly") },
];

export const B_STORY_REJECT_RESUME_OPTIONS: { value: string; label: string }[] = [
  { value: "extraction_gate", label: pick("章末設定整理", "章末设定整理", "Chapter settings wrap-up") },
  { value: "author", label: pick("撰寫內文", "撰写正文", "Writing draft") },
  { value: "anchor_resolve", label: pick("里程碑達成確認", "里程碑达成确认", "Milestone check") },
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

export type HitlSolutionId = "outline" | "anchor" | "director" | "draft" | "remap" | "b_story" | "prune";

export function solutionsForReason(reason: string): { id: HitlSolutionId; title: string; blurb: string }[] {
  if (reason === HITL_REASON.PLAN_LOOP) {
    return [
      {
        id: "director",
        title: pick("微調章節方向", "微调章节方向", "Tune Chapter Direction"),
        blurb: pick(
          "調整本章類型、主線指示、想新登場的元素等。",
          "调整本章类型、主线指示、想新登场的元素等。",
          "Adjust chapter type, narrative directive, and new elements.",
        ),
      },
      {
        id: "outline",
        title: pick("手動調整事件大綱", "手动调整事件大纲", "Manually Edit Event Outline"),
        blurb: pick(
          "直接編輯事件表與表層敘事，交給系統重新規劃細節。",
          "直接编辑事件表与表层叙事，交给系统重新规划细节。",
          "Directly edit events and narrative script, then let system re-plan details.",
        ),
      },
    ];
  }
  if (isPlanFamilyReason(reason) && reason !== HITL_REASON.PLAN_LOOP) {
    return [
      {
        id: "director",
        title: pick("微調章節方向", "微调章节方向", "Tune Chapter Direction"),
        blurb: pick("從章節定位與副線指示下手，讓規劃更容易過審。", "从章节定位与副线指示下手，让规划更容易过审。", "Refine chapter positioning and subplot guidance to pass review."),
      },
      {
        id: "outline",
        title: pick("調整大綱與敘事", "调整大纲与叙事", "Adjust Outline and Narrative"),
        blurb: pick(
          "修改事件與敘事走向，避開重複的收尾或氛圍。",
          "修改事件与叙事走向，避开重复的收尾或氛围。",
          "Adjust event flow to avoid repeated ending tactics or vibe.",
        ),
      },
    ];
  }
  if (reason === HITL_REASON.B_STORY_COOLDOWN) {
    return [
      {
        id: "director",
        title: pick("調整副線與章節方向", "调整副线与章节方向", "Adjust Subplot and Direction"),
        blurb: pick("換一種副線類型或寫法，避免與前幾章撞題。", "换一种副线类型或写法，避免与前几章撞题。", "Change subplot type or treatment to avoid repeating recent chapters."),
      },
    ];
  }
  if (reason === HITL_REASON.DRAFT_LOOP) {
    return [
      {
        id: "draft",
        title: pick("直接修改章節內文", "直接修改章节正文", "Edit Chapter Draft Directly"),
        blurb: pick("在下方編輯正文，再從適當步驟續跑。", "在下方编辑正文，再从合适步骤续跑。", "Edit draft below, then resume from the proper step."),
      },
    ];
  }
  if (reason === HITL_REASON.OUTPUT_LANGUAGE) {
    return [
      {
        id: "draft",
        title: pick("手動修正本章內文", "手动修正本章正文", "Manually Edit Chapter Text"),
        blurb: pick(
          "直接在下方修改正文，然後回到語言檢查步驟繼續。",
          "直接在下方修改正文，然后回到语言检查步骤继续。",
          "Edit the chapter text below, then continue from the language check step.",
        ),
      },
    ];
  }
  if (reason === HITL_REASON.EXTRACTION_GATE) {
    return [
      {
        id: "remap",
        title: pick("對照角色與道具名稱", "对照角色与道具名称", "Map Character and Item Names"),
        blurb: pick(
          "依系統猜測修正「文中說法」對應到「設定表」的哪一筆。",
          "按系统猜测修正“文中说法”对应到“设定表”的哪一笔。",
          "Fix mapping from in-text mentions to canonical records.",
        ),
      },
    ];
  }
  if (reason === HITL_REASON.B_STORY) {
    // Legacy: kept for backward compatibility but should not be triggered in current workflow.
    return [];
  }
  if (reason === HITL_REASON.ANCHOR_RESOLVE) {
    return [];
  }
  if (reason === HITL_REASON.CONTEXT) {
    return [
      {
        id: "prune",
        title: pick("精簡參考資料", "精简参考资料", "Prune Context"),
        blurb: pick("刪短各段背景文字，降低一次載入量。", "删短各段背景文字，降低一次载入量。", "Trim context blocks to reduce prompt size."),
      },
    ];
  }
  return [];
}

export function defaultSolutionForReason(reason: string): HitlSolutionId {
  const list = solutionsForReason(reason);
  return list[0]?.id ?? "outline";
}

export type HitlReasonMatrixRow = {
  reason: string;
  title: string;
  defaultSolution: HitlSolutionId | null;
  solutionIds: HitlSolutionId[];
  optionIds: string[];
};

export const HITL_REASON_MATRIX: HitlReasonMatrixRow[] = [
  {
    reason: HITL_REASON.PLAN_LOOP,
    title: getSituationCopy(HITL_REASON.PLAN_LOOP).title,
    defaultSolution: "director",
    solutionIds: ["director", "outline"],
    optionIds: ["force_rewrite_plan", "force_approve_plan"],
  },
  {
    reason: HITL_REASON.RESOLUTION_TACTIC,
    title: getSituationCopy(HITL_REASON.RESOLUTION_TACTIC).title,
    defaultSolution: "director",
    solutionIds: ["director", "outline"],
    optionIds: ["force_rewrite_plan", "force_approve_plan"],
  },
  {
    reason: HITL_REASON.ENDING_VIBE,
    title: getSituationCopy(HITL_REASON.ENDING_VIBE).title,
    defaultSolution: "director",
    solutionIds: ["director", "outline"],
    optionIds: ["force_rewrite_plan", "force_approve_plan"],
  },
  {
    reason: HITL_REASON.B_STORY_COOLDOWN,
    title: getSituationCopy(HITL_REASON.B_STORY_COOLDOWN).title,
    defaultSolution: "director",
    solutionIds: ["director"],
    optionIds: [],
  },
  {
    reason: HITL_REASON.DRAFT_LOOP,
    title: getSituationCopy(HITL_REASON.DRAFT_LOOP).title,
    defaultSolution: "draft",
    solutionIds: ["draft"],
    optionIds: ["keep_current_logic", "relax_word_count"],
  },
  {
    reason: HITL_REASON.EXTRACTION_GATE,
    title: getSituationCopy(HITL_REASON.EXTRACTION_GATE).title,
    defaultSolution: "remap",
    solutionIds: ["remap"],
    optionIds: ["extraction_return_author"],
  },
  {
    reason: HITL_REASON.ANCHOR_RESOLVE,
    title: getSituationCopy(HITL_REASON.ANCHOR_RESOLVE).title,
    defaultSolution: null,
    solutionIds: [],
    optionIds: [],
  },
  {
    reason: HITL_REASON.B_STORY,
    title: getSituationCopy(HITL_REASON.B_STORY).title,
    defaultSolution: null,
    solutionIds: [],
    optionIds: [],
  },
  {
    reason: HITL_REASON.CONTEXT,
    title: getSituationCopy(HITL_REASON.CONTEXT).title,
    defaultSolution: "prune",
    solutionIds: ["prune"],
    optionIds: [],
  },
  {
    reason: HITL_REASON.ALIGNMENT_RULES_REQUIRED,
    title: getSituationCopy(HITL_REASON.ALIGNMENT_RULES_REQUIRED).title,
    defaultSolution: null,
    solutionIds: [],
    optionIds: [],
  },
  {
    reason: HITL_REASON.OUTPUT_LANGUAGE,
    title: getSituationCopy(HITL_REASON.OUTPUT_LANGUAGE).title,
    defaultSolution: "draft",
    solutionIds: ["draft"],
    optionIds: ["language_return_author", "language_force_continue"],
  },
  {
    // Post-reader human review is handled in the reading area (ChapterReviewGate),
    // not the HitlPanel; the panel renders a redirect stub. Keep solution arrays
    // empty so HITL_REASON_MATRIX stays consistent with solutionsForReason().
    reason: HITL_REASON.CHAPTER_DRAFT_REVIEW,
    title: getSituationCopy(HITL_REASON.CHAPTER_DRAFT_REVIEW).title,
    defaultSolution: null,
    solutionIds: [],
    optionIds: ["APPROVE_DRAFT", "RERUN_KEEP_DIRECTOR", "ABANDON_CHAPTER"],
  },
];
