import type { GraphSnapshot, WorkflowPayload } from "../types";

export type WorkflowMockEntry = {
  workflow: WorkflowPayload;
  graph?: GraphSnapshot;
};

export const WORKFLOW_MOCKS: Record<string, WorkflowMockEntry> = {
  extraction_gate: {
    graph: {
      nodes: [
        { node_id: "char_001", node_type: "CHARACTER", canonical_name: "林默" },
        { node_id: "char_002", node_type: "CHARACTER", canonical_name: "沈青" },
        { node_id: "item_001", node_type: "ITEM", canonical_name: "黑曜短刃" },
        { node_id: "loc_001", node_type: "LOCATION", canonical_name: "霧港" },
      ],
      edges: [],
    },
    workflow: {
      run: {
        run_id: "mock-run-extraction",
        story_id: "mock-story",
        chapter_id: 7,
        status: "WAITING_HITL",
        requires_hitl: true,
        hitl_reason: "Extraction_Gate_Failed",
        hitl_decision_mode: "MANUAL_EDIT",
        hitl_context: {
          primary_issue: "Found unmatched extracted entities during canon archive.",
          supervisor_feedbacks: ["Some names in draft don't map to planned canon nodes."],
          conflict_notes: [],
          problematic_draft_snippet:
            "「林默握住黑曜短刃」…但系統不確定『黑曜短刃』要不要對應到既有道具節點，或建立新節點。",
          context_metadata: { payload_type: "extraction_remap" },
        },
      },
      state: {
        workflow_status: "WAITING_HITL",
        resume_from: "extraction_gate",
        pending_hitl_options: [{ id: "extraction_return_author", label: "打回給 AI 重寫（叫它寫對名字）" }],
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
      },
      steps: [],
    },
  },
  draft_loop: {
    workflow: {
      run: {
        run_id: "mock-run-draft",
        story_id: "mock-story",
        chapter_id: 7,
        status: "WAITING_HITL",
        requires_hitl: true,
        hitl_reason: "Draft_Loop_Exceeded",
        hitl_decision_mode: "DASHBOARD",
        hitl_context: {
          primary_issue: "Draft repeatedly fails review thresholds.",
          supervisor_feedbacks: ["Word count too low", "Drifts from outline"],
          conflict_notes: [],
          problematic_draft_snippet: "……（節錄）",
          context_metadata: { payload_type: "draft_loop" },
        },
      },
      state: {
        workflow_status: "WAITING_HITL",
        resume_from: "author",
        pending_hitl_options: [
          { id: "keep_current_logic", label: "維持現有草稿（強制通過）" },
          { id: "relax_word_count", label: "放寬字數要求" },
        ],
        current_draft: "（把你要測的正文貼這裡）\n\n第二段……",
      },
      steps: [],
    },
  },
  anchor_resolve: {
    workflow: {
      run: {
        run_id: "mock-run-anchor",
        story_id: "mock-story",
        chapter_id: 7,
        status: "WAITING_HITL",
        requires_hitl: true,
        hitl_reason: "Anchor_Resolution_Failed",
        hitl_decision_mode: "DASHBOARD",
        hitl_context: {
          primary_issue: "Resolver is uncertain about milestone achievement.",
          supervisor_feedbacks: [],
          conflict_notes: [],
          problematic_draft_snippet:
            "林默終於在霧港的倉庫找到那把黑曜短刃，但他遲疑著沒有帶走……",
          context_metadata: { payload_type: "generic" },
        },
      },
      state: {
        workflow_status: "WAITING_HITL",
        resume_from: "anchor_resolve",
        pending_hitl_options: [],
        anchor_resolution_hitl_candidate: {
          anchor_title: "取得黑曜短刃",
          anchor_id: "anchor_get_obsidian_dagger",
          requires_human_review: true,
          resolver_confidence: 0.42,
          resolved_anchor_ids: ["anchor_get_obsidian_dagger"],
          unresolved_anchor_ids: [],
          evidence_summary: [
            { anchor_id: "anchor_get_obsidian_dagger", decision_reason: "Draft mentions finding the dagger." },
            { anchor_id: "anchor_get_obsidian_dagger", decision_reason: "But protagonist did not take it—ambiguity." },
          ],
          decision_reason: "Ambiguous: found vs obtained/kept.",
        },
      },
      steps: [],
    },
  },
};

