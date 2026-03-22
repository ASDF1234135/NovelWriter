# NovelBuilder v2

NovelBuilder v2 is a full-stack AI novel orchestration system built around a waypoint-driven, multi-agent workflow. It combines a FastAPI/LangGraph backend, a React/Vite dashboard, and a hybrid storage layer backed by SQLite, Neo4j, and Qdrant.

## Architecture

- `backend/`: FastAPI app, domain schemas, workflow engine, storage adapters, tests.
- `frontend/`: React dashboard for story setup, workflow monitoring, graph visualization, and HITL controls.
- `docker-compose.yml`: Local development stack for Neo4j, Qdrant, backend, and frontend.

## Quick start

1. Copy `.env.example` to `.env`.
2. Start infrastructure with `docker compose up --build`.
3. Open the dashboard at `http://localhost:5173`.
4. Open the API docs at `http://localhost:8000/docs`.

## Runtime modes

- `NOVEL_BUILDER_USE_IN_MEMORY_STORES=true` uses the in-memory graph/vector adapters for fast local testing.
- `NOVEL_BUILDER_USE_IN_MEMORY_STORES=false` switches the backend to `Neo4jGraphStore` and `QdrantVectorStore`.
- `NOVEL_BUILDER_QDRANT_VECTOR_SIZE` must match the configured embedding model output dimension.
- `NOVEL_BUILDER_QDRANT_RECREATE_ON_DIMENSION_MISMATCH=true` allows the backend to delete and recreate the target Qdrant collection when an old collection dimension no longer matches the current embedding model.
- `NOVEL_BUILDER_USE_MOCK_LLM=true` keeps chapter generation on the mock LLM.
- `NOVEL_BUILDER_USE_MOCK_LLM=false` with `NOVEL_BUILDER_LLM_PROVIDER=openai-compatible` enables the OpenAI-compatible chat client using `NOVEL_BUILDER_OPENAI_BASE_URL` and `NOVEL_BUILDER_OPENAI_API_KEY`.
- `NOVEL_BUILDER_OPENAI_TIMEOUT_SECONDS` controls the per-request timeout for the OpenAI-compatible provider. Increase it for long-form author generation.
- `NOVEL_BUILDER_OPENAI_EMBEDDING_MODEL` controls the embedding model used by vector search when mock mode is disabled.
- You can override models and temperatures per role with `NOVEL_BUILDER_MACRO_LLM_MODEL`, `NOVEL_BUILDER_DIRECTOR_LLM_MODEL`, `NOVEL_BUILDER_PLANNER_LLM_MODEL`, `NOVEL_BUILDER_SUPERVISOR_LLM_MODEL`, `NOVEL_BUILDER_AUTHOR_LLM_MODEL`, `NOVEL_BUILDER_READER_LLM_MODEL`, plus their matching `*_TEMPERATURE` settings.

## Docker note

- The frontend container uses its own `/app/node_modules` volume so Linux-native Vite and Rollup dependencies are not overwritten by host `node_modules`.

## Key backend capabilities

- Macro compilation from one-line story premise into volumes and anchors, with optional structured LLM planning.
- Chapter generation workflow with Director, Graph RAG, Planner, Supervisors, Author, Reader, and State Updater.
- Prompt masking to preserve air-gapped author generation.
- Workflow observability via stored step logs and server-sent events.
- HITL controls for decisions, outline editing, and graph state injection.
- State updater transaction logging and replay support for cross-store recovery.

## Development notes

- The default LLM provider is a mock provider so the workflow can run locally before wiring external models.
- When `NOVEL_BUILDER_USE_IN_MEMORY_STORES=true`, the graph and vector adapters use deterministic in-memory implementations while keeping the same service contracts.
- When mock mode is disabled, macro compile can use the same OpenAI-compatible provider to generate structured volumes and anchors.
- When mock mode is disabled, the vector pipeline uses the configured OpenAI-compatible embeddings model; mock mode keeps deterministic local embeddings as fallback.
- On startup, the Qdrant adapter now validates both the embedding output dimension and the existing collection dimension, so dimension mismatches fail fast with a clear remediation hint.
- HITL actions now auto-resume the workflow from the stored resume point, instead of only mutating the paused state.
- The author agent now uses plain text generation instead of structured JSON mode, which reduces timeout risk for long chapter drafts.
