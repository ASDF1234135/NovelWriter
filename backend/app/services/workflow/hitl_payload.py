"""Build BFF `HitlContextPayload` from raw workflow state when paused for HITL."""

from __future__ import annotations

from typing import Any

from app.domain.schema import HitlContextMetadata, HitlContextPayload, HitlReason


def _snippet(text: str | None, max_chars: int = 2400) -> str:
    raw = (text or "").strip()
    if len(raw) <= max_chars:
        return raw
    return raw[: max_chars - 1].rstrip() + "…"


def _feedback_lines(items: list[Any], limit: int = 12) -> list[str]:
    out: list[str] = []
    for row in (items or [])[:limit]:
        if not isinstance(row, dict):
            continue
        msg = str(row.get("message") or row.get("violation") or "").strip()
        sug = str(row.get("suggestion") or "").strip()
        if msg and sug:
            out.append(f"{msg} → {sug}")
        elif msg:
            out.append(msg)
        elif sug:
            out.append(sug)
    return out


def product_context_tier_from_internal(internal: int | None) -> int | None:
    """Invert graph_rag internal tier (0=tight .. 2=wide) to product 0=full .. 2=aggressive."""
    if internal is None:
        return None
    try:
        i = int(internal)
    except (TypeError, ValueError):
        return None
    i = max(0, min(2, i))
    return 2 - i


def build_hitl_context_payload(state: dict[str, Any]) -> HitlContextPayload | None:
    if not (
        bool(state.get("requires_hitl"))
        and str(state.get("workflow_status") or "") == "WAITING_HITL"
    ):
        return None

    reason = str(state.get("hitl_reason") or "").strip()
    draft = str(state.get("current_draft") or state.get("best_draft_content") or "")

    if reason == HitlReason.ALIGNMENT_RULES_REQUIRED:
        log = str(state.get("alignment_log") or "").strip()
        conflicts = [str(x).strip() for x in (state.get("human_outline_conflict_notes") or []) if str(x).strip()]
        sup = _feedback_lines(list(state.get("plan_feedback") or []))
        sup.extend(_feedback_lines(list(state.get("draft_feedback") or [])))
        issue = log[-1200:] if log else "邏輯對齊需要補充規則或調整大綱。"
        return HitlContextPayload(
            primary_issue=issue,
            supervisor_feedbacks=sup[:20],
            conflict_notes=conflicts[:30],
            problematic_draft_snippet=_snippet(draft),
            context_metadata=HitlContextMetadata(payload_type="alignment"),
        )

    if reason == HitlReason.EXTRACTION_GATE_FAILED:
        hints = state.get("hitl_extraction_remap_hints") or []
        rows = [h for h in hints if isinstance(h, dict)]
        streak = int(state.get("extraction_gate_failure_streak") or 0)
        issue = f"抽取閘門未通過（連續 {streak} 次失敗）；請綁定未知實體或放寬強制節點。"
        return HitlContextPayload(
            primary_issue=issue,
            supervisor_feedbacks=[],
            conflict_notes=[],
            problematic_draft_snippet=_snippet(draft),
            context_metadata=HitlContextMetadata(
                payload_type="extraction_remap",
                unknown_entities=rows[:50],
            ),
        )

    if reason == HitlReason.DRAFT_LOOP_EXCEEDED:
        sup = _feedback_lines(list(state.get("draft_feedback") or []))
        sup.extend(_feedback_lines(list(state.get("reader_feedback") or [])))
        issue = "內文審核多次未過；請依退件理由修改正文或調整抽取提示後重試。"
        return HitlContextPayload(
            primary_issue=issue,
            supervisor_feedbacks=sup[:24],
            conflict_notes=[],
            problematic_draft_snippet=_snippet(draft),
            context_metadata=HitlContextMetadata(payload_type="draft_loop"),
        )

    if reason == HitlReason.CONTEXT_LENGTH_EXCEEDED:
        est = int(state.get("context_overflow_char_estimate") or 0)
        internal = state.get("graph_rag_context_tier")
        prod = product_context_tier_from_internal(int(internal) if internal is not None else None)
        issue = f"組裝上下文超過預算（估計約 {est} 字元）；請選擇較激進的瘦身層級。"
        return HitlContextPayload(
            primary_issue=issue,
            supervisor_feedbacks=[],
            conflict_notes=[],
            problematic_draft_snippet="",
            context_metadata=HitlContextMetadata(
                payload_type="context_prune",
                graph_rag_context_tier=prod,
            ),
        )

    sup = _feedback_lines(list(state.get("plan_feedback") or []))
    sup.extend(_feedback_lines(list(state.get("draft_feedback") or [])))
    return HitlContextPayload(
        primary_issue=f"流程暫停：{reason or 'HITL'}",
        supervisor_feedbacks=sup[:16],
        conflict_notes=[],
        problematic_draft_snippet=_snippet(draft) if draft else "",
        context_metadata=HitlContextMetadata(payload_type="generic"),
    )
