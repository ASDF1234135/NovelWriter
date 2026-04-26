from __future__ import annotations

from typing import Any

from app.domain.schema import (
    EventOutline,
    GraphQueryRequest,
    LengthAdjustment,
    ProposedGraphNode,
    SuggestionType,
    ViolationType,
)
from app.services.workflow.chapter_pipeline import (
    apply_full_extraction_remaps,
    build_extraction_remap_hints,
    validate_mandatory_planned_nodes,
)
from app.services.workflow.context import WorkflowContext
from app.services.workflow.extraction import extract_chapter_artifacts


def _author_surface_map(state: dict) -> dict[str, list[str]]:
    raw = state.get("author_extraction_surface_hints") or []
    out: dict[str, list[str]] = {}
    for h in raw:
        if not isinstance(h, dict):
            continue
        nid = str(h.get("node_id") or "").strip()
        if not nid:
            continue
        forms = [s for s in (h.get("surface_forms") or []) if isinstance(s, str) and s]
        if forms:
            out[nid] = forms
    return out


def _planned_by_node_id(planned: list[Any]) -> dict[str, ProposedGraphNode]:
    out: dict[str, ProposedGraphNode] = {}
    for row in planned:
        try:
            p = ProposedGraphNode.model_validate(row)
            out[p.node_id] = p
        except Exception:
            continue
    return out


def _format_missing_mandatory_feedback(
    missing_ids: list[str], planned: list[Any]
) -> tuple[str, list[dict[str, Any]]]:
    by_id = _planned_by_node_id(planned)
    lines: list[str] = []
    structured: list[dict[str, Any]] = []
    for nid in missing_ids:
        p = by_id.get(nid)
        if p:
            nt = p.node_type.value if hasattr(p.node_type, "value") else str(p.node_type)
            brief = (p.writing_brief or "").strip()
            if len(brief) > 200:
                brief = brief[:200] + "…"
            line = f"- node_id={nid} | type={nt} | planned_name={p.canonical_name!r} | mission_role={p.role!r}"
            if brief:
                line += f" | writing_brief_excerpt={brief}"
            lines.append(line)
            structured.append(
                {
                    "node_id": nid,
                    "node_type": nt,
                    "canonical_name": p.canonical_name,
                    "role": p.role,
                }
            )
        else:
            lines.append(f"- node_id={nid} | (no matching row in planned_graph_nodes)")
            structured.append(
                {
                    "node_id": nid,
                    "node_type": "",
                    "canonical_name": "",
                    "role": "",
                    "note": "not_in_planned",
                }
            )

    body = "\n".join(lines)
    intro = (
        "These mandatory planned graph nodes could not be aligned to extracted node_ids after prose extraction "
        "(too oblique, surface names diverge too far from the plan, or the extraction pipeline missed them):"
    )
    suffix = (
        "Add clearer in-text names, looks, or actions consistent with the mission card for those roles/locations; "
        "when needed, extend surface hints to include exact substrings that literally appear in the draft."
    )
    msg = f"{intro}\n{body}\n{suffix}"
    return msg, structured


def _extraction_fallback_notice(diag: dict[str, Any] | None) -> str:
    if not diag:
        return ""
    steps = diag.get("steps")
    if not isinstance(steps, dict):
        return ""
    labels: list[str] = []
    ent = steps.get("entity_extractor")
    if isinstance(ent, dict) and ent.get("fallback"):
        labels.append("entity extraction")
    mem = steps.get("chapter_memory_extractor")
    if isinstance(mem, dict) and mem.get("fallback"):
        labels.append("chapter memory extraction")
    if not labels:
        return ""
    joined = " and ".join(labels)
    return (
        f"[System notice] This chapter's {joined} ran in fallback mode; structured outputs may be less reliable. "
        "If alignment keeps failing, check draft extractability, API health, and model output.\n\n"
    )


def run_extraction_gate(state: dict, context: WorkflowContext) -> dict:
    """
    Extract + remap mandatory planned ids + R6 validation.
    On failure: route back to author with MISSING_MANDATORY_ENTITY_MAPPING.
    """
    chapter_content = state.get("best_draft_content") or state.get("current_draft") or ""
    events = [EventOutline.model_validate(event) for event in state.get("ground_truth_events") or []]
    tier = int(state.get("graph_rag_context_tier", 2) or 2)
    graph_snapshot = context.graph_store.query_context(
        GraphQueryRequest(
            story_id=state["story_id"],
            active_epoch_id=state["active_epoch_id"],
            pov_character_id=state["pov_character_id"],
            narrative_directive=state.get("narrative_directive", ""),
            context_hop_tier=max(0, min(2, tier)),
        )
    )
    extracted, diag = extract_chapter_artifacts(state, context, graph_snapshot, chapter_content, events)
    planned = list(state.get("planned_graph_nodes") or [])
    extracted = apply_full_extraction_remaps(
        extracted,
        list(state.get("manual_entity_remap") or []),
        planned,
        _author_surface_map(state),
    )
    skips = {str(x).strip() for x in (state.get("mandatory_extraction_skips") or []) if str(x).strip()}
    ok, missing = validate_mandatory_planned_nodes(
        list(extracted.entities), planned, skip_mandatory_node_ids=skips
    )
    if not ok:
        msg, missing_detail = _format_missing_mandatory_feedback(missing, planned)
        prefix = _extraction_fallback_notice(diag if isinstance(diag, dict) else None)
        msg = prefix + msg
        hints = build_extraction_remap_hints(list(extracted.entities), missing, planned)
        return {
            "post_polish_route": "author",
            "pending_chapter_extraction": {},
            "extraction_gate_feedback_entry": {
                "attempt": state.get("draft_retry_count", 0) + 1,
                "violation": [ViolationType.MISSING_MANDATORY_ENTITY_MAPPING.value],
                "suggestion": SuggestionType.REWRITE.value,
                "length_adjustment": LengthAdjustment.NONE.value,
                "message": msg,
                "missing_mandatory_entities": missing_detail,
            },
            "extraction_gate_error": msg,
            "hitl_extraction_remap_hints": hints,
        }

    return {
        "post_polish_route": "anchor_resolve",
        "pending_chapter_extraction": extracted.model_dump(mode="json"),
        "extraction_gate_error": "",
    }
