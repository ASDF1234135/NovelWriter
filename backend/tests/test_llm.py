import json
from typing import Any

import httpx
import pytest

from app.services.llm import (
    LLMProviderError,
    OpenAICompatibleEmbeddingClient,
    OpenAICompatibleLLMClient,
    _coerce_message_content,
    _extract_json_payload,
)
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


class FakeHTTPXTimeoutClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, *args, **kwargs) -> httpx.Response:
        raise httpx.TimeoutException("request timeout")


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


def test_openai_compatible_embedding_client_surfaces_provider_error(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.com/embeddings")
    response = httpx.Response(
        404,
        request=request,
        json={"error": {"message": "model not found"}},
    )
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: FakeHTTPXClient(response))
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.com",
        api_key="test-key",
        model="gemini-embedding-001",
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.embed_texts(["hello"])

    assert "404" in str(exc_info.value)
    assert "model not found" in str(exc_info.value)


def test_openai_compatible_embedding_client_timeout_raises_provider_error(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: FakeHTTPXTimeoutClient())
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.com",
        api_key="test-key",
        model="gemini-embedding-001",
        timeout=3,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.embed_texts(["hello"])

    assert "timed out after 3s" in str(exc_info.value)


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


def test_coerce_message_content_none_and_list_parts() -> None:
    assert _coerce_message_content(None) == ""
    parts = [
        {"type": "text", "text": "hel"},
        {"type": "text", "text": "lo"},
    ]
    assert _coerce_message_content(parts) == "hello"


def test_extract_json_payload_markdown_fence() -> None:
    raw = '```json\n{"ok": true, "n": 1}\n```'
    assert _extract_json_payload(raw) == {"ok": True, "n": 1}


def test_extract_json_payload_prefix_before_balanced_object() -> None:
    raw = 'Here you go:\n{"x": 2}\ntrailing'
    assert _extract_json_payload(raw) == {"x": 2}


def test_invoke_json_repair_succeeds_on_second_attempt(monkeypatch) -> None:
    """Initial broken JSON, first repair still broken, second repair valid."""
    calls: list[dict[str, Any]] = []
    state = {"repair_idx": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        calls.append(payload)
        user = str(payload["messages"][-1].get("content", ""))
        if "Repair the following output" not in user:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{broken"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 10},
                },
            )
        state["repair_idx"] += 1
        if state["repair_idx"] < 2:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{still bad"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 11},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 12},
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
        json_repair_max_attempts=2,
    )
    out, res = client.invoke_json(
        "x",
        Out,
        AgentPromptProfile(agent_name="planner", system_prompt="sys", model="m", temperature=0.0),
    )
    assert out.ok is True
    assert res.content.strip() == '{"ok": true}'
    assert len(calls) == 3


def test_invoke_json_all_repairs_exhausted_raises(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "not-json"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 3},
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
        json_repair_max_attempts=1,
    )
    with pytest.raises(RuntimeError, match="repair attempt"):
        client.invoke_json(
            "x",
            Out,
            AgentPromptProfile(agent_name="planner", system_prompt="sys", model="m", temperature=0.0),
        )


def test_invoke_json_disables_response_format_when_configured(monkeypatch) -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 5},
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
        json_response_format_enabled=False,
    )
    out, _ = client.invoke_json(
        "x",
        Out,
        AgentPromptProfile(agent_name="planner", system_prompt="sys", model="m", temperature=0.0),
    )
    assert out.ok is True
    assert payloads[0].get("response_format") is None


def test_invoke_json_repair_plain_on_retry_second_call_has_no_format(monkeypatch) -> None:
    payloads: list[dict[str, Any]] = []
    rep = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        p = json.loads(request.content.decode())
        payloads.append(p)
        user = str(p["messages"][-1].get("content", ""))
        if "Repair the following output" not in user:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{bad"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 1},
                },
            )
        rep["n"] += 1
        if rep["n"] < 2:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{bad2"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 2},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 3},
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
        json_repair_max_attempts=2,
        json_repair_plain_on_retry=True,
    )
    out, _ = client.invoke_json(
        "x",
        Out,
        AgentPromptProfile(agent_name="planner", system_prompt="sys", model="m", temperature=0.0),
    )
    assert out.ok is True
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert payloads[1]["response_format"] == {"type": "json_object"}
    assert payloads[2].get("response_format") is None
