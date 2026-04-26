from __future__ import annotations

import json

from app.domain.schema import AnchorResolutionOutput
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _anchor_match_score(chapter_text: str, anchor_desc: str) -> float:
    text = _normalize_text(chapter_text)
    desc = _normalize_text(anchor_desc)
    if not text or not desc:
        return 0.0
    tokens = [t for t in desc.replace("，", " ").replace(",", " ").split(" ") if len(t) >= 2]
    if not tokens:
        return 0.0
    hits = sum(1 for token in tokens if token in text)
    return hits / max(1, len(tokens))


def _build_anchor_evidence(chapter_text: str, anchor_id: str, anchor_desc: str) -> dict:
    text = _normalize_text(chapter_text)
    desc = _normalize_text(anchor_desc)
    tokens = [t for t in desc.replace("，", " ").replace(",", " ").split(" ") if len(t) >= 2]
    matched = [t for t in tokens if t in text][:8]
    score = _anchor_match_score(chapter_text, anchor_desc)
    decision = "RESOLVED" if score >= 0.2 else "UNRESOLVED"
    excerpt = ""
    for token in matched:
        pos = text.find(token)
        if pos >= 0:
            excerpt = text[max(0, pos - 80) : pos + 120]
            break
    return {
        "anchor_id": anchor_id,
        "score": round(score, 3),
        "matched_terms": matched,
        "evidence_excerpt": excerpt,
        "decision": decision,
        "decision_reason": (
            "Anchor evidence threshold passed with sufficient semantic token overlap."
            if decision == "RESOLVED"
            else "Anchor evidence insufficient: chapter draft does not clearly execute required event."
        ),
    }


def _build_anchor_resolve_prompt(chapter_text: str, selected_rows: list[dict], hints: list[dict]) -> str:
    selected_json = json.dumps(selected_rows, ensure_ascii=False)
    hints_json = json.dumps(hints, ensure_ascii=False)
    return (
        "You are an anchor resolver.\n"
        "Judge whether each selected anchor is clearly executed in the current chapter draft.\n"
        "Return strict JSON with fields:\n"
        "- resolution_analysis: concise reasoning in output language\n"
        "- resolved_anchor_ids: selected ids that are clearly executed\n"
        "- unresolved_anchor_ids: selected ids not clearly executed\n"
        "- chapter_matches_plan: true only when all selected anchors are resolved\n"
        "- evidence_summary: list with objects {anchor_id, score, matched_terms, evidence_excerpt, decision, decision_reason}\n"
        "- decision_reason: concise final decision rationale\n"
        "- resolver_confidence: number 0..1 (how confident this judgement is)\n"
        "- requires_human_review: boolean (true only when uncertain/ambiguous)\n\n"
        "Rules:\n"
        "1) Do NOT ask HITL if judgement is confident, even when unresolved exists.\n"
        "2) Use requires_human_review=true only for real ambiguity (insufficient draft signal, conflicting cues, or unclear anchor text).\n"
        "3) resolved_anchor_ids + unresolved_anchor_ids must exactly partition selected ids.\n\n"
        f"selected_anchors={selected_json}\n"
        f"deterministic_hints={hints_json}\n"
        f"chapter_draft={chapter_text[:9000]}"
    )


def _fallback_resolution(
    chapter_text: str,
    selected: list[str],
    node_by_id: dict[str, dict],
) -> tuple[AnchorResolutionOutput, bool]:
    resolved_now: list[str] = []
    unresolved: list[str] = []
    evidence_rows: list[dict] = []
    for aid in selected:
        row = node_by_id.get(aid) or {}
        evidence = _build_anchor_evidence(chapter_text, aid, str(row.get("description") or ""))
        evidence_rows.append(evidence)
        score = float(evidence.get("score") or 0.0)
        if score >= 0.2:
            resolved_now.append(aid)
        else:
            unresolved.append(aid)
    chapter_matches_plan = len(unresolved) == 0
    return (
        AnchorResolutionOutput(
            resolution_analysis=(
                "Anchor resolution succeeded for all selected anchors."
                if chapter_matches_plan
                else "Anchor resolution mismatch: selected anchors were not fully evidenced in chapter draft."
            ),
            resolved_anchor_ids=resolved_now,
            unresolved_anchor_ids=unresolved,
            chapter_matches_plan=chapter_matches_plan,
            evidence_summary=evidence_rows,
            decision_reason=(
                "All selected anchors reached evidence threshold."
                if chapter_matches_plan
                else "Selected anchors are not fully met, but evidence is sufficiently clear to continue without HITL."
            ),
        ),
        False,
    )


def _normalize_partition(selected: list[str], resolved_now: list[str], unresolved: list[str]) -> tuple[list[str], list[str]]:
    sel = [x for x in selected if x]
    r = [x for x in resolved_now if x in sel]
    u = [x for x in unresolved if x in sel and x not in r]
    remaining = [x for x in sel if x not in r and x not in u]
    if remaining:
        u.extend(remaining)
    return sorted(set(r)), sorted(set(u))


def _recompute_unlocks(anchor_nodes: list[dict], resolved: set[str]) -> tuple[list[dict], list[str]]:
    by_id = {str(n.get("id") or ""): dict(n) for n in anchor_nodes if str(n.get("id") or "").strip()}
    candidates: list[str] = []
    for node_id, row in by_id.items():
        deps = [str(x) for x in (row.get("depends_on") or []) if str(x).strip()]
        if node_id in resolved:
            row["status"] = "RESOLVED"
            continue
        if all(dep in resolved for dep in deps):
            row["status"] = "UNLOCKED"
            candidates.append(node_id)
        else:
            row["status"] = "LOCKED"
    return list(by_id.values()), sorted(set(candidates))


def run_anchor_resolve(state: dict, context: WorkflowContext) -> dict:
    chapter_text = str(state.get("current_draft") or state.get("best_draft_content") or "")
    anchor_nodes = list(state.get("anchor_nodes") or [])
    selected = [str(x).strip() for x in (state.get("selected_anchor_ids") or []) if str(x).strip()]
    node_by_id = {str(n.get("id") or ""): n for n in anchor_nodes}
    resolved = set(str(x).strip() for x in (state.get("resolved_anchors") or []) if str(x).strip())
    hitl_required = False

    if not selected:
        output = AnchorResolutionOutput(
            resolution_analysis="No selected anchors for this chapter; skip anchor resolution.",
            resolved_anchor_ids=[],
            unresolved_anchor_ids=[],
            chapter_matches_plan=True,
            evidence_summary=[],
            decision_reason="No selected anchors; continue workflow.",
        )
    elif isinstance(context.llm_client, MockLLMClient):
        output, hitl_required = _fallback_resolution(chapter_text, selected, node_by_id)
    else:
        selected_rows = [
            {
                "anchor_id": aid,
                "title": str((node_by_id.get(aid) or {}).get("title") or ""),
                "description": str((node_by_id.get(aid) or {}).get("description") or ""),
                "node_kind": str((node_by_id.get(aid) or {}).get("node_kind") or ""),
            }
            for aid in selected
        ]
        deterministic_hints = [
            _build_anchor_evidence(chapter_text, aid, str((node_by_id.get(aid) or {}).get("description") or ""))
            for aid in selected
        ]
        profile = augment_profile_system_prompt(get_profile("anchor_resolver"), context.output_language)
        prompt = _build_anchor_resolve_prompt(chapter_text, selected_rows, deterministic_hints)
        try:
            structured, _llm_result = context.llm_client.invoke_json(prompt, AnchorResolutionOutput, profile)
            resolved_now, unresolved = _normalize_partition(
                selected,
                [str(x).strip() for x in structured.resolved_anchor_ids if str(x).strip()],
                [str(x).strip() for x in structured.unresolved_anchor_ids if str(x).strip()],
            )
            chapter_matches_plan = len(unresolved) == 0
            output = AnchorResolutionOutput(
                resolution_analysis=str(structured.resolution_analysis or "").strip()
                or ("Anchor resolution succeeded." if chapter_matches_plan else "Anchor resolution mismatch."),
                resolved_anchor_ids=resolved_now,
                unresolved_anchor_ids=unresolved,
                chapter_matches_plan=chapter_matches_plan,
                evidence_summary=list(structured.evidence_summary or deterministic_hints),
                decision_reason=str(structured.decision_reason or "").strip()
                or ("All selected anchors are resolved." if chapter_matches_plan else "Some selected anchors are unresolved."),
                resolver_confidence=float(structured.resolver_confidence),
                requires_human_review=bool(structured.requires_human_review),
            )
            hitl_required = bool(structured.requires_human_review) or float(structured.resolver_confidence) < 0.45
        except Exception:
            output, hitl_required = _fallback_resolution(chapter_text, selected, node_by_id)

    for aid in output.resolved_anchor_ids:
        resolved.add(str(aid).strip())
    next_nodes, candidates = _recompute_unlocks(anchor_nodes, resolved)
    unresolved_non_terminal = [
        n
        for n in next_nodes
        if str(n.get("status") or "").upper() != "RESOLVED"
        and str(n.get("node_kind") or "").upper() not in {"ENDING", "CHECKPOINT"}
    ]
    volume_stretch_required = len(candidates) == 0 and len(unresolved_non_terminal) > 0
    return {
        "anchor_resolution": output.model_dump(mode="json"),
        "anchor_hitl_required": bool(hitl_required and len(selected) > 0),
        "anchor_resolution_hitl_candidate": output.model_dump(mode="json") if hitl_required and len(selected) > 0 else {},
        "resolved_anchors": sorted(resolved),
        "active_anchors": selected,
        "anchor_candidates": candidates,
        "anchor_nodes": next_nodes,
        "volume_stretch_required": volume_stretch_required,
    }

