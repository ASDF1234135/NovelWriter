from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NOVEL_BUILDER_",
        extra="ignore",
    )

    app_name: str = "NovelBuilder AI"
    env: str = "development"
    api_prefix: str = "/api"
    sqlite_path: str = "./data/novelbuilder.sqlite3"
    # SQLite concurrency: lock wait on connect (seconds) and busy_handler (milliseconds).
    sqlite_connect_timeout_seconds: float = 30.0
    sqlite_busy_timeout_ms: int = 30000
    use_in_memory_stores: bool = True
    use_mock_llm: bool = True
    use_mock_generation: bool | None = None
    use_mock_embeddings: bool | None = None
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "novelbuilder"
    neo4j_database: str = "neo4j"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "story_chunks"
    qdrant_vector_size: int = 64
    qdrant_recreate_on_dimension_mismatch: bool = False
    llm_provider: str = "mock"
    embedding_provider: str = ""
    llm_model: str = "mock-story-model"
    macro_llm_model: str = ""
    director_llm_model: str = ""
    planner_llm_model: str = ""
    supervisor_llm_model: str = ""
    author_llm_model: str = ""
    reader_llm_model: str = ""
    copyeditor_llm_model: str = ""
    macro_temperature: float = 0.25
    director_temperature: float = 0.2
    planner_temperature: float = 0.35
    supervisor_temperature: float = 0.1
    author_temperature: float = 0.85
    reader_temperature: float = 0.3
    copyeditor_temperature: float = 0.0
    # Post-extraction prose cleanup (reader-approved draft); does not re-run extraction.
    copyeditor_enabled: bool = True
    copyeditor_prev_tail_n1_max_chars: int = 800
    copyeditor_prev_tail_n2_max_chars: int = 500
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 120.0
    embedding_timeout_seconds: float = 0.0
    # Chat completions: optional SSE streaming (keeps connection busy; may help proxy idle timeouts).
    openai_stream_chat: bool = False
    # When True, structured (json_object) calls may use stream; unsupported providers fall back to non-stream on 4xx.
    openai_stream_structured: bool = False
    # Request stream_options.include_usage when streaming (OpenAI-compatible; disable if the API returns 400).
    openai_stream_include_usage: bool = False
    openai_connect_timeout_seconds: float = 30.0
    # Max idle time between SSE chunks while streaming.
    openai_stream_read_timeout_seconds: float = 300.0
    # invoke_json: send OpenAI-style response_format json_object (disable for broken gateways).
    llm_json_response_format: bool = True
    # Max repair HTTP calls after the initial structured_generation fails parse/validate.
    llm_json_repair_attempts: int = 2
    # From the 2nd repair onward, omit response_format (prompt-only JSON).
    llm_json_repair_plain_on_retry: bool = False
    # Chapter word targets (Planner output is clamped; independent of volume budgets).
    chapter_word_min: int = 800
    chapter_word_max: int = 12000
    # Non-English output_language defaults (zh-Hans / zh-Hant / other).
    default_chapter_words: int = 2500
    # English (en) per-chapter target in words (whitespace tokens); calibrated from legacy isalnum gate (~1800 letters ≈ ~360 words).
    default_chapter_words_en: int = 360
    # Macro compile: assumed chapters per volume when deriving volume count from target_total_words.
    macro_chapters_per_volume: int = 10
    # Macro compile for English only: chapter divisor for target_total_words (legacy ~alnum-per-chapter scale; decoupled from workflow word targets).
    macro_english_chapter_unit: int = 1800
    # Macro compile anchor slot-fill: after mainline batches, run side-arc slot-fill LLM calls in parallel (ThreadPoolExecutor). 1 = serial.
    side_slot_fill_max_workers: int = Field(default=3, ge=1, le=16)
    # Plan supervisor: heuristic min normalized words per must_include_beat.
    plan_supervisor_words_per_beat_floor: int = 200
    cors_origins: str = Field(default="http://localhost:5173")
    extraction_entity_text_budget: int = 9000
    extraction_memory_full_text_budget: int = 14000
    extraction_relation_text_budget: int = 8000
    extraction_candidate_nodes_cap: int = 60
    extraction_entity_glossary_cap: int = 40
    extraction_graph_summary_max_chars: int = 2500
    # Relation extractor: chunk canonical_entities into batches (smaller N reduces provider timeouts).
    # 0 = legacy single call with all entities in one prompt.
    extraction_relation_entity_batch_size: int = 12
    # Phase 2 bridge: 1-hop EVENT candidates via Phase 1 hubs, epoch filter, vector-store sim + overlap, top-K.
    extraction_phase2_bridge_top_k: int = Field(default=0, ge=0, le=64)
    extraction_phase2_bridge_pool_cap: int = Field(default=128, ge=1, le=2000)
    extraction_phase2_bridge_sim_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    extraction_phase2_bridge_overlap_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    # Relation validation: LLM repair rounds when endpoints cannot be resolved (id + name index fail).
    extraction_relation_align_retry_max: int = Field(default=2, ge=0, le=4)
    # Second-pass Author call: extraction surface hints (lightweight model recommended).
    author_hints_llm_model: str = ""
    author_hints_temperature: float = 0.1
    # Per-story logging: JSON-Lines file under story_log_dir, deleted on story cascade-delete.
    story_log_dir: str = "./data/logs"
    story_log_level: str = "INFO"
    story_log_max_bytes: int = 10_000_000
    story_log_backup_count: int = 3

    @property
    def sqlite_file(self) -> Path:
        return Path(self.sqlite_path).resolve()

    @property
    def story_log_dir_path(self) -> Path:
        return Path(self.story_log_dir).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def effective_use_mock_generation(self) -> bool:
        if self.use_mock_generation is None:
            return self.use_mock_llm
        return self.use_mock_generation

    @property
    def effective_use_mock_embeddings(self) -> bool:
        if self.use_mock_embeddings is None:
            return self.use_mock_llm
        return self.use_mock_embeddings

    @property
    def effective_embedding_provider(self) -> str:
        return self.embedding_provider or self.llm_provider

    @property
    def effective_embedding_base_url(self) -> str:
        return self.embedding_base_url or self.openai_base_url

    @property
    def effective_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.openai_api_key

    @property
    def effective_embedding_timeout_seconds(self) -> float:
        return self.embedding_timeout_seconds if self.embedding_timeout_seconds > 0 else self.openai_timeout_seconds


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    settings.story_log_dir_path.mkdir(parents=True, exist_ok=True)
    return settings
