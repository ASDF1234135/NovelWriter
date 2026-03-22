# Memery Graph

## 文件目的

這份文件說明 NovelBuilder 的記憶儲存方法。重點不是程式細節，而是讓技術人員快速理解：

- 哪些資料存在哪裡
- 每種儲存層負責什麼角色
- 一章完成後，資料如何被拆分、轉寫與查詢

系統目前採用三層記憶架構：

- SQLite：流程與章節主資料
- Graph Store：實體、關係、世界狀態
- Vector Store：章節摘要、片段、可檢索記憶

## 記憶分層總覽

### 1. SQLite

用途：

- 保存「系統運行事實」
- 保存「可直接讀取的章節正文」
- 保存 workflow 與 HITL 的過程記錄

它是系統的流程主帳本。

### 2. Graph Store

用途：

- 保存故事世界的結構化狀態
- 保存角色、地點、物品、事件與它們之間的關係

它是系統的狀態真相層。

### 3. Vector Store

用途：

- 保存可供語意檢索的章節記憶
- 讓後續章節能快速取回前情提要、未解線索、片段與實體名單

它是系統的回憶檢索層。

## SQLite 存什麼

### Stories

每個故事的基礎資料：

- `story_id`
- 標題
- premise
- bible
- 目標總字數

### Volumes

Macro compile 後的卷級資料：

- `volume_id`
- `story_id`
- 標題
- 摘要
- 章節起訖

### Anchors

故事里程碑資料：

- `anchor_id`
- `story_id`
- `volume_id`
- 標題
- 描述
- `target_state`
- `chapter_target`
- `priority`

### Chapters

真正的章節內容：

- `chapter_key`
- `story_id`
- `chapter_id`
- `title`
- `content`
- `status`

### Workflow Runs

每次章節生成的總體狀態：

- `run_id`
- `story_id`
- `chapter_id`
- 目前 workflow status
- 當前 agent
- 是否等待 HITL
- `current_state_json`

### Workflow Steps

每個 agent step 的完整紀錄：

- `agent_name`
- `step_index`
- `input_payload_json`
- `output_payload_json`
- `masked_payload_json`
- `token_usage`
- `latency_ms`
- `route_decision`

這一層是觀測與除錯最重要的資料來源。

### HITL Actions

人工介入紀錄：

- 決策
- 手動改大綱
- 狀態注入

### State Transactions

章節落盤時的交易紀錄：

- `transaction_id`
- `run_id`
- `story_id`
- `chapter_id`
- graph 是否已寫入
- vector 是否已寫入
- sqlite 是否已寫入
- payload
- error_text

這是 replay / recovery 的核心基礎。

## Graph Store 存什麼

Graph Store 有兩大類資料：

- Nodes
- Edges

## Node 類型

目前主要節點型別包括：

- `CHARACTER`
- `PERSONA`
- `LOCATION`
- `ITEM`
- `CONCEPT`
- `EVENT`
- `EPOCH`

### CHARACTER

表示真正角色本體。

常見資料：

- `node_id`
- `canonical_name`
- `aliases`
- `description`
- `is_alive`

### PERSONA

表示角色在表層看到的身份、偽裝身份、社會面具。

### LOCATION

表示地點。

常見資料：

- 名稱
- aliases
- `environmental_condition`
- `is_accessible`

### ITEM

表示道具或證物。

### EVENT

表示已發生的事件。

這些事件既可作為章節大綱的真實事件，也可作為 graph 關係的因果錨點。

### EPOCH

表示時間層或時代層。

用途：

- 限制 graph query 僅取當前時代有效資料
- 讓事件可掛回時序框架

## Edge 存什麼

Edge 不只是一條關係，還會帶上 epistemic 與時序資訊。

每條 edge 主要包含：

- `source_id`
- `relation_type`
- `target_id`
- `valid_epoch`
- `start_event_id`
- `end_event_id`
- `is_truth`
- `is_public`
- `known_by`
- `holder`
- `context_details`

## 關係邏輯重點

### `is_truth`

表示這條關係在世界真相層是否成立。

### `is_public`

表示這條關係是否是大眾可知的公開事實。

重要原則：

- 真實不代表公開
- 私下知情、秘密行動、暗中監視通常不是 public

### `known_by`

當 `is_truth = true` 且 `is_public = false` 時，這裡記錄哪些角色知道這件事。

### `holder`

當 `is_truth = false` 時，這裡記錄是誰持有這個錯誤認知或誤信。

### `start_event_id` / `end_event_id`

用來表達關係的生命週期。

最重要的用途之一是位置關係：

- 新位置建立時，舊位置不應一直有效
- 舊的 `LOCATED_IN` 會補上 `end_event_id`

## 目前的主要關係類型

常見關係包括：

- `LOCATED_IN`
- `HAS_ITEM`
- `HAS_RELATION`
- `PARTICIPATED_IN`
- `IS_ACTUALLY`
- `HAS_ATTRIBUTE`
- `BELIEVED_AS`
- `KNOWS_ABOUT`
- `BELONGS_TO_EPOCH`
- `HAPPENED_BEFORE`
- `CAUSED`

## Location Lifecycle 怎麼處理

系統目前不是單純一直新增位置，而是有位置生命週期機制。

### 原則

當角色移動到新地點時：

1. 新的 `LOCATED_IN` 會被建立
2. 舊的 active `LOCATED_IN` 會被補上 `end_event_id`
3. Query 端只會把 active 的位置視為當前位置

這樣做的目的，是避免角色同時停留在兩個地方，造成空間殘影。

## Graph Query 怎麼工作

查詢 graph 時，系統會用四個條件過濾：

1. `story_id`
2. `active_epoch_id`
3. `pov_character_id`
4. `narrative_directive`

實際上只會回：

- 當前 epoch 有效的資料
- 對目前 POV 可見的資料
- 仍為 active 的位置關係

這就是 Air-Gap 與 continuity 的關鍵基礎。

## Vector Store 存什麼

Vector Store 每次不是直接存整章一筆，而是存多種可檢索文件。

每筆文件都長得像：

- `text_chunk`
- `metadata`

## 常見 vector document 類型

### 1. Chapter Summary

用途：

- 給後續章節快速取回前情提要

常見 metadata：

- `epoch_id`
- `chapter_id`
- `location_id`
- `location_name`
- `entity_names`
- `chapter_summary`
- `memory_type = chapter_summary`

### 2. Chapter Excerpt

用途：

- 保留較長正文片段，讓語意搜尋可以抓到局部情節與語感細節

### 3. Unresolved Threads

用途：

- 保存本章未解線索
- 供下一章 continuity 與 planner 使用

### 4. Entity Name List

用途：

- 讓系統快速知道最近哪些角色、物件、地點活躍

## 向量記憶如何產生

在章節定稿後，`state_updater` 會先把正文交給 `state_extractor`。

`state_extractor` 會產生：

- `entities`
- `relations`
- `chapter_memory`

其中 `chapter_memory` 目前主要包含：

- `summary`
- `unresolved_threads`
- `notable_entities`
- `latest_location`

然後 `state_updater` 再把這些資料拆成多筆 vector document。

## `chapter_memory` 的角色

`chapter_memory` 不是全文儲存，而是章節層的安全摘要。

它主要是給後續章節使用的「短期可檢索記憶」。

如果它品質不好，後面會直接影響：

- `previous_chapter_summary`
- `recent_chapter_context`
- `last_known_location`
- unresolved threads continuity

## 記憶落盤流程

一章完成後，記憶層的大致流程如下：

1. 正文定稿
2. `state_extractor` 從正文抽出實體、關係、章節記憶
3. `state_updater` 轉成 graph mutations
4. `state_updater` 轉成 vector documents
5. Graph Store 寫入
6. Vector Store 寫入
7. SQLite chapters 寫入
8. state transaction 更新為 committed

## 目前 continuity 主要吃哪些記憶

後續章節在 `graph_rag` 階段，主要會重新組出：

- `previous_chapter_summary`
- `recent_chapter_context`
- `last_known_location`
- `continuity_notes`
- `recent_entity_names`

其來源優先順序大致是：

### `previous_chapter_summary`

1. 最近章節的 vector `chapter_summary`
2. 若缺失，再 fallback 到 SQLite 章節正文摘要

### `last_known_location`

1. graph 裡 active 的 `LOCATED_IN`
2. 若 graph 沒有，再 fallback 到 vector metadata

目前 fallback 也會考慮：

- 最近章節優先
- active epoch 過濾

### `recent_entity_names`

綜合：

- vector metadata 的 `entity_names`
- graph node 名稱
- 最近章節正文中出現的實體名

## 為什麼要分三層記憶，而不是只存一種

因為三層負責的問題不同：

### SQLite

回答：

- 這章正文是什麼？
- 這次 workflow 跑了哪些步驟？
- 哪裡退稿過？
- 有沒有 HITL？

### Graph

回答：

- 誰在哪裡？
- 誰知道什麼？
- 哪個事件造成了哪個後果？
- 哪條關係現在仍有效？

### Vector

回答：

- 最近幾章發生過什麼？
- 哪個線索還沒解？
- 哪段正文和目前任務最像？
- 近期有哪些關鍵實體？

## 技術人員需要特別注意的幾個風險點

### 1. POV ID 對不上 Graph Node ID

若 `pov_character_id` 不是圖譜中的 canonical node id，會直接污染：

- graph 可見性查詢
- `last_known_location`
- continuity packet

### 2. `is_public` 濫用

若秘密行動被標成 public，Graph RAG 就可能把它當成全世界都知道，直接擊穿 Air-Gap。

### 3. `chapter_memory.summary` 品質太差

若章節摘要只是正文前幾百字，而不是章末狀態摘要，planner 與 supervisor 很容易吃到錯的 continuity。

### 4. `LOCATED_IN` 沒有正確收束

若新位置建立後，舊位置沒退役，角色就會同時卡在兩處。

### 5. Vector metadata 與 Graph 狀態不同步

如果 graph 已更新，但 vector 還保留舊章節位置或舊摘要，就會造成 continuity 漂移。

## 給技術人員的最實用理解方式

可以把整個記憶系統理解成：

- SQLite：帳本
- Graph：世界狀態
- Vector：回憶索引

三層都正確時，系統才會同時做到：

- 寫得出章節
- 記得前情
- 不亂劇透
- 不發生位置與時序錯亂
