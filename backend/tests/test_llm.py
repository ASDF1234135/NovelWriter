import json

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
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: FakeHTTPXClient(response))
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
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: FakeHTTPXClient(response))
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.com",
        api_key="test-key",
        model="text-embedding-test",
    )

    vectors = client.embed_texts(["hello", "world"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def _sse_body(chunks: list[dict]) -> str:
    lines: list[str] = []
    for c in chunks:
        lines.append(f"data: {json.dumps(c)}\n")
    lines.append("data: [DONE]\n")
    return "".join(lines)


def test_openai_compatible_stream_accumulates_content(monkeypatch) -> None:
    chunks = [
        {"choices": [{"delta": {"content": "hel"}, "index": 0}]},
        {"choices": [{"delta": {"content": "lo"}, "index": 0}]},
        {
            "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
            "usage": {"total_tokens": 42, "prompt_tokens": 5, "completion_tokens": 37},
        },
    ]
    sse = _sse_body(chunks)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content.decode())
        assert body.get("stream") is True
        return httpx.Response(
            200,
            text=sse,
            headers={"content-type": "text/event-stream; charset=utf-8"},
        )

    transport = httpx.MockTransport(handler)
    RealClient = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: RealClient(transport=transport, **kwargs),
    )

    client = OpenAICompatibleLLMClient(
        base_url="https://example.com",
        api_key="k",
        model="m",
        stream_chat=True,
    )
    result = client.invoke_text(
        "hi",
        AgentPromptProfile(agent_name="author", system_prompt="s", model="m", temperature=0.5),
    )
    assert result.content == "hello"
    assert result.token_usage == 42


def test_structured_stream_400_falls_back_to_non_stream(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        calls.append((request.url.path, payload))
        if payload.get("stream") is True:
            return httpx.Response(400, json={"error": {"message": "no streaming json"}})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 9},
            },
        )

    transport = httpx.MockTransport(handler)
    RealClient = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: RealClient(transport=transport, **kwargs),
    )

    from pydantic import BaseModel

    class Out(BaseModel):
        ok: bool

    client = OpenAICompatibleLLMClient(
        base_url="https://example.com",
        api_key="k",
        model="m",
        stream_chat=True,
        stream_structured=True,
    )
    out, res = client.invoke_json(
        "x",
        Out,
        AgentPromptProfile(agent_name="planner", system_prompt="sys", model="m", temperature=0.0),
    )
    assert out.ok is True
    assert res.content.strip() == '{"ok": true}'
    assert len(calls) == 2
    assert calls[0][1].get("stream") is True
    assert calls[1][1].get("stream") is not True
