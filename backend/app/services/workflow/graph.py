from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.domain.schema import EdgeMutation, EdgeType, GraphQueryRequest, StateUpdaterOutput, WorkflowStatus
from app.domain.state import AgentWorkflowState, apply_length_bounds_to_state
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.author import run_author
from app.services.workflow.nodes.b_story_resolve import run_b_story_resolve
from app.services.workflow.nodes.director import run_director
from app.services.workflow.nodes.draft_supervisor import run_draft_supervisor
from app.services.workflow.nodes.extraction_gate import run_extraction_gate
from app.services.workflow.nodes.graph_rag import run_graph_rag
from app.services.workflow.nodes.plan_supervisor import run_plan_supervisor
from app.services.workflow.nodes.planner import run_planner
from app.services.workflow.nodes.reader import run_reader
from app.services.workflow.nodes.state_updater import run_state_updater
from app.services.workflow.chapter_pipeline import extraction_substantiated_event_ids, validate_b_story_resolution
from app.services.workflow.recorder import WorkflowRecorder, elapsed_ms, timed


def build_chapter_graph(context: WorkflowContext):
    workflow_repository: WorkflowRepository = context.workflow_repository
    recorder = WorkflowRecorder(context)

    def director_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output = run_director(state, context)
        recorder.record("director", dict(state), output, latency_ms=elapsed_ms(start))
        updated = {**state, **output, "last_agent": "director"}
        workflow_repository.update_run(context.run_id, updated)
        return output | {"last_agent": "director", "resume_from": "director"}

    def graph_rag_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output = run_graph_rag(state, context)
        recorder.record("graph_rag", dict(state), output, latency_ms=elapsed_ms(start))
        updated = {**state, **output, "last_agent": "graph_rag"}
        workflow_repository.update_run(context.run_id, updated)
        return output | {"last_agent": "graph_rag"}

    def planner_node(state: AgentWorkflowState) -> dict:
        start = timed()
        output, masked, tokens, latency = run_planner(state, context)
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
            pending_b.append({"id": bid, "desc": str(row.get("desc") or "")[:800]})
        merged_planner["pending_b_story_additions"] = pending_b
        tmp_state = {**state, **merged_planner}
        apply_length_bounds_to_state(tmp_state)
        merged_planner["normalized_length_min"] = tmp_state["normalized_length_min"]
        merged_planner["normalized_length_max"] = tmp_state["normalized_length_max"]
        recorder.record("planner", dict(state), merged_planner, masked_payload=masked, token_usage=tokens, latency_ms=latency or elapsed_ms(start))
        updated = {**state, **merged_planner, "last_agent": "planner"}
        workflow_repository.update_run(context.run_id, updated)
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
                    {"id": "allow_adjust_anchor", "label": "允許調整錨點"},
                    {"id": "force_rewrite_plan", "label": "強制重寫大綱"},
                ],
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
        recorder.record("author", masked, output, masked_payload=masked, token_usage=tokens, latency_ms=latency or elapsed_ms(start))
        hints = list(output.get("author_extraction_surface_hints") or [])
        updated = {
            **state,
            **output,
            "current_draft": output["chapter_content"],
            "author_extraction_surface_hints": hints,
            "last_agent": "author",
        }
        workflow_repository.update_run(context.run_id, updated)
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
        recorder.record(
            "reader",
            dict(state),
            merged,
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        workflow_repository.update_run(context.run_id, {**state, **merged})
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
            merged = {
                **gate_out,
                "draft_feedback": draft_feedback,
                "draft_retry_count": state["draft_retry_count"] + 1,
                "last_agent": "extraction_gate",
                "resume_from": "author",
            }
        else:
            merged = {**gate_out, "last_agent": "extraction_gate", "resume_from": "b_story_resolve"}
        recorder.record(
            "extraction_gate",
            dict(state),
            merged,
            latency_ms=elapsed_ms(start),
            route_decision=route,
        )
        workflow_repository.update_run(context.run_id, {**state, **merged})
        return merged

    def b_story_resolve_node(state: AgentWorkflowState) -> dict:
        start = timed()
        out = run_b_story_resolve(state, context)
        merged = {**out, "last_agent": "b_story_resolve", "resume_from": "state_updater"}
        recorder.record("b_story_resolve", dict(state), merged, latency_ms=elapsed_ms(start))
        workflow_repository.update_run(context.run_id, {**state, **merged})
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
                {"id": str(a.get("id")), "desc": str(a.get("desc") or "")[:800]}
                for a in additions
                if str(a.get("id") or "").strip()
            ]
            if seed:
                context.story_repository.merge_active_b_stories_seed(state["story_id"], seed)
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
        recorder.record("state_updater", dict(state), merged, latency_ms=elapsed_ms(start))
        workflow_repository.update_run(context.run_id, {**state, **merged})
        return merged

    def hitl_node(state: AgentWorkflowState) -> dict:
        merged = {
            "workflow_status": WorkflowStatus.WAITING_HITL.value,
            "requires_hitl": True,
            "last_agent": "hitl",
        }
        recorder.record("hitl", dict(state), merged, route_decision="pause")
        workflow_repository.update_run(context.run_id, {**state, **merged})
        return merged

    def route_plan_supervisor(state: AgentWorkflowState) -> str:
        return state["plan_route"]

    def route_draft_supervisor(state: AgentWorkflowState) -> str:
        return state["draft_route"]

    def route_reader(state: AgentWorkflowState) -> str:
        return state["reader_route"]

    def route_post_polish(state: AgentWorkflowState) -> str:
        return state.get("post_polish_route") or "resolve_subplots"

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
            "state_updater": "state_updater",
            "extraction_gate": "extraction_gate",
            "b_story_resolve": "b_story_resolve",
        },
    )
    graph.add_edge("director", "graph_rag")
    graph.add_edge("graph_rag", "planner")
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
        {"author": "author", "resolve_subplots": "b_story_resolve"},
    )
    graph.add_edge("b_story_resolve", "state_updater")
    graph.add_edge("hitl", END)
    graph.add_edge("state_updater", END)
    return graph.compile()
