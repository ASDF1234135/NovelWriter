from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.domain.schema import EventOutline
from app.domain.state import (
    SafeAuthorPayload,
    SafePlannerPayload,
    SafeSupervisorPayload,
    planned_nodes_to_mandatory_entities,
)
from app.services.workflow.constants import (
    PLAN_SUPERVISOR_BIBLE_CAP,
    PLAN_SUPERVISOR_ENDING_BOUNDARY_CAP,
    PLAN_SUPERVISOR_EVENT_DESC_CAP,
    PLAN_SUPERVISOR_GRAPH_CAP,
    PLAN_SUPERVISOR_MAX_BEATS_IN_PROMPT,
    PLAN_SUPERVISOR_MAX_EVENTS_IN_PROMPT,
    PLAN_SUPERVISOR_NARRATIVE_SCRIPT_CAP,
    PLAN_SUPERVISOR_PREVIOUS_SUMMARY_CAP,
    PLAN_SUPERVISOR_RECENT_CONTEXT_CAP,
    PLAN_SUPERVISOR_VECTOR_CAP,
    PLAN_SUPERVISOR_BEAT_STRING_CAP,
    VISIBLE_UNACHIEVED_ANCHOR_LIMIT,
)
from app.services.workflow.utils import normalized_text_length


def visible_unachieved_anchors(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Sliding window: first N unfinished anchors (ordered like list_anchors / state)."""
    anchors = state.get("unachieved_anchors") or []
    return list(anchors[:VISIBLE_UNACHIEVED_ANCHOR_LIMIT])


def build_planner_payload(state: dict, story: dict | None = None, volumes: list[dict] | None = None) -> SafePlannerPayload:
    settings = get_settings()
    target_anchor = _resolve_target_anchor(state)
    current_volume = _resolve_current_volume(state["chapter_id"], volumes or [])
    window = visible_unachieved_anchors(state)
    upcoming = [
        {
            "anchor_id": a.get("anchor_id"),
            "title": a.get("title"),
            "chapter_target": a.get("chapter_target"),
        }
        for a in window
    ]
    return SafePlannerPayload(
        active_epoch_id=state["active_epoch_id"],
        pov_character_id=state["pov_character_id"],
        narrative_directive=state["narrative_directive"],
        target_anchor_id=state.get("target_anchor_id"),
        story_premise=(story or {}).get("premise", ""),
        current_volume_title=(current_volume or {}).get("title", ""),
        current_volume_summary=(current_volume or {}).get("summary", ""),
        current_anchor_title=(target_anchor or {}).get("title", ""),
        current_anchor_description=(target_anchor or {}).get("description", ""),
        upcoming_unachieved_anchors=upcoming,
        graph_context=state["graph_context"],
        vector_context=state["vector_context"],
        bible_context=state["bible_context"],
        previous_chapter_summary=state.get("previous_chapter_summary", ""),
        recent_chapter_context=state.get("recent_chapter_context", ""),
        last_known_location=state.get("last_known_location", ""),
        previous_attempt_ground_truth_events=[
            EventOutline.model_validate(event) for event in state.get("ground_truth_events", [])
        ],
        previous_attempt_narrative_script=state.get("narrative_script", ""),
        continuity_notes=state.get("continuity_notes", []),
        recent_entity_names=state.get("recent_entity_names", []),
        prior_feedback=state["plan_feedback"],
        default_chapter_words=int(state.get("target_word_count") or settings.default_chapter_words),
        chapter_word_min=settings.chapter_word_min,
        chapter_word_max=settings.chapter_word_max,
        chapter_type=str(state.get("chapter_type") or "PLOT_DRIVEN"),
        b_story_directive=state.get("b_story_directive"),
        new_elements_to_introduce=list(state.get("new_elements_to_introduce") or []),
        distance_to_anchor=state.get("distance_to_anchor"),
        active_b_stories=list(state.get("active_b_stories") or []),
    )


def build_author_payload(state: dict) -> SafeAuthorPayload:
    target_word_count = state["target_word_count"]
    nmin = int(state.get("normalized_length_min") or 0)
    nmax = int(state.get("normalized_length_max") or 0)
    if nmin <= 0 or nmax <= 0:
        nmin = int(target_word_count * 0.65)
        nmax = int(target_word_count * 1.35)
    mandatory = planned_nodes_to_mandatory_entities(list(state.get("planned_graph_nodes") or []))
    return SafeAuthorPayload(
        narrative_script=state["narrative_script"],
        chapter_start_location=state.get("chapter_start_location", ""),
        author_goal=state.get("author_goal", ""),
        must_include_beats=state.get("must_include_beats", []),
        reader_visible_facts=state.get("reader_visible_facts", []),
        reader_unresolved_questions=state.get("reader_unresolved_questions", []),
        chapter_end_location_hint=state.get("chapter_end_location_hint", ""),
        ending_state_shift=state.get("ending_state_shift", ""),
        ending_boundary_rule=state.get("ending_boundary_rule", ""),
        forbidden_next_scene_actions=state.get("forbidden_next_scene_actions", []),
        forbidden_reveals=state.get("forbidden_reveals", []),
        tone_direction=state["tone_direction"],
        target_word_count=target_word_count,
        normalized_length_min=nmin,
        normalized_length_max=nmax,
        previous_chapter_summary=state.get("previous_chapter_summary", ""),
        previous_attempt_draft=state.get("current_draft", ""),
        last_known_location=state.get("last_known_location", ""),
        author_safe_continuity_notes=list(state.get("author_safe_continuity_notes") or []),
        recent_entity_names=state.get("recent_entity_names", []),
        draft_feedback=state["draft_feedback"],
        reader_feedback=state["reader_feedback"],
        length_adjustment=state.get("length_adjustment", "NONE"),
        mandatory_new_entities=mandatory,
    )


def build_plan_supervisor_payload(state: dict) -> SafeSupervisorPayload:
    settings = get_settings()
    target_anchor = _resolve_target_anchor(state)
    target_anchor_chapter = target_anchor["chapter_target"] if target_anchor else None
    chapters_until_anchor = (
        target_anchor_chapter - state["chapter_id"]
        if target_anchor_chapter is not None
        else None
    )
    return SafeSupervisorPayload(
        chapter_id=state["chapter_id"],
        current_chapter_id=state["chapter_id"],
        active_epoch_id=state["active_epoch_id"],
        target_anchor_id=state.get("target_anchor_id"),
        target_anchor_chapter=target_anchor_chapter,
        chapters_until_anchor=chapters_until_anchor,
        partial_convergence_allowed=bool(chapters_until_anchor is not None and chapters_until_anchor > 0),
        target_word_count=state.get("target_word_count", 0),
        chapter_word_min=settings.chapter_word_min,
        chapter_word_max=settings.chapter_word_max,
        words_per_beat_floor=settings.plan_supervisor_words_per_beat_floor,
        previous_chapter_summary=state.get("previous_chapter_summary", ""),
        recent_chapter_context=state.get("recent_chapter_context", ""),
        last_known_location=state.get("last_known_location", ""),
        ground_truth_events=[EventOutline.model_validate(event) for event in state["ground_truth_events"]],
        narrative_script=state["narrative_script"],
        chapter_start_location=state.get("chapter_start_location", ""),
        chapter_end_location_hint=state.get("chapter_end_location_hint", ""),
        ending_boundary_rule=state.get("ending_boundary_rule", ""),
        forbidden_next_scene_actions=state.get("forbidden_next_scene_actions", []),
        must_include_beats=state.get("must_include_beats", []),
        graph_context=state["graph_context"],
        vector_context=state["vector_context"],
        bible_context=state["bible_context"],
        chapter_type=str(state.get("chapter_type") or "PLOT_DRIVEN"),
        distance_to_anchor=state.get("distance_to_anchor"),
        b_story_directive=state.get("b_story_directive"),
        new_elements_to_introduce=list(state.get("new_elements_to_introduce") or []),
        proposed_new_nodes=list(state.get("planned_graph_nodes") or []),
    )


def build_draft_supervisor_payload(state: dict) -> SafeSupervisorPayload:
    settings = get_settings()
    target_anchor = _resolve_target_anchor(state)
    target_anchor_chapter = target_anchor["chapter_target"] if target_anchor else None
    chapters_until_anchor = (
        target_anchor_chapter - state["chapter_id"]
        if target_anchor_chapter is not None
        else None
    )
    return SafeSupervisorPayload(
        chapter_id=state["chapter_id"],
        current_chapter_id=state["chapter_id"],
        active_epoch_id=state["active_epoch_id"],
        target_anchor_id=state.get("target_anchor_id"),
        target_anchor_chapter=target_anchor_chapter,
        chapters_until_anchor=chapters_until_anchor,
        partial_convergence_allowed=bool(chapters_until_anchor is not None and chapters_until_anchor > 0),
        target_word_count=state.get("target_word_count", 0),
        chapter_word_min=settings.chapter_word_min,
        chapter_word_max=settings.chapter_word_max,
        words_per_beat_floor=settings.plan_supervisor_words_per_beat_floor,
        normalized_current_draft_length=normalized_text_length(state["current_draft"]),
        previous_chapter_summary=state.get("previous_chapter_summary", ""),
        recent_chapter_context=state.get("recent_chapter_context", ""),
        last_known_location=state.get("last_known_location", ""),
        ground_truth_events=[EventOutline.model_validate(event) for event in state["ground_truth_events"]],
        narrative_script=state["narrative_script"],
        chapter_start_location=state.get("chapter_start_location", ""),
        chapter_end_location_hint=state.get("chapter_end_location_hint", ""),
        ending_boundary_rule=state.get("ending_boundary_rule", ""),
        forbidden_next_scene_actions=state.get("forbidden_next_scene_actions", []),
        must_include_beats=state.get("must_include_beats", []),
        current_draft=state["current_draft"],
        graph_context=state["graph_context"],
        vector_context=state["vector_context"],
        bible_context=state["bible_context"],
        chapter_type=str(state.get("chapter_type") or "PLOT_DRIVEN"),
        distance_to_anchor=state.get("distance_to_anchor"),
        b_story_directive=state.get("b_story_directive"),
        new_elements_to_introduce=list(state.get("new_elements_to_introduce") or []),
        proposed_new_nodes=list(state.get("planned_graph_nodes") or []),
        normalized_length_min=int(state.get("normalized_length_min") or 0),
        normalized_length_max=int(state.get("normalized_length_max") or 0),
        mandatory_new_entities=planned_nodes_to_mandatory_entities(list(state.get("planned_graph_nodes") or [])),
    )


def compact_plan_supervisor_payload_for_prompt(payload: SafeSupervisorPayload) -> str:
    """Shrink JSON embedded in plan_supervisor LLM prompt (full payload may be huge)."""
    events: list[dict[str, Any]] = []
    for event in payload.ground_truth_events[:PLAN_SUPERVISOR_MAX_EVENTS_IN_PROMPT]:
        events.append(
            {
                "event_id": event.event_id,
                "description": (event.description or "")[:PLAN_SUPERVISOR_EVENT_DESC_CAP],
                "caused_by_event_id": event.caused_by_event_id,
            }
        )
    beats: list[str] = []
    for beat in (payload.must_include_beats or [])[:PLAN_SUPERVISOR_MAX_BEATS_IN_PROMPT]:
        beats.append((beat or "")[:PLAN_SUPERVISOR_BEAT_STRING_CAP])
    forbidden = [
        (x or "")[:PLAN_SUPERVISOR_BEAT_STRING_CAP]
        for x in (payload.forbidden_next_scene_actions or [])[:8]
    ]
    compact: dict[str, Any] = {
        "chapter_id": payload.chapter_id,
        "current_chapter_id": payload.current_chapter_id,
        "target_word_count": payload.target_word_count,
        "chapter_word_min": payload.chapter_word_min,
        "chapter_word_max": payload.chapter_word_max,
        "words_per_beat_floor": payload.words_per_beat_floor,
        "target_anchor_id": payload.target_anchor_id,
        "target_anchor_chapter": payload.target_anchor_chapter,
        "partial_convergence_allowed": payload.partial_convergence_allowed,
        "previous_chapter_summary": (payload.previous_chapter_summary or "")[:PLAN_SUPERVISOR_PREVIOUS_SUMMARY_CAP],
        "recent_chapter_context": (payload.recent_chapter_context or "")[:PLAN_SUPERVISOR_RECENT_CONTEXT_CAP],
        "last_known_location": payload.last_known_location,
        "chapter_start_location": payload.chapter_start_location,
        "chapter_end_location_hint": payload.chapter_end_location_hint,
        "ending_boundary_rule": (payload.ending_boundary_rule or "")[:PLAN_SUPERVISOR_ENDING_BOUNDARY_CAP],
        "narrative_script": (payload.narrative_script or "")[:PLAN_SUPERVISOR_NARRATIVE_SCRIPT_CAP],
        "ground_truth_events": events,
        "must_include_beats": beats,
        "forbidden_next_scene_actions": forbidden,
        "graph_context": (payload.graph_context or "")[:PLAN_SUPERVISOR_GRAPH_CAP],
        "vector_context": (payload.vector_context or "")[:PLAN_SUPERVISOR_VECTOR_CAP],
        "bible_context": (payload.bible_context or "")[:PLAN_SUPERVISOR_BIBLE_CAP],
        "chapter_type": payload.chapter_type,
        "distance_to_anchor": payload.distance_to_anchor,
        "b_story_directive": (payload.b_story_directive or "")[:240],
        "new_elements_to_introduce": (payload.new_elements_to_introduce or [])[:8],
        "proposed_new_nodes": (payload.proposed_new_nodes or [])[:3],
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)


def _resolve_target_anchor(state: dict) -> dict | None:
    target_anchor_id = state.get("target_anchor_id")
    if not target_anchor_id:
        return None
    for anchor in state.get("unachieved_anchors", []):
        if anchor.get("anchor_id") == target_anchor_id:
            return anchor
    return None


def _resolve_current_volume(chapter_id: int, volumes: list[dict]) -> dict | None:
    for volume in volumes:
        start = volume.get("chapter_start")
        end = volume.get("chapter_end")
        if isinstance(start, int) and isinstance(end, int) and start <= chapter_id <= end:
            return volume
    return None
