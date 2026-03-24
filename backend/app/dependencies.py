from functools import lru_cache

from app.core.config import get_settings
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import GraphStore, InMemoryGraphStore, Neo4jGraphStore
from app.services.llm import EmbeddingClient, LLMClient, MockLLMClient, OpenAICompatibleEmbeddingClient, OpenAICompatibleLLMClient
from app.services.vector_store import DeterministicEmbeddingClient, InMemoryVectorStore, QdrantVectorStore, VectorStore
from app.services.workflow.service import WorkflowService


@lru_cache
def get_db() -> SQLiteDatabase:
    return SQLiteDatabase()


@lru_cache
def get_story_repository() -> StoryRepository:
    return StoryRepository(get_db())


@lru_cache
def get_workflow_repository() -> WorkflowRepository:
    return WorkflowRepository(get_db())


@lru_cache
def get_graph_store() -> GraphStore:
    settings = get_settings()
    if settings.use_in_memory_stores:
        return InMemoryGraphStore()
    return Neo4jGraphStore(
        uri=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )


@lru_cache
def get_vector_store() -> VectorStore:
    settings = get_settings()
    if settings.use_in_memory_stores:
        return InMemoryVectorStore(get_embedding_client())
    return QdrantVectorStore(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        vector_size=settings.qdrant_vector_size,
        embedding_client=get_embedding_client(),
        recreate_on_dimension_mismatch=settings.qdrant_recreate_on_dimension_mismatch,
    )


@lru_cache
def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.use_mock_llm or settings.llm_provider == "mock":
        return MockLLMClient()
    return OpenAICompatibleLLMClient(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model=settings.llm_model,
        timeout=settings.openai_timeout_seconds,
        stream_chat=settings.openai_stream_chat,
        stream_structured=settings.openai_stream_structured,
        stream_include_usage=settings.openai_stream_include_usage,
        connect_timeout=settings.openai_connect_timeout_seconds,
        stream_read_timeout=settings.openai_stream_read_timeout_seconds,
    )


@lru_cache
def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    if settings.use_mock_llm or settings.llm_provider == "mock":
        return DeterministicEmbeddingClient(settings.qdrant_vector_size)
    return OpenAICompatibleEmbeddingClient(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
        timeout=settings.openai_timeout_seconds,
    )


@lru_cache
def get_workflow_service() -> WorkflowService:
    return WorkflowService(
        story_repository=get_story_repository(),
        workflow_repository=get_workflow_repository(),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=get_graph_store(),
        vector_store=get_vector_store(),
        llm_client=get_llm_client(),
    )
