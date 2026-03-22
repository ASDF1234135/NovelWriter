import httpx
import pytest

from app.services.llm import LLMProviderError, OpenAICompatibleEmbeddingClient, OpenAICompatibleLLMClient
from app.services.workflow.profiles import AgentPromptProfile


class FakeHTTPXClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, *args, **kwargs) -> httpx.Response:
        return self.response


def test_openai_compatible_client_surfaces_provider_error(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.com/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "messages must contain the word json"}},
    )
    monkeypatch.setattr(httpx, "Client", lambda timeout: FakeHTTPXClient(response))
    client = OpenAICompatibleLLMClient(
        base_url="https://example.com",
        api_key="test-key",
        model="qwen-plus",
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.invoke_text(
            "hello",
            AgentPromptProfile(
                agent_name="planner",
                system_prompt="Output JSON only.",
                model="qwen-plus",
                temperature=0.1,
            ),
        )

    assert "400" in str(exc_info.value)
    assert "messages must contain the word json" in str(exc_info.value)


def test_openai_compatible_embedding_client_parses_embeddings(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.com/embeddings")
    response = httpx.Response(
        200,
        request=request,
        json={
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        },
    )
    monkeypatch.setattr(httpx, "Client", lambda timeout: FakeHTTPXClient(response))
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.com",
        api_key="test-key",
        model="text-embedding-test",
    )

    vectors = client.embed_texts(["hello", "world"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
