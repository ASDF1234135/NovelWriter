# NovelBuilder v2

NovelBuilder v2 是一套支援 **多 Agent 協作與人工介入（HITL）** 的長篇小說生成系統。它會先把故事 premise 與世界觀 **編譯成宏觀大綱**（卷、錨點、卡司），再對每一章執行 **LangGraph 章節工作流**（導演 → RAG → 企劃 → 督導 → 主筆 → 讀者 → 抽取關卡 → 狀態結算），並以 SQLite、圖譜與向量庫分層儲存。

---

## 主架構說明

### 兩層流程

1. **Macro planning（宏觀規劃）**  
   將整部故事拆成卷與卷內錨點，寫入卡司、在圖譜建立角色節點。細節見 **[`agent_workflow.md`](agent_workflow.md)** 的〈Macro Planning〉一節。

2. **Chapter workflow（單章工作流）**  
   產出單章：組裝上下文、雙軌大綱（planner）、多層審核、正文（含抽取用 surface hints）、讀者評分，通過後 **extraction_gate** 抽取並落盤。節點順序、狀態欄位與 **HITL 暫停點** 見 **[`agent_workflow.md`](agent_workflow.md)** 的〈Chapter Workflow〉與後續章節。

### 記憶與儲存

系統採 **三層記憶**（各層職責、一章完成後如何切分與查詢）：

- **SQLite** — 故事主資料、卷／錨點、章節正文、workflow 與 HITL 紀錄、交易狀態。
- **Graph Store** — 實體、關係、世界狀態（非 in-memory 時為 Neo4j）。
- **Vector Store** — 語意檢索用向量（非 in-memory 時為 Qdrant）。

完整說明請見 **[`memery_graph.md`](memery_graph.md)**（檔名依專案現況）。

### 目錄結構

| 路徑 | 說明 |
|------|------|
| [`backend/`](backend/) | FastAPI、網域模型、LangGraph、LLM 適配器、測試 |
| [`frontend/`](frontend/) | React + Vite 儀表板（開故事、觀測 workflow、圖譜、HITL） |
| [`docker-compose.yml`](docker-compose.yml) | 本機 Neo4j、Qdrant、前後端 |
| [`agent_workflow.md`](agent_workflow.md) | Agent 職責、流程、HITL |
| [`memery_graph.md`](memery_graph.md) | 記憶分層與落盤流程 |

---

## 部署方式

### 環境需求

- Docker、Docker Compose  
- （可選）本機開發時：Python 3.11+、Node 20+

### 建議：Docker Compose

1. 複製專案根目錄的 **`.env.example`** 為 **`.env`**，並依需求設定，例如：  
   - 使用真實 LLM 時設定 `NOVEL_BUILDER_OPENAI_API_KEY`（及非官方端點時的 `NOVEL_BUILDER_OPENAI_BASE_URL`）  
   - `NOVEL_BUILDER_USE_IN_MEMORY_STORES=false` 以使用 Compose 內的 Neo4j + Qdrant  
   - `NOVEL_BUILDER_USE_MOCK_LLM=false` 以呼叫真實對話模型  
   - `NOVEL_BUILDER_QDRANT_VECTOR_SIZE` 須與 embedding 模型維度一致  

2. 啟動：

   ```bash
   docker compose up --build
   ```

3. 開啟：  
   - **儀表板：** http://localhost:5173  
   - **API 文件：** http://localhost:8000/docs  

4. **資料：** Compose 將 `./data` 掛載進後端容器，供 SQLite 等使用。

**說明：** 前端容器對 `/app/node_modules` 使用獨立 volume，避免被宿主機的 `node_modules` 覆蓋。

### 本機開發（不全用容器）

- **後端：** 在 `backend/` 安裝依賴後執行 `uvicorn`（搭配根目錄 `.env`）。  
- **前端：** 在 `frontend/` 執行 `npm install`、`npm run dev`；預設 API 為 `http://localhost:8000/api`（見 `frontend/src/api.ts`）。

### 執行模式速查

| 變數 | 作用 |
|------|------|
| `NOVEL_BUILDER_USE_IN_MEMORY_STORES` | `true` 為記憶體圖／向量；`false` 為 Neo4j + Qdrant |
| `NOVEL_BUILDER_USE_MOCK_LLM` | `true` 為 Mock LLM，方便離線跑通流程 |
| `NOVEL_BUILDER_LLM_PROVIDER` | 例如 `openai-compatible`，配合金鑰與 base URL |

完整變數列表見 **[`.env.example`](.env.example)**。

---

## 文件索引

- **[`agent_workflow.md`](agent_workflow.md)** — Agent、章節圖、HITL  
- **[`memery_graph.md`](memery_graph.md)** — SQLite／圖譜／向量記憶模型  

[English README](README.md) · 繁體中文說明
