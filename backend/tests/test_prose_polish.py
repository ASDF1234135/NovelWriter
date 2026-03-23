"""Tests for prose_polish gate and passthrough."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from app.core.config import get_settings
from app.domain.schema import ProsePolishOutput
from app.services.llm import LLMResult
from app.services.workflow.nodes.prose_polish import polish_draft
from app.services.workflow.profiles import AgentPromptProfile


class GateTestLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    def invoke_json(self, prompt: str, response_model: type[BaseModel], profile: AgentPromptProfile):
        out = ProsePolishOutput(polished_text=self._text, change_summary="test")
        return response_model.model_validate(out.model_dump(mode="json")), LLMResult(
            content="{}", token_usage=1, latency_ms=1
        )


def test_prose_polish_gate_rejects_large_length_change(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_BUILDER_PROSE_POLISH_ENABLED", "true")
    get_settings.cache_clear()
    original = "章節本文" * 50
    candidate = original + "x" * 500
    ctx = SimpleNamespace(llm_client=GateTestLLM(candidate))
    text, diag = polish_draft(original, ctx)
    assert text == original
    assert diag.get("gate_failed") is True
    assert diag.get("skipped_reason") == "length_change_exceeded"
    get_settings.cache_clear()


def test_prose_polish_gate_rejects_low_similarity(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_BUILDER_PROSE_POLISH_ENABLED", "true")
    get_settings.cache_clear()
    # Same length so length gate passes; content unrelated so similarity fails.
    original = "甲" * 80
    candidate = "乙" * 80
    ctx = SimpleNamespace(llm_client=GateTestLLM(candidate))
    text, diag = polish_draft(original, ctx)
    assert text == original
    assert diag.get("gate_failed") is True
    assert diag.get("skipped_reason") == "similarity_below_threshold"
    get_settings.cache_clear()


def test_prose_polish_accepts_minor_edit(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_BUILDER_PROSE_POLISH_ENABLED", "true")
    monkeypatch.setenv("NOVEL_BUILDER_PROSE_POLISH_MIN_SIMILARITY_RATIO", "0.75")
    monkeypatch.setenv("NOVEL_BUILDER_PROSE_POLISH_MAX_RELATIVE_LENGTH_CHANGE", "0.25")
    get_settings.cache_clear()
    original = "他說：「你好。」然後離開了。"
    candidate = "他說：「你好。」\n\n然後離開了。"
    ctx = SimpleNamespace(llm_client=GateTestLLM(candidate))
    text, diag = polish_draft(original, ctx)
    assert text == candidate
    assert diag.get("applied") is True
    get_settings.cache_clear()
