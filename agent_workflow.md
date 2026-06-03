# Agent Workflow（使用者操作版）

> 英文版請見 [agent_workflow.en.md](./agent_workflow.en.md)。

## 這份文件在講什麼

這份文件用「你要怎麼操作系統」的角度，說明 NovelBuilder 目前的章節工作流：

- 你在開跑前要準備什麼
- agent 會怎麼接力
- 什麼情況會停在 HITL（人工介入）
- 最後哪些資料會被寫入

本文以目前程式實作為準（`backend/app/services/workflow/graph.py` 與 `service.py`）。

---

## 0) 開跑前你要知道的事

### 必要前提

1. 先有 `story`（標題、premise、目標字數等）
2. 建議先完成 macro 規劃（卷、錨點、初始 cast）
3. 再執行章節 run

### 啟動章節 run 時可帶的關鍵參數

- `chapter_outline`：你的人類大綱
- `chapter_hard_rules`：本章硬規則（不能違反）
- `ai_freedom_level`：`strict` / `balanced` / `wild`
- `selected_anchor_ids`、`next_anchor_ids`：若你要指定錨點路線
- `extraction_surface_hints`：你想提示抽取器的字面線索（可選）

### 重要限制

- 若該章已是 `completed`，不能再跑完整 agent pipeline
- 若故事已經有 workflow run，部分 story 設定與 macro 拓樸不可再改

---

## 1) 你看到的主流程（章節）

目前主路徑如下：

1. `director`
2. `graph_rag`
3. `planner`
4. `plan_supervisor`
5. `logic_alignment`
6. `author`
7. `draft_supervisor`
8. `reader`
9. `extraction_gate`
10. `copyeditor`（若啟用）
11. `output_language_gate`
12. `chapter_summarizer`
13. `anchor_resolve`
14. `profile_expander`
15. `state_updater`
16. `commit_to_databases`

若任一節點判定需要人工介入，流程會轉到 `hitl` 並暫停。

---

## 2) 每個 agent 在做什麼（使用者可理解版）

下列 JSON 為**代表性範例**（長文以 `…` 省略；實際值依故事／章節而異）。結構化 LLM 輸出對應 `backend/app/domain/schema.py`；workflow state 欄位見 `backend/app/domain/state.py`。

---

### `director`（定調與導演指令）

- 產出本章方向：章節類型、敘事指令、副線意圖、新元素引入等
- 若使用者已預選 `selected_anchor_ids`，會略過 LLM，只寫入 bypass 說明
- 若踩到副線冷卻規則（最近用過的類型又被選中），會直接進 HITL

**輸入（workflow state 摘要）**

| 欄位 | 說明 |
|------|------|
| `story_id`, `chapter_id` | 故事與章節 |
| `anchor_nodes`, `anchor_candidates`, `resolved_anchors` | 錨點拓樸 |
| `selected_anchor_ids`（可選） | 使用者預選時跳過 LLM |
| `bible_context` | 若空則由 `BibleService.compile_full_context` 補齊 |

**輸入範例**

```json
{
  "story_id": "story_abc",
  "chapter_id": 3,
  "pov_character_id": "char_lin",
  "anchor_candidates": ["anchor_market", "anchor_reveal"],
  "resolved_anchors": ["anchor_intro"],
  "anchor_nodes": [
    {"id": "anchor_market", "title": "夜市衝突", "description": "…"}
  ],
  "bible_context": "## World lore\n…\n## User bible appendix\n{…}"
}
```

**輸出（寫回 state）**

`DirectorOutput` 欄位 + `director_state_brief`、`tone_direction`、`chapter_type` 等；可能帶 HITL 旗標。

**輸出範例**

```json
{
  "chapter_id": 3,
  "active_epoch_id": "epoch_present",
  "pov_character_id": "char_lin",
  "narrative_directive": "推進至夜市錨點：讓主角在群眾壓力下做出不可逆選擇。",
  "tone_direction": "緊繃、壓抑的懸疑",
  "target_anchor_id": "anchor_market",
  "chapter_type": "PLOT_DRIVEN",
  "selected_anchor_ids": ["anchor_market"],
  "next_anchor_ids": ["anchor_reveal"],
  "b_story_directive": null,
  "b_story_type": null,
  "new_elements_to_introduce": [],
  "request_new_b_story": null,
  "state_operational_brief": "本章鎖定 anchor_market；副線暫停；注意上一章尾聲地點銜接。"
}
```

---

### `graph_rag`（組上下文，不寫文）

- 整合 **完整 `bible_context`**（`general_world_lore` + 使用者 `bible_json` 附錄 + `macro_author_notes`，章節啟動時寫入 state，不截斷）/ graph / vector / 章節連續性上下文
- 對本章 `selected_anchor_ids`（不含 `next_anchor_ids`）做 GraphRAG 錨點前置評估，結果併入 `graph_context`；若上一章 `anchor_resolve` 已判定未達成，沿用快取不重跑 evaluate
- 若上下文長度超預算，觸發 HITL（`CONTEXT_LENGTH_EXCEEDED`）

**輸入（workflow state 摘要）**

| 欄位 | 說明 |
|------|------|
| `narrative_directive`, `pov_character_id`, `active_epoch_id` | 查詢與 POV |
| `selected_anchor_ids` | 錨點前置評估 |
| `bible_context` | 可沿用章節啟動時寫入的完整本 |

**輸入範例**

```json
{
  "story_id": "story_abc",
  "chapter_id": 3,
  "active_epoch_id": "epoch_present",
  "pov_character_id": "char_lin",
  "narrative_directive": "推進至夜市錨點…",
  "selected_anchor_ids": ["anchor_market"],
  "chapter_outline": "主角抵達夜市後遭遇盤查…",
  "graph_rag_context_tier": 2
}
```

**輸出（寫回 state）**

無 LLM JSON schema；回傳上下文字串與 cast 視圖、連續性包。

**輸出範例**

```json
{
  "pov_character_id": "char_lin",
  "bible_context": "## World lore\n…",
  "graph_context": "[GraphRAG] 相關節點與關係…",
  "vector_context": "{\"hits\":[…],\"policy\":\"…\"}",
  "chunk_context": "對齊的 chunk 摘要…",
  "local_enforced_rules_context": "【地點規則】夜市禁火…",
  "previous_chapter_summary": "上一章結尾：林在巷口被跟蹤。",
  "recent_chapter_context": "近兩章摘要…",
  "continuity_notes": ["林左臂傷未癒"],
  "last_known_location": "舊城巷口",
  "cast_slim_view": [
    {"node_id": "char_lin", "name": "林默", "personality": "內斂", "speech_style": "短句"}
  ],
  "anchor_preflight_evaluations": [
    {"anchor_id": "anchor_market", "resolved": false, "confidence": 0.42, "reasoning": "…"}
  ],
  "context_overflow_char_estimate": 18500,
  "context_hitl_required": false,
  "graph_rag_context_tier": 2
}
```

---

### `planner`（生成可執行劇情計畫）

- 輸出事件、敘事腳本、必帶節點、字數目標
- 會寫入 `planned_graph_nodes`（來自 `proposed_new_nodes`）與 `pending_cast_evolutions`
- LLM 輸入為 `SafePlannerPayload`（`masking.build_planner_payload`）

**輸入範例（`SafePlannerPayload`）**

```json
{
  "active_epoch_id": "epoch_present",
  "pov_character_id": "char_lin",
  "narrative_directive": "推進至夜市錨點…",
  "bible_context": "## World lore\n…",
  "graph_context": "[GraphRAG] …",
  "vector_context": "{\"hits\":[]}",
  "previous_chapter_summary": "上一章結尾…",
  "selected_anchor_ids": ["anchor_market"],
  "chapter_type": "PLOT_DRIVEN",
  "default_chapter_words": 3200,
  "chapter_word_min": 800,
  "chapter_word_max": 12000,
  "prior_feedback": []
}
```

**輸出範例（`PlannerOutput` → 併入 state）**

```json
{
  "ground_truth_events": [
    {
      "event_id": "ch3_e1",
      "description": "林在夜市入口被盤查，被迫出示通行證。",
      "caused_by_event_id": null,
      "links": [],
      "is_ai_invention": false
    }
  ],
  "narrative_script": "開場承接巷口跟蹤；進入夜市盤查線…",
  "target_word_count": 3200,
  "chapter_start_location": "舊城夜市入口",
  "must_include_beats": ["盤查升級為公開對峙"],
  "ending_state_shift": "林被迫在眾目下站隊。",
  "ending_boundary_rule": "不得寫入離開夜市後的場景。",
  "author_safe_continuity_notes": ["左臂傷影響動作"],
  "proposed_new_nodes": [],
  "character_evolution_requests": [],
  "planned_graph_nodes": []
}
```

---

### `plan_supervisor`（審核 planner）

- 判斷通過/不通過
- 不通過會回 `planner` 重試；超過上限進 HITL（`PLAN_LOOP_EXCEEDED`）
- LLM 輸入為 `SafeSupervisorPayload`（精簡版送 prompt）

**輸入範例（`SafeSupervisorPayload` 摘要）**

```json
{
  "chapter_id": 3,
  "ground_truth_events": [{"event_id": "ch3_e1", "description": "…"}],
  "narrative_script": "開場承接…",
  "must_include_beats": ["盤查升級為公開對峙"],
  "target_word_count": 3200,
  "selected_anchor_ids": ["anchor_market"],
  "bible_context": "## World lore\n…"
}
```

**輸出範例（`PlanSupervisorOutput`）**

```json
{
  "is_approved": true,
  "violation_type": ["NONE"],
  "suggestion_type": "NONE",
  "feedback_to_agent": "",
  "anchor_achieved": false,
  "soft_warnings": ["結尾 vibe 偏靜態，請確認與 ending_boundary_rule 一致"]
}
```

---

### `logic_alignment`（規則與設定對齊）

- 檢查大綱、規則、設定是否衝突
- 會把衝突寫入 `human_outline_conflict_notes` / `plan_warnings`
- 無法安全放行時進 HITL（`ALIGNMENT_RULES_REQUIRED`）
- 無 `chapter_hard_rules` 且無需 canon 稽核時可跳過 LLM

**輸入範例**

```json
{
  "chapter_id": 3,
  "pov_character_id": "char_lin",
  "chapter_hard_rules": "本章不可揭露「真兇身分」。林不可使用未習得的火系法術。",
  "chapter_outline": "夜市盤查→對峙→被迫站隊",
  "draft_ground_truth_events": [{"event_id": "ch3_e1", "description": "…"}],
  "draft_narrative_script": "開場承接…"
}
```

**輸出範例（`AlignmentOutput` → state 對應欄位）**

```json
{
  "final_ground_truth_events": [{"event_id": "ch3_e1", "description": "…"}],
  "final_narrative_script": "開場承接…（對齊後）",
  "final_must_include_beats": ["盤查升級為公開對峙"],
  "safe_chapter_rules": "【POV 安全規則】本章不可揭露真兇身分…",
  "alignment_log": "已遮蔽 POV 不可知資訊；無需改寫事件鏈。",
  "human_outline_conflict_notes": [],
  "requires_hitl": false,
  "hitl_reason": null
}
```

寫回 state 時另含：`safe_chapter_rules`、`human_outline_conflict_notes`；通過時可能覆寫 `ground_truth_events`、`narrative_script`、`must_include_beats`。

---

### `author`（產正文）

- 依規劃寫出章節草稿（`current_draft`）；prompt 強調**人物活動／心理合理性**（不可為趕 beat 跳過過渡）
- 可使用 **`graph_rag_ask` tool**（每章最多 4 次）查證傷勢、關係、已知事實後再寫關鍵行動
- 讀取完整 `bible_context`（不截斷）
- 同時產出 `author_extraction_surface_hints` 供後續抽取 gate 使用；可選診斷 `author_graph_rag_queries`

**輸入範例（`SafeAuthorPayload` 摘要）**

```json
{
  "narrative_script": "開場承接…",
  "must_include_beats": ["盤查升級為公開對峙"],
  "tone_direction": "緊繃、壓抑的懸疑",
  "target_word_count": 3200,
  "normalized_length_min": 2880,
  "normalized_length_max": 3520,
  "bible_context": "## World lore\n…\n## User bible appendix\n{…}",
  "safe_chapter_rules": "不可揭露真兇…",
  "author_safe_continuity_notes": ["左臂傷影響動作"],
  "active_character_profiles": [{"name": "林默", "personality": "內斂"}],
  "draft_feedback": [],
  "length_adjustment": "NONE"
}
```

**輸出範例（`AuthorOutput` → state）**

```json
{
  "chapter_content": "第3章\n\n林在巷口的腳步還沒穩，夜市的人聲已經壓過來…",
  "word_count": 3156,
  "extraction_surface_hints": [
    {"node_id": "char_lin", "surface_forms": ["林默", "林"]},
    {"node_id": "loc_night_market", "surface_forms": ["夜市"]}
  ],
  "current_draft": "（同上 chapter_content）",
  "author_extraction_surface_hints": [{"node_id": "char_lin", "surface_forms": ["林默", "林"]}],
  "author_graph_rag_queries": [
    {"question": "林左臂傷是否仍限制舉臂？", "answer_snippet": "…"}
  ]
}
```

---

### `draft_supervisor`（草稿硬檢）

- 檢查字數、規格與必要條件
- 另審 **人物合理性／節奏**（開章銜接、行動鏈、心理鏈、急推劇情、結尾過程）— 與 Author 規則鏡像
- 不通過退回 `author`（`draft_feedback` 需指出缺哪類過渡）
- 連續失敗超限進 HITL（`DRAFT_LOOP_EXCEEDED`）

**輸入範例（`SafeSupervisorPayload` + `current_draft`）**

```json
{
  "chapter_id": 3,
  "current_draft": "第3章\n\n林在巷口的腳步…",
  "normalized_current_draft_length": 3156,
  "target_word_count": 3200,
  "normalized_length_min": 2880,
  "normalized_length_max": 3520,
  "must_include_beats": ["盤查升級為公開對峙"],
  "ending_boundary_rule": "不得寫入離開夜市後的場景。",
  "active_character_profiles": [{"name": "林默"}],
  "author_safe_continuity_notes": ["左臂傷影響動作"],
  "ending_state_shift": "林被迫在眾目下站隊。"
}
```

**輸出範例（`DraftSupervisorOutput` + 路由欄位）**

```json
{
  "is_approved": false,
  "violation_type": ["INCONSISTENCY"],
  "suggestion_type": "REWRITE",
  "feedback_to_agent": "盤查升級前缺少林的心理猶豫與肢體過渡；請補 1–2 段再進入對峙。",
  "length_adjustment": "NONE",
  "draft_route": "author",
  "draft_feedback": [
    {
      "attempt": 1,
      "violation": ["INCONSISTENCY"],
      "suggestion": "REWRITE",
      "length_adjustment": "NONE",
      "message": "盤查升級前缺少…"
    }
  ]
}
```

---

### `reader`（可讀性審核）

- 做文學分數與評論（**不**審字數）
- 通過後進 `chapter_review_gate`（可選人工審稿）→ `chunker` → …
- 未通過則回 `author`；若迴圈太多次，會採用 `best_draft_content` 繼續

**輸入範例**

```json
{
  "current_draft": "第3章\n\n林在巷口的腳步…（全文送 prompt，實作截斷約 6000 字）"
}
```

**輸出範例（`ReaderOutput` + 路由）**

```json
{
  "is_approved": true,
  "literary_score": 72,
  "suggestion_type": "NONE",
  "critique": "節奏穩，對峙張力足；可增加夜市感官細節。",
  "best_draft_score": 72,
  "best_draft_content": "第3章\n\n…",
  "reader_route": "chapter_review_gate"
}
```

---

### `extraction_gate`（定稿抽取與實體對齊閘門）

- 前置：`chunker` 產 `chapter_chunks`；`vectorize_chunks` 將 `current_body` chunks 寫入向量庫
- 對定稿文本做抽取與 mandatory 節點對齊
- 失敗退回 `author`；連續失敗達門檻進 HITL（`EXTRACTION_GATE_FAILED`）

**輸入範例**

```json
{
  "story_id": "story_abc",
  "chapter_id": 3,
  "current_draft": "第3章\n\n…",
  "best_draft_content": "第3章\n\n…",
  "ground_truth_events": [{"event_id": "ch3_e1", "description": "…"}],
  "planned_graph_nodes": [
    {"node_id": "char_guard_captain", "node_type": "CHARACTER", "canonical_name": "巡邏隊長", "mandatory": true}
  ],
  "author_extraction_surface_hints": [
    {"node_id": "char_guard_captain", "surface_forms": ["巡邏隊長"]}
  ],
  "chapter_chunks": [
    {"chunk_id": "ch3_c0", "source_role": "current_body", "text_chunk": "…"}
  ]
}
```

**輸出範例（成功）**

```json
{
  "extraction_route": "continue",
  "pending_chapter_extraction": {
    "chapter_memory": {
      "summary": "林在夜市被盤查並被迫站隊。",
      "unresolved_threads": ["真兇身分仍未揭露"],
      "notable_entities": ["林默", "巡邏隊長"],
      "latest_location": "舊城夜市"
    },
    "entities": [
      {
        "node_id": "char_lin",
        "node_type": "CHARACTER",
        "canonical_name": "林默",
        "aliases": ["林"],
        "summary": "…"
      }
    ],
    "relations": []
  },
  "last_chapter_extraction_metrics": {
    "mandatory_mapping_ok": true,
    "entities_final": 4,
    "relations_final": 2
  }
}
```

**輸出範例（失敗 → 退回 author）**

```json
{
  "extraction_route": "author",
  "pending_chapter_extraction": {},
  "extraction_gate_feedback_entry": {
    "attempt": 2,
    "violation": ["MISSING_MANDATORY_ENTITY_MAPPING"],
    "suggestion": "REWRITE",
    "message": "正文未出現必帶節點：巡邏隊長（char_guard_captain）"
  },
  "hitl_extraction_remap_hints": [
    {"planned_node_id": "char_guard_captain", "suggested_surface": "巡邏隊長"}
  ]
}
```

---

### `copyeditor`（可選）

- 若 `copyeditor_enabled`，潤修 `best_draft_content` / `current_draft`
- 輸出為純文字（非 JSON schema）

**輸入範例**

```json
{
  "chapter_id": 3,
  "current_draft": "第3章\n\n林在巷口…",
  "best_draft_content": "第3章\n\n林在巷口…"
}
```

**輸出範例**

```json
{
  "current_draft": "第3章\n\n林在巷口，腳步尚未穩住，夜市的人聲已經壓過來…",
  "best_draft_content": "第3章\n\n林在巷口，腳步尚未穩住，夜市的人聲已經壓過來…"
}
```

---

### `output_language_gate`（語言一致性閘門）

- 啟發式檢查草稿語言是否與 `output_language` 一致（Mock 管線略過）
- 不符時進 HITL

**輸入範例**

```json
{
  "current_draft": "第3章\n\n林在巷口…",
  "output_language_hitl_waived": false
}
```

**輸出範例（通過）**

```json
{
  "language_gate_route": "chapter_summarizer",
  "hitl_output_language_detail": "",
  "hitl_expected_output_language": ""
}
```

**輸出範例（需 HITL）**

```json
{
  "requires_hitl": true,
  "hitl_reason": "OUTPUT_LANGUAGE_MISMATCH",
  "language_gate_route": "hitl",
  "hitl_output_language_detail": "CJK ratio about 12%…",
  "hitl_expected_output_language": "zh-TW",
  "pending_hitl_options": [
    {"id": "language_return_author", "label": "退回 Author 依設定語言重寫"},
    {"id": "language_force_continue", "label": "略過檢查並繼續彙總"}
  ]
}
```

---

### `chapter_summarizer`（章節摘要）

- LLM 產 `ChapterSummaryOutput` 後 **寫入 DB**（`chapter_summaries`）
- workflow node 主要更新 `last_agent`；摘要不在 state 長期保存

**輸入範例**

```json
{
  "story_id": "story_abc",
  "chapter_id": 3,
  "best_draft_content": "第3章\n\n…",
  "ground_truth_events": [{"event_id": "ch3_e1", "description": "…"}],
  "narrative_directive": "推進至夜市錨點…"
}
```

**輸出範例（LLM：`ChapterSummaryOutput`）**

```json
{
  "plot_summary": "林在夜市遭盤查並被迫公開站隊，懸念推向下一錨點。",
  "conflict_type": "SOCIAL",
  "resolution_method": "STALEMATE",
  "ending_vibe": "ON_THE_MOVE"
}
```

**輸出範例（`persist_chapter_summary` 回傳）**

```json
{
  "written": true,
  "plot_summary": "林在夜市遭盤查…",
  "plot_summary_source": "CHAPTER_SUMMARIZER_LLM",
  "regenerated_llm": true
}
```

---

### `anchor_resolve`（錨點達成判定）

- 對 `selected_anchor_ids` 做 GraphRAG evaluate（或 Mock 規則）
- 更新 `resolved_anchors`、`anchor_candidates`、`anchor_nodes`
- 低信心時 `anchor_hitl_required` → HITL

**輸入範例**

```json
{
  "selected_anchor_ids": ["anchor_market"],
  "anchor_nodes": [{"id": "anchor_market", "title": "夜市衝突", "status": "ACTIVE"}],
  "resolved_anchors": [],
  "current_draft": "第3章\n\n…"
}
```

**輸出範例（`AnchorResolutionOutput` + 拓樸更新）**

```json
{
  "anchor_resolution": {
    "resolution_analysis": "正文完成盤查對峙與站隊，符合 anchor_market 描述。",
    "resolved_anchor_ids": ["anchor_market"],
    "unresolved_anchor_ids": [],
    "chapter_matches_plan": true,
    "evidence_summary": [
      {"anchor_id": "anchor_market", "resolved": true, "confidence": 0.81, "reasoning": "…"}
    ],
    "resolver_confidence": 0.81,
    "requires_human_review": false
  },
  "resolved_anchors": ["anchor_market"],
  "anchor_candidates": ["anchor_reveal"],
  "anchor_hitl_required": false,
  "anchor_route": "profile_expander"
}
```

---

### `profile_expander`（角色資料補齊與演化）

- 合併 `planned_graph_nodes` 與抽取實體的新角色
- 套用 `pending_cast_evolutions` 至 cast

**輸入範例**

```json
{
  "planned_graph_nodes": [
    {
      "node_id": "char_guard_captain",
      "node_type": "CHARACTER",
      "canonical_name": "巡邏隊長",
      "character_profile": {"personality": "嚴苛", "speech_style": "命令句"}
    }
  ],
  "pending_chapter_extraction": {
    "entities": [{"node_id": "char_guard_captain", "node_type": "CHARACTER", "canonical_name": "巡邏隊長"}]
  },
  "pending_cast_evolutions": [
    {
      "node_id": "char_lin",
      "personality_delta": "對權威更警惕",
      "speech_style_delta": "",
      "source": "planner",
      "reason": "夜市羞辱事件"
    }
  ]
}
```

**輸出範例**

```json
{
  "pending_cast_updates": [
    {
      "update_mode": "fill_empty",
      "member": {
        "node_id": "char_guard_captain",
        "canonical_name": "巡邏隊長",
        "personality": "嚴苛",
        "speech_style": "命令句"
      }
    },
    {
      "update_mode": "evolution",
      "member": {"node_id": "char_lin", "personality": "內斂、對權威更警惕"},
      "milestone": {"chapter_id": 3, "reason": "夜市羞辱事件"}
    }
  ],
  "pending_cast_evolutions": []
}
```

---

### `state_updater`（組提交封包）

- 依 `pending_chapter_extraction` 與 `ground_truth_events` 組 graph mutations 與 vector documents
- graph node 寫入 `state_updater_output` 與 `pending_db_commit`

**輸入範例**

```json
{
  "story_id": "story_abc",
  "chapter_id": 3,
  "active_epoch_id": "epoch_present",
  "pov_character_id": "char_lin",
  "best_draft_content": "第3章\n\n…",
  "ground_truth_events": [{"event_id": "ch3_e1", "description": "…"}],
  "pending_chapter_extraction": {
    "entities": [{"node_id": "char_lin", "node_type": "CHARACTER", "canonical_name": "林默"}],
    "relations": [],
    "chapter_memory": {"summary": "…", "latest_location": "舊城夜市"}
  },
  "chapter_chunks": [{"chunk_id": "ch3_c0", "source_role": "current_body", "text_chunk": "…"}]
}
```

**輸出範例（`StateUpdaterOutput`）**

```json
{
  "mutations": [
    {
      "action": "CREATE_NODE",
      "node_id": "evt_ch3_memory",
      "node_type": "EVENT",
      "properties": {"canonical_name": "林在夜市被盤查並被迫站隊"}
    },
    {
      "action": "CREATE_EDGE",
      "relation_type": "LOCATED_IN",
      "source_id": "char_lin",
      "target_id": "loc_night_market",
      "attributes": {"epoch_id": "epoch_present"}
    }
  ],
  "vector_documents": [
    {
      "text_chunk": "林在巷口的腳步…",
      "metadata": {
        "chunk_id": "ch3_c0",
        "chapter_id": 3,
        "epoch_id": "epoch_present",
        "location_id": "loc_night_market",
        "characters_involved": ["char_lin"]
      }
    }
  ]
}
```

**graph node 額外寫入**

```json
{
  "state_updater_output": { "mutations": [], "vector_documents": [] },
  "pending_db_commit": {
    "state_updater_output": { "mutations": [], "vector_documents": [] },
    "chapter_title": "第3章",
    "chapter_content": "第3章\n\n…"
  }
}
```

---

### `commit_to_databases`（真正提交）

- 消費 `pending_db_commit`：Graph → Vector → SQLite 章節正文
- 套用 `pending_cast_updates`、合併 `resolved_anchors` 至 `story_runtime_json`
- 成功後 `workflow_status` → `COMPLETED`

**輸入範例**

```json
{
  "story_id": "story_abc",
  "chapter_id": 3,
  "pending_db_commit": {
    "state_updater_output": {"mutations": [], "vector_documents": []},
    "chapter_title": "第3章",
    "chapter_content": "第3章\n\n…"
  },
  "pending_cast_updates": [{"update_mode": "fill_empty", "member": {"node_id": "char_guard_captain"}}],
  "resolved_anchors": ["anchor_market"],
  "anchor_nodes": []
}
```

**輸出範例**

```json
{
  "workflow_status": "COMPLETED",
  "commit_executed": true,
  "state_transaction_id": "txn_01HXYZ…",
  "pending_db_commit": {},
  "last_agent": "commit_to_databases"
}
```

---

### 流程輔助節點（§1 未單列，但會執行）

| 節點 | 輸入要點 | 輸出要點 |
|------|----------|----------|
| `chapter_review_gate` | `require_chapter_review` | 通過 → `resume_from: chunker`；否則 HITL 三選項 |
| `chunker` | `best_draft_content` / `current_draft` | `chapter_chunks[]` |
| `vectorize_chunks` | `chapter_chunks`（僅 `current_body`） | 寫 Qdrant；`resume_from: extraction_gate` |

**`chunker` 輸出範例**

```json
{
  "chapter_chunks": [
    {
      "chunk_id": "ch3_prev_tail_0",
      "source_role": "prev_tail",
      "text_chunk": "（上一章尾段，供抽取對齊）"
    },
    {
      "chunk_id": "ch3_c0",
      "chunk_index": 0,
      "source_role": "current_body",
      "text_chunk": "林在巷口的腳步…"
    }
  ]
}
```

---

## 3) 你何時需要 HITL（人工介入）

常見原因（`hitl_reason`）：

- `CONTEXT_LENGTH_EXCEEDED`：上下文太大
- `PLAN_LOOP_EXCEEDED`：企劃反覆不過
- `DRAFT_LOOP_EXCEEDED`：草稿反覆不過
- `ALIGNMENT_RULES_REQUIRED`：規則/設定需要人工裁決
- `EXTRACTION_GATE_FAILED`：抽取/實體對齊連續失敗
- `ANCHOR_RESOLUTION_FAILED`：錨點判定需要人工裁決
- 其他冷卻規則違規（例如副線策略）

你在 HITL 常做的事：

- 選擇決策（繼續、退回、放寬限制）
- 直接編修大綱、草稿或 director 指令
- 注入狀態（規則、cast 演化、graph mutation）
- 指定 `resume_from` 從某節點繼續

---

## 4) 一次 run 結束後你會拿到什麼

- 章節正文（SQLite，狀態 `completed`）
- 該 run 的完整 steps、審核回饋、HITL 操作紀錄
- 更新後的圖譜與向量文件（供下一章檢索）
- 更新後的 bible 與 anchor/cast 狀態（供連載延續）

---

## 5) 建議的使用方式（實務）

1. 先給 `chapter_outline`，再補 `chapter_hard_rules`（不要混在一起寫）
2. 新專案先用 `balanced`，只有高控制需求再改 `strict`
3. 若常卡在 `extraction_gate`，優先補可辨識的人名/稱呼與實體描述
4. 真的卡住就用 HITL 明確指定 `resume_from`，不要盲目重跑整條鏈
5. 觀察 `plan_warnings` 與 `human_outline_conflict_notes`，那是最早期風險訊號
