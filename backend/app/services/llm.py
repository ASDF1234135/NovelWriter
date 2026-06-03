from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from collections.abc import Callable
from typing import Any, Iterator, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.logging import get_logger
from app.services.workflow.profiles import AgentPromptProfile

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
logger = get_logger(__name__)

_JSON_REPAIR_RAW_MAX_CHARS = 100_000
_JSON_ERROR_CONTEXT_CHARS = 400


def _coerce_message_content(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif "text" in item:
                    parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(raw)


def _strip_markdown_json_fence(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if not lines:
        return t
    if lines[0].strip().startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].strip() == "```":
        lines.pop()
    return "\n".join(lines).strip()


def _first_balanced_json_object(s: str) -> str | None:
    """Return the first top-level `{...}` slice with brace depth outside of JSON strings."""
    i = 0
    start = -1
    depth = 0
    in_string = False
    escape = False
    n = len(s)
    while i < n:
        c = s[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    return s[start : i + 1]
        i += 1
    return None


def _legacy_brace_slice(stripped: str) -> str | None:
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return stripped[start : end + 1]


def _extract_json_payload(content: str) -> Any:
    stripped = _strip_markdown_json_fence(content.strip())
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(cand: str | None) -> None:
        if not cand or cand in seen:
            return
        seen.add(cand)
        candidates.append(cand)

    _add(stripped)
    _add(_first_balanced_json_object(stripped))
    _add(_legacy_brace_slice(stripped))

    last_err: json.JSONDecodeError | None = None
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError as e:
            last_err = e
    if last_err is not None:
        raise last_err
    raise json.JSONDecodeError("Expected JSON value", stripped, 0)


def _log_structured_parse_failure(
    *,
    agent_name: str,
    provider: str,
    model: str,
    request_kind: str,
    content_preview: str,
    exc: Exception,
    repair_round: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "agent_name": agent_name,
        "provider": provider,
        "model": model,
        "request_kind": request_kind,
        "error_type": type(exc).__name__,
        "error_message": str(exc)[:800],
    }
    if repair_round is not None:
        payload["repair_round"] = repair_round
    if isinstance(exc, json.JSONDecodeError):
        pos = exc.pos if exc.pos is not None else 0
        lo = max(0, pos - _JSON_ERROR_CONTEXT_CHARS)
        hi = min(len(content_preview), pos + _JSON_ERROR_CONTEXT_CHARS)
        payload["json_exc_lineno"] = exc.lineno
        payload["json_exc_colno"] = exc.colno
        payload["json_exc_pos"] = pos
        payload["context_snippet"] = content_preview[lo:hi]
    logger.warning("LLM structured output parse failed", extra={"extra_payload": payload})


def _build_json_repair_user_prompt(
    schema: str,
    raw_text: str,
    error: Exception | None,
    repair_idx: int,
) -> str:
    head = (
        "Repair the following output so it becomes exactly one valid JSON object that matches the schema. "
        "Return JSON only — no markdown fences, comments, or surrounding text.\n"
    )
    err_detail = ""
    if error is not None:
        err_detail = f"\nParse/validation error:\n{error}\n"
        if isinstance(error, json.JSONDecodeError):
            pos = error.pos if error.pos is not None else 0
            lo = max(0, pos - _JSON_ERROR_CONTEXT_CHARS)
            hi = min(len(raw_text), pos + _JSON_ERROR_CONTEXT_CHARS)
            err_detail += (
                f"\nContext around character position {pos} "
                f"(line {error.lineno}, col {error.colno}):\n{raw_text[lo:hi]}\n"
            )

    if repair_idx == 0:
        body = raw_text
        if len(body) > _JSON_REPAIR_RAW_MAX_CHARS:
            body = body[:_JSON_REPAIR_RAW_MAX_CHARS] + "\n... [truncated]"
        return f"{head}{err_detail}\nSchema:\n{schema}\n\nRaw output:\n{body}"

    if isinstance(error, json.JSONDecodeError) and error.pos is not None:
        pos = error.pos
        lo = max(0, pos - _JSON_ERROR_CONTEXT_CHARS)
        hi = min(len(raw_text), pos + _JSON_ERROR_CONTEXT_CHARS)
        excerpt = raw_text[lo:hi]
    else:
        excerpt = raw_text[-8000:] if len(raw_text) > 8000 else raw_text
    return f"{head}{err_detail}\nSchema:\n{schema}\n\nRaw excerpt:\n{excerpt}"


@dataclass
class LLMResult:
    content: str
    token_usage: int
    latency_ms: int


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, provider_body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_body = provider_body


class LLMClient(Protocol):
    def invoke(self, prompt: str) -> LLMResult:
        ...

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResult:
        ...

    def invoke_json(
        self,
        prompt: str,
        response_model: type[StructuredModelT],
        profile: AgentPromptProfile,
    ) -> tuple[StructuredModelT, LLMResult]:
        ...

    def invoke_text_with_tools(
        self,
        messages: list[dict[str, Any]],
        profile: AgentPromptProfile,
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], str],
        *,
        max_tool_rounds: int = 4,
    ) -> LLMResult:
        ...


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class MockLLMClient:
    def invoke(self, prompt: str) -> LLMResult:
        return self.invoke_text(
            prompt,
            AgentPromptProfile(
                agent_name="mock",
                system_prompt="",
                model="mock",
                temperature=0.0,
            ),
        )

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResult:
        content = (
            "[Mock LLM]\n"
            "This is a local stub response so multi-agent workflows, observability, and persistence can run end-to-end.\n"
            f"Summary: {prompt[:280]}"
        )
        return LLMResult(content=content, token_usage=max(32, len(prompt) // 2), latency_ms=35)

    def invoke_json(
        self,
        prompt: str,
        response_model: type[StructuredModelT],
        profile: AgentPromptProfile,
    ) -> tuple[StructuredModelT, LLMResult]:
        raise NotImplementedError("MockLLMClient does not synthesize structured outputs; node fallback should be used.")

    def invoke_text_with_tools(
        self,
        messages: list[dict[str, Any]],
        profile: AgentPromptProfile,
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], str],
        *,
        max_tool_rounds: int = 4,
    ) -> LLMResult:
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                user_content = msg["content"]
                break
        return self.invoke_text(user_content or "(empty)", profile)


def _iter_sse_chat_events(response: httpx.Response) -> Iterator[dict[str, Any]]:
    for raw in response.iter_lines():
        if not raw:
            continue
        line = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
        if line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            logger.warning(
                "LLM stream skipped non-JSON SSE line",
                extra={"extra_payload": {"preview": data[:200]}},
            )


def _append_delta_content(parts: list[str], delta: dict[str, Any]) -> None:
    c = delta.get("content")
    if c is None:
        return
    if isinstance(c, str):
        parts.append(c)
        return
    if isinstance(c, list):
        for item in c:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)


def _consume_chat_completion_stream(response: httpx.Response) -> dict[str, Any]:
    parts: list[str] = []
    finish_reason: str | None = None
    usage: dict[str, Any] = {}
    for event in _iter_sse_chat_events(response):
        if "error" in event:
            err = event["error"]
            msg = err.get("message", json.dumps(err, ensure_ascii=False))
            raise LLMProviderError(
                f"LLM stream error: {msg}",
                status_code=502,
                provider_body=msg,
            )
        if event.get("usage"):
            usage = event["usage"]
        choices = event.get("choices") or []
        if not choices:
            continue
        ch0 = choices[0]
        delta = ch0.get("delta") or {}
        _append_delta_content(parts, delta)
        if ch0.get("finish_reason"):
            finish_reason = ch0["finish_reason"]
    content = "".join(parts)
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": usage,
    }


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        *,
        stream_chat: bool = False,
        stream_structured: bool = False,
        stream_include_usage: bool = False,
        connect_timeout: float = 10.0,
        stream_read_timeout: float = 300.0,
        json_response_format_enabled: bool = True,
        json_repair_max_attempts: int = 2,
        json_repair_plain_on_retry: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.stream_chat = stream_chat
        self.stream_structured = stream_structured
        self.stream_include_usage = stream_include_usage
        self.connect_timeout = connect_timeout
        self.stream_read_timeout = stream_read_timeout
        self.json_response_format_enabled = json_response_format_enabled
        self.json_repair_max_attempts = max(0, int(json_repair_max_attempts))
        self.json_repair_plain_on_retry = json_repair_plain_on_retry

    def invoke(self, prompt: str) -> LLMResult:
        return self.invoke_text(
            prompt,
            AgentPromptProfile(
                agent_name="default",
                system_prompt="You are a helpful assistant.",
                model=self.model,
                temperature=0.3,
            ),
        )

    def _structured_rf_for_generation(self) -> dict[str, Any] | None:
        if not self.json_response_format_enabled:
            return None
        return {"type": "json_object"}

    def _structured_rf_for_repair(self, repair_idx: int) -> dict[str, Any] | None:
        if not self.json_response_format_enabled:
            return None
        if self.json_repair_plain_on_retry and repair_idx >= 1:
            return None
        return {"type": "json_object"}

    def _httpx_timeout_non_stream(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect_timeout,
            read=self.timeout,
            write=self.timeout,
            pool=self.timeout,
        )

    def _httpx_timeout_stream(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect_timeout,
            read=self.stream_read_timeout,
            write=self.timeout,
            pool=self.timeout,
        )

    def _use_stream(self, response_format: dict[str, Any] | None) -> bool:
        if not self.stream_chat:
            return False
        if response_format is not None and not self.stream_structured:
            return False
        return True

    def _request_non_stream(
        self,
        *,
        messages: list[dict[str, str]],
        agent_name: str,
        model: str,
        temperature: float,
        request_kind: str,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        started: float,
    ) -> tuple[dict[str, Any], int]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        timeout = self._httpx_timeout_non_stream()
        with httpx.Client(timeout=timeout) as client:
            try:
                response = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                detail = f"LLM provider request timed out after {self.timeout:.0f}s."
                latency_ms = int((perf_counter() - started) * 1000)
                logger.error(
                    "LLM provider request timed out",
                    extra={
                        "extra_payload": {
                            "agent_name": agent_name,
                            "provider": self.base_url,
                            "model": model,
                            "request_kind": request_kind,
                            "timeout_seconds": self.timeout,
                            "latency_ms": latency_ms,
                            "stream": False,
                        }
                    },
                )
                raise LLMProviderError(detail, status_code=504, provider_body=detail) from exc
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                response_text = response.text.strip()
                detail = _compact_error_text(response_text)
                latency_ms = int((perf_counter() - started) * 1000)
                logger.error(
                    "LLM provider request failed",
                    extra={
                        "extra_payload": {
                            "agent_name": agent_name,
                            "provider": self.base_url,
                            "model": model,
                            "request_kind": request_kind,
                            "status_code": response.status_code,
                            "response_text": detail,
                            "latency_ms": latency_ms,
                            "stream": False,
                        }
                    },
                )
                raise LLMProviderError(
                    f"LLM provider request failed ({response.status_code}): {detail}",
                    status_code=response.status_code,
                    provider_body=detail,
                ) from exc
            data = response.json()
        latency_ms = int((perf_counter() - started) * 1000)
        return data, latency_ms

    def _request_stream(
        self,
        *,
        messages: list[dict[str, str]],
        agent_name: str,
        model: str,
        temperature: float,
        request_kind: str,
        response_format: dict[str, Any] | None = None,
        started: float,
    ) -> tuple[dict[str, Any], int]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if self.stream_include_usage:
            payload["stream_options"] = {"include_usage": True}
        timeout = self._httpx_timeout_stream()
        url = f"{self.base_url}/chat/completions"
        with httpx.Client(timeout=timeout) as client:
            try:
                with client.stream("POST", url, headers=headers, json=payload) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        response_text = response.read().decode("utf-8", errors="replace").strip()
                        detail = _compact_error_text(response_text)
                        latency_ms = int((perf_counter() - started) * 1000)
                        logger.error(
                            "LLM provider stream request failed",
                            extra={
                                "extra_payload": {
                                    "agent_name": agent_name,
                                    "provider": self.base_url,
                                    "model": model,
                                    "request_kind": request_kind,
                                    "status_code": response.status_code,
                                    "response_text": detail,
                                    "latency_ms": latency_ms,
                                    "stream": True,
                                }
                            },
                        )
                        raise LLMProviderError(
                            f"LLM provider request failed ({response.status_code}): {detail}",
                            status_code=response.status_code,
                            provider_body=detail,
                        ) from exc
                    try:
                        data = _consume_chat_completion_stream(response)
                    except httpx.TimeoutException as exc:
                        detail = (
                            f"LLM provider stream idle timed out "
                            f"(no chunk for {self.stream_read_timeout:.0f}s)."
                        )
                        latency_ms = int((perf_counter() - started) * 1000)
                        logger.error(
                            "LLM provider stream read timed out",
                            extra={
                                "extra_payload": {
                                    "agent_name": agent_name,
                                    "provider": self.base_url,
                                    "model": model,
                                    "request_kind": request_kind,
                                    "stream_read_timeout_seconds": self.stream_read_timeout,
                                    "latency_ms": latency_ms,
                                }
                            },
                        )
                        raise LLMProviderError(detail, status_code=504, provider_body=detail) from exc
            except httpx.TimeoutException as exc:
                detail = f"LLM provider stream connection timed out (connect {self.connect_timeout:.0f}s)."
                latency_ms = int((perf_counter() - started) * 1000)
                logger.error(
                    "LLM provider stream timed out",
                    extra={
                        "extra_payload": {
                            "agent_name": agent_name,
                            "provider": self.base_url,
                            "model": model,
                            "request_kind": request_kind,
                            "latency_ms": latency_ms,
                            "stream": True,
                        }
                    },
                )
                raise LLMProviderError(detail, status_code=504, provider_body=detail) from exc
        latency_ms = int((perf_counter() - started) * 1000)
        return data, latency_ms

    def _request(
        self,
        *,
        messages: list[dict[str, str]],
        agent_name: str,
        model: str,
        temperature: float,
        request_kind: str,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        started = perf_counter()
        use_stream = self._use_stream(response_format)
        headers_log = {
            "agent_name": agent_name,
            "provider": self.base_url,
            "model": model,
            "request_kind": request_kind,
            "temperature": temperature,
            "timeout_seconds": self.timeout,
            "stream_read_timeout_seconds": self.stream_read_timeout,
            "prompt_char_count": sum(len(message.get("content", "")) for message in messages),
            "has_response_format": response_format is not None,
            "stream": use_stream,
        }
        logger.info("LLM request started", extra={"extra_payload": headers_log})

        if use_stream:
            try:
                data, latency_ms = self._request_stream(
                    messages=messages,
                    agent_name=agent_name,
                    model=model,
                    temperature=temperature,
                    request_kind=request_kind,
                    response_format=response_format,
                    started=started,
                )
            except LLMProviderError as exc:
                if response_format is not None and exc.status_code in (400, 415, 422, 405):
                    logger.warning(
                        "LLM structured stream rejected; falling back to non-stream",
                        extra={
                            "extra_payload": {
                                "agent_name": agent_name,
                                "status_code": exc.status_code,
                                "request_kind": request_kind,
                            }
                        },
                    )
                    data, latency_ms = self._request_non_stream(
                        messages=messages,
                        agent_name=agent_name,
                        model=model,
                        temperature=temperature,
                        request_kind=request_kind,
                        response_format=response_format,
                        started=started,
                    )
                else:
                    raise
        else:
            data, latency_ms = self._request_non_stream(
                messages=messages,
                agent_name=agent_name,
                model=model,
                temperature=temperature,
                request_kind=request_kind,
                response_format=response_format,
                started=started,
            )

        usage = data.get("usage", {})
        logger.info(
            "LLM request completed",
            extra={
                "extra_payload": {
                    "agent_name": agent_name,
                    "provider": self.base_url,
                    "model": model,
                    "request_kind": request_kind,
                    "status_code": 200,
                    "latency_ms": latency_ms,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "finish_reason": ((data.get("choices") or [{}])[0].get("finish_reason")),
                    "stream": use_stream,
                }
            },
        )
        return data, latency_ms

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResult:
        data, latency_ms = self._request(
            messages=[
                {"role": "system", "content": profile.system_prompt},
                {"role": "user", "content": prompt},
            ],
            agent_name=profile.agent_name,
            model=profile.model or self.model,
            temperature=profile.temperature,
            request_kind="text_generation",
        )
        choice0 = (data.get("choices") or [{}])[0]
        msg = choice0.get("message") or {}
        content = _coerce_message_content(msg.get("content"))
        usage = data.get("usage", {})
        token_usage = usage.get("total_tokens", max(32, len(prompt) // 2))
        return LLMResult(content=content, token_usage=token_usage, latency_ms=latency_ms)

    def invoke_text_with_tools(
        self,
        messages: list[dict[str, Any]],
        profile: AgentPromptProfile,
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], str],
        *,
        max_tool_rounds: int = 4,
    ) -> LLMResult:
        msgs: list[dict[str, Any]] = list(messages)
        total_tokens = 0
        total_latency = 0
        model = profile.model or self.model
        last_content = ""
        for round_idx in range(max_tool_rounds + 1):
            use_tools = bool(tools) and round_idx < max_tool_rounds
            data, latency_ms = self._request_non_stream(
                messages=msgs,
                agent_name=profile.agent_name,
                model=model,
                temperature=profile.temperature,
                request_kind="text_generation_with_tools",
                response_format=None,
                tools=tools if use_tools else None,
                started=perf_counter(),
            )
            total_latency += latency_ms
            usage = data.get("usage", {})
            total_tokens += int(usage.get("total_tokens") or 0)
            choice0 = (data.get("choices") or [{}])[0]
            msg = choice0.get("message") or {}
            tool_calls = msg.get("tool_calls") if isinstance(msg.get("tool_calls"), list) else []
            last_content = _coerce_message_content(msg.get("content"))
            if not tool_calls:
                return LLMResult(
                    content=last_content,
                    token_usage=total_tokens or max(32, sum(len(str(m.get("content") or "")) for m in msgs) // 2),
                    latency_ms=total_latency,
                )
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
            assistant_msg["tool_calls"] = tool_calls
            msgs.append(assistant_msg)
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                name = str(fn.get("name") or "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                result = tool_handler(name, args)
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tc.get("id") or ""),
                        "content": result,
                    }
                )
        return LLMResult(
            content=last_content,
            token_usage=total_tokens or max(32, sum(len(str(m.get("content") or "")) for m in msgs) // 2),
            latency_ms=total_latency,
        )

    def invoke_json(
        self,
        prompt: str,
        response_model: type[StructuredModelT],
        profile: AgentPromptProfile,
    ) -> tuple[StructuredModelT, LLMResult]:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        system_prompt = (
            f"{profile.system_prompt}\n"
            "You must return exactly one JSON object and nothing else. "
            "Do not include markdown, comments, or extra explanation."
            f"\nJSON Schema:\n{schema}"
        )
        gen_rf = self._structured_rf_for_generation()
        data, latency_ms = self._request(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            agent_name=profile.agent_name,
            model=profile.model or self.model,
            temperature=profile.temperature,
            request_kind="structured_generation",
            response_format=gen_rf,
        )
        choice0 = (data.get("choices") or [{}])[0]
        msg0 = choice0.get("message") or {}
        content = _coerce_message_content(msg0.get("content"))
        usage = data.get("usage", {})
        token_usage = usage.get("total_tokens", max(32, len(prompt) // 2))
        llm_result = LLMResult(content=content, token_usage=token_usage, latency_ms=latency_ms)
        model_name = profile.model or self.model

        def try_validate(raw: str) -> tuple[StructuredModelT | None, Exception | None]:
            try:
                parsed_json = _extract_json_payload(raw)
                validated = response_model.model_validate(parsed_json)
                return validated, None
            except (json.JSONDecodeError, ValidationError) as e:
                return None, e

        parsed, err = try_validate(content)
        if parsed is not None:
            return parsed, llm_result

        assert err is not None
        _log_structured_parse_failure(
            agent_name=profile.agent_name,
            provider=self.base_url,
            model=model_name,
            request_kind="structured_generation",
            content_preview=content,
            exc=err,
        )

        last_exc: Exception = err
        current_raw = content

        for repair_idx in range(self.json_repair_max_attempts):
            repair_rf = self._structured_rf_for_repair(repair_idx)
            repair_body = _build_json_repair_user_prompt(schema, current_raw, last_exc, repair_idx)
            repair_data, repair_latency_ms = self._request(
                messages=[
                    {"role": "system", "content": "You are a JSON repair assistant. Return valid JSON only."},
                    {"role": "user", "content": repair_body},
                ],
                agent_name=profile.agent_name,
                model=profile.model or self.model,
                temperature=0.0,
                request_kind="json_repair",
                response_format=repair_rf,
            )
            r_choice = (repair_data.get("choices") or [{}])[0]
            r_msg = r_choice.get("message") or {}
            repaired_content = _coerce_message_content(r_msg.get("content"))
            repair_usage = repair_data.get("usage", {})
            repaired_result = LLMResult(
                content=repaired_content,
                token_usage=repair_usage.get("total_tokens", token_usage),
                latency_ms=repair_latency_ms,
            )
            parsed_r, err_r = try_validate(repaired_content)
            if parsed_r is not None:
                return parsed_r, repaired_result
            last_exc = err_r if err_r is not None else last_exc
            current_raw = repaired_content
            _log_structured_parse_failure(
                agent_name=profile.agent_name,
                provider=self.base_url,
                model=model_name,
                request_kind="json_repair",
                content_preview=repaired_content,
                exc=last_exc,
                repair_round=repair_idx + 1,
            )

        raise RuntimeError(
            f"LLM structured output failed after {self.json_repair_max_attempts} repair attempt(s) "
            f"for agent {profile.agent_name}: {last_exc}"
        ) from last_exc


def _compact_error_text(text: str, limit: int = 1200) -> str:
    compact = " ".join(text.split())
    return compact[:limit] if len(compact) > limit else compact


class OpenAICompatibleEmbeddingClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        started = perf_counter()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": texts,
        }
        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.post(f"{self.base_url}/embeddings", headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                detail = f"Embedding provider request timed out after {self.timeout:.0f}s."
                raise LLMProviderError(detail, status_code=504, provider_body=detail) from exc
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                response_text = response.text.strip()
                detail = _compact_error_text(response_text)
                raise LLMProviderError(
                    f"Embedding provider request failed ({response.status_code}): {detail}",
                    status_code=response.status_code,
                    provider_body=detail,
                ) from exc
            data = response.json()
        latency_ms = int((perf_counter() - started) * 1000)
        logger.info(
            "Embedding request completed",
            extra={
                "extra_payload": {
                    "provider": self.base_url,
                    "model": self.model,
                    "input_count": len(texts),
                    "latency_ms": latency_ms,
                }
            },
        )
        rows = sorted(data.get("data", []), key=lambda row: row.get("index", 0))
        return [list(row.get("embedding", [])) for row in rows]
