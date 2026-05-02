from app.core.config import get_settings
from app.dependencies import get_embedding_client, get_graph_store, get_llm_client, get_vector_store
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient, OpenAICompatibleEmbeddingClient, OpenAICompatibleLLMClient
from app.services.vector_store import DeterministicEmbeddingClient, InMemoryVectorStore


def clear_caches() -> None:
    get_settings.cache_clear()
    get_graph_store.cache_clear()
    get_vector_store.cache_clear()
    get_llm_client.cache_clear()
    get_embedding_client.cache_clear()


def test_in_memory_factories_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_BUILDER_USE_IN_MEMORY_STORES", "true")
    monkeypatch.setenv("NOVEL_BUILDER_USE_MOCK_LLM", "true")
    clear_caches()

    assert isinstance(get_graph_store(), InMemoryGraphStore)
    assert isinstance(get_vector_store(), InMemoryVectorStore)
    assert isinstance(get_llm_client(), MockLLMClient)
    assert isinstance(get_embedding_client(), DeterministicEmbeddingClient)


def test_openai_compatible_client_when_mock_disabled(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_BUILDER_USE_MOCK_LLM", "false")
    monkeypatch.setenv("NOVEL_BUILDER_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("NOVEL_BUILDER_OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("NOVEL_BUILDER_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("NOVEL_BUILDER_LLM_MODEL", "test-model")
    monkeypatch.setenv("NOVEL_BUILDER_OPENAI_EMBEDDING_MODEL", "text-embedding-test")
    monkeypatch.setenv("NOVEL_BUILDER_OPENAI_TIMEOUT_SECONDS", "180")
    clear_caches()

    client = get_llm_client()
    embedding_client = get_embedding_client()
    assert isinstance(client, OpenAICompatibleLLMClient)
    assert isinstance(embedding_client, OpenAICompatibleEmbeddingClient)
    assert client.timeout == 180


def test_runtime_factories_allow_mixed_generation_embedding_backends(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_BUILDER_USE_MOCK_LLM", "false")
    monkeypatch.setenv("NOVEL_BUILDER_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("NOVEL_BUILDER_OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("NOVEL_BUILDER_OPENAI_API_KEY", "deepseek-key")
    monkeypatch.setenv("NOVEL_BUILDER_LLM_MODEL", "DeepSeek-V4-Flash")
    monkeypatch.setenv("NOVEL_BUILDER_EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("NOVEL_BUILDER_EMBEDDING_BASE_URL", "https://embedding-gateway.example.com/v1")
    monkeypatch.setenv("NOVEL_BUILDER_EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("NOVEL_BUILDER_OPENAI_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("NOVEL_BUILDER_EMBEDDING_TIMEOUT_SECONDS", "200")
    clear_caches()

    llm_client = get_llm_client()
    embedding_client = get_embedding_client()

    assert isinstance(llm_client, OpenAICompatibleLLMClient)
    assert isinstance(embedding_client, OpenAICompatibleEmbeddingClient)
    assert llm_client.base_url == "https://api.deepseek.com"
    assert llm_client.model == "DeepSeek-V4-Flash"
    assert embedding_client.base_url == "https://embedding-gateway.example.com/v1"
    assert embedding_client.model == "gemini-embedding-001"
    assert embedding_client.timeout == 200
