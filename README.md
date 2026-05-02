# NovelBuilder v2

NovelBuilder v2 is a **multi-agent, human-in-the-loop (HITL)** system for long-form fiction. It turns a story premise and world bible into **macro plans** (volumes, anchors, cast) and then runs a **per-chapter LangGraph workflow** (director → RAG → planner → supervisors → author → reader → optional prose polish → state updater) with SQLite, graph, and vector stores.

---

## Architecture overview

### Two pipeline levels

1. **Macro planning** — Compiles the whole story into volumes and per-volume anchors, persists cast and seeds graph characters. See **[`agent_workflow.md`](agent_workflow.md)** (section *Macro Planning*).
2. **Chapter workflow** — Generates one chapter end-to-end: context assembly, dual-track outline (planner), reviews, drafting, reader scoring, optional polish, then extraction and persistence. Full node list and HITL pause points are documented in **[`agent_workflow.md`](agent_workflow.md)** (*Chapter Workflow*).

### Memory and storage

Data is split across three layers (what lives where, how a chapter commit flows):

- **SQLite** — Stories, volumes, anchors, chapter text, workflow runs, HITL audit, transactions.
- **Graph store** — Entities, relationships, world state (Neo4j when not in-memory).
- **Vector store** — Embeddings for retrieval (Qdrant when not in-memory).

Details: **[`memery_graph.md`](memery_graph.md)** *(filename as in repo).*

### Repository layout

| Path | Role |
|------|------|
| [`backend/`](backend/) | FastAPI app, domain models, LangGraph graph, LLM adapters, tests |
| [`frontend/`](frontend/) | React + Vite dashboard (story setup, workflow monitor, graph, HITL) |
| [`docker-compose.yml`](docker-compose.yml) | Neo4j, Qdrant, backend, frontend for local deployment |
| [`agent_workflow.md`](agent_workflow.md) | Agent responsibilities, state, HITL |
| [`memery_graph.md`](memery_graph.md) | Memory architecture and persistence flow |

---

## Deployment

### Prerequisites

- Docker and Docker Compose
- (Optional) Python 3.11+ and Node 20+ if you run backend/frontend outside containers

### Recommended: Docker Compose

1. Copy **`.env.example`** to **`.env`** at the repo root and set at least:
   - `NOVEL_BUILDER_OPENAI_API_KEY` (and `NOVEL_BUILDER_OPENAI_BASE_URL` if not using OpenAI) when using a real LLM
   - `NOVEL_BUILDER_USE_IN_MEMORY_STORES=false` to use Neo4j + Qdrant from Compose
   - `NOVEL_BUILDER_USE_MOCK_LLM=false` when calling a real chat model
   - `NOVEL_BUILDER_QDRANT_VECTOR_SIZE` must match your embedding model dimension

### Split generation and embedding providers

The backend now supports independent provider settings for generation vs embeddings.

- Generation uses `NOVEL_BUILDER_OPENAI_BASE_URL` + `NOVEL_BUILDER_OPENAI_API_KEY`.
- Embeddings can override with `NOVEL_BUILDER_EMBEDDING_BASE_URL` + `NOVEL_BUILDER_EMBEDDING_API_KEY`.
- If embedding override fields are empty, they fall back to generation settings.
- `NOVEL_BUILDER_QDRANT_VECTOR_SIZE` must still match embedding model output dimension.

Example mixed setup:

- Generation: DeepSeek (`NOVEL_BUILDER_OPENAI_BASE_URL=https://api.deepseek.com`)
- Embeddings: Gemini through an OpenAI-compatible embeddings gateway (`NOVEL_BUILDER_EMBEDDING_BASE_URL=...`, `NOVEL_BUILDER_OPENAI_EMBEDDING_MODEL=gemini-embedding-001`)

If your generation provider has structured JSON or streaming limits, consider disabling `NOVEL_BUILDER_OPENAI_STREAM_STRUCTURED` for first-pass validation.

2. Start the stack:

   ```bash
   docker compose up --build
   ```

3. Open:
   - **Dashboard:** http://localhost:5173  
   - **API docs:** http://localhost:8000/docs  

4. **Data:** `./data` is mounted into the backend container for SQLite (see Compose `volumes`).

**Note:** The frontend service uses a named volume for `/app/node_modules` so Linux-built dependencies are not overwritten by a host `node_modules` folder.

### Local development (without full stack)

- **Backend:** from `backend/`, install deps, set `PYTHONPATH` or run as package, then e.g. `uvicorn app.main:app --reload` (see `backend/` and `.env`).
- **Frontend:** from `frontend/`, `npm install` and `npm run dev` — default API base URL is `http://localhost:8000/api` (see `frontend/src/api.ts`).

### Quick runtime switches (summary)

| Variable | Effect |
|----------|--------|
| `NOVEL_BUILDER_USE_IN_MEMORY_STORES` | `true` = in-memory graph/vector; `false` = Neo4j + Qdrant |
| `NOVEL_BUILDER_USE_MOCK_LLM` | `true` = mock LLM for offline flow tests |
| `NOVEL_BUILDER_LLM_PROVIDER` | e.g. `openai-compatible` with base URL + API key |

For the full list, see **[`.env.example`](.env.example)**.

---

## Documentation index

- **[`agent_workflow.md`](agent_workflow.md)** — Agents, chapter graph, HITL  
- **[`memery_graph.md`](memery_graph.md)** — SQLite / graph / vector memory model  

English README · [繁體中文說明](README.zh.md)
