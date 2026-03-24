# Agent Workflow（繁體中文）

> 英文版請見 [agent_workflow.en.md](./agent_workflow.en.md)。

## 文件目的

說明 NovelBuilder 在「生成單一章節小說」時，各 agent 如何接力、傳遞哪些資料、何處審核、何時進入 HITL，以及 **B 線核銷、實體綁定與定稿後抽取閘門** 等較新行為。以技術人員可讀的流程為主，不逐行對應程式碼。

## 系統分成兩個層級

### 1. Macro Planning

負責把整體故事拆成：

- **Volumes**：卷級規劃（LLM 輸出為每卷內嵌 `anchors`），正規化後展平寫入 SQLite `anchors` 表（含 `volume_id`）。

**契約**：每卷 **3–5** 個錨點；`chapter_target` 須落在該卷章節範圍內。過少後端補位，過多截斷。

**輸入**：標題、premise、bible、目標總字數。

**輸出**：

- 各卷標題、摘要、章節範圍、字數預算
- 各 anchor 的標題、描述、目標狀態、預計章節
- **Cast**：至少一名 protagonist 與可選 supporting；後端指派穩定 `node_id`（`{story_id}_mc_01`…），寫入 `stories.cast_json` 與 `protagonist_character_id`
- **圖譜**：macro compile 時清除舊 `{story_id}_mc_*` 角色節點，再為每位 cast 建立 CHARACTER 節點
- **副線種子（可選）**：macro 規劃若產出 `initial_b_stories`，成功 compile 後會 **merge** 進 `stories.bible_json.active_b_stories`（依 id 去重）

資料寫入 SQLite 與 GraphStore，作為章節級導航與 POV 基礎。

**章節入口**：`start_run_chapter` 會從 bible 載入 **`active_b_stories`**，計算 **`distance_to_anchor`**（相對當前錨點章距），並對 **`target_word_count`** 套用 **`normalized_length_min/max`**（字數 SSOT 下限／上限）。

**章內導航**：director / planner prompt 僅帶「最近數個」未完成錨點；state 仍保留完整未完成列表與 `target_anchor_id`。

### 2. Chapter Workflow

從 `director` 起，經審核與定稿後進入 **抽取閘門（extraction_gate）**、**副線核銷（b_story_resolve）**，最後 **`state_updater`** 原子落盤。

## 單章 workflow 全流程（總覽）

節點順序（主路徑）：

1. `director` — 章節類型、副線指令、POV、epoch、基調、敘事方向等  
2. `graph_rag` — bible / graph / vector / 近章正文組上下文  
3. `planner` — 底層事件 + 表層劇本 + **`proposed_new_nodes`（≤3）** + **`new_active_b_stories`（≤2，可選）** + `target_word_count`（並寫入字數 SSOT）  
4. `plan_supervisor` — 大綱審核（**Hard / Soft** 分野；創世／B 線核心缺漏為 **Hard**）  
5. `author` — 依安全任務卡寫正文；定稿後第二段 LLM 產出 **`author_extraction_surface_hints`**（`node_id` + 正文精確子字串）  
6. `draft_supervisor` — 字數 SSOT；**必選實體**改由 **`author_extraction_surface_hints`**（正文精確子字串）決定性檢查  
7. `reader` — 文學可讀性  
8. **`extraction_gate`** — **抽取 + `remap_planned_entities`（R1/R5）+ `validate_mandatory_planned_nodes`（R6）**（併用 Author 登記的 surface hints）  
   - 失敗 → 退回 **`author`**（`MISSING_MANDATORY_ENTITY_MAPPING` 類回饋）  
   - 成功 → 寫入 **`pending_chapter_extraction`**，前往副線核銷  
9. **`b_story_resolve`** — LLM 輸出 `resolution_analysis`、`resolution_evidence_event_ids`、`resolved_b_stories`；證據 event id 須在 **抽取結果中可佐證**（R2c）  
10. **`state_updater`** — 以 `pending_chapter_extraction` 為主做 mutations + vector；SQLite 章節寫入後更新 bible：**剔除核銷副線**、**merge 本章新增副線種子**

`plan_supervisor`、`draft_supervisor`、`reader` 可將流程打回前一層；重試過多進入 HITL。`extraction_gate` 退回 author 亦會累積 `draft_feedback`。

## Chapter State 重點欄位

除既有章節定位、上下文、大綱與草稿欄位外，尚包含：

- **敘事策略**：`chapter_type`、`b_story_directive`、`new_elements_to_introduce`  
- **副線池**：`active_b_stories`（來自 bible）、**`pending_b_story_additions`**（planner 本輪擬新增，commit 時寫回）  
- **距離與創世**：`distance_to_anchor`、`planned_graph_nodes`（通過 plan 後與 `proposed_new_nodes` 對齊）  
- **字數 SSOT**：`target_word_count`、`normalized_length_min`、`normalized_length_max`  
- **審核軌跡**：`plan_warnings`（含 plan_supervisor 的 soft_warnings 合併）  
- **定稿後抽取**：`author_extraction_surface_hints`、`pending_chapter_extraction`、`b_story_resolution`、`post_polish_route`、`extraction_gate_*` 回饋（失敗時）

## 各 agent 角色與 I/O（精要）

### Director

決定 **POV、epoch、敘事方向、基調**；輸出 **`chapter_type`**、**`b_story_directive`**、**`new_elements_to_introduce`** 等。  
**`normalize_director_output`**：當離錨點較遠且副線池無有效 id 或副線指令為空時，降級為 **WORLD_BUILDING** 並補預設探索向副線描述。

### Graph RAG

組裝 `bible_context`、`graph_context`、`vector_context`、前情與連續性欄位；不創作。

### Planner

將導演方向轉成可執行大綱：**`ground_truth_events`**、**`narrative_script`**、作者任務卡欄位、**`proposed_new_nodes`**、**`new_active_b_stories`**、**`target_word_count`**。  
後端在 `planner` 節點將 **`planned_graph_nodes`** 與字數 SSOT 寫回 state。

### Plan Supervisor

審核大綱；**Hard** 包含：創世節點與 director 交代不一致、**B 線核心動作缺失**、時序／空間硬傷等。  
**Soft**（寫入 `soft_warnings` 再進 **`plan_warnings`**）：idle 節奏、超前解錨疑慮、字數微偏等——**不得**掩蓋會導致下游缺欄的 Hard 問題。

### Author

依表層劇本寫作；payload 含 **`mandatory_new_entities`**（由 `planned_graph_nodes` 衍生），提示須寫出可對齊 **role / canonical_name** 的辨識特徵。

### Draft Supervisor

**字數**以 state 的 **normalized_length_min/max** 為準。  
**R4**：若 `mandatory_new_entities` 非空，正文須能以關鍵字／別名等 **可檢測方式** 對齊每一項，否則 **Hard** 退回 author。

### Reader

文學評分與評論；不負責字數硬審。

### Prose polish

定稿輕修飾；完成後 **`resume_from`** 指向 **`extraction_gate`**。

### Extraction gate（非 LLM「角色名」但為圖中節點）

對 **已定稿正文** 跑抽取，**`remap_planned_entities`**（無法對齊時可保留新 id 並 log **R5**），再跑 **R6**：每個 **mandatory** 的 `planned_graph_nodes.node_id` 必須出現在抽取實體集合中，否則退回 author。  
成功則 **`pending_chapter_extraction`** 供後續 resolve 與 state_updater 共用。

### B story resolve

輸入含 **remap 後結構化抽取** 摘要；輸出 **CoT** + **`resolution_evidence_event_ids`** + **`resolved_b_stories`**。後端只接受 **在抽取結構中可佐證** 的 event id，避免 SQLite 核銷與圖譜狀態脫節（R2c）。

### State updater

優先使用 **`pending_chapter_extraction`** 產生 graph / vector；與 SQLite 章節寫入同一 try 區塊內：依核銷結果 **更新 bible**（移除 resolved、merge 本章 `pending_b_story_additions`），並記錄 **state_transaction**。

## HITL

與先前相同：**Plan_Loop_Exceeded**、**Draft_Loop_Exceeded**、大綱編輯、正文修訂、狀態注入。  
`resume_from` 可包含 **`extraction_gate`**、**`b_story_resolve`**（見 `WorkflowService` 允許集合），以便從定稿後路徑恢復。

## 每章最終產物

- SQLite：章節正文、workflow 狀態、步驟 log、HITL、transaction、**更新後的 `bible_json.active_b_stories`**  
- Graph / Vector：由定稿抽取與事件一致寫入  
- Workflow state：供下一章連續性使用  

## 技術人員應記住的原則

- **Director / Planner** 定方向與可執行大綱；**Author** 僅看表層任務卡。  
- **R4（draft）** 與 **R6（extraction_gate）** 分工：前者偏「正文可讀的對齊」，後者偏「抽取結果是否落到 planned `node_id`」。  
- **R5** 允許非 mandatory 實體以新 id 落圖並打 log；**mandatory** 不得在未對齊情況下通過 R6。  
- **副線核銷** 必須綁 **抽取可佐證的 event id**，再與 graph 寫入同次 commit 更新 bible。  
