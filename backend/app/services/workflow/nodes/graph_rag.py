from __future__ import annotations

from app.domain.schema import GraphQueryRequest
from app.services.workflow.continuity import build_continuity_packet, resolve_pov_character_id
from app.services.workflow.context import WorkflowContext
from app.services.workflow.utils import truncate_json_payload


def run_graph_rag(state: dict, context: WorkflowContext) -> dict:
    story = context.story_repository.get_story(state["story_id"])
    request = GraphQueryRequest(
        story_id=state["story_id"],
        active_epoch_id=state["active_epoch_id"],
        pov_character_id=state["pov_character_id"],
        narrative_directive=state["narrative_directive"],
    )
    graph_snapshot = context.graph_store.query_context(request)
    resolved_pov_character_id = resolve_pov_character_id(state["pov_character_id"], graph_snapshot)
    if resolved_pov_character_id != state["pov_character_id"]:
        request = GraphQueryRequest(
            story_id=state["story_id"],
            active_epoch_id=state["active_epoch_id"],
            pov_character_id=resolved_pov_character_id,
            narrative_directive=state["narrative_directive"],
        )
        graph_snapshot = context.graph_store.query_context(request)
    vector_hits = context.vector_store.search(state["story_id"], state["narrative_directive"])
    recent_chapters = context.story_repository.list_recent_chapters_with_content(
        state["story_id"],
        state["chapter_id"],
        limit=2,
    )
    continuity = build_continuity_packet(
        recent_chapters,
        graph_snapshot,
        vector_hits,
        pov_character_id=resolved_pov_character_id,
        active_epoch_id=state["active_epoch_id"],
    )
    bible_context = context.bible_service.compile_context(story["bible_json"] if story else {})
    graph_context = truncate_json_payload(graph_snapshot.model_dump(mode="json"), max_chars=6000)
    vector_context = truncate_json_payload(
        {
            "hits": [hit.model_dump() for hit in vector_hits],
            "policy": "Older events may be truncated to keep active causal chain in scope.",
        },
        max_chars=4000,
    )
    return {
        "pov_character_id": resolved_pov_character_id,
        "bible_context": bible_context,
        "graph_context": graph_context,
        "vector_context": vector_context,
        **continuity,
    }
