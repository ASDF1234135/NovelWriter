from __future__ import annotations

import json

from app.domain.schema import BStoryResolutionOutput
from app.services.llm import MockLLMClient
from app.services.workflow.chapter_pipeline import extraction_substantiated_event_ids, validate_b_story_resolution
from app.services.workflow.context import WorkflowContext
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile


def _compact_extraction_for_resolve(state: dict) -> str:
    pending = state.get("pending_chapter_extraction") or {}
    entities = pending.get("entities") or []
    rows = [
        {"node_id": e.get("node_id"), "canonical_name": e.get("canonical_name"), "node_type": e.get("node_type")}
        for e in entities[:40]
    ]
    rels = pending.get("relations") or []
    rel_compact = [
        {
            "source_node_id": r.get("source_node_id"),
            "target_node_id": r.get("target_node_id"),
            "relation_type": r.get("relation_type"),
        }
        for r in rels[:80]
        if isinstance(r, dict)
    ]
    events = state.get("ground_truth_events") or []
    ev_compact = [{"event_id": e.get("event_id"), "description": (e.get("description") or "")[:120]} for e in events[:12]]
    return json.dumps(
        {"entities": rows, "relations": rel_compact, "ground_truth_events": ev_compact},
        ensure_ascii=False,
    )


def run_b_story_resolve(state: dict, context: WorkflowContext) -> dict:
    gt_ids = {str(e["event_id"]) for e in (state.get("ground_truth_events") or []) if e.get("event_id")}
    pending = state.get("pending_chapter_extraction") or {}
    valid_ids = extraction_substantiated_event_ids(pending, gt_ids)
    active = state.get("active_b_stories") or []
    if not active:
        out = BStoryResolutionOutput(
            resolution_analysis="No active_b_stories pool for this chapter; nothing to resolve.",
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
            resolution_analysis="Mock: no B-stories auto-resolved; real LLM path should decide from extracted events.",
            resolution_evidence_event_ids=[],
            resolved_b_stories=[],
        )
        return {
            "b_story_resolution": out.model_dump(mode="json"),
            "b_story_hitl_required": False,
            "b_story_resolution_hitl_candidate": {},
        }

    profile = augment_profile_system_prompt(
        get_profile("b_story_resolver"), context.output_language
    )
    payload = _compact_extraction_for_resolve(state)
    stories_json = json.dumps(active, ensure_ascii=False)[:2000]
    prompt = (
        "You are the B-story resolver. resolution_evidence_event_ids may ONLY use event_ids present in the structured summary: "
        "each id must appear on extracted entities.node_id or relation endpoints (source_node_id / target_node_id), and also exist in this chapter's ground_truth_events; "
        "do not invent evidence from outline imagination alone.\n"
        "If a B-story is not irreversibly completed in events, resolved_b_stories must be empty.\n"
        "Return JSON: resolution_analysis (stepwise reasoning, in the story output_language), resolution_evidence_event_ids, resolved_b_stories (list of b_story ids).\n\n"
        f"active_b_stories: {stories_json}\n\n"
        f"structured_summary: {payload}\n"
    )
    try:
        structured, _ = context.llm_client.invoke_json(prompt, BStoryResolutionOutput, profile)
        data_raw = structured.model_dump(mode="json")
    except Exception as exc:
        out = BStoryResolutionOutput(
            resolution_analysis=f"B-story resolver LLM call failed; no auto-resolution. ({str(exc)})",
            resolution_evidence_event_ids=[],
            resolved_b_stories=[],
        )
        data = out.model_dump(mode="json")
        return {
            "b_story_resolution": data,
            "b_story_hitl_required": False,
            "b_story_resolution_hitl_candidate": {},
        }
    ok, err = validate_b_story_resolution(data_raw, valid_ids)
    had_intent = bool(data_raw.get("resolved_b_stories")) or bool(data_raw.get("resolution_evidence_event_ids"))
    hitl_needed = (not ok) and had_intent
    if not ok:
        structured = BStoryResolutionOutput(
            resolution_analysis=(structured.resolution_analysis or "") + f" [backend rejected: {err}]",
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
