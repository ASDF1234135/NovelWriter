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
    use_in_memory_stores: bool = True
    use_mock_llm: bool = True
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "novelbuilder"
    neo4j_database: str = "neo4j"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "story_chunks"
    qdrant_vector_size: int = 64
    qdrant_recreate_on_dimension_mismatch: bool = False
    llm_provider: str = "mock"
    llm_model: str = "mock-story-model"
    macro_llm_model: str = ""
    director_llm_model: str = ""
    planner_llm_model: str = ""
    supervisor_llm_model: str = ""
    author_llm_model: str = ""
    reader_llm_model: str = ""
    macro_temperature: float = 0.25
    director_temperature: float = 0.2
    planner_temperature: float = 0.35
    supervisor_temperature: float = 0.1
    author_temperature: float = 0.85
    reader_temperature: float = 0.3
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 120.0
    # Chapter word targets (Planner output is clamped; independent of volume budgets).
    chapter_word_min: int = 800
    chapter_word_max: int = 12000
    default_chapter_words: int = 2500
    # Plan supervisor: heuristic min normalized words per must_include_beat.
    plan_supervisor_words_per_beat_floor: int = 200
    cors_origins: str = Field(default="http://localhost:5173")
    extraction_entity_text_budget: int = 9000
    extraction_memory_full_text_budget: int = 14000
    extraction_relation_text_budget: int = 8000
    extraction_candidate_nodes_cap: int = 60
    extraction_graph_summary_max_chars: int = 2500
    # Relation extractor: chunk canonical_entities into batches (smaller N reduces provider timeouts).
    # 0 = legacy single call with all entities in one prompt.
    extraction_relation_entity_batch_size: int = 12
    # After reader approves: light prose polish before persist (Traditional Chinese unification, format).
    prose_polish_enabled: bool = True
    prose_polish_llm_model: str = ""
    prose_polish_temperature: float = 0.15
    prose_polish_max_relative_length_change: float = 0.12
    prose_polish_min_similarity_ratio: float = 0.82

    @property
    def sqlite_file(self) -> Path:
        return Path(self.sqlite_path).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    return settings
