"""Deterministic check that chapter prose roughly matches the story output_language."""

from __future__ import annotations

import os

from app.domain.schema import HitlReason, WorkflowStatus
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.output_language import (
    OUTPUT_LANGUAGE_LABEL,
    normalize_output_language,
)


def _is_cjk_letter(ch: str) -> bool:
    if len(ch) != 1:
        return False
    o = ord(ch)
    return (0x3400 <= o <= 0x4DBF) or (0x4E00 <= o <= 0x9FFF) or (0xF900 <= o <= 0xFAFF)


def _output_language_gate_mode() -> str:
    return (os.environ.get("OUTPUT_LANGUAGE_GATE_MODE") or "strict").strip().lower()


def _script_letter_counts(text: str) -> tuple[int, int]:
    cjk = 0
    latin = 0
    for ch in text:
        if ch.isascii() and ch.isalpha():
            latin += 1
        elif ch.isalpha() and _is_cjk_letter(ch):
            cjk += 1
    return cjk, latin


def output_language_letter_summary(draft: str, output_language: str) -> str:
    """Short, user-facing summary of script counts (for HITL context)."""
    stripped = (draft or "").strip()
    norm = normalize_output_language(output_language)
    cjk, latin = _script_letter_counts(stripped)
    total = cjk + latin
    return f"Heuristic letter counts: {cjk} CJK-style letters, {latin} Latin A–Z letters (setting: {norm}, total counted {total})."


def detect_output_language_mismatch(draft: str, output_language: str, *, mode: str | None = None) -> str | None:
    """
    Return a short human-readable explanation if prose likely violates output_language, else None.

    Heuristic only: tuned to avoid short-chapter noise and name-only Latin/CJK edge cases.
    Set OUTPUT_LANGUAGE_GATE_MODE=lenient to reduce false positives (slightly stricter ratio gates).
    """
    stripped = (draft or "").strip()
    if len(stripped) < 120:
        return None
    norm = normalize_output_language(output_language)
    cjk, latin = _script_letter_counts(stripped)
    total = cjk + latin
    if total < 80:
        return None
    cjk_ratio = cjk / total
    m = (mode or _output_language_gate_mode()).lower()
    lenient = m == "lenient"

    if norm == "en":
        min_cjk = 55 if lenient else 40
        min_ratio = 0.32 if lenient else 0.22
        if cjk >= min_cjk and cjk_ratio >= min_ratio:
            label = OUTPUT_LANGUAGE_LABEL["en"]
            return (
                f"Story is set to {label}, but the draft has many CJK letters "
                f"(about {cjk_ratio:.0%} of counted A–Z vs CJK letters: {cjk} CJK, {latin} Latin)."
            )
        return None

    if norm in ("zh-Hant", "zh-Hans"):
        min_total = 260 if lenient else 220
        min_latin = 180 if lenient else 140
        max_ratio = 0.09 if lenient else 0.14
        if total >= min_total and latin >= min_latin and cjk_ratio <= max_ratio:
            label = OUTPUT_LANGUAGE_LABEL.get(norm, norm)
            return (
                f"Story is set to {label}, but counted letters look mostly Latin "
                f"(CJK ratio about {cjk_ratio:.0%}: {cjk} CJK, {latin} Latin)."
            )
        return None

    return None


def run_output_language_gate(state: dict, context: WorkflowContext) -> dict[str, object]:
    """Return state updates after the post-polish language gate (caller merges into workflow state)."""
    waived = bool(state.get("output_language_hitl_waived"))
    if waived:
        return {
            "output_language_hitl_waived": False,
            "language_gate_route": "chapter_summarizer",
            "last_agent": "output_language_gate",
            "resume_from": "chapter_summarizer",
            "requires_hitl": False,
            "workflow_status": WorkflowStatus.RUNNING.value,
        }

    # Mock pipelines often mix English scaffolding with a localized story setting; skip the heuristic.
    if isinstance(context.llm_client, MockLLMClient):
        return {
            "language_gate_route": "chapter_summarizer",
            "last_agent": "output_language_gate",
            "resume_from": "chapter_summarizer",
            "hitl_output_language_detail": "",
            "hitl_expected_output_language": "",
        }

    detail = detect_output_language_mismatch(
        str(state.get("current_draft") or ""),
        context.output_language,
        mode=_output_language_gate_mode(),
    )
    if detail is None:
        return {
            "language_gate_route": "chapter_summarizer",
            "last_agent": "output_language_gate",
            "resume_from": "chapter_summarizer",
            "hitl_output_language_detail": "",
            "hitl_expected_output_language": "",
        }

    return {
        "requires_hitl": True,
        "hitl_reason": HitlReason.OUTPUT_LANGUAGE_MISMATCH,
        "hitl_decision_mode": "DASHBOARD",
        "workflow_status": WorkflowStatus.WAITING_HITL.value,
        "pending_hitl_options": [
            {"id": "language_return_author", "label": "退回 Author 依設定語言重寫"},
            {"id": "language_force_continue", "label": "略過檢查並繼續彙總"},
        ],
        "hitl_output_language_detail": detail,
        "hitl_expected_output_language": context.output_language,
        "language_gate_route": "hitl",
        "resume_from": "output_language_gate",
    }
