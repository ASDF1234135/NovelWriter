/**
 * Dev-only HITL workflow fixtures. Field names, option ids, labels, and resume_from
 * mirror `backend/app/services/workflow/graph.py` and `hitl_payload.py`.
 */
import {
  HITL_REASON,
  HITL_REASON_MATRIX,
  type HitlReasonValue,
} from "../features/hitl-panel/hitlCopy";
import type { GraphSnapshot, HitlContextPayload, WorkflowPayload } from "../types";

export type HitlDevPayload = {
  workflow: WorkflowPayload;
  graph?: GraphSnapshot;
};

const MOCK_STORY_ID = "dev_mock_story";
const MOCK_CHAPTER_ID = 7;

const SAMPLE_DRAFT = `林默在霧港的倉庫深處找到那把黑曜短刃，指尖卻在刀柄前停住。
「現在拿走，後面的伏筆就全斷了。」他低聲說。
潮氣從破窗灌進來，像一條看不見的河。`;

const SAMPLE_OUTLINE_EVENTS = [
  { event_id: "event_01", description: "林默抵達霧港倉庫，發現黑曜短刃", caused_by_event_id: "" },
  { event_id: "event_02", description: "他選擇暫不取走短刃，改以談判試探對方", caused_by_event_id: "event_01" },
];

/** Backend `pending_hitl_options` labels from graph.py / output_language_gate.py */
const BACKEND_PENDING_OPTIONS: Partial<Record<HitlReasonValue, Array<{ id: string; label: string }>>> = {
  [HITL_REASON.PLAN_LOOP]: [
    { id: "force_rewrite_plan", label: "強制重寫大綱" },
    { id: "force_approve_plan", label: "強制放行（以目前大綱進入 Author）" },
  ],
  [HITL_REASON.RESOLUTION_TACTIC]: [
    { id: "force_rewrite_plan", label: "重來一次（清空大綱重試計次）" },
    { id: "force_approve_plan", label: "強制放行（以目前大綱進入 Author）" },
  ],
  [HITL_REASON.ENDING_VIBE]: [
    { id: "force_rewrite_plan", label: "重來一次（清空大綱重試計次）" },
    { id: "force_approve_plan", label: "強制放行（以目前大綱進入 Author）" },
  ],
  [HITL_REASON.DRAFT_LOOP]: [
    { id: "keep_current_logic", label: "維持現有草稿（強制通過）" },
    { id: "relax_word_count", label: "退回重寫並放寬字數限制" },
  ],
  [HITL_REASON.EXTRACTION_GATE]: [{ id: "extraction_return_author", label: "退回 Author 改寫正文" }],
  [HITL_REASON.ANCHOR_RESOLVE]: [],
  [HITL_REASON.OUTPUT_LANGUAGE]: [
    { id: "language_return_author", label: "退回 Author 依設定語言重寫" },
    { id: "language_force_continue", label: "略過檢查並繼續彙總" },
  ],
  [HITL_REASON.CHAPTER_DRAFT_REVIEW]: [
    { id: "APPROVE_DRAFT", label: "通過（可修改）" },
    { id: "RERUN_KEEP_DIRECTOR", label: "保留劇情節點重跑" },
    { id: "ABANDON_CHAPTER", label: "放棄此次生成" },
  ],
};

const BACKEND_RESUME_FROM: Record<HitlReasonValue, string> = {
  [HITL_REASON.PLAN_LOOP]: "planner",
  [HITL_REASON.RESOLUTION_TACTIC]: "planner",
  [HITL_REASON.ENDING_VIBE]: "planner",
  [HITL_REASON.B_STORY_COOLDOWN]: "graph_rag",
  [HITL_REASON.DRAFT_LOOP]: "author",
  [HITL_REASON.EXTRACTION_GATE]: "extraction_gate",
  [HITL_REASON.B_STORY]: "anchor_resolve",
  [HITL_REASON.ANCHOR_RESOLVE]: "anchor_resolve",
  [HITL_REASON.CONTEXT]: "graph_rag",
  [HITL_REASON.ALIGNMENT_RULES_REQUIRED]: "logic_alignment",
  [HITL_REASON.OUTPUT_LANGUAGE]: "output_language_gate",
  [HITL_REASON.CHAPTER_DRAFT_REVIEW]: "chunker",
};

const BACKEND_DECISION_MODE: Partial<Record<HitlReasonValue, string>> = {
  [HITL_REASON.PLAN_LOOP]: "MANUAL_EDIT",
  [HITL_REASON.RESOLUTION_TACTIC]: "MANUAL_EDIT",
  [HITL_REASON.ENDING_VIBE]: "MANUAL_EDIT",
  [HITL_REASON.B_STORY_COOLDOWN]: "MANUAL_EDIT",
  [HITL_REASON.DRAFT_LOOP]: "DASHBOARD",
  [HITL_REASON.EXTRACTION_GATE]: "MANUAL_EDIT",
  [HITL_REASON.ANCHOR_RESOLVE]: "MANUAL_EDIT",
  [HITL_REASON.CONTEXT]: "MANUAL_EDIT",
  [HITL_REASON.ALIGNMENT_RULES_REQUIRED]: "MANUAL_EDIT",
  [HITL_REASON.OUTPUT_LANGUAGE]: "DASHBOARD",
  [HITL_REASON.CHAPTER_DRAFT_REVIEW]: "MANUAL_EDIT",
};

export const HITL_DEV_GRAPH: GraphSnapshot = {
  nodes: [
    { node_id: "char_001", node_type: "CHARACTER", canonical_name: "林默" },
    { node_id: "char_002", node_type: "CHARACTER", canonical_name: "沈青" },
    { node_id: "item_001", node_type: "ITEM", canonical_name: "黑曜短刃" },
    { node_id: "loc_001", node_type: "LOCATION", canonical_name: "霧港" },
  ],
  edges: [],
};

function pendingForReason(reason: HitlReasonValue): Array<{ id: string; label: string }> {
  return [...(BACKEND_PENDING_OPTIONS[reason] ?? [])];
}

function hitlContextForReason(reason: HitlReasonValue, state: Record<string, unknown>): HitlContextPayload {
  const draft = String(state.current_draft ?? state.best_draft_content ?? SAMPLE_DRAFT);

  if (reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED) {
    return {
      primary_issue: String(state.alignment_log ?? "").trim().slice(-400) || "邏輯對齊需要補充規則或調整大綱。",
      supervisor_feedbacks: ["計畫審核：節奏過快 → 放慢鋪陳"],
      conflict_notes: (state.human_outline_conflict_notes as string[]) ?? [],
      problematic_draft_snippet: draft.slice(0, 800),
      context_metadata: { payload_type: "alignment" },
    };
  }

  if (reason === HITL_REASON.EXTRACTION_GATE) {
    return {
      primary_issue: "抽取閘門未通過（連續 4 次失敗）；請綁定未知實體或放寬強制節點。",
      supervisor_feedbacks: [],
      conflict_notes: [],
      problematic_draft_snippet: draft.slice(0, 800),
      context_metadata: {
        payload_type: "extraction_remap",
        unknown_entities: (state.hitl_extraction_remap_hints as Array<Record<string, unknown>>) ?? [],
      },
    };
  }

  if (reason === HITL_REASON.DRAFT_LOOP) {
    return {
      primary_issue: "內文審核多次未過；請依退件理由修改正文或調整抽取提示後重試。",
      supervisor_feedbacks: ["字數不足 → 擴寫", "偏離大綱節拍 → 對齊 event_02"],
      conflict_notes: [],
      problematic_draft_snippet: draft.slice(0, 800),
      context_metadata: { payload_type: "draft_loop" },
    };
  }

  if (reason === HITL_REASON.CONTEXT) {
    return {
      primary_issue: "組裝上下文超過預算（估計約 128000 字元）；請選擇較激進的瘦身層級。",
      supervisor_feedbacks: [],
      conflict_notes: [],
      problematic_draft_snippet: "",
      context_metadata: { payload_type: "context_prune", graph_rag_context_tier: 1 },
    };
  }

  if (reason === HITL_REASON.CHAPTER_DRAFT_REVIEW) {
    return {
      primary_issue: "章節草稿已完成審核，請人類確認是否歸檔（後續會由編輯再潤飾）。",
      supervisor_feedbacks: [],
      conflict_notes: [],
      problematic_draft_snippet: draft.slice(0, 800),
      context_metadata: { payload_type: "chapter_review", reader_score: 88 },
    };
  }

  if (reason === HITL_REASON.OUTPUT_LANGUAGE) {
    return {
      primary_issue:
        String(state.hitl_output_language_detail ?? "").trim() ||
        "Chapter text may not match the configured story language (繁體中文).",
      supervisor_feedbacks: [],
      conflict_notes: [],
      problematic_draft_snippet: draft.slice(0, 800),
      context_metadata: {
        payload_type: "output_language",
        expected_output_language: "zh-Hant",
        language_detection_summary: "Latin 62% · CJK 35% · other 3%",
      },
    };
  }

  if (reason === HITL_REASON.ANCHOR_RESOLVE || reason === HITL_REASON.B_STORY) {
    return {
      primary_issue: "Resolver is uncertain about milestone achievement.",
      supervisor_feedbacks: [],
      conflict_notes: [],
      problematic_draft_snippet: draft.slice(0, 800),
      context_metadata: { payload_type: "generic" },
    };
  }

  if (reason === HITL_REASON.B_STORY_COOLDOWN) {
    return {
      primary_issue: "副線類型與近期章節撞期，請調整章節方向。",
      supervisor_feedbacks: [],
      conflict_notes: [],
      problematic_draft_snippet: "",
      context_metadata: { payload_type: "generic" },
    };
  }

  return {
    primary_issue: `流程暫停：${reason}`,
    supervisor_feedbacks: ["大綱與錨點衝突 → 調整事件或放寬條件"],
    conflict_notes: [],
    problematic_draft_snippet: draft.slice(0, 800),
    context_metadata: { payload_type: "generic" },
  };
}

function stateExtrasForReason(reason: HitlReasonValue): Record<string, unknown> {
  const base: Record<string, unknown> = {
    current_draft: SAMPLE_DRAFT,
    best_draft_content: SAMPLE_DRAFT,
  };

  switch (reason) {
    case HITL_REASON.PLAN_LOOP:
      return {
        ...base,
        ground_truth_events: SAMPLE_OUTLINE_EVENTS,
        narrative_script: "倉庫對峙：林默發現短刃但選擇談判，為後續奪刃伏筆留白。",
        plan_feedback: [{ violation: "ANCHOR", suggestion: "RELAX", message: "大綱與錨點「取得黑曜短刃」衝突：本章未取走短刃。" }],
        plan_warnings: ["[提醒] 第 6 章已使用類似倉庫對峙場景"],
      };
    case HITL_REASON.RESOLUTION_TACTIC:
      return {
        ...base,
        ground_truth_events: SAMPLE_OUTLINE_EVENTS,
        narrative_script: "以談判拖延收束，避免重複上一章的追逐戰。",
        recent_chapter_summaries: [
          { chapter_id: 5, resolution_method: "CHASE", ending_vibe: "tense" },
          { chapter_id: 6, resolution_method: "CHASE", ending_vibe: "rain" },
        ],
        plan_feedback: [
          {
            violation: "RESOLUTION_COOLDOWN_HARD_VIOLATION",
            message: "收尾方式「追逐」與近兩章重複。",
          },
        ],
      };
    case HITL_REASON.ENDING_VIBE:
      return {
        ...base,
        ground_truth_events: SAMPLE_OUTLINE_EVENTS,
        narrative_script: "雨夜倉庫收束，情緒基調偏沉。",
        recent_chapter_summaries: [
          { chapter_id: 5, resolution_method: "NEGOTIATION", ending_vibe: "rain_warehouse" },
          { chapter_id: 6, resolution_method: "STANDOFF", ending_vibe: "rain_warehouse" },
        ],
        plan_feedback: [
          {
            violation: "ENDING_VIBE_COOLDOWN_HARD_VIOLATION",
            message: "結尾氛圍 rain_warehouse 與近兩章過於接近。",
          },
        ],
      };
    case HITL_REASON.B_STORY_COOLDOWN:
      return {
        ...base,
        b_story_type: "MYSTERY_THREAD",
        b_story_directive: "延續「霧港密碼」副線，本章以試探性對話推進",
        narrative_directive: "主線：倉庫對峙；副線：密碼線索只露一半",
        recent_b_story_types: ["MYSTERY_THREAD", "ROMANCE_BEAT"],
      };
    case HITL_REASON.DRAFT_LOOP:
      return {
        ...base,
        draft_feedback: [
          {
            attempt: 4,
            violation: "LENGTH",
            message: "正文長度低於目標約 35%，且 event_02 節拍未落地。",
          },
        ],
        reader_feedback: [{ score: 62, message: "節奏偏慢，收束不夠有力。" }],
      };
    case HITL_REASON.EXTRACTION_GATE:
      return {
        ...base,
        extraction_gate_failure_streak: 4,
        planned_graph_nodes: [
          { node_id: "item_001", node_type: "ITEM", canonical_name: "黑曜短刃" },
          { node_id: "char_001", node_type: "CHARACTER", canonical_name: "林默" },
        ],
        hitl_extraction_remap_hints: [
          {
            missing_planned_node_id: "item_001",
            planned_canonical_name: "黑曜短刃",
            candidate_extracted: [
              { node_id: "ghost_item_aaa", canonical_name: "黑曜短刃" },
              { node_id: "ghost_item_bbb", canonical_name: "曜黑匕首" },
            ],
          },
          {
            missing_planned_node_id: "char_001",
            planned_canonical_name: "林默",
            candidate_extracted: [
              { node_id: "ghost_char_ccc", canonical_name: "林默" },
              { node_id: "ghost_char_ddd", canonical_name: "阿默" },
            ],
          },
        ],
        draft_feedback: [{ message: "抽取對照：文中「曜黑匕首」無法對應設定表。" }],
      };
    case HITL_REASON.ANCHOR_RESOLVE:
      return {
        ...base,
        anchor_nodes: [
          {
            id: "anchor_get_obsidian_dagger",
            title: "取得黑曜短刃",
            description: "主角在本章結尾前應確實取得或帶走黑曜短刃，作為後續伏筆的關鍵道具。",
            node_kind: "CHECKPOINT",
            status: "ACTIVE",
          },
        ],
        selected_anchor_ids: ["anchor_get_obsidian_dagger"],
        anchor_resolution_hitl_candidate: {
          resolution_analysis:
            "系統評估：正文提到發現短刃，但主角未帶走，無法自動判定里程碑是否達成。",
          resolved_anchor_ids: [],
          unresolved_anchor_ids: ["anchor_get_obsidian_dagger"],
          chapter_matches_plan: false,
          evidence_summary: [
            {
              anchor_id: "anchor_get_obsidian_dagger",
              reasoning: "草稿描寫找到短刃但未取走，與「取得」定義有落差。",
            },
          ],
          decision_reason: "Ambiguous: found vs obtained/kept.",
          resolver_confidence: 0.42,
          requires_human_review: true,
        },
      };
    case HITL_REASON.B_STORY:
      return {
        ...base,
        b_story_resolution_hitl_candidate: {
          title: "霧港密碼副線",
          id: "b_story_mystery_01",
          decision_reason: "系統無法判定副線是否收束。",
        },
      };
    case HITL_REASON.CONTEXT:
      return {
        ...base,
        context_overflow_char_estimate: 128000,
        graph_rag_context_tier: 1,
      };
    case HITL_REASON.ALIGNMENT_RULES_REQUIRED:
      return {
        ...base,
        chapter_hard_rules: "",
        alignment_log:
          "[HITL_REQUEST] 偵測到高複雜智鬥：缺少可執行回合規則。\n需要：勝負條件、籌碼、判定流程。",
        human_outline_conflict_notes: ["倉庫談判與第 3 章賭局規則可能衝突"],
        chapter_outline: "林默與對方在倉庫進行三回合心理博弈，以密碼換取短刃情報。",
        plan_feedback: [{ message: "智鬥場景需補充硬性規則後才能對齊。" }],
      };
    case HITL_REASON.OUTPUT_LANGUAGE:
      return {
        ...base,
        current_draft: "Lin Mo paused at the warehouse door. 「這把刀不能現在拿走。」",
        hitl_output_language_detail: "專案設定為繁體中文，但正文拉丁字母比例偏高。",
        hitl_expected_output_language: "zh-Hant",
      };
    case HITL_REASON.CHAPTER_DRAFT_REVIEW:
      return {
        ...base,
        last_reader_score: 88,
        require_chapter_review: true,
      };
    default:
      return base;
  }
}

/** All injectable HITL reasons with human-readable labels for the dev picker. */
export const HITL_DEV_SCENARIOS = HITL_REASON_MATRIX.map((row) => ({
  reason: row.reason as HitlReasonValue,
  title: row.title,
  optionIds: row.optionIds,
  solutionIds: row.solutionIds,
}));

export function buildHitlDevPayload(reason: HitlReasonValue, prev: WorkflowPayload | null): HitlDevPayload {
  const runId = prev?.run.run_id?.startsWith("dev_") ? prev.run.run_id : `dev_hitl_${reason}`;
  const storyId = prev?.run.story_id?.trim() || MOCK_STORY_ID;
  const chapterId = prev?.run.chapter_id ?? MOCK_CHAPTER_ID;
  const pending = pendingForReason(reason);
  const stateExtras = stateExtrasForReason(reason);
  const resumeFrom = BACKEND_RESUME_FROM[reason] ?? "author";
  const decisionMode = BACKEND_DECISION_MODE[reason] ?? (pending.length ? "CHOICE" : "MANUAL_EDIT");

  const state: Record<string, unknown> = {
    ...(prev?.state ?? {}),
    workflow_status: "WAITING_HITL",
    requires_hitl: true,
    hitl_reason: reason,
    resume_from: resumeFrom,
    pending_hitl_options: pending,
    ...stateExtras,
  };

  const hitl_context = hitlContextForReason(reason, state);

  const workflow: WorkflowPayload = {
    run: {
      ...(prev?.run ?? {
        run_id: runId,
        story_id: storyId,
        chapter_id: chapterId,
        status: "WAITING_HITL",
        requires_hitl: true,
        hitl_reason: reason,
        hitl_decision_mode: decisionMode,
        hitl_context,
      }),
      run_id: runId,
      story_id: storyId,
      chapter_id: chapterId,
      status: "WAITING_HITL",
      requires_hitl: true,
      hitl_reason: reason,
      hitl_decision_mode: decisionMode,
      hitl_context,
    },
    state,
    steps: prev?.steps ?? [],
  };

  const graph = reason === HITL_REASON.EXTRACTION_GATE ? HITL_DEV_GRAPH : undefined;
  return { workflow, graph };
}

/** Slug keys for `window.__NB_SET_WORKFLOW_MOCK(name)`. */
export const HITL_DEV_MOCK_SLUGS: Record<string, HitlReasonValue> = {
  plan_loop: HITL_REASON.PLAN_LOOP,
  resolution_tactic: HITL_REASON.RESOLUTION_TACTIC,
  ending_vibe: HITL_REASON.ENDING_VIBE,
  b_story_cooldown: HITL_REASON.B_STORY_COOLDOWN,
  draft_loop: HITL_REASON.DRAFT_LOOP,
  extraction_gate: HITL_REASON.EXTRACTION_GATE,
  anchor_resolve: HITL_REASON.ANCHOR_RESOLVE,
  b_story: HITL_REASON.B_STORY,
  context: HITL_REASON.CONTEXT,
  alignment_rules: HITL_REASON.ALIGNMENT_RULES_REQUIRED,
  output_language: HITL_REASON.OUTPUT_LANGUAGE,
  chapter_draft_review: HITL_REASON.CHAPTER_DRAFT_REVIEW,
};

export function buildHitlDevPayloadBySlug(slug: string, prev: WorkflowPayload | null): HitlDevPayload | null {
  const reason = HITL_DEV_MOCK_SLUGS[slug];
  if (!reason) return null;
  return buildHitlDevPayload(reason, prev);
}
