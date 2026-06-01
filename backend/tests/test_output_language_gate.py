from unittest.mock import MagicMock

from app.domain.schema import HitlReason, WorkflowStatus
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.hitl_payload import build_hitl_context_payload
from app.services.workflow.output_language_gate import (
    detect_output_language_mismatch,
    run_output_language_gate,
)


def _ctx(lang: str, llm_client: object | None = None) -> WorkflowContext:
    return WorkflowContext(
        story_repository=MagicMock(),
        workflow_repository=MagicMock(),
        bible_service=MagicMock(),
        anchor_service=MagicMock(),
        graph_store=MagicMock(),
        vector_store=MagicMock(),
        llm_client=llm_client or MagicMock(),
        run_id="r1",
        output_language=lang,
    )


def test_detect_en_mismatch_when_draft_is_mostly_cjk() -> None:
    body = "第一章\n\n" + ("他在夜色中等待，心中忐忑不安。" * 45)
    msg = detect_output_language_mismatch(body, "en")
    assert msg is not None
    assert "English" in msg or "english" in msg.lower()


def test_detect_zh_pass_on_cjk_prose() -> None:
    body = "第一章\n\n" + ("他在夜色中等待，心中忐忑不安。" * 45)
    assert detect_output_language_mismatch(body, "zh-Hant") is None


def test_run_gate_waived_skips_check() -> None:
    state = {"output_language_hitl_waived": True, "current_draft": "x"}
    out = run_output_language_gate(state, _ctx("en"))
    assert out["language_gate_route"] == "chapter_summarizer"
    assert out["workflow_status"] == WorkflowStatus.RUNNING.value


def test_run_gate_skips_heuristic_when_using_mock_llm() -> None:
    body = "Chapter One\n\n" + ("他在夜色中等待，心中忐忑不安。" * 45)
    state = {"current_draft": body, "output_language_hitl_waived": False}
    out = run_output_language_gate(state, _ctx("en", MockLLMClient()))
    assert out["language_gate_route"] == "chapter_summarizer"
    assert out.get("requires_hitl") is None


def test_run_gate_triggers_hitl_on_en_story_with_cjk_draft() -> None:
    body = "Chapter One\n\n" + ("他在夜色中等待，心中忐忑不安。" * 45)
    state = {"current_draft": body, "output_language_hitl_waived": False}
    out = run_output_language_gate(state, _ctx("en"))
    assert out["hitl_reason"] == HitlReason.OUTPUT_LANGUAGE_MISMATCH
    assert out["language_gate_route"] == "hitl"
    assert str(out.get("hitl_output_language_detail") or "")


def test_lenient_gate_skips_borderline_en_mismatch() -> None:
    # Strict flags CJK-heavy English-setting drafts; lenient raises thresholds so this mix passes.
    latin = "a" * 146
    cjk = "测" * 54
    body = "Chapter One\n\n" + latin + cjk
    assert detect_output_language_mismatch(body, "en", mode="strict") is not None
    assert detect_output_language_mismatch(body, "en", mode="lenient") is None


def test_build_hitl_context_payload_output_language() -> None:
    state = {
        "requires_hitl": True,
        "workflow_status": WorkflowStatus.WAITING_HITL.value,
        "hitl_reason": HitlReason.OUTPUT_LANGUAGE_MISMATCH,
        "hitl_output_language_detail": "Heuristic detail line.",
        "hitl_expected_output_language": "en",
        "current_draft": "hello world " * 50,
    }
    p = build_hitl_context_payload(state)
    assert p is not None
    assert p.context_metadata.payload_type == "output_language"
    assert p.context_metadata.expected_output_language == "en"
    assert "detail" in p.primary_issue.lower() or "Heuristic" in p.primary_issue
    assert p.context_metadata.language_detection_summary
    assert "CJK" in (p.context_metadata.language_detection_summary or "")


def test_build_hitl_context_payload_includes_full_draft_without_truncation() -> None:
    draft = "章" * 5000
    state = {
        "requires_hitl": True,
        "workflow_status": WorkflowStatus.WAITING_HITL.value,
        "hitl_reason": HitlReason.DRAFT_LOOP_EXCEEDED,
        "current_draft": draft,
    }
    p = build_hitl_context_payload(state)
    assert p is not None
    assert p.problematic_draft_snippet == draft
    assert not p.problematic_draft_snippet.endswith("…")
