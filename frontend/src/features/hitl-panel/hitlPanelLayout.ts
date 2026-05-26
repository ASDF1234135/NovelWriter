import { HITL_REASON, type HitlReasonValue } from "./hitlCopy";

export type HitlPanelSectionFlags = {
  content: boolean;
  quick: boolean;
  manual: boolean;
};

const DEFAULT_FLAGS: HitlPanelSectionFlags = { content: true, quick: true, manual: true };

/** Per-reason visibility for 內容顯示 / 快速處理 / 手動處理. */
export const HITL_PANEL_SECTION_FLAGS: Record<HitlReasonValue, HitlPanelSectionFlags> = {
  [HITL_REASON.PLAN_LOOP]: DEFAULT_FLAGS,
  [HITL_REASON.RESOLUTION_TACTIC]: DEFAULT_FLAGS,
  [HITL_REASON.ENDING_VIBE]: DEFAULT_FLAGS,
  [HITL_REASON.B_STORY_COOLDOWN]: { content: false, quick: false, manual: true },
  [HITL_REASON.DRAFT_LOOP]: DEFAULT_FLAGS,
  [HITL_REASON.EXTRACTION_GATE]: DEFAULT_FLAGS,
  [HITL_REASON.ANCHOR_RESOLVE]: { content: true, quick: true, manual: false },
  [HITL_REASON.B_STORY]: { content: true, quick: false, manual: false },
  [HITL_REASON.CONTEXT]: { content: true, quick: false, manual: true },
  [HITL_REASON.ALIGNMENT_RULES_REQUIRED]: { content: true, quick: false, manual: true },
  [HITL_REASON.OUTPUT_LANGUAGE]: DEFAULT_FLAGS,
  [HITL_REASON.CHAPTER_DRAFT_REVIEW]: { content: false, quick: false, manual: false },
};

export function getHitlPanelSectionFlags(reason: string): HitlPanelSectionFlags {
  return HITL_PANEL_SECTION_FLAGS[reason as HitlReasonValue] ?? DEFAULT_FLAGS;
}

export type QuickActionItem = { id: string; label: string };

const HIDDEN_SERVER_OPTION_IDS = new Set(["b_story_wait_judgement", "anchor_wait_judgement"]);

/** Anchor adjudication uses synthetic quick actions (not `pending_hitl_options`). */
export const ANCHOR_QUICK_ACTION_IDS = [
  "anchor_force_resolve",
  "anchor_continue_unresolved",
  "anchor_rewrite",
] as const;

export function resolveQuickActions(
  reason: string,
  serverOptions: QuickActionItem[],
): QuickActionItem[] {
  if (reason === HITL_REASON.ANCHOR_RESOLVE) {
    return ANCHOR_QUICK_ACTION_IDS.map((id) => ({ id, label: "" }));
  }
  return serverOptions.filter((o) => !HIDDEN_SERVER_OPTION_IDS.has(o.id));
}
