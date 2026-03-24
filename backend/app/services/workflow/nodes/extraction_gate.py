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
    apply_resolution_to_extraction,
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
            line = (
                f"- node_id={nid} | 類型={nt} | 規劃名稱={p.canonical_name!r} | 任務角色={p.role!r}"
            )
            if brief:
                line += f" | 寫作要點摘要={brief}"
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
            lines.append(f"- node_id={nid} | （規劃表 planned_graph_nodes 中找不到對應列）")
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
    intro = "本章規劃的以下必選圖節點在正文抽取與對齊後，仍無法對應到抽取結果中的 node_id（可能過於隱晦、稱呼與規劃差異過大，或抽取管線遺漏）："
    suffix = "請在正文中加入更可辨識的稱呼、外觀或動作，並與任務卡中的角色／地點一致；必要時讓 surface hints 涵蓋文中實際出現的精確子字串。"
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
        labels.append("實體抽取")
    mem = steps.get("chapter_memory_extractor")
    if isinstance(mem, dict) and mem.get("fallback"):
        labels.append("章節記憶抽取")
    if not labels:
        return ""
    joined = "與".join(labels)
    return (
        f"【系統提示】本章{joined}曾降級為後備流程，結構化結果可信度較低；"
        "若反覆對齊失敗請檢查正文可抽性、API 與模型輸出。\n\n"
    )


def run_extraction_gate(state: dict, context: WorkflowContext) -> dict:
    """
    Extract + remap mandatory planned ids + R6 validation.
    On failure: route back to author with MISSING_MANDATORY_ENTITY_MAPPING.
    """
    chapter_content = state.get("best_draft_content") or state.get("current_draft") or ""
    events = [EventOutline.model_validate(event) for event in state.get("ground_truth_events") or []]
    graph_snapshot = context.graph_store.query_context(
        GraphQueryRequest(
            story_id=state["story_id"],
            active_epoch_id=state["active_epoch_id"],
            pov_character_id=state["pov_character_id"],
            narrative_directive=state.get("narrative_directive", ""),
        )
    )
    extracted, diag = extract_chapter_artifacts(state, context, graph_snapshot, chapter_content, events)
    planned = list(state.get("planned_graph_nodes") or [])
    extracted = apply_resolution_to_extraction(extracted, planned, _author_surface_map(state))
    ok, missing = validate_mandatory_planned_nodes(list(extracted.entities), planned)
    if not ok:
        msg, missing_detail = _format_missing_mandatory_feedback(missing, planned)
        prefix = _extraction_fallback_notice(diag if isinstance(diag, dict) else None)
        msg = prefix + msg
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
        }

    return {
        "post_polish_route": "resolve_subplots",
        "pending_chapter_extraction": extracted.model_dump(mode="json"),
        "extraction_gate_error": "",
    }
