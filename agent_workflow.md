# Agent Workflow

## 文件目的

這份文件說明 NovelBuilder 在「生成單一章節小說」時，各個 agent 如何接力工作、彼此傳遞哪些資料、在哪些地方做審核，以及何時會進入 HITL。

本文盡量用人類技術人員可直接理解的流程描述，而不是程式碼細節。

## 系統分成兩個層級

### 1. Macro Planning

這一層負責先把整個故事拆成：

- `volumes`：卷級規劃（LLM 輸出為**每卷內嵌** `anchors` 陣列）
- 正規化後仍會展平成 SQLite 的 `anchors` 表，每筆帶 `volume_id`

**契約**：每一卷需 **3–5** 個錨點；各錨點的 `chapter_target` 必須落在該卷章節範圍內。若模型給太少，後端會補位；給太多則截到 5 個。

主要輸入：

- 故事標題
- premise
- bible / 世界規則
- 目標總字數

主要輸出：

- 每一卷的標題、摘要、章節範圍、字數預算
- 每個 anchor 的標題、描述、目標狀態、預計章節（存庫時依章節／優先序排序編號）
- **`cast`**：至少一名 **protagonist** 與可選 **supporting**；後端指派穩定 `node_id`（`{story_id}_mc_01`…）並寫入 `stories.cast_json` 與 **`protagonist_character_id`**
- **圖譜**：macro compile 結束時會先清除舊的 `{story_id}_mc_*` 角色節點，再為每位 cast 成員建立 **CHARACTER** 節點（`apply_mutations`）

這些資料會寫入 SQLite 與 GraphStore，成為後續章節生成的長期導航與 POV 解析基礎。

**章節入口**：`run_chapter` 會把初始 `pov_character_id` 設為 **`protagonist_character_id`**（若尚未 macro 或為空則仍用 `char_public_observer`）。Mock `director` 會沿用 state 內已設定的 POV，避免覆寫回旁觀者。

**章內導航（滑動視窗）**：`director` / `planner` 的 prompt 只帶「最近 5 個」未完成錨點摘要；workflow state 仍保留完整未完成列表與 `target_anchor_id`。故事往後章推進後，已過期的錨點會從篩選中消失，視窗自然滑動。

### 2. Chapter Workflow

這一層負責生成某一章，會從 `director` 開始，一路跑到 `state_updater`。

## 單章 workflow 全流程

### 總覽

每一章大致會經過以下節點：

1. `director`
2. `graph_rag`
3. `planner`
4. `plan_supervisor`
5. `author`
6. `draft_supervisor`
7. `reader`
8. `state_updater`

其中 `plan_supervisor`、`draft_supervisor`、`reader` 都可能把流程打回前一層；若重試次數過多，會進入 HITL。

## Chapter State 是什麼

每一章執行時，都有一份中心狀態物件，可理解為「這一章目前所有 agent 共享的工作記錄」。

它包含四種資訊：

- 章節定位：`story_id`、`chapter_id`、`target_anchor_id`、`active_epoch_id`
- 上下文資料：`bible_context`、`graph_context`、`vector_context`
- 本章規劃：`narrative_directive`、`ground_truth_events`、`narrative_script`
- 生成與審核結果：`current_draft`、`draft_feedback`、`reader_feedback`、`workflow_status`

## 各 agent 的角色與 I/O

### 1. Director

用途：

- 決定本章該由誰當 POV
- 決定本章位於哪個 epoch
- 決定本章的主要劇情推進方向
- 決定 tone 與目標字數

主要輸入：

- 當前章號
- 未完成 anchors
- story premise
- volume summary
- anchor description
- bible context
- graph hint

主要輸出：

- `pov_character_id`
- `active_epoch_id`
- `narrative_directive`
- `tone_direction`
- `target_word_count`
- `target_anchor_id`

對人的理解方式：

- `director` 不是寫故事的人
- 它像是「章節導演」，先決定這章要拍什麼、從誰的視角拍、節奏大概多長

### 2. Graph RAG

用途：

- 把當前章節需要的世界記憶與前情提要整理出來

它會同時查三類來源：

- Graph Store：角色、地點、事件、關係
- Vector Store：章節摘要、片段、未解線索
- SQLite 章節內容：最近幾章正文

主要輸入：

- `story_id`
- `active_epoch_id`
- `pov_character_id`
- `narrative_directive`

主要輸出：

- `bible_context`
- `graph_context`
- `vector_context`
- `previous_chapter_summary`
- `recent_chapter_context`
- `last_known_location`
- `continuity_notes`
- `recent_entity_names`

對人的理解方式：

- 這一層像「資料準備員」
- 它不做創作，只做安全且可控的上下文組裝

### 3. Planner

用途：

- 把 director 的章節方向，轉成真正可執行的「本章大綱」
- 同時產生底層真實事件與給 author 的安全任務卡

主要輸入：

- `narrative_directive`
- `active_epoch_id`
- `pov_character_id`
- story / volume / anchor 資訊
- `previous_chapter_summary`
- `recent_chapter_context`
- `last_known_location`
- `continuity_notes`
- `recent_entity_names`
- `bible_context`
- `graph_context`
- `vector_context`
- 舊的 `plan_feedback`

主要輸出：

- `ground_truth_events`
- `narrative_script`
- `chapter_start_location`
- `author_goal`
- `must_include_beats`
- `reader_visible_facts`
- `reader_unresolved_questions`
- `private_facts_or_secret_actions`
- `ending_state_shift`
- `chapter_end_location_hint`
- `ending_boundary_rule`
- `forbidden_next_scene_actions`
- `forbidden_reveals`
- `author_safe_continuity_notes`（0–4 條；由 planner 對 `continuity_notes` 做 POV／出場過濾後下發，**不得**把 RAG 未解線索原句直接交給 author）

對人的理解方式：

- `ground_truth_events`：系統內部認定本章真實發生了什麼
- `narrative_script`：給作者看的表層劇本
- `author_goal / must_include_beats`：作者這章一定要做到的任務
- `ending_boundary_rule / forbidden_next_scene_actions`：作者不可越界到下一章的硬限制

### 4. Plan Supervisor

用途：

- 審核 planner 大綱是否合理

主要檢查：

- 是否朝 anchor 收斂
- 是否重演上一章已完成事件
- 是否出現 timeline rollback
- 是否出現 teleportation / location paradox（由 LLM 判斷；後端僅保留 timeline rollback 等確定性檢查）
- 是否有 POV 洩漏

主要輸入：

- `ground_truth_events`
- `narrative_script`
- `previous_chapter_summary`
- `recent_chapter_context`
- `last_known_location`
- `chapter_start_location`
- `chapter_end_location_hint`
- `must_include_beats`
- anchor 資訊

主要輸出：

- `is_approved`
- `violation_type`
- `suggestion_type`
- `feedback_to_agent`
- `anchor_achieved`

如果不通過：

- 退回 `planner`
- 超過一定次數後進入 HITL，要求人工改大綱

### 5. Author

用途：

- 根據 planner 的安全任務卡，真正生成小說正文

主要輸入：

- `narrative_script`
- `chapter_start_location`
- `author_goal`
- `must_include_beats`
- `reader_visible_facts`
- `reader_unresolved_questions`
- `chapter_end_location_hint`
- `ending_state_shift`
- `ending_boundary_rule`
- `forbidden_next_scene_actions`
- `forbidden_reveals`
- `tone_direction`
- `target_word_count`
- `normalized_length_min`
- `normalized_length_max`
- `previous_chapter_summary`
- `last_known_location`
- `author_safe_continuity_notes`（僅 planner 輸出之過濾版；**不再**直接餵 raw `continuity_notes`）
- `recent_entity_names`
- `draft_feedback`
- `reader_feedback`

主要輸出：

- `chapter_content`
- `word_count`

重要特性：

- Author 處於 Air-Gap 模式
- 它看不到底層真實大綱細節，只能看安全版任務卡
- 若正文太短，系統可能要求它補寫
- 若正文越過章節終點邊界，系統可能要求它局部修正結尾

### 6. Draft Supervisor

用途：

- 檢查 author 的正文是否違反本章劇本與硬邏輯

主要檢查：

- 字數是否在允許範圍內
- 是否違反 `ground_truth_events`
- 是否越過 `chapter_end_location_hint`
- 是否違反 `ending_boundary_rule`
- 是否提前做了 `forbidden_next_scene_actions`
- 是否有 POV 洩漏

主要輸出：

- `is_approved`
- `violation_type`
- `suggestion_type`
- `feedback_to_agent`

如果不通過：

- 退回 `author`
- 系統會把本次退稿原因記錄進 `draft_feedback`
- 超過一定次數後進入 HITL

### 7. Reader

用途：

- 用讀者視角評估可讀性與文學體驗

主要輸入：

- `current_draft`
- `target_word_count`

主要輸出：

- `is_approved`
- `literary_score`
- `suggestion_type`
- `critique`

如果不通過：

- 通常會退回 `author`
- 若多次仍不理想，系統可能保留最高分版本往下走

### 8. State Updater

用途：

- 在章節定稿後，將本章內容轉成可落盤的知識與記憶

這一層會做兩件事：

1. 呼叫 `state_extractor`，從正文抽出：
   - 實體
   - 關係
   - 章節記憶

2. 將抽取結果轉成：
   - graph mutations
   - vector documents
   - SQLite chapter content 寫入

主要輸出：

- `mutations`
- `vector_documents`

此外，它還會建立一筆 `state_transaction`，確保：

- Graph 寫入
- Vector 寫入
- SQLite 寫入

是可以追蹤與 replay 的。

## HITL 會在哪些地方出現

### Plan Loop

當 `plan_supervisor` 多次退回 planner 後：

- `workflow_status = WAITING_HITL`
- `hitl_reason = Plan_Loop_Exceeded`
- `resume_from = planner`

人工可做的事：

- 允許調整 anchor
- 強制重寫大綱

### Draft Loop

當 `draft_supervisor` 多次退回 author 後：

- `workflow_status = WAITING_HITL`
- `hitl_reason = Draft_Loop_Exceeded`
- `resume_from = author`

人工可做的事：

- 保持邏輯並重寫
- 放寬字數要求

### 手動大綱編輯

人工可以直接提交：

- 新的 `ground_truth_events`
- 新的 `narrative_script`

提交後流程會從 `author` 繼續。

### 狀態注入

人工也可以直接對 graph 注入 mutation，修正世界狀態後再續跑。

## 每章最終會留下什麼

每一章完成後，系統會留下四類結果：

1. SQLite
   - 章節標題
   - 章節正文
   - workflow run 狀態
   - 每一步 agent log
   - HITL 操作紀錄
   - state transaction

2. Graph
   - 新事件節點
   - 新實體或更新過的實體
   - 新關係
   - 新位置狀態

3. Vector
   - 章節摘要
   - 摘錄片段
   - 未解線索
   - 實體名單
   - location metadata

4. Workflow State
   - 供下一章繼續使用的 continuity 與回饋資料

## 技術人員最該注意的幾個關鍵原則

- `director` 定方向，`planner` 定章節真實事件，`author` 只負責表層寫作
- `author` 不能直接看到底層真相
- `plan_supervisor` 與 `draft_supervisor` 是兩道不同的審核
- `state_updater` 不是直接把正文存起來而已，而是把正文轉成可查詢的長期記憶
- 真正的 continuity 品質，取決於：
  - POV ID 是否對齊圖譜節點
  - `previous_chapter_summary` 是否乾淨
  - `last_known_location` 是否正確
  - `chapter_end_location_hint` 與 `ending_boundary_rule` 是否足夠清楚
