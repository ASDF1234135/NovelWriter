from __future__ import annotations

import logging
from typing import Any

from app.domain.schema import ChapterExtractionOutput, ExtractedEntity, ProposedGraphNode

logger = logging.getLogger(__name__)


def extraction_substantiated_event_ids(
    pending_extraction: dict[str, Any],
    ground_truth_event_ids: set[str],
) -> set[str]:
    """
    R2c: event_ids from ground_truth that appear in structured extraction (entities or relations).
    Used so Resolve cannot cite planner-only events that the extractor did not anchor in the draft output.
    """
    found: set[str] = set()
    for e in pending_extraction.get("entities") or []:
        nid = str(e.get("node_id") or "").strip()
        if nid and nid in ground_truth_event_ids:
            found.add(nid)
    for r in pending_extraction.get("relations") or []:
        for key in ("source_node_id", "target_node_id"):
            nid = str(r.get(key) or "").strip()
            if nid in ground_truth_event_ids:
                found.add(nid)
    return found


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _planned_row(row: Any) -> ProposedGraphNode:
    if isinstance(row, ProposedGraphNode):
        return row
    return ProposedGraphNode.model_validate(row)


def remap_planned_entities(
    entities: list[ExtractedEntity],
    planned: list[dict[str, Any]],
    author_surfaces: dict[str, list[str]] | None = None,
) -> tuple[list[ExtractedEntity], list[dict[str, Any]]]:
    """
    Merge extracted entities onto planned node_ids when names/roles align (R1/R5).
    Returns (remapped_entities, remap_warnings).
    """
    if not planned:
        return list(entities), []

    planned_rows = [_planned_row(p) for p in planned]
    planned_by_id = {p.node_id: p for p in planned_rows}
    warnings: list[dict[str, Any]] = []
    out: list[ExtractedEntity] = []
    used_planned: set[str] = set()

    for ent in entities:
        e = ent.model_copy(deep=True)
        if e.node_id in planned_by_id:
            used_planned.add(e.node_id)
            out.append(e)
            continue

        matched_pid: str | None = None
        en = _norm(e.canonical_name)
        for pid, prow in planned_by_id.items():
            if pid in used_planned:
                continue
            pr = _norm(prow.role)
            pc = _norm(prow.canonical_name)
            if pr and (pr in en or en in pr):
                matched_pid = pid
                break
            if pc and (pc in en or en in pc):
                matched_pid = pid
                break
            for al in e.aliases:
                an = _norm(al)
                if pr and (pr in an or an in pr):
                    matched_pid = pid
                    break
                if pc and (pc in an or an in pc):
                    matched_pid = pid
                    break
            if not matched_pid and author_surfaces:
                for surface in author_surfaces.get(pid, []) or []:
                    s = _norm(surface)
                    if not s:
                        continue
                    if s in en or en in s:
                        matched_pid = pid
                        break
                    if pr and (s in pr or pr in s):
                        matched_pid = pid
                        break
                    if pc and (s in pc or pc in s):
                        matched_pid = pid
                        break
                    for al in e.aliases:
                        an = _norm(al)
                        if s in an or an in s:
                            matched_pid = pid
                            break
                    if matched_pid:
                        break
            if matched_pid:
                break

        if matched_pid:
            warnings.append(
                {
                    "type": "remap_merge",
                    "from_id": e.node_id,
                    "to_id": matched_pid,
                }
            )
            e.node_id = matched_pid
            used_planned.add(matched_pid)
            out.append(e)
        else:
            if planned_rows:
                logger.warning(
                    "low_confidence_remap_skipped",
                    extra={
                        "extracted_id": e.node_id,
                        "canonical_name": e.canonical_name,
                        "reason": "no_planned_alias_match",
                    },
                )
            out.append(e)

    return out, warnings


def validate_mandatory_planned_nodes(
    entities: list[ExtractedEntity],
    planned: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """
    R6: every mandatory planned graph node must appear as an entity node_id after remap.
    Returns (ok, missing_node_ids).
    """
    missing: list[str] = []
    entity_ids = {e.node_id for e in entities}
    for row in planned:
        p = _planned_row(row)
        if not p.mandatory:
            continue
        if p.node_id not in entity_ids:
            missing.append(p.node_id)
    return (not missing, missing)


def validate_b_story_resolution(
    resolution: dict[str, Any],
    valid_event_ids: set[str],
) -> tuple[bool, str]:
    """R2c: nuclearization requires evidence; every evidence id must be substantiated in extraction."""
    resolved = [str(x).strip() for x in (resolution.get("resolved_b_stories") or []) if str(x).strip()]
    ev_ids = [str(e).strip() for e in (resolution.get("resolution_evidence_event_ids") or []) if str(e).strip()]
    if resolved and not ev_ids:
        return False, "resolved_b_stories requires non-empty resolution_evidence_event_ids"
    bad = [e for e in ev_ids if e not in valid_event_ids]
    if bad:
        return False, f"resolution_evidence_event_ids not substantiated in extraction: {bad}"
    return True, ""


def apply_resolution_to_extraction(
    extraction: ChapterExtractionOutput,
    planned: list[dict[str, Any]],
    author_surfaces: dict[str, list[str]] | None = None,
) -> ChapterExtractionOutput:
    """Run remap on a full extraction payload."""
    remapped, warnings = remap_planned_entities(list(extraction.entities), planned, author_surfaces)
    if warnings:
        for w in warnings:
            logger.warning("remap_planned_entities", extra=w)
    return extraction.model_copy(update={"entities": remapped})
