from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.logging import get_logger
from app.services.workflow.profiles import AgentPromptProfile

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
logger = get_logger(__name__)


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
            "【Mock LLM】\n"
            "這是一個可替換的本機回應，用來讓多 Agent 工作流、觀測面板與資料落盤先完整跑通。\n"
            f"摘要：{prompt[:280]}"
        )
        return LLMResult(content=content, token_usage=max(32, len(prompt) // 2), latency_ms=35)

    def invoke_json(
        self,
        prompt: str,
        response_model: type[StructuredModelT],
        profile: AgentPromptProfile,
    ) -> tuple[StructuredModelT, LLMResult]:
        raise NotImplementedError("MockLLMClient does not synthesize structured outputs; node fallback should be used.")


class OpenAICompatibleLLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

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
        logger.info(
            "LLM request started",
            extra={
                "extra_payload": {
                    "agent_name": agent_name,
                    "provider": self.base_url,
                    "model": model,
                    "request_kind": request_kind,
                    "temperature": temperature,
                    "timeout_seconds": self.timeout,
                    "prompt_char_count": sum(len(message.get("content", "")) for message in messages),
                    "has_response_format": response_format is not None,
                }
            },
        )
        with httpx.Client(timeout=self.timeout) as client:
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
        usage = data.get("usage", {})
        logger.info(
            "LLM request completed",
            extra={
                "extra_payload": {
                    "agent_name": agent_name,
                    "provider": self.base_url,
                    "model": model,
                    "request_kind": request_kind,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "finish_reason": ((data.get("choices") or [{}])[0].get("finish_reason")),
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
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        token_usage = usage.get("total_tokens", max(32, len(prompt) // 2))
        return LLMResult(content=content, token_usage=token_usage, latency_ms=latency_ms)

    def invoke_json(
        self,
        prompt: str,
        response_model: type[StructuredModelT],
        profile: AgentPromptProfile,
    ) -> tuple[StructuredModelT, LLMResult]:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        system_prompt = (
            f"{profile.system_prompt}\n"
            "你必須只輸出單一 JSON 物件，不可加入 markdown、註解或額外說明。"
            f"\nJSON Schema:\n{schema}"
        )
        data, latency_ms = self._request(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            agent_name=profile.agent_name,
            model=profile.model or self.model,
            temperature=profile.temperature,
            request_kind="structured_generation",
            response_format={"type": "json_object"},
        )
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        token_usage = usage.get("total_tokens", max(32, len(prompt) // 2))
        llm_result = LLMResult(content=content, token_usage=token_usage, latency_ms=latency_ms)
        try:
            parsed_json = _extract_json_payload(content)
            parsed = response_model.model_validate(parsed_json)
            return parsed, llm_result
        except (json.JSONDecodeError, ValidationError):
            logger.warning(
                "LLM structured output requires repair",
                extra={
                    "extra_payload": {
                        "agent_name": profile.agent_name,
                        "provider": self.base_url,
                        "model": profile.model or self.model,
                        "request_kind": "structured_generation",
                        "initial_latency_ms": latency_ms,
                    }
                },
            )
            repair_prompt = (
                "請修復下列輸出，使其成為符合 schema 的單一 JSON 物件。"
                f"\nSchema:\n{schema}\n原始輸出:\n{content}"
            )
            repair_data, repair_latency_ms = self._request(
                messages=[
                    {"role": "system", "content": "你是 JSON 修復器，只能回傳合法 JSON。"},
                    {"role": "user", "content": repair_prompt},
                ],
                agent_name=profile.agent_name,
                model=profile.model or self.model,
                temperature=0.0,
                request_kind="json_repair",
                response_format={"type": "json_object"},
            )
            repaired_content = repair_data["choices"][0]["message"]["content"]
            repair_usage = repair_data.get("usage", {})
            repaired_result = LLMResult(
                content=repaired_content,
                token_usage=repair_usage.get("total_tokens", token_usage),
                latency_ms=repair_latency_ms,
            )
            parsed = response_model.model_validate(_extract_json_payload(repaired_content))
            return parsed, repaired_result


def _extract_json_payload(content: str) -> dict[str, Any]:
    stripped = content.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


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
