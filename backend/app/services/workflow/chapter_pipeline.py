from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any

from app.domain.schema import (
    ChapterExtractionOutput,
    ExtractedEntity,
    ExtractedRelation,
    ProposedGraphNode,
)
from app.services.workflow.utils import latin_word_boundary_search, looks_like_latin_word

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


def _plausible_contains_match(a: str, b: str, *, min_len: int = 4) -> bool:
    aa = _norm(a)
    bb = _norm(b)
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    if len(aa) < min_len or len(bb) < min_len:
        return False
    if looks_like_latin_word(aa):
        return latin_word_boundary_search(aa, b or "")
    if looks_like_latin_word(bb):
        return latin_word_boundary_search(bb, a or "")
    return aa in bb or bb in aa


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
            if pr and _plausible_contains_match(pr, en):
                matched_pid = pid
                break
            if pc and _plausible_contains_match(pc, en):
                matched_pid = pid
                break
            for al in e.aliases:
                an = _norm(al)
                if pr and _plausible_contains_match(pr, an):
                    matched_pid = pid
                    break
                if pc and _plausible_contains_match(pc, an):
                    matched_pid = pid
                    break
            if not matched_pid and author_surfaces:
                for surface in author_surfaces.get(pid, []) or []:
                    s = _norm(surface)
                    if not s:
                        continue
                    if _plausible_contains_match(s, en):
                        matched_pid = pid
                        break
                    if pr and _plausible_contains_match(s, pr):
                        matched_pid = pid
                        break
                    if pc and _plausible_contains_match(s, pc):
                        matched_pid = pid
                        break
                    for al in e.aliases:
                        an = _norm(al)
                        if _plausible_contains_match(s, an):
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
    *,
    skip_mandatory_node_ids: set[str] | None = None,
) -> tuple[bool, list[str]]:
    """
    R6: every mandatory planned graph node must appear as an entity node_id after remap.
    Returns (ok, missing_node_ids).
    """
    skip = skip_mandatory_node_ids or set()
    missing: list[str] = []
    entity_ids = {e.node_id for e in entities}
    for row in planned:
        p = _planned_row(row)
        if not p.mandatory:
            continue
        if p.node_id in skip:
            continue
        if p.node_id not in entity_ids:
            missing.append(p.node_id)
    return (not missing, missing)


def build_manual_entity_remap_map(remaps: list[dict[str, Any]]) -> dict[str, str]:
    """Parse manual_entity_remap rows into from_node_id -> to_node_id."""
    m: dict[str, str] = {}
    for row in remaps or []:
        if not isinstance(row, dict):
            continue
        a = str(row.get("from_node_id") or row.get("from_id") or "").strip()
        b = str(row.get("to_node_id") or row.get("to_id") or "").strip()
        if a and b:
            m[a] = b
    return m


def _follow_remap_chain(node_id: str, id_map: dict[str, str]) -> str:
    """Resolve transitive remaps (a->b, b->c)."""
    y = node_id
    seen: set[str] = set()
    while y in id_map and y not in seen:
        seen.add(y)
        y = id_map[y]
    return y


def resolve_endpoint_after_remaps(
    node_id: str,
    manual_m: dict[str, str],
    planned_m: dict[str, str],
) -> str:
    """Apply manual remap chain, then planned remap chain, to a graph node_id."""
    if not (node_id or "").strip():
        return node_id
    y = _follow_remap_chain(node_id.strip(), manual_m)
    return _follow_remap_chain(y, planned_m)


def apply_endpoint_rewrites_to_relations(
    relations: list[ExtractedRelation],
    manual_m: dict[str, str],
    planned_m: dict[str, str],
) -> list[ExtractedRelation]:
    """Rewrite relation source/target node_ids after the same id merges applied to entities."""
    if not manual_m and not planned_m:
        return list(relations)
    out: list[ExtractedRelation] = []
    for rel in relations:
        r = rel.model_copy(deep=True)
        if r.source_node_id:
            r.source_node_id = resolve_endpoint_after_remaps(r.source_node_id, manual_m, planned_m)
        if r.target_node_id:
            r.target_node_id = resolve_endpoint_after_remaps(r.target_node_id, manual_m, planned_m)
        out.append(r)
    return out


def _planned_remap_dict_from_warnings(warnings: list[dict[str, Any]]) -> dict[str, str]:
    m: dict[str, str] = {}
    for w in warnings:
        if w.get("type") != "remap_merge":
            continue
        a = str(w.get("from_id") or "").strip()
        b = str(w.get("to_id") or "").strip()
        if a and b:
            m[a] = b
    return m


def apply_manual_entity_remap(
    entities: list[ExtractedEntity],
    remaps: list[dict[str, Any]],
) -> list[ExtractedEntity]:
    """Apply human mappings from_node_id -> to_node_id on extracted entities."""
    m = build_manual_entity_remap_map(remaps)
    if not m:
        return entities
    out: list[ExtractedEntity] = []
    for ent in entities:
        e = ent.model_copy(deep=True)
        if e.node_id in m:
            e.node_id = _follow_remap_chain(e.node_id, m)
        out.append(e)
    return out


def _fuzzy_score(a: str, b: str) -> int:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0
    if a == b:
        return 100
    if _plausible_contains_match(a, b, min_len=5):
        return 85
    return int(100 * SequenceMatcher(None, a, b).ratio())


def build_extraction_remap_hints(
    entities: list[ExtractedEntity],
    missing_planned_ids: list[str],
    planned: list[dict[str, Any]],
    limit_per_missing: int = 5,
) -> list[dict[str, Any]]:
    """
    For HITL UI: each missing mandatory planned id with top extracted entity candidates by name similarity.
    """
    if not missing_planned_ids or not entities:
        return []
    planned_by_id = {_planned_row(p).node_id: _planned_row(p) for p in planned}
    hints: list[dict[str, Any]] = []
    for mid in missing_planned_ids:
        prow = planned_by_id.get(mid)
        pname = _norm(prow.canonical_name) if prow else ""
        prole = _norm(prow.role) if prow else ""
        scored: list[tuple[int, ExtractedEntity]] = []
        for ent in entities:
            if ent.node_id == mid:
                continue
            s1 = _fuzzy_score(pname, ent.canonical_name) if pname else 0
            s2 = _fuzzy_score(prole, ent.canonical_name) if prole else 0
            s3 = (
                max((_fuzzy_score(pname, al) for al in ent.aliases), default=0) if pname and ent.aliases else 0
            )
            score = max(s1, s2, s3)
            if score > 0:
                scored.append((score, ent))
        scored.sort(key=lambda x: -x[0])
        top = scored[:limit_per_missing]
        hints.append(
            {
                "missing_planned_node_id": mid,
                "planned_canonical_name": prow.canonical_name if prow else "",
                "planned_role": prow.role if prow else "",
                "candidate_extracted": [
                    {
                        "node_id": e.node_id,
                        "canonical_name": e.canonical_name,
                        "score": sc,
                    }
                    for sc, e in top
                ],
            }
        )
    return hints


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
    """Run planned remap on entities and matching relation endpoints (no manual remap)."""
    remapped, warnings = remap_planned_entities(list(extraction.entities), planned, author_surfaces)
    if warnings:
        for w in warnings:
            logger.warning("remap_planned_entities", extra=w)
    planned_m = _planned_remap_dict_from_warnings(warnings)
    relations = apply_endpoint_rewrites_to_relations(list(extraction.relations), {}, planned_m)
    return extraction.model_copy(update={"entities": remapped, "relations": relations})


def apply_full_extraction_remaps(
    extraction: ChapterExtractionOutput,
    manual_remaps: list[dict[str, Any]],
    planned: list[dict[str, Any]],
    author_surfaces: dict[str, list[str]] | None = None,
) -> ChapterExtractionOutput:
    """Apply manual entity remap, then planned remap, and rewrite relation endpoints consistently."""
    manual_m = build_manual_entity_remap_map(manual_remaps)
    entities = apply_manual_entity_remap(list(extraction.entities), manual_remaps)
    remapped, warnings = remap_planned_entities(entities, planned, author_surfaces)
    if warnings:
        for w in warnings:
            logger.warning("remap_planned_entities", extra=w)
    planned_m = _planned_remap_dict_from_warnings(warnings)
    relations = apply_endpoint_rewrites_to_relations(list(extraction.relations), manual_m, planned_m)
    return extraction.model_copy(update={"entities": remapped, "relations": relations})
