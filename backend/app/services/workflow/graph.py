from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from app.core.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor

logger = logging.getLogger(__name__)

from langgraph.graph import END, START, StateGraph

from app.domain.schema import (
    EdgeMutation,
    EdgeType,
    GraphQueryRequest,
    HitlReason,
    StateUpdaterOutput,
    StoryCastMemberStored,
    WorkflowStatus,
)
from app.core.config import get_settings
from app.domain.state import AgentWorkflowState, apply_length_bounds_to_state
from app.domain.story_runtime import parse_story_runtime
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.author import run_author
from app.services.workflow.nodes.anchor_resolve import run_anchor_resolve
from app.services.workflow.nodes.director import run_director
from app.services.workflow.nodes.draft_supervisor import run_draft_supervisor
from app.services.workflow.nodes.extraction_gate import run_extraction_gate
from app.services.workflow.nodes.chapter_summarizer import run_chapter_summarizer
from app.services.workflow.nodes.copyeditor import run_copyeditor
from app.services.workflow.policy_gates import run_semantic_gate
from app.services.workflow.output_language import chapter_heading_line
from app.services.workflow.output_language_gate import run_output_language_gate
from app.services.workflow.nodes.graph_rag import run_graph_rag
from app.services.workflow.nodes.logic_alignment import run_logic_alignment
from app.services.workflow.nodes.plan_supervisor import run_plan_supervisor
from app.services.workflow.nodes.planner import run_planner
from app.services.workflow.nodes.profile_expander import run_profile_expander
from app.services.workflow.nodes.reader import run_reader
from app.services.workflow.nodes.state_updater import run_state_updater
from app.services.workflow.recorder import WorkflowRecorder, elapsed_ms, timed
from app.services.workflow.chunking import build_chapter_chunks, extract_prev_tail


LLM_NODE_TIMEOUT_MS = 10 * 60 * 1000
LOGIC_NODE_TIMEOUT_MS = 3 * 60 * 1000
# extraction_gate runs multi-phase LLM extraction; base budget covers entity/memory/relation
# extractors plus the first validation pass. Each potential alignment repair round adds
# extra headroom (see _extraction_gate_timeout_ms below).
EXTRACTION_GATE_BASE_TIMEOUT_MS = 6 * 60 * 1000
EXTRACTION_GATE_PER_REPAIR_BUDGET_MS = 2 * 60 * 1000


class WorkflowNodeTimeoutError(TimeoutError):
    def __init__(self, node_name: str, timeout_ms: int) -> None:
        self.node_name = node_name
        self.timeout_ms = timeout_ms
        super().__init__(f"Node '{node_name}' exceeded timeout {timeout_ms}ms")


def _extraction_gate_timeout_ms() -> int:
    """Base extraction budget + 2 minutes per potential alignment repair round.

    Repairs are bounded by ``settings.extraction_relation_align_retry_max`` (default 2,
    max 4). With defaults this yields 10 min; the absolute cap is 14 min.
    """
    settings = get_settings()
    max_repairs = max(0, int(getattr(settings, "extraction_relation_align_retry_max", 0) or 0))
    return EXTRACTION_GATE_BASE_TIMEOUT_MS + max_repairs * EXTRACTION_GATE_PER_REPAIR_BUDGET_MS


def _timeout_ms_for_node(node_name: str) -> int:
    if node_name in {"director", "planner", "author", "reader"}:
        return LLM_NODE_TIMEOUT_MS
    if node_name == "extraction_gate":
        return _extraction_gate_timeout_ms()
    return LOGIC_NODE_TIMEOUT_MS


def _run_with_timeout(node_name: str, fn: Any, state: AgentWorkflowState) -> dict:
    timeout_ms = _timeout_ms_for_node(node_name)
    timeout_s = timeout_ms / 1000.0
    story_id = str(state.get("story_id") or "") or None
    try:
        chapter_id_val = int(state.get("chapter_id") or 0) or None
    except (TypeError, ValueError):
        chapter_id_val = None
    log_extra = {
        "source": f"node.{node_name}",
        "story_id": story_id,
        "chapter_id": chapter_id_val,
    }
    logger.info("Node started", extra=log_extra)
    start = time.perf_counter()
    try:
        result = asyncio.run(
            asyncio.wait_for(asyncio.to_thread(fn, state), timeout=timeout_s)
        )
    except TimeoutError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        logger.error(
            "Node timed out",
            extra={**log_extra, "elapsed_ms": elapsed, "timeout_ms": timeout_ms},
        )
        raise WorkflowNodeTimeoutError(node_name=node_name, timeout_ms=timeout_ms) from exc
    except Exception as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        logger.error(
            "Node failed",
            extra={**log_extra, "elapsed_ms": elapsed, "error": str(exc)[:500]},
            exc_info=exc,
        )
        raise
    elapsed = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Node finished",
        extra={**log_extra, "elapsed_ms": elapsed},
    )
    return result


def _promote_planned_characters_to_cast(story_repository: Any, story_id: str, planned_nodes: list[dict[str, Any]]) -> None:
    """Append planner CHARACTER nodes with character_profile into stories.cast_json."""
    for row in planned_nodes:
        if str(row.get("node_type") or "") != "CHARACTER":
            continue
        prof = row.get("character_profile")
        if not isinstance(prof, dict) or not prof:
            continue
        node_id = str(row.get("node_id") or "").strip()
        name = str(row.get("canonical_name") or "").strip() or node_id
        if not node_id:
            continue
        core = str(prof.get("core_motivation") or "")[:600]
        personality = str(prof.get("personality") or "")[:600]
        core_value = str(prof.get("core_value") or "")[:600] or core
        member = StoryCastMemberStored(
            node_id=node_id,
            canonical_name=name,
            role="supporting",
            short_bio=str(prof.get("short_bio") or "")[:500],
            aliases=[],
            age=str(prof.get("age") or "")[:48],
            personality=personality,
            core_motivation=core,
            core_value=core_value,
            speech_style=str(prof.get("speech_style") or "")[:240],
            fatal_flaw=str(prof.get("fatal_flaw") or "")[:400],
            quirks_and_habits=str(prof.get("quirks_and_habits") or "")[:400],
        )
        story_repository.soft_upsert_story_cast_member(story_id, member)


def _has_forbidden_resolution_keywords(text: str) -> bool:
    lowered = (text or "").lower()
    keys = ("精神連結", "神經駭入", "腦機", "mind link", "neural hack", "mental duel")
    return any(k in lowered for k in keys)


def _semantic_resolution_cooldown_hitl(context: WorkflowContext, narrative: str) -> bool:
    if not _has_forbidden_resolution_keywords(narrative):
        return False
    gate, _ = run_semantic_gate(
        context=context,
        profile_name="plan_supervisor",
        rule_id="planner_resolution_cooldown_route",
        fallback_decision="block",
        fallback_confidence=0.7,
        prompt=(
            "Decide whether this plan truly uses a forbidden resolution tactic.\n"
            "Block only when core resolution depends on mind-link/neural-hack/mental-duel style path.\n"
            "Return JSON decision allow/warn/block with evidence_snippet and rationale.\n\n"
            f"narrative_script={narrative[:2500]}"
        ),
    )
    return gate.decision == "block"


def _semantic_vibe_cooldown_hitl(context: WorkflowContext, boundary: str, narrative: str) -> bool:
    boundary_cf = boundary.casefold()
    narrative_cf = narrative.casefold()
    has_signal = (
        "安全屋" in boundary
        or "密室" in boundary
        or "總結對話" in narrative
        or "safe house" in boundary_cf
        or "locked room" in boundary_cf
        or "debrief dialogue" in narrative_cf
    )
    if not has_signal:
        return False
    gate, _ = run_semantic_gate(
        context=context,
        profile_name="plan_supervisor",
        rule_id="planner_ending_vibe_route",
        fallback_decision="block",
        fallback_confidence=0.7,
        prompt=(
            "Decide whether this chapter ending is SAFE_ROOM_EXPOSITION forbidden vibe.\n"
            "Block only if ending truly resolves into safe-room debrief exposition.\n"
            "Return JSON decision allow/warn/block with evidence_snippet and rationale.\n\n"
            f"ending_boundary_rule={boundary[:1000]}\n"
            f"narrative_script={narrative[:2500]}"
        ),
    )
    return gate.decision == "block"


def _slug(raw: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (raw or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:36]


def _canonicalize_planner_events(events_raw: list[dict[str, Any]], chapter_id: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    old_to_new: dict[str, str] = {}
    for idx, ev in enumerate(events_raw, start=1):
        if not isinstance(ev, dict):
            continue
        desc = str(ev.get("description") or "").strip()
        old_id = str(ev.get("event_id") or "").strip()
        new_id = f"event_ch{chapter_id}_{idx:02d}"
        slug = _slug(desc)
        if slug:
            new_id = f"event_{slug}_{idx:02d}"
        old_to_new[old_id] = new_id
        out.append(
            {
                "event_id": new_id,
                "description": desc,
                "caused_by_event_id": str(ev.get("caused_by_event_id") or "").strip() or None,
                "links": list(ev.get("links") or []),
            }
        )
    for ev in out:
        cause = ev.get("caused_by_event_id")
        if cause:
            ev["caused_by_event_id"] = old_to_new.get(cause, cause)
        links = []
        for link in ev.get("links") or []:
            if not isinstance(link, dict):
                continue
            target = str(link.get("target_event_id") or "").strip()
            if not target:
                continue
            links.append(
                {
                    **link,
                    "target_event_id": old_to_new.get(target, target),
                }
            )
        ev["links"] = links
    return out


def build_chapter_graph(context: WorkflowContext):
    workflow_repository: WorkflowRepository = context.workflow_repository
    recorder = WorkflowRecorder(context)

    def director_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output = run_director(state, context)
        # Cooldown enforcement: if director picks a b_story_type contained in the recent pool,
        # pause for manual correction (HITL).
        forbidden = {str(x).strip() for x in (state.get("recent_b_story_types") or []) if str(x).strip()}
        chosen = output.get("b_story_type") or output.get("b_story_type_selected")
        bdir = output.get("b_story_directive") or ""
        chosen_str = str(chosen).strip() if chosen is not None else ""
        chosen_norm = chosen_str.upper()
        forbidden_norm = {f.upper() for f in forbidden}
        req_b = output.get("request_new_b_story")
        req_type = ""
        if isinstance(req_b, dict):
            req_type = str(req_b.get("type") or "").strip().upper()
        if req_type and req_type in forbidden_norm:
            output = {
                **output,
                "requires_hitl": True,
                "hitl_reason": HitlReason.B_STORY_COOLDOWN_VIOLATION,
                "hitl_decision_mode": "MANUAL_EDIT",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [],
                "resume_from": "graph_rag",
            }
        elif chosen_norm and chosen_norm in forbidden_norm:
            output = {
                **output,
                "requires_hitl": True,
                "hitl_reason": HitlReason.B_STORY_COOLDOWN_VIOLATION,
                "hitl_decision_mode": "MANUAL_EDIT",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [],
                "resume_from": "graph_rag",
            }
        updated = {**state, **output, "last_agent": "director"}
        recorder.record_and_update_run("director", dict(state), output, updated, latency_ms=elapsed_ms(start))
        return output | {"last_agent": "director", "resume_from": output.get("resume_from", "director")}

    def graph_rag_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output = run_graph_rag(state, context)
        route = "planner"
        extra: dict = {}
        if output.get("context_hitl_required"):
            route = "hitl"
            extra = {
                "requires_hitl": True,
                "hitl_reason": HitlReason.CONTEXT_LENGTH_EXCEEDED,
                "hitl_decision_mode": "MANUAL_EDIT",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [],
                "resume_from": "graph_rag",
            }
        merged = {**output, **extra, "graph_rag_route": route, "last_agent": "graph_rag"}
        recorder.record_and_update_run(
            "graph_rag",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        return merged

    def planner_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output, masked, tokens, latency = run_planner(state, context)
        output["ground_truth_events"] = _canonicalize_planner_events(
            list(output.get("ground_truth_events") or []),
            int(state["chapter_id"]),
        )
        output = {**output, "manual_plan_force_approve": False}
        planned_nodes = list(output.get("proposed_new_nodes") or [])
        merged_planner = {**output, "planned_graph_nodes": planned_nodes}
        pending_evolutions = list(state.get("pending_cast_evolutions") or [])
        for row in list(merged_planner.get("character_evolution_requests") or []):
            if isinstance(row, dict):
                pending_evolutions.append(row)
        merged_planner["pending_cast_evolutions"] = pending_evolutions
        cooldown = state.get("resolution_cooldown_constraint") or {}
        vibe_cooldown = state.get("ending_vibe_cooldown_constraint") or {}
        narrative = str(merged_planner.get("narrative_script") or "")
        boundary = str(merged_planner.get("ending_boundary_rule") or "")
        res_precheck = bool(cooldown.get("active"))
        vibe_precheck = bool(
            vibe_cooldown.get("active")
            and "SAFE_ROOM_EXPOSITION" in str(vibe_cooldown.get("forbidden_vibes") or [])
        )
        resolution_hitl = False
        vibe_hitl = False
        if res_precheck and vibe_precheck:
            _gate_workers = max(1, min(2, get_settings().side_slot_fill_max_workers))
            with ThreadPoolExecutor(max_workers=_gate_workers) as pool:
                fut_res = pool.submit(_semantic_resolution_cooldown_hitl, context, narrative)
                fut_vibe = pool.submit(_semantic_vibe_cooldown_hitl, context, boundary, narrative)
                resolution_hitl = bool(fut_res.result())
                vibe_hitl = bool(fut_vibe.result())
        elif res_precheck:
            resolution_hitl = _semantic_resolution_cooldown_hitl(context, narrative)
        elif vibe_precheck:
            vibe_hitl = _semantic_vibe_cooldown_hitl(context, boundary, narrative)

        if resolution_hitl:
            merged_planner.update(
                {
                    "requires_hitl": True,
                    "hitl_reason": HitlReason.RESOLUTION_TACTIC_COOLDOWN_VIOLATION,
                    "hitl_decision_mode": "MANUAL_EDIT",
                    "workflow_status": WorkflowStatus.WAITING_HITL.value,
                    "resume_from": "planner",
                }
            )
        if vibe_hitl:
            merged_planner.update(
                {
                    "requires_hitl": True,
                    "hitl_reason": HitlReason.ENDING_VIBE_COOLDOWN_VIOLATION,
                    "hitl_decision_mode": "MANUAL_EDIT",
                    "workflow_status": WorkflowStatus.WAITING_HITL.value,
                    "resume_from": "planner",
                }
            )
        tmp_state = {**state, **merged_planner}
        apply_length_bounds_to_state(tmp_state)
        merged_planner["normalized_length_min"] = tmp_state["normalized_length_min"]
        merged_planner["normalized_length_max"] = tmp_state["normalized_length_max"]
        pw_hint = list(merged_planner.get("plan_warnings") or [])
        bind = str(state.get("outline_binding_mode") or "ABSENT")
        if str(state.get("ai_freedom_level") or "") == "strict" and bind != "FULL":
            tag = (
                "[大綱模式] 作者大綱未達「具體」長度閾值：AI 可主導補齊結構；"
                "人類已寫片段仍須遵守；腦補請以 is_ai_invention=true 標記。"
            )
            if tag not in pw_hint:
                pw_hint.append(tag)
        elif bind == "FULL":
            tag2 = "[大綱模式] outline_binding_mode=FULL：strict 下已寫明情節具約束力。"
            if tag2 not in pw_hint:
                pw_hint.append(tag2)
        merged_planner["plan_warnings"] = pw_hint
        updated = {**state, **merged_planner, "last_agent": "planner"}
        recorder.record_and_update_run(
            "planner",
            dict(state),
            merged_planner,
            updated,
            masked_payload=masked,
            token_usage=tokens,
            latency_ms=latency or elapsed_ms(start),
        )
        return merged_planner | {
            "last_agent": "planner",
            "resume_from": "planner",
            "original_draft_narrative_script": str(merged_planner.get("narrative_script") or ""),
            "original_draft_must_include_beats": list(merged_planner.get("must_include_beats") or []),
            "original_draft_ground_truth_events": list(merged_planner.get("ground_truth_events") or []),
        }

    def logic_alignment_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output, masked, tokens, latency = run_logic_alignment(state, context)
        max_hitl_retry = 1

        # State hygiene: always overwrite HITL flags from this node's fresh decision.
        conflicts = [str(x).strip() for x in (output.get("human_outline_conflict_notes") or []) if str(x).strip()]
        updates: dict[str, Any] = {
            "safe_chapter_rules": str(output.get("safe_chapter_rules") or ""),
            "alignment_log": str(output.get("alignment_log") or ""),
            "human_outline_conflict_notes": conflicts,
            "requires_hitl": False,
            "hitl_reason": "",
            "hitl_decision_mode": "NONE",
            "pending_hitl_options": [],
            "workflow_status": WorkflowStatus.RUNNING.value,
        }
        if conflicts:
            plan_warnings = list(state.get("plan_warnings") or [])
            for c in conflicts:
                line = f"[設定衝突] {c}"
                if line not in plan_warnings:
                    plan_warnings.append(line)
            updates["plan_warnings"] = plan_warnings
        wants_hitl = bool(output.get("requires_hitl"))
        if wants_hitl:
            retry_count = int(state.get("alignment_hitl_retry_count") or 0) + 1
            updates["alignment_hitl_retry_count"] = retry_count
            reason_detail = str(output.get("hitl_reason") or "").strip()
            if retry_count > max_hitl_retry:
                warn = (
                    "Alignment HITL exceeded retry limit; force-pass without hard rules. "
                    "Please review chapter_hard_rules quality."
                )
                plan_warnings = list(updates.get("plan_warnings") or state.get("plan_warnings") or [])
                if warn not in plan_warnings:
                    plan_warnings.append(warn)
                updates["plan_warnings"] = plan_warnings
                updates["alignment_log"] = f"{updates['alignment_log']}\n[WARN] {warn}".strip()
            else:
                if reason_detail:
                    updates["alignment_log"] = f"{updates['alignment_log']}\n[HITL_REQUEST] {reason_detail}".strip()
                updates.update(
                    {
                        "requires_hitl": True,
                        "hitl_reason": HitlReason.ALIGNMENT_RULES_REQUIRED,
                        "hitl_decision_mode": "MANUAL_EDIT",
                        "workflow_status": WorkflowStatus.WAITING_HITL.value,
                        "pending_hitl_options": [],
                        "resume_from": "logic_alignment",
                    }
                )
        else:
            updates["alignment_hitl_retry_count"] = 0

        if (
            not updates.get("requires_hitl")
            and ("final_narrative_script" in output or "final_must_include_beats" in output or "final_ground_truth_events" in output)
        ):
            final_beats = list(output.get("final_must_include_beats") or [])
            # Overwrite draft fields with aligned final fields.
            updates.update(
                {
                    "ground_truth_events": list(output.get("final_ground_truth_events") or []),
                    "narrative_script": str(output.get("final_narrative_script") or ""),
                    "must_include_beats": final_beats,
                    "must_include_beat_outlines": [
                        {"text": beat, "is_ai_invention": False, "invention_scope": ""} for beat in final_beats
                    ],
                }
            )

        merged = {**updates, "last_agent": "logic_alignment", "resume_from": "logic_alignment"}
        recorder.record_and_update_run(
            "logic_alignment",
            dict(state),
            merged,
            {**state, **merged},
            masked_payload=masked,
            token_usage=tokens,
            latency_ms=latency or elapsed_ms(start),
        )
        return merged

    def plan_supervisor_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output, masked = run_plan_supervisor(state, context)
        approved = output["is_approved"]
        plan_feedback = list(state["plan_feedback"])
        if not approved:
            plan_feedback.append(
                {
                    "violation": output["violation_type"],
                    "suggestion": output["suggestion_type"],
                    "message": output["feedback_to_agent"],
                }
            )
        retry_count = state["plan_retry_count"] + (0 if approved else 1)
        if not approved and retry_count > state.get("plan_retry_limit", 3):
            route = "hitl"
            updates = {
                "requires_hitl": True,
                "hitl_reason": HitlReason.PLAN_LOOP_EXCEEDED,
                "hitl_decision_mode": "MANUAL_EDIT",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [
                    {"id": "force_rewrite_plan", "label": "強制重寫大綱"},
                    {"id": "force_approve_plan", "label": "強制放行（以目前大綱進入 Author）"},
                ],
                "resume_from": "planner",
            }
        else:
            feedback_text = str(output.get("feedback_to_agent") or "")
            if not approved and "RESOLUTION_COOLDOWN_HARD_VIOLATION" in feedback_text:
                route = "hitl"
                updates = {
                    "requires_hitl": True,
                    "hitl_reason": HitlReason.RESOLUTION_TACTIC_COOLDOWN_VIOLATION,
                    "hitl_decision_mode": "MANUAL_EDIT",
                    "workflow_status": WorkflowStatus.WAITING_HITL.value,
                    "pending_hitl_options": [
                        {"id": "force_rewrite_plan", "label": "重來一次（清空大綱重試計次）"},
                        {"id": "force_approve_plan", "label": "強制放行（以目前大綱進入 Author）"},
                    ],
                    "resume_from": "planner",
                }
            elif not approved and "ENDING_VIBE_COOLDOWN_HARD_VIOLATION" in feedback_text:
                route = "hitl"
                updates = {
                    "requires_hitl": True,
                    "hitl_reason": HitlReason.ENDING_VIBE_COOLDOWN_VIOLATION,
                    "hitl_decision_mode": "MANUAL_EDIT",
                    "workflow_status": WorkflowStatus.WAITING_HITL.value,
                    "pending_hitl_options": [
                        {"id": "force_rewrite_plan", "label": "重來一次（清空大綱重試計次）"},
                        {"id": "force_approve_plan", "label": "強制放行（以目前大綱進入 Author）"},
                    ],
                    "resume_from": "planner",
                }
            else:
                route = "logic_alignment" if approved else "planner"
                updates = {
                    "requires_hitl": False,
                    "hitl_reason": "",
                    "hitl_decision_mode": "NONE",
                    "workflow_status": WorkflowStatus.RUNNING.value,
                }
        soft = list(output.get("soft_warnings") or [])
        plan_warnings = list(state.get("plan_warnings") or [])
        for w in soft:
            w = (w or "").strip()
            if w and w not in plan_warnings:
                plan_warnings.append(w)
        merged = {
            **output,
            **updates,
            "plan_feedback": plan_feedback,
            "plan_retry_count": retry_count,
            "anchor_achieved": output["anchor_achieved"],
            "plan_warnings": plan_warnings,
            "last_agent": "plan_supervisor",
            "plan_route": route,
            "resume_from": "logic_alignment" if approved else updates.get("resume_from", state.get("resume_from", "planner")),
        }
        recorder.record(
            "plan_supervisor",
            dict(state),
            merged,
            masked_payload=masked,
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        workflow_repository.update_run(context.run_id, {**state, **merged})
        return merged

    def author_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output, masked, tokens, latency = run_author(state, context)
        hints = list(output.get("author_extraction_surface_hints") or [])
        updated = {
            **state,
            **output,
            "current_draft": output["chapter_content"],
            "author_extraction_surface_hints": hints,
            "last_agent": "author",
        }
        recorder.record_and_update_run(
            "author",
            masked,
            output,
            updated,
            masked_payload=masked,
            token_usage=tokens,
            latency_ms=latency or elapsed_ms(start),
        )
        return {
            "current_draft": output["chapter_content"],
            "author_extraction_surface_hints": hints,
            "word_count": output.get("word_count", 0),
            "last_agent": "author",
            "resume_from": "author",
        }

    def draft_supervisor_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output, masked = run_draft_supervisor(state, context)
        approved = output["is_approved"]
        draft_feedback = list(state["draft_feedback"])
        next_attempt = state["draft_retry_count"] + 1
        if not approved:
            draft_feedback.append(
                {
                    "attempt": next_attempt,
                    "violation": output["violation_type"],
                    "suggestion": output["suggestion_type"],
                    "length_adjustment": output.get("length_adjustment", "NONE"),
                    "message": output["feedback_to_agent"],
                }
            )
        retry_count = state["draft_retry_count"] + (0 if approved else 1)
        draft_loop_retry_count = state.get("draft_loop_retry_count", 0) + (0 if approved else 1)
        if not approved and draft_loop_retry_count > state.get("draft_loop_retry_limit", 3):
            route = "hitl"
            updates = {
                "requires_hitl": True,
                "hitl_reason": HitlReason.DRAFT_LOOP_EXCEEDED,
                "hitl_decision_mode": "DASHBOARD",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [
                    {"id": "keep_current_logic", "label": "維持現有草稿（強制通過）"},
                    {"id": "relax_word_count", "label": "放寬字數要求"},
                ],
                "resume_from": "author",
            }
        else:
            route = "reader" if approved else "author"
            updates = {
                "requires_hitl": False,
                "hitl_reason": "",
                "hitl_decision_mode": "NONE",
                "workflow_status": WorkflowStatus.RUNNING.value,
            }
        merged = {
            **output,
            **updates,
            "draft_feedback": draft_feedback,
            "draft_loop_retry_count": draft_loop_retry_count,
            "draft_retry_count": retry_count,
            "last_agent": "draft_supervisor",
            "draft_route": route,
            "resume_from": "author" if route in {"author", "hitl"} else state.get("resume_from", "author"),
        }
        recorder.record(
            "draft_supervisor",
            dict(state),
            merged,
            masked_payload=masked,
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        workflow_repository.update_run(context.run_id, {**state, **merged})
        return merged

    def reader_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output = run_reader(state, context)
        retry_count = state["reader_retry_count"] + (0 if output["is_approved"] else 1)
        draft_loop_retry_count = state.get("draft_loop_retry_count", 0) + (0 if output["is_approved"] else 1)
        best_score = state["best_draft_score"]
        best_content = state["best_draft_content"]
        if output["literary_score"] >= best_score:
            best_score = output["literary_score"]
            best_content = state["current_draft"]
        if output["is_approved"]:
            # Route to the chapter_review_gate; gate decides pass-through vs HITL.
            route = "chapter_review_gate"
            current_draft = state["current_draft"]
            next_resume = "chapter_review_gate"
        elif draft_loop_retry_count > state.get("draft_loop_retry_limit", 3):
            route = "chapter_review_gate"
            current_draft = best_content or state["current_draft"]
            next_resume = "chapter_review_gate"
        else:
            route = "author"
            current_draft = state["current_draft"]
            next_resume = "author"
        reader_feedback = list(state["reader_feedback"])
        if not output["is_approved"]:
            reader_feedback.append(
                {
                    "score": output["literary_score"],
                    "message": output["critique"],
                    "suggestion": output["suggestion_type"],
                }
            )
        merged = {
            **output,
            "draft_loop_retry_count": draft_loop_retry_count,
            "reader_retry_count": retry_count,
            "reader_feedback": reader_feedback,
            "best_draft_score": best_score,
            "best_draft_content": best_content,
            "current_draft": current_draft,
            "last_reader_score": output["literary_score"],
            "last_agent": "reader",
            "reader_route": route,
            "resume_from": next_resume,
        }
        recorder.record_and_update_run(
            "reader",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        return merged

    def chapter_review_gate_node(state: AgentWorkflowState) -> dict:
        """Pause after reader approval when require_chapter_review flag is set.

        Pass-through when the flag is false; otherwise emit a HITL with three options:
        APPROVE_DRAFT, RERUN_KEEP_DIRECTOR, ABANDON_CHAPTER.
        """
        start = timed()
        require_review = bool(state.get("require_chapter_review") or False)
        if not require_review:
            merged: dict[str, Any] = {
                "last_agent": "chapter_review_gate",
                "resume_from": "chunker",
            }
            recorder.record_and_update_run(
                "chapter_review_gate",
                dict(state),
                merged,
                {**state, **merged},
                latency_ms=elapsed_ms(start),
                route_decision="chunker",
            )
            return merged
        merged = {
            "requires_hitl": True,
            "hitl_reason": HitlReason.CHAPTER_DRAFT_REVIEW,
            "hitl_decision_mode": "MANUAL_EDIT",
            "workflow_status": WorkflowStatus.WAITING_HITL.value,
            "pending_hitl_options": [
                {"id": "APPROVE_DRAFT", "label": "通過（可修改）"},
                {"id": "RERUN_KEEP_DIRECTOR", "label": "保留劇情節點重跑"},
                {"id": "ABANDON_CHAPTER", "label": "放棄此次生成"},
            ],
            "resume_from": "chunker",
            "last_agent": "chapter_review_gate",
        }
        recorder.record_and_update_run(
            "chapter_review_gate",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
            route_decision="hitl",
        )
        return merged

    def chunker_node(state: AgentWorkflowState) -> dict:
        """
        Build chunk list for this chapter.
        Includes prev_tail chunks for extraction alignment (NOT for Qdrant embedding).
        """
        start = timed()
        body = str(state.get("best_draft_content") or state.get("current_draft") or "")
        prev_row = None
        if int(state["chapter_id"]) > 1:
            prev_row = context.story_repository.get_chapter(state["story_id"], int(state["chapter_id"]) - 1)
        prev_content = str(prev_row.get("content") or "") if isinstance(prev_row, dict) else ""
        prev_tail = extract_prev_tail(prev_content, output_language=context.output_language)
        chunks = build_chapter_chunks(
            story_id=state["story_id"],
            chapter_id=int(state["chapter_id"]),
            current_body=body,
            prev_tail=prev_tail,
        )
        merged = {
            "chapter_chunks": [c.__dict__ for c in chunks],
            "last_agent": "chunker",
            "resume_from": "vectorize_chunks",
        }
        recorder.record_and_update_run(
            "chunker",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
        )
        return merged

    def vectorize_chunks_node(state: AgentWorkflowState) -> dict:
        """
        Vectorize only current_body chunks into Qdrant.
        prev_tail chunks are excluded by design.
        """
        start = timed()
        vector_docs = []
        # Build VectorDocument-like payloads without importing VectorDocument here to avoid import cycles.
        for raw in list(state.get("chapter_chunks") or []):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("source_role") or "") != "current_body":
                continue
            text_chunk = str(raw.get("text_chunk") or "")
            chunk_id = str(raw.get("chunk_id") or "").strip()
            if not text_chunk.strip() or not chunk_id:
                continue
            vector_docs.append(
                {
                    "text_chunk": text_chunk,
                    "metadata": {
                        "chunk_id": chunk_id,
                        "chunk_index": int(raw.get("chunk_index") or 0),
                        "chapter_id": int(state["chapter_id"]),
                        "epoch_id": str(state.get("active_epoch_id") or ""),
                        "source_role": "current_body",
                    },
                }
            )
        # Use the vector store protocol directly (expects VectorDocument objects).
        from app.domain.schema import VectorDocument

        context.vector_store.add_documents(
            state["story_id"],
            [VectorDocument.model_validate(d) for d in vector_docs],
        )
        merged = {
            "last_agent": "vectorize_chunks",
            "resume_from": "extraction_gate",
        }
        recorder.record_and_update_run(
            "vectorize_chunks",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
        )
        return merged

    def extraction_gate_node(state: AgentWorkflowState) -> dict:
        start = timed()
        gate_out = run_extraction_gate(state, context)
        route = str(gate_out.get("extraction_route") or "continue")
        if route == "author":
            entry = gate_out.get("extraction_gate_feedback_entry") or {}
            draft_feedback = list(state["draft_feedback"])
            if entry:
                draft_feedback.append(entry)
            streak = int(state.get("extraction_gate_failure_streak", 0) or 0) + 1
            limit = int(state.get("extraction_hitl_limit", 4) or 4)
            hints = list(gate_out.get("hitl_extraction_remap_hints") or [])
            # HITL after extraction_hitl_limit consecutive failures (inclusive: streak == limit triggers).
            if streak >= limit:
                route = "hitl"
                merged = {
                    **gate_out,
                    "draft_feedback": draft_feedback,
                    "draft_retry_count": state["draft_retry_count"] + 1,
                    "extraction_gate_failure_streak": streak,
                    "hitl_extraction_remap_hints": hints,
                    "requires_hitl": True,
                    "hitl_reason": HitlReason.EXTRACTION_GATE_FAILED,
                    "hitl_decision_mode": "MANUAL_EDIT",
                    "workflow_status": WorkflowStatus.WAITING_HITL.value,
                    "pending_hitl_options": [
                        {"id": "extraction_return_author", "label": "退回 Author 改寫正文"},
                    ],
                    "last_agent": "extraction_gate",
                    "resume_from": "extraction_gate",
                    "extraction_route": "hitl",
                }
            else:
                merged = {
                    **gate_out,
                    "draft_feedback": draft_feedback,
                    "draft_retry_count": state["draft_retry_count"] + 1,
                    "extraction_gate_failure_streak": streak,
                    "hitl_extraction_remap_hints": hints,
                    "last_agent": "extraction_gate",
                    "resume_from": "author",
                    "extraction_route": "author",
                }
        else:
            route = "copyeditor" if get_settings().copyeditor_enabled else "output_language_gate"
            merged = {
                **gate_out,
                "extraction_gate_failure_streak": 0,
                "last_agent": "extraction_gate",
                "resume_from": route,
                "extraction_route": route,
            }
        recorder.record_and_update_run(
            "extraction_gate",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        return merged

    def copyeditor_node(state: AgentWorkflowState) -> dict:
        start = timed()
        out = run_copyeditor(dict(state), context)
        merged = {
            **out,
            "last_agent": "copyeditor",
            "resume_from": "output_language_gate",
        }
        recorder.record_and_update_run(
            "copyeditor",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
            route_decision="output_language_gate",
        )
        return merged

    def output_language_gate_node(state: AgentWorkflowState) -> dict:
        start = timed()
        gate_out = run_output_language_gate(dict(state), context)
        merged = {**dict(state), **gate_out}
        route = str(gate_out.get("language_gate_route") or "chapter_summarizer")
        recorder.record_and_update_run(
            "output_language_gate",
            dict(state),
            gate_out,
            merged,
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        return gate_out

    def chapter_summarizer_node(state: AgentWorkflowState) -> dict:
        start = timed()
        run_chapter_summarizer(state, context)
        merged = {
            "last_agent": "chapter_summarizer",
            # Deterministic flow continues to anchor_resolve.
            "resume_from": "anchor_resolve",
        }
        recorder.record_and_update_run(
            "chapter_summarizer",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
        )
        return merged

    def anchor_resolve_node(state: AgentWorkflowState) -> dict:
        start = timed()
        out = run_anchor_resolve(state, context)
        route = "profile_expander"
        base = {**out, "last_agent": "anchor_resolve"}
        if out.get("anchor_hitl_required"):
            route = "hitl"
            merged = {
                **base,
                "requires_hitl": True,
                "hitl_reason": HitlReason.ANCHOR_RESOLUTION_FAILED,
                "hitl_decision_mode": "MANUAL_EDIT",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [
                    {"id": "anchor_wait_judgement", "label": "請使用 Anchor 裁判表單提交"},
                ],
                "resume_from": "anchor_resolve",
                "anchor_route": "hitl",
            }
        else:
            merged = {**base, "resume_from": "profile_expander", "anchor_route": "profile_expander"}
        recorder.record_and_update_run(
            "anchor_resolve",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        return merged

    def state_updater_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output = run_state_updater(state, context)
        title = chapter_heading_line(int(state["chapter_id"]), context.output_language)
        chapter_content = state["best_draft_content"] or state["current_draft"]
        merged = {
            "state_updater_output": output,
            "pending_db_commit": {
                "state_updater_output": output,
                "chapter_title": title,
                "chapter_content": chapter_content,
            },
            "workflow_status": WorkflowStatus.RUNNING.value,
            "last_agent": "state_updater",
            "commit_executed": False,
            "pending_cast_updates": [],
            "pending_cast_evolutions": [],
            "resume_from": "commit_to_databases",
        }
        recorder.record_and_update_run(
            "state_updater",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
        )
        return merged

    def commit_to_databases_node(state: AgentWorkflowState) -> dict:
        start = timed()
        pending = dict(state.get("pending_db_commit") or {})
        raw_output = pending.get("state_updater_output") or state.get("state_updater_output") or {}
        parsed = StateUpdaterOutput.model_validate(raw_output)
        title = str(pending.get("chapter_title") or chapter_heading_line(int(state["chapter_id"]), context.output_language))
        chapter_content = str(pending.get("chapter_content") or state.get("best_draft_content") or state.get("current_draft") or "")
        transaction_payload = {
            "state_updater_output": raw_output,
            "chapter_title": title,
            "chapter_content": chapter_content,
            "committed_status": "COMMITTED",
        }
        transaction = workflow_repository.create_state_transaction(
            run_id=context.run_id,
            story_id=state["story_id"],
            chapter_id=state["chapter_id"],
            payload=transaction_payload,
        )
        try:
            context.graph_store.apply_mutations(state["story_id"], parsed.mutations)
            workflow_repository.update_state_transaction(
                transaction.transaction_id,
                status=type(transaction.status).GRAPH_APPLIED,
                graph_applied=True,
            )
            context.vector_store.add_documents(state["story_id"], parsed.vector_documents)
            workflow_repository.update_state_transaction(
                transaction.transaction_id,
                status=type(transaction.status).VECTOR_APPLIED,
                vector_applied=True,
            )
            context.story_repository.upsert_chapter_content(
                story_id=state["story_id"],
                chapter_id=state["chapter_id"],
                title=title,
                content=chapter_content,
                status="completed",
            )
            pending_ext = state.get("pending_chapter_extraction") or {}
            story = context.story_repository.get_story(state["story_id"]) or {}
            rt = dict(parse_story_runtime(story.get("story_runtime_json")))
            rt["resolved_anchors"] = list(state.get("resolved_anchors") or [])
            rt["anchor_candidates"] = list(state.get("anchor_candidates") or [])
            lore = list(state.get("lore_mysteries_progression") or [])
            narrative = str(state.get("narrative_script") or "")
            mentions_memory = ("記憶" in narrative) or ("memory" in narrative.lower())
            if lore and mentions_memory:
                for item in lore:
                    if not isinstance(item, dict):
                        continue
                    pending_stages = list(item.get("pending_stages") or [])
                    if not pending_stages:
                        continue
                    stage = pending_stages.pop(0)
                    revealed = list(item.get("revealed_stages") or [])
                    if isinstance(stage, dict):
                        stage["chapter_revealed"] = int(state["chapter_id"])
                        revealed.append(stage)
                    item["revealed_stages"] = revealed
                    item["pending_stages"] = pending_stages
                    break
            rt["lore_mysteries_progression"] = lore
            context.story_repository.update_story_runtime_json(state["story_id"], rt)
            context.story_repository.update_story_macro_topology(
                state["story_id"],
                storylines=list(story.get("storylines_json") or []),
                anchor_nodes=list(state.get("anchor_nodes") or story.get("anchor_nodes_json") or []),
            )
            for raw in list(state.get("pending_cast_updates") or []):
                if not isinstance(raw, dict):
                    continue
                context.story_repository.apply_cast_update(state["story_id"], raw)
            workflow_repository.update_state_transaction(
                transaction.transaction_id,
                status=type(transaction.status).COMMITTED,
                sqlite_applied=True,
            )
        except Exception as exc:
            workflow_repository.update_state_transaction(
                transaction.transaction_id,
                status=type(transaction.status).FAILED,
                error_text=str(exc),
            )
            raise
        merged = {
            "workflow_status": WorkflowStatus.COMPLETED.value,
            "last_agent": "commit_to_databases",
            "state_transaction_id": transaction.transaction_id,
            "commit_executed": True,
            "pending_db_commit": {},
        }
        recorder.record_and_update_run(
            "commit_to_databases",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
        )
        return merged

    def profile_expander_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output = run_profile_expander(state, context)
        merged = {**output, "last_agent": "profile_expander", "resume_from": "state_updater"}
        recorder.record_and_update_run(
            "profile_expander",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
            route_decision="state_updater",
        )
        return merged

    def hitl_node(state: AgentWorkflowState) -> dict:
        merged = {
            "workflow_status": WorkflowStatus.WAITING_HITL.value,
            "requires_hitl": True,
            "last_agent": "hitl",
        }
        recorder.record_and_update_run("hitl", dict(state), merged, {**state, **merged}, route_decision="pause")
        return merged

    def route_plan_supervisor(state: AgentWorkflowState) -> str:
        return state["plan_route"]

    def route_draft_supervisor(state: AgentWorkflowState) -> str:
        return state["draft_route"]

    def route_reader(state: AgentWorkflowState) -> str:
        return state["reader_route"]

    def route_chapter_review_gate(state: AgentWorkflowState) -> str:
        return "hitl" if state.get("requires_hitl") else "chunker"

    def route_extraction_gate(state: AgentWorkflowState) -> str:
        r = str(state.get("extraction_route") or "")
        if r == "author":
            return "author"
        if r == "hitl":
            return "hitl"
        if r == "output_language_gate":
            return "output_language_gate"
        return "copyeditor" if get_settings().copyeditor_enabled else "output_language_gate"

    def route_output_language_gate(state: AgentWorkflowState) -> str:
        return str(state.get("language_gate_route") or "chapter_summarizer")

    def route_graph_rag(state: AgentWorkflowState) -> str:
        return state.get("graph_rag_route", "planner")

    def route_director(state: AgentWorkflowState) -> str:
        return "hitl" if state.get("requires_hitl") else "graph_rag"

    def route_anchor(state: AgentWorkflowState) -> str:
        return state.get("anchor_route", "profile_expander")

    def route_profile_expander(state: AgentWorkflowState) -> str:
        return "state_updater"

    def route_logic_alignment(state: AgentWorkflowState) -> str:
        return "hitl" if state.get("requires_hitl") else "author"

    def route_start(state: AgentWorkflowState) -> str:
        resume = str(state.get("resume_from") or "director")
        if resume == "director":
            selected = [str(x).strip() for x in (state.get("selected_anchor_ids") or []) if str(x).strip()]
            if selected:
                return "graph_rag"
        return resume

    def _timeout_node(name: str, fn: Any):
        return lambda s: _run_with_timeout(name, fn, s)

    graph = StateGraph(AgentWorkflowState)
    graph.add_node("director", _timeout_node("director", director_node))
    graph.add_node("graph_rag", _timeout_node("graph_rag", graph_rag_node))
    graph.add_node("planner", _timeout_node("planner", planner_node))
    graph.add_node("plan_supervisor", _timeout_node("plan_supervisor", plan_supervisor_node))
    graph.add_node("logic_alignment", _timeout_node("logic_alignment", logic_alignment_node))
    graph.add_node("author", _timeout_node("author", author_node))
    graph.add_node("draft_supervisor", _timeout_node("draft_supervisor", draft_supervisor_node))
    graph.add_node("reader", _timeout_node("reader", reader_node))
    graph.add_node("chapter_review_gate", _timeout_node("chapter_review_gate", chapter_review_gate_node))
    graph.add_node("chunker", _timeout_node("chunker", chunker_node))
    graph.add_node("vectorize_chunks", _timeout_node("vectorize_chunks", vectorize_chunks_node))
    graph.add_node("extraction_gate", _timeout_node("extraction_gate", extraction_gate_node))
    graph.add_node("copyeditor", _timeout_node("copyeditor", copyeditor_node))
    graph.add_node("output_language_gate", _timeout_node("output_language_gate", output_language_gate_node))
    graph.add_node("chapter_summarizer", _timeout_node("chapter_summarizer", chapter_summarizer_node))
    graph.add_node("anchor_resolve", _timeout_node("anchor_resolve", anchor_resolve_node))
    graph.add_node("profile_expander", _timeout_node("profile_expander", profile_expander_node))
    graph.add_node("state_updater", _timeout_node("state_updater", state_updater_node))
    graph.add_node("commit_to_databases", _timeout_node("commit_to_databases", commit_to_databases_node))
    graph.add_node("hitl", hitl_node)

    graph.add_conditional_edges(
        START,
        route_start,
        {
            "director": "director",
            "planner": "planner",
            "logic_alignment": "logic_alignment",
            "author": "author",
            "graph_rag": "graph_rag",
            "draft_supervisor": "draft_supervisor",
            "reader": "reader",
            "chapter_review_gate": "chapter_review_gate",
            "chunker": "chunker",
            "vectorize_chunks": "vectorize_chunks",
            "profile_expander": "profile_expander",
            "state_updater": "state_updater",
            "commit_to_databases": "commit_to_databases",
            "extraction_gate": "extraction_gate",
            "copyeditor": "copyeditor",
            "output_language_gate": "output_language_gate",
            "chapter_summarizer": "chapter_summarizer",
            "anchor_resolve": "anchor_resolve",
        },
    )
    graph.add_conditional_edges("director", route_director, {"graph_rag": "graph_rag", "hitl": "hitl"})
    graph.add_conditional_edges(
        "graph_rag",
        route_graph_rag,
        {"planner": "planner", "hitl": "hitl"},
    )
    graph.add_edge("planner", "plan_supervisor")
    graph.add_conditional_edges(
        "plan_supervisor",
        route_plan_supervisor,
        {"planner": "planner", "logic_alignment": "logic_alignment", "hitl": "hitl"},
    )
    graph.add_conditional_edges(
        "logic_alignment",
        route_logic_alignment,
        {"hitl": "hitl", "author": "author"},
    )
    graph.add_edge("author", "draft_supervisor")
    graph.add_conditional_edges(
        "draft_supervisor",
        route_draft_supervisor,
        {"author": "author", "reader": "reader", "hitl": "hitl"},
    )
    graph.add_conditional_edges(
        "reader",
        route_reader,
        {"author": "author", "chapter_review_gate": "chapter_review_gate"},
    )
    graph.add_conditional_edges(
        "chapter_review_gate",
        route_chapter_review_gate,
        {"chunker": "chunker", "hitl": "hitl"},
    )
    graph.add_edge("chunker", "vectorize_chunks")
    graph.add_edge("vectorize_chunks", "extraction_gate")
    graph.add_conditional_edges(
        "extraction_gate",
        route_extraction_gate,
        {
            "author": "author",
            "copyeditor": "copyeditor",
            "output_language_gate": "output_language_gate",
            "hitl": "hitl",
        },
    )
    graph.add_edge("copyeditor", "output_language_gate")
    graph.add_conditional_edges(
        "output_language_gate",
        route_output_language_gate,
        {"chapter_summarizer": "chapter_summarizer", "hitl": "hitl"},
    )
    graph.add_edge("chapter_summarizer", "anchor_resolve")
    graph.add_conditional_edges(
        "anchor_resolve",
        route_anchor,
        {"profile_expander": "profile_expander", "hitl": "hitl"},
    )
    graph.add_conditional_edges(
        "profile_expander",
        route_profile_expander,
        {"state_updater": "state_updater"},
    )
    graph.add_edge("hitl", END)
    graph.add_edge("state_updater", "commit_to_databases")
    graph.add_edge("commit_to_databases", END)
    return graph.compile()
