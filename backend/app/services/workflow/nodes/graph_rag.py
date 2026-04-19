from __future__ import annotations

from app.domain.schema import GraphQueryRequest, NodeType, StoryCastMemberStored
from app.services.workflow.continuity import (
    build_continuity_packet,
    format_local_enforced_rules_block,
    resolve_pov_character_id,
    resolve_pov_location_node_id,
)
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
        location_id = resolve_pov_location_node_id(
            graph_snapshot,
            resolved_pov_character_id,
            state["active_epoch_id"],
        )
        node_names = {n.node_id: n.canonical_name for n in graph_snapshot.nodes}
        location_display = (continuity.get("last_known_location") or "").strip()
        if not location_display and location_id:
            location_display = (node_names.get(location_id) or location_id).strip()
        enforced = context.graph_store.list_enforced_rules_for_context(
            state["story_id"],
            location_id,
            state["active_epoch_id"],
            resolved_pov_character_id,
        )
        local_enforced_rules_context = format_local_enforced_rules_block(enforced, location_display)
        bible_context = context.bible_service.compile_context(
            (story.get("bible_json") or {}) if story else {},
            macro_author_notes=str(story.get("macro_author_notes") or "") if story else "",
        )
        cast_index: dict[str, dict] = {}
        cast_full: dict[str, dict] = {}
        for raw in (story.get("cast_json") or []) if story else []:
            if not isinstance(raw, dict):
                continue
            try:
                member = StoryCastMemberStored.model_validate(raw)
            except Exception:
                continue
            cast_index[member.node_id] = {
                "name": member.canonical_name,
                "personality": member.personality,
                "speech_style": member.speech_style,
                "fatal_flaw": member.fatal_flaw,
                "habit": member.quirks_and_habits,
            }
            cast_full[member.node_id] = member.model_dump(mode="json")
        slim_cards = [
            {"node_id": node.node_id, **cast_index[node.node_id]}
            for node in graph_snapshot.nodes
            if node.node_type in {NodeType.CHARACTER, NodeType.PERSONA} and node.node_id in cast_index
        ]
        full_cards = [
            cast_full[node.node_id]
            for node in graph_snapshot.nodes
            if node.node_type in {NodeType.CHARACTER, NodeType.PERSONA} and node.node_id in cast_full
        ]
        gc_max, vc_max = _tier_truncate_limits(tier)
        graph_context = truncate_json_payload(
            {
                "graph_snapshot": graph_snapshot.model_dump(mode="json"),
                "cast_slim_view": slim_cards,
            },
            max_chars=gc_max,
        )
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
            + len(local_enforced_rules_context)
        )
        last_out = {
            "pov_character_id": resolved_pov_character_id,
            "bible_context": bible_context,
            "graph_context": graph_context,
            "vector_context": vector_context,
            "local_enforced_rules_context": local_enforced_rules_context,
            "graph_rag_context_tier": tier,
            "context_overflow_char_estimate": total,
            "context_hitl_required": False,
            "cast_slim_view": slim_cards,
            "cast_full_view": full_cards,
            **continuity,
        }
        if total <= _CONTEXT_CHAR_BUDGET:
            return last_out
        tier -= 1

    assert last_out is not None
    last_out["context_hitl_required"] = True
    return last_out
