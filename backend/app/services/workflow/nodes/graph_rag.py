from __future__ import annotations

from app.domain.schema import GraphQueryRequest, NodeType, StoryCastMemberStored
from app.services.graph_rag_service import GraphRAGService
from app.services.llm import LLMProviderError, MockLLMClient
from app.services.workflow.anchor_graph_eval import run_anchor_preflight
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


def _build_aligned_chunk_context(graph_snapshot, vector_hits: list, *, max_chars: int = 5000) -> str:
    """
    Build aligned chunk context with required fallback semantics:
    - If hit.chunk_id aligns to graph event/edge chunk_ids -> group by event_id:
      1 event summary + multiple supporting text chunks
    - If cannot align -> keep raw text as background ambience (never drop)
    """
    # Index edges by chunk_ids for quick lookup.
    chunk_to_edges: dict[str, list] = {}
    for e in getattr(graph_snapshot, "edges", []) or []:
        attrs = getattr(e, "attributes", None) or {}
        chunk_ids = attrs.get("chunk_ids") or []
        if isinstance(chunk_ids, str):
            chunk_ids = [chunk_ids]
        if not isinstance(chunk_ids, list):
            continue
        for cid in chunk_ids:
            cid_s = str(cid).strip()
            if cid_s:
                chunk_to_edges.setdefault(cid_s, []).append(e)

    # Index event nodes by chunk_ids stored on node metadata/properties (tolerate absence).
    chunk_to_events: dict[str, list] = {}
    for n in getattr(graph_snapshot, "nodes", []) or []:
        if getattr(n, "node_type", None) is None:
            continue
        if str(getattr(n, "node_type", "")) != "NodeType.EVENT" and str(getattr(n, "node_type", "")) != "EVENT":
            continue
        chunk_ids = getattr(n, "chunk_ids", None) or []
        if isinstance(chunk_ids, str):
            chunk_ids = [chunk_ids]
        if isinstance(chunk_ids, list):
            for cid in chunk_ids:
                cid_s = str(cid).strip()
                if cid_s:
                    chunk_to_events.setdefault(cid_s, []).append(n)

    grouped: dict[str, dict[str, object]] = {}
    ambience: list[str] = []
    for hit in vector_hits:
        meta = getattr(hit, "metadata", {}) or {}
        cid = str(meta.get("chunk_id") or "").strip()
        text = str(getattr(hit, "text_chunk", "") or "").strip()
        if not text:
            continue
        aligned_events = chunk_to_events.get(cid, []) if cid else []
        aligned_edges = chunk_to_edges.get(cid, []) if cid else []
        if aligned_events:
            for ev in aligned_events:
                ev_id = str(getattr(ev, "node_id", "") or "").strip() or "event_unknown"
                entry = grouped.setdefault(ev_id, {"event": ev, "texts": []})
                entry["texts"].append(text)
        elif aligned_edges:
            # No event node alignment; treat as edge-triggered context.
            # Group under a synthetic key so we don't drop it.
            key = f"edge:{cid or 'unknown'}"
            entry = grouped.setdefault(key, {"event": None, "texts": [], "edges": aligned_edges})
            entry["texts"].append(text)
        else:
            ambience.append(text)

    lines: list[str] = []
    if grouped:
        lines.append("【Aligned Evidence Chunks】")
        for key, payload in list(grouped.items())[:10]:
            ev = payload.get("event")
            if ev is not None:
                ev_id = str(getattr(ev, "node_id", "") or "").strip() or key
                ev_name = str(getattr(ev, "canonical_name", "") or "").strip()
                header = f"- event_id={ev_id}"
                if ev_name:
                    header += f" | {ev_name}"
                lines.append(header)
            else:
                lines.append(f"- {key}")
            texts = payload.get("texts") or []
            for t in texts[:4]:
                lines.append(f"  - {t[:400]}")
    if ambience:
        lines.append("")
        lines.append("【背景語意/氛圍 (Unaligned but retained)】")
        for t in ambience[:8]:
            lines.append(f"- {t[:400]}")
    out = "\n".join(lines).strip()
    return out if len(out) <= max_chars else out[: max_chars - 1] + "…"


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
        aligned_chunk_context = _build_aligned_chunk_context(graph_snapshot, vector_hits, max_chars=5000)
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
            output_language=context.output_language,
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
        bible_context = str(state.get("bible_context") or "").strip()
        if not bible_context:
            bible_context = context.bible_service.compile_full_context(
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
        graph_rag_svc = GraphRAGService(
            graph_store=context.graph_store,
            vector_store=context.vector_store,
            llm=context.llm_client,
        )
        chapter_goal = str(state.get("chapter_outline") or state.get("author_chapter_plan") or "").strip()
        try:
            raw_background = graph_rag_svc.summarize_story_background(
                narrative_directive=str(state.get("narrative_directive") or "").strip(),
                chapter_goal=chapter_goal,
                story_id=state["story_id"],
                active_epoch_id=state["active_epoch_id"],
                pov_character_id=resolved_pov_character_id,
                output_language=context.output_language,
                top_k=5,
                context_hop_tier=tier,
            )
            text = (raw_background or "").strip()
            graph_context = text if len(text) <= gc_max else text[: max(gc_max - 1, 0)] + "…"
        except LLMProviderError:
            graph_context = truncate_json_payload(
                {
                    "graph_background_fallback": True,
                    "graph": graph_rag_svc.prune_graph_snapshot(graph_snapshot),
                },
                max_chars=gc_max,
            )
        anchor_preflight_evaluations: list[dict] = []
        node_by_id = {
            str(n.get("id") or ""): n
            for n in (state.get("anchor_nodes") or [])
            if isinstance(n, dict) and str(n.get("id") or "").strip()
        }
        if not isinstance(context.llm_client, MockLLMClient):
            preflight_md, anchor_preflight_evaluations = run_anchor_preflight(
                graph_rag=graph_rag_svc,
                state=state,
                node_by_id=node_by_id,
                resolved_pov_character_id=resolved_pov_character_id,
            )
            if preflight_md:
                combined = f"{preflight_md}\n\n---\n\n{graph_context}"
                graph_context = combined if len(combined) <= gc_max else combined[: max(gc_max - 1, 0)] + "…"
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
            + len(aligned_chunk_context)
            + len(continuity.get("previous_chapter_summary") or "")
            + len(continuity.get("recent_chapter_context") or "")
            + len(local_enforced_rules_context)
        )
        last_out = {
            "pov_character_id": resolved_pov_character_id,
            "bible_context": bible_context,
            "graph_context": graph_context,
            "vector_context": vector_context,
            "chunk_context": aligned_chunk_context,
            "local_enforced_rules_context": local_enforced_rules_context,
            "graph_rag_context_tier": tier,
            "context_overflow_char_estimate": total,
            "context_hitl_required": False,
            "cast_slim_view": slim_cards,
            "cast_full_view": full_cards,
            "anchor_preflight_evaluations": anchor_preflight_evaluations,
            **continuity,
        }
        if total <= _CONTEXT_CHAR_BUDGET:
            return last_out
        tier -= 1

    assert last_out is not None
    last_out["context_hitl_required"] = True
    return last_out
