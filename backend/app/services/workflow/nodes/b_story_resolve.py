from __future__ import annotations

import json

from app.domain.schema import BStoryResolutionOutput
from app.services.llm import MockLLMClient
from app.services.workflow.chapter_pipeline import extraction_substantiated_event_ids, validate_b_story_resolution
from app.services.workflow.context import WorkflowContext
from app.services.workflow.profiles import get_profile


def _compact_extraction_for_resolve(state: dict) -> str:
    pending = state.get("pending_chapter_extraction") or {}
    entities = pending.get("entities") or []
    rows = [
        {"node_id": e.get("node_id"), "canonical_name": e.get("canonical_name"), "node_type": e.get("node_type")}
        for e in entities[:40]
    ]
    events = state.get("ground_truth_events") or []
    ev_compact = [{"event_id": e.get("event_id"), "description": (e.get("description") or "")[:120]} for e in events[:12]]
    return json.dumps({"entities": rows, "ground_truth_events": ev_compact}, ensure_ascii=False)


def run_b_story_resolve(state: dict, context: WorkflowContext) -> dict:
    gt_ids = {str(e["event_id"]) for e in (state.get("ground_truth_events") or []) if e.get("event_id")}
    pending = state.get("pending_chapter_extraction") or {}
    valid_ids = extraction_substantiated_event_ids(pending, gt_ids)
    active = state.get("active_b_stories") or []
    if not active:
        out = BStoryResolutionOutput(
            resolution_analysis="本章無 active_b_stories 副線池，無需核銷。",
            resolution_evidence_event_ids=[],
            resolved_b_stories=[],
        )
        return {
            "b_story_resolution": out.model_dump(mode="json"),
            "b_story_hitl_required": False,
            "b_story_resolution_hitl_candidate": {},
        }

    if isinstance(context.llm_client, MockLLMClient):
        out = BStoryResolutionOutput(
            resolution_analysis="Mock：未自動核銷任何副線；請在真實 LLM 路徑由模型依抽取事件判定。",
            resolution_evidence_event_ids=[],
            resolved_b_stories=[],
        )
        return {
            "b_story_resolution": out.model_dump(mode="json"),
            "b_story_hitl_required": False,
            "b_story_resolution_hitl_candidate": {},
        }

    profile = get_profile("b_story_resolver")
    payload = _compact_extraction_for_resolve(state)
    stories_json = json.dumps(active, ensure_ascii=False)[:2000]
    prompt = (
        "你是副線核銷員。resolution_evidence_event_ids 只能使用「結構化摘要」中已出現的 event_id："
        "該 id 必須在抽取的 entities.node_id 或 relations 的端點出現，且於本章 ground_truth_events；"
        "不得只用大綱想像證據。\n"
        "若副線尚未在事件中不可逆完結，resolved_b_stories 必須為空。\n"
        "輸出 JSON：resolution_analysis（逐步推理，繁中）, resolution_evidence_event_ids, resolved_b_stories（b_story id 列表）。\n\n"
        f"active_b_stories: {stories_json}\n\n"
        f"結構化摘要: {payload}\n"
    )
    structured, _ = context.llm_client.invoke_json(prompt, BStoryResolutionOutput, profile)
    data_raw = structured.model_dump(mode="json")
    ok, err = validate_b_story_resolution(data_raw, valid_ids)
    had_intent = bool(data_raw.get("resolved_b_stories")) or bool(data_raw.get("resolution_evidence_event_ids"))
    hitl_needed = (not ok) and had_intent
    if not ok:
        structured = BStoryResolutionOutput(
            resolution_analysis=(structured.resolution_analysis or "") + f" [後端拒絕: {err}]",
            resolution_evidence_event_ids=[e for e in structured.resolution_evidence_event_ids if e in valid_ids],
            resolved_b_stories=[],
        )
        data = structured.model_dump(mode="json")
    else:
        data = data_raw
    return {
        "b_story_resolution": data,
        "b_story_hitl_required": hitl_needed,
        "b_story_resolution_hitl_candidate": data_raw if hitl_needed else {},
    }
