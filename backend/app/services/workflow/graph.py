from __future__ import annotations

from typing import Any

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
from app.domain.state import AgentWorkflowState, apply_length_bounds_to_state
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.author import run_author
from app.services.workflow.nodes.b_story_resolve import run_b_story_resolve
from app.services.workflow.nodes.director import run_director
from app.services.workflow.nodes.draft_supervisor import run_draft_supervisor
from app.services.workflow.nodes.extraction_gate import run_extraction_gate
from app.services.workflow.nodes.chapter_summarizer import run_chapter_summarizer
from app.services.workflow.nodes.graph_rag import run_graph_rag
from app.services.workflow.nodes.plan_supervisor import run_plan_supervisor
from app.services.workflow.nodes.planner import run_planner
from app.services.workflow.nodes.reader import run_reader
from app.services.workflow.nodes.state_updater import run_state_updater
from app.services.workflow.chapter_pipeline import extraction_substantiated_event_ids, validate_b_story_resolution
from app.services.workflow.recorder import WorkflowRecorder, elapsed_ms, timed


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
        core_value = str(prof.get("core_value") or "")[:600] or core
        member = StoryCastMemberStored(
            node_id=node_id,
            canonical_name=name,
            role="supporting",
            short_bio=str(prof.get("short_bio") or "")[:500],
            aliases=[],
            age=str(prof.get("age") or "")[:48],
            motivation=core or str(prof.get("motivation") or "")[:600],
            core_motivation=core,
            core_value=core_value,
            speech_style=str(prof.get("speech_style") or "")[:240],
            fatal_flaw=str(prof.get("fatal_flaw") or "")[:400],
            quirks_and_habits=str(prof.get("quirks_and_habits") or "")[:400],
        )
        story_repository.append_story_cast_member_if_absent(story_id, member)


def _has_forbidden_resolution_keywords(text: str) -> bool:
    lowered = (text or "").lower()
    keys = ("精神連結", "神經駭入", "腦機", "mind link", "neural hack", "mental duel")
    return any(k in lowered for k in keys)


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
        if not chosen and bdir:
            for bs in state.get("active_b_stories") or []:
                if not isinstance(bs, dict):
                    continue
                desc = str(bs.get("desc") or "")
                if desc and (desc in bdir or bdir in desc):
                    chosen = bs.get("type")
                    break
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
        output = {**output, "manual_plan_force_approve": False}
        planned_nodes = list(output.get("proposed_new_nodes") or [])
        merged_planner = {**output, "planned_graph_nodes": planned_nodes}
        adds_raw = merged_planner.get("new_active_b_stories") or []
        pending_b: list[dict] = []
        for row in adds_raw[:2]:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("id") or "").strip()
            if not bid:
                continue
            pending_b.append(
                {
                    "id": bid,
                    "desc": str(row.get("desc") or "")[:800],
                    "type": str(row.get("type") or "UNKNOWN"),
                    "resolution_condition": str(row.get("resolution_condition") or "")[:800],
                }
            )
        merged_planner["pending_b_story_additions"] = pending_b
        cooldown = state.get("resolution_cooldown_constraint") or {}
        vibe_cooldown = state.get("ending_vibe_cooldown_constraint") or {}
        narrative = str(merged_planner.get("narrative_script") or "")
        boundary = str(merged_planner.get("ending_boundary_rule") or "")
        if cooldown.get("active") and _has_forbidden_resolution_keywords(narrative):
            merged_planner.update(
                {
                    "requires_hitl": True,
                    "hitl_reason": HitlReason.RESOLUTION_TACTIC_COOLDOWN_VIOLATION,
                    "hitl_decision_mode": "MANUAL_EDIT",
                    "workflow_status": WorkflowStatus.WAITING_HITL.value,
                    "resume_from": "planner",
                }
            )
        if (
            vibe_cooldown.get("active")
            and "SAFE_ROOM_EXPOSITION" in str(vibe_cooldown.get("forbidden_vibes") or [])
            and ("安全屋" in boundary or "密室" in boundary or "總結對話" in narrative)
        ):
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
        return merged_planner | {"last_agent": "planner", "resume_from": "planner"}

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
                "hitl_reason": "Plan_Loop_Exceeded",
                "hitl_decision_mode": "MANUAL_EDIT",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [
                    {"id": "allow_adjust_anchor", "label": "允許調整錨點（請另提交錨點延期）"},
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
                    "pending_hitl_options": [],
                    "resume_from": "planner",
                }
            elif not approved and "ENDING_VIBE_COOLDOWN_HARD_VIOLATION" in feedback_text:
                route = "hitl"
                updates = {
                    "requires_hitl": True,
                    "hitl_reason": HitlReason.ENDING_VIBE_COOLDOWN_VIOLATION,
                    "hitl_decision_mode": "MANUAL_EDIT",
                    "workflow_status": WorkflowStatus.WAITING_HITL.value,
                    "pending_hitl_options": [],
                    "resume_from": "planner",
                }
            else:
                route = "author" if approved else "planner"
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
            "resume_from": "author" if approved else updates.get("resume_from", state.get("resume_from", "planner")),
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
                "hitl_reason": "Draft_Loop_Exceeded",
                "hitl_decision_mode": "DASHBOARD",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [
                    {"id": "keep_current_logic", "label": "保持邏輯並重寫"},
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
            route = "extraction_gate"
            current_draft = state["current_draft"]
        elif draft_loop_retry_count > state.get("draft_loop_retry_limit", 3):
            route = "extraction_gate"
            current_draft = best_content or state["current_draft"]
        else:
            route = "author"
            current_draft = state["current_draft"]
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
            "resume_from": "author" if route == "author" else "extraction_gate",
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

    def extraction_gate_node(state: AgentWorkflowState) -> dict:
        start = timed()
        gate_out = run_extraction_gate(state, context)
        route = gate_out.get("post_polish_route") or "resolve_subplots"
        if route == "author":
            entry = gate_out.get("extraction_gate_feedback_entry") or {}
            draft_feedback = list(state["draft_feedback"])
            if entry:
                draft_feedback.append(entry)
            streak = int(state.get("extraction_gate_failure_streak", 0) or 0) + 1
            limit = int(state.get("extraction_hitl_limit", 4) or 4)
            hints = list(gate_out.get("hitl_extraction_remap_hints") or [])
            if streak > limit:
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
                    "post_polish_route": "hitl",
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
                }
        else:
            merged = {
                **gate_out,
                "extraction_gate_failure_streak": 0,
                "last_agent": "extraction_gate",
                "resume_from": "chapter_summarizer",
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

    def chapter_summarizer_node(state: AgentWorkflowState) -> dict:
        start = timed()
        run_chapter_summarizer(state, context)
        merged = {
            "last_agent": "chapter_summarizer",
            # Deterministic flow continues to b_story_resolve.
            "resume_from": "b_story_resolve",
        }
        recorder.record_and_update_run(
            "chapter_summarizer",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
        )
        return merged

    def b_story_resolve_node(state: AgentWorkflowState) -> dict:
        start = timed()
        out = run_b_story_resolve(state, context)
        route = "state_updater"
        base = {**out, "last_agent": "b_story_resolve"}
        if out.get("b_story_hitl_required"):
            route = "hitl"
            merged = {
                **base,
                "requires_hitl": True,
                "hitl_reason": HitlReason.B_STORY_RESOLUTION_FAILED,
                "hitl_decision_mode": "MANUAL_EDIT",
                "workflow_status": WorkflowStatus.WAITING_HITL.value,
                "pending_hitl_options": [
                    {"id": "b_story_wait_judgement", "label": "請使用副線裁判表單提交"},
                ],
                "resume_from": "b_story_resolve",
                "b_story_route": "hitl",
            }
        else:
            merged = {**base, "resume_from": "state_updater", "b_story_route": "state_updater"}
        recorder.record_and_update_run(
            "b_story_resolve",
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
        parsed = StateUpdaterOutput.model_validate(output)
        title = f"第 {state['chapter_id']} 章"
        chapter_content = state["best_draft_content"] or state["current_draft"]
        transaction_payload = {
            "state_updater_output": output,
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
            gt_ids = {str(e.get("event_id")) for e in (state.get("ground_truth_events") or []) if e.get("event_id")}
            substantiated = extraction_substantiated_event_ids(pending_ext, gt_ids)
            br = state.get("b_story_resolution") or {}
            resolved = [str(x).strip() for x in (br.get("resolved_b_stories") or []) if str(x).strip()]
            ok_resolve, _ = validate_b_story_resolution(br, substantiated)
            if not ok_resolve:
                resolved = []
            if resolved:
                context.story_repository.remove_resolved_b_stories_from_bible(state["story_id"], resolved)
            additions = state.get("pending_b_story_additions") or []
            seed = [
                {
                    "id": str(a.get("id")),
                    "desc": str(a.get("desc") or "")[:800],
                    "type": str(a.get("type") or "UNKNOWN"),
                    "resolution_condition": str(a.get("resolution_condition") or "")[:800],
                }
                for a in additions
                if str(a.get("id") or "").strip()
            ]
            if seed:
                context.story_repository.merge_active_b_stories_seed(state["story_id"], seed)
            lore = list(state.get("lore_mysteries_progression") or [])
            if lore:
                narrative = str(state.get("narrative_script") or "")
                mentions_memory = ("記憶" in narrative) or ("memory" in narrative.lower())
                if mentions_memory:
                    for item in lore:
                        if not isinstance(item, dict):
                            continue
                        pending = list(item.get("pending_stages") or [])
                        if not pending:
                            continue
                        stage = pending.pop(0)
                        revealed = list(item.get("revealed_stages") or [])
                        if isinstance(stage, dict):
                            stage["chapter_revealed"] = int(state["chapter_id"])
                            revealed.append(stage)
                        item["revealed_stages"] = revealed
                        item["pending_stages"] = pending
                        break
                story = context.story_repository.get_story(state["story_id"]) or {}
                bible = dict(story.get("bible_json") or {})
                bible["lore_mysteries_progression"] = lore
                context.story_repository.update_story_bible_json(state["story_id"], bible)
            _promote_planned_characters_to_cast(
                context.story_repository,
                state["story_id"],
                list(state.get("planned_graph_nodes") or []),
            )
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
            "state_updater_output": output,
            "workflow_status": WorkflowStatus.COMPLETED.value,
            "last_agent": "state_updater",
            "state_transaction_id": transaction.transaction_id,
            "pending_b_story_additions": [],
        }
        recorder.record_and_update_run(
            "state_updater",
            dict(state),
            merged,
            {**state, **merged},
            latency_ms=elapsed_ms(start),
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

    def route_post_polish(state: AgentWorkflowState) -> str:
        r = state.get("post_polish_route") or "resolve_subplots"
        if r == "hitl":
            return "hitl"
        return r

    def route_graph_rag(state: AgentWorkflowState) -> str:
        return state.get("graph_rag_route", "planner")

    def route_director(state: AgentWorkflowState) -> str:
        return "hitl" if state.get("requires_hitl") else "graph_rag"

    def route_b_story(state: AgentWorkflowState) -> str:
        return state.get("b_story_route", "state_updater")

    def route_start(state: AgentWorkflowState) -> str:
        return state.get("resume_from", "director")

    graph = StateGraph(AgentWorkflowState)
    graph.add_node("director", director_node)
    graph.add_node("graph_rag", graph_rag_node)
    graph.add_node("planner", planner_node)
    graph.add_node("plan_supervisor", plan_supervisor_node)
    graph.add_node("author", author_node)
    graph.add_node("draft_supervisor", draft_supervisor_node)
    graph.add_node("reader", reader_node)
    graph.add_node("extraction_gate", extraction_gate_node)
    graph.add_node("chapter_summarizer", chapter_summarizer_node)
    graph.add_node("b_story_resolve", b_story_resolve_node)
    graph.add_node("state_updater", state_updater_node)
    graph.add_node("hitl", hitl_node)

    graph.add_conditional_edges(
        START,
        route_start,
        {
            "director": "director",
            "planner": "planner",
            "author": "author",
            "graph_rag": "graph_rag",
            "draft_supervisor": "draft_supervisor",
            "reader": "reader",
            "state_updater": "state_updater",
            "extraction_gate": "extraction_gate",
            "chapter_summarizer": "chapter_summarizer",
            "b_story_resolve": "b_story_resolve",
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
        {"planner": "planner", "author": "author", "hitl": "hitl"},
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
        {"author": "author", "extraction_gate": "extraction_gate"},
    )
    graph.add_conditional_edges(
        "extraction_gate",
        route_post_polish,
        {"author": "author", "resolve_subplots": "chapter_summarizer", "hitl": "hitl"},
    )
    graph.add_edge("chapter_summarizer", "b_story_resolve")
    graph.add_conditional_edges(
        "b_story_resolve",
        route_b_story,
        {"state_updater": "state_updater", "hitl": "hitl"},
    )
    graph.add_edge("hitl", END)
    graph.add_edge("state_updater", END)
    return graph.compile()
