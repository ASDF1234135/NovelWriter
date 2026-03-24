# Memory Graph 說明（繁體中文）

> 檔名保留 **`memery_graph.md`**（歷史拼字）；語意上為 **memory / 記憶分層** 說明。  
> English: [memery_graph.en.md](./memery_graph.en.md)。

## 文件目的

說明 NovelBuilder 的記憶如何分層存放、各層職責，以及 **一章定稿後** 資料如何經 **抽取閘門** 再寫入圖譜／向量／SQLite，並與 **`bible_json` 副線池** 同步。重點是架構與風險，而非逐 API 列舉。

## 三層記憶架構

| 層級 | 角色 |
|------|------|
| **SQLite** | 流程主帳本、章節正文、workflow／HITL／transaction；**故事 bible（含 `active_b_stories`）** |
| **Graph Store** | 世界結構化狀態：角色、地點、物品、事件、關係 |
| **Vector Store** | 語意檢索：摘要、片段、未解線索、實體名單等 |

## SQLite 重點表與欄位

### Stories

- `story_id`、標題、premise、**`bible_json`**（JSON）、目標總字數、cast、retry 限制等  
- **`bible_json.active_b_stories`**：進行中的副線列表（`id` + `desc` 等）。**Macro compile** 可寫入種子；**章節成功 commit** 時可 **merge 新增** 或 **依核銷移除**（與 graph 寫入同一事務區塊，避免半套狀態）

### 其餘（與先前一致）

- **Volumes / Anchors / Chapters**：卷、錨點、章節正文  
- **Workflow runs / steps / HITL actions / state_transactions**：執行軌跡、除錯、重放  

## Graph Store

### Node 類型（摘）

`CHARACTER`、`PERSONA`、`LOCATION`、`ITEM`、`CONCEPT`、`EVENT`、`EPOCH` 等。

### EVENT

大綱中的 **`ground_truth_events.event_id`** 會在 **state_updater** 中落成 EVENT 節點（與抽取結果一併支撐關係與查詢）。**副線核銷（Resolve）** 所引用的證據 event id，後端要求須在 **定稿後結構化抽取**（entities 的 `node_id` 或 relations 端點）中可對應到這些 id，以降低 **SQLite 已核銷但圖上缺少關鍵事件** 的因果錯位（R2c）。

### Edge 與認知欄位

- `is_truth` / `is_public`：**真實不等於公開**  
- `known_by` / `holder`、**`start_event_id` / `end_event_id`**（含位置生命週期）  

（關係枚舉與 location lifecycle 行為與先前文件一致。）

## Vector Store

章節定稿並經 **state_updater** 後，由抽取結果拆成多筆 `text_chunk` + `metadata`（chapter_summary、excerpt、unresolved_threads、entity names 等）。**實際抽取內容**在現行流程中優先來自 **`pending_chapter_extraction`**（於 **extraction_gate** 通過 R6 後寫入 state），與入庫正文一致。

## 一章的記憶落盤順序（更新後）

1. Author → Draft / Reader → **Prose polish**（定稿用正文）  
2. **`extraction_gate`**：對定稿正文做 **抽取 + remap + R6**；失敗則不進入後續落盤  
3. **`b_story_resolve`**：僅使用 **結構化抽取** 與 CoT／證據 event id 決定是否核銷副線  
4. **`state_updater`**：  
   - Graph mutations  
   - Vector documents  
   - SQLite `chapters`  
   - **同一 try 內**：依 **R2c 校驗後的** `resolved_b_stories` 更新 **`bible_json.active_b_stories`**，並 **merge** 本章 **`pending_b_story_additions`**  
5. `state_transaction` 標記為 committed（失敗則標記 failed，原則上不應留下半套 bible 更新）

## Continuity 仍主要依賴

`graph_rag` 組出的 `previous_chapter_summary`、`recent_chapter_context`、`last_known_location`、`continuity_notes`、`recent_entity_names` 等；來源仍為 vector + graph + SQLite 的組合（細節與舊版相同）。

## 技術人員須注意的風險（補充）

1. **POV / node id 不一致** — 仍會污染查詢與位置連續性。  
2. **`is_public` 濫用** — 仍會擊穿 Air-Gap。  
3. **Mandatory 幽靈節點** — Draft（R4）與 Remap（R5）口徑不一致時，靠 **R6** 在抽取後擋下，避免 `char_xxx` 未入圖卻 commit。  
4. **Bible 與 Graph 因果錯位** — 核銷副線必須綁 **抽取可佐證的 event id**；否則應拒絕從 `active_b_stories` 剔除。  
5. **Vector 與 Graph 不同步** — 仍會造成 continuity 漂移。  

## 實用類比

- **SQLite**：帳本 + 章節正文 + **副線池（bible）**  
- **Graph**：世界狀態與事件因果  
- **Vector**：回憶索引與語意檢索  

三層與 **定稿後抽取閘門** 一致時，較能同時滿足：可寫作、可記憶、不亂劇透、不空殼創世 id、副線不殭屍也不誤殺。
