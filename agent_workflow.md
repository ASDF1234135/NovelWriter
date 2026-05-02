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

### `director`（定調與導演指令）

- 產出本章方向：章節類型、敘事指令、副線意圖、新元素引入等
- 若踩到副線冷卻規則（最近用過的類型又被選中），會直接進 HITL

### `graph_rag`（組上下文，不寫文）

- 整合 bible / graph / vector / 章節連續性上下文
- 若上下文長度超預算，觸發 HITL（`CONTEXT_LENGTH_EXCEEDED`）

### `planner`（生成可執行劇情計畫）

- 輸出事件、敘事腳本、必帶節點、字數目標
- 會寫入 `planned_graph_nodes` 與 `pending_b_story_additions`
- 可加入 `pending_cast_evolutions`（角色演化請求）

### `plan_supervisor`（審核 planner）

- 判斷通過/不通過
- 不通過會回 `planner` 重試；超過上限進 HITL（`PLAN_LOOP_EXCEEDED`）

### `logic_alignment`（規則與設定對齊）

- 檢查大綱、規則、設定是否衝突
- 會把衝突寫入 `human_outline_conflict_notes` / `plan_warnings`
- 無法安全放行時進 HITL（`ALIGNMENT_RULES_REQUIRED`）

### `author`（產正文）

- 依規劃寫出章節草稿（`current_draft`）
- 同時產出 `author_extraction_surface_hints` 供後續抽取 gate 使用

### `draft_supervisor`（草稿硬檢）

- 檢查字數、規格與必要條件
- 不通過退回 `author`
- 連續失敗超限進 HITL（`DRAFT_LOOP_EXCEEDED`）

### `reader`（可讀性審核）

- 做文學分數與評論
- 通過就進 `extraction_gate`
- 未通過則回 `author`；若迴圈太多次，會採用最佳草稿直接往下

### `extraction_gate`（定稿抽取與實體對齊閘門）

- 對定稿文本做抽取與對齊
- 失敗會退回 `author`，累積 `extraction_gate_failure_streak`
- 連續失敗達門檻進 HITL（`EXTRACTION_GATE_FAILED`）
- 成功後才會進入後續收尾節點

### `copyeditor`（可選）

- 若系統啟用 copyeditor，就在這裡做文稿潤修

### `output_language_gate`（語言一致性閘門）

- 檢查章節語言是否符合故事設定的輸出語言
- 可能要求你在 HITL 決定「強制繼續」或「退回重寫」

### `chapter_summarizer`（章節摘要）

- 產出並保存章節摘要相關資訊，供後續連續性使用

### `anchor_resolve`（錨點達成判定）

- 判斷錨點是否已達成、如何更新候選與已解決集合
- 判定不穩定時會進 HITL（`ANCHOR_RESOLUTION_FAILED`）

### `profile_expander`（角色資料補齊與演化）

- 將新角色/抽取角色補成 cast profile
- 套用角色演化（如個性、語氣變化）並寫 arc 里程碑
- 產生 `pending_cast_updates` 給後續落盤

### `state_updater`（組提交封包）

- 把本章變更整理為 graph/vector/sqlite 的提交 payload
- 不直接寫 DB，先放進 `pending_db_commit`

### `commit_to_databases`（真正提交）

- 依序寫入 Graph、Vector、SQLite
- 更新章節為 `completed`
- 更新 bible / anchor 狀態、cast 變更等
- 寫入 state transaction，確保可追蹤與重放

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
