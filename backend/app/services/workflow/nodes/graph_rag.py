from __future__ import annotations

from app.domain.schema import GraphQueryRequest
from app.services.workflow.continuity import build_continuity_packet, resolve_pov_character_id
from app.services.workflow.context import WorkflowContext
from app.services.workflow.utils import truncate_json_payload

# Rough budget for assembled text context (planner + downstream prompts).
_CONTEXT_CHAR_BUDGET = 26_000


def _tier_truncate_limits(tier: int) -> tuple[int, int]:
    if tier >= 2:
        return 6000, 4000
    if tier == 1:
        return 3500, 2500
    return 1800, 1200


def run_graph_rag(state: dict, context: WorkflowContext) -> dict:
    story = context.story_repository.get_story(state["story_id"])
    start_tier = int(state.get("graph_rag_context_tier", 2) or 2)
    start_tier = max(0, min(2, start_tier))

    last_out: dict | None = None
    tier = start_tier
    while tier >= 0:
        request = GraphQueryRequest(
            story_id=state["story_id"],
            active_epoch_id=state["active_epoch_id"],
            pov_character_id=state["pov_character_id"],
            narrative_directive=state["narrative_directive"],
            context_hop_tier=tier,
        )
        graph_snapshot = context.graph_store.query_context(request)
        resolved_pov_character_id = resolve_pov_character_id(state["pov_character_id"], graph_snapshot)
        if resolved_pov_character_id != state["pov_character_id"]:
            request = GraphQueryRequest(
                story_id=state["story_id"],
                active_epoch_id=state["active_epoch_id"],
                pov_character_id=resolved_pov_character_id,
                narrative_directive=state["narrative_directive"],
                context_hop_tier=tier,
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
        bible_context = context.bible_service.compile_context(
            (story.get("bible_json") or {}) if story else {},
            macro_author_notes=str(story.get("macro_author_notes") or "") if story else "",
        )
        gc_max, vc_max = _tier_truncate_limits(tier)
        graph_context = truncate_json_payload(graph_snapshot.model_dump(mode="json"), max_chars=gc_max)
        vector_context = truncate_json_payload(
            {
                "hits": [hit.model_dump() for hit in vector_hits],
                "policy": "Older events may be truncated to keep active causal chain in scope.",
            },
            max_chars=vc_max,
        )
        total = (
            len(bible_context)
            + len(graph_context)
            + len(vector_context)
            + len(continuity.get("previous_chapter_summary") or "")
            + len(continuity.get("recent_chapter_context") or "")
        )
        last_out = {
            "pov_character_id": resolved_pov_character_id,
            "bible_context": bible_context,
            "graph_context": graph_context,
            "vector_context": vector_context,
            "graph_rag_context_tier": tier,
            "context_overflow_char_estimate": total,
            "context_hitl_required": False,
            **continuity,
        }
        if total <= _CONTEXT_CHAR_BUDGET:
            return last_out
        tier -= 1

    assert last_out is not None
    last_out["context_hitl_required"] = True
    return last_out
