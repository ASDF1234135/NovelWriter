"""Tests for the post-reader human review HITL (chapter_review_gate)."""

from __future__ import annotations

import pytest

from app.domain.schema import (
    HitlDecisionRequest,
    HitlDraftEditRequest,
    HitlReason,
    StoryInput,
)
from app.domain.state import build_initial_state
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.graph import build_chapter_graph
from app.services.workflow.service import WorkflowService


def build_service(db_path: str) -> WorkflowService:
    db = SQLiteDatabase(db_path)
    return WorkflowService(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
    )


def _create_story(service: WorkflowService, *, require_review: bool = False) -> dict:
    return service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
            require_chapter_review=require_review,
        )
    )


def _fake_reader_approved(_state, _context):
    return {
        "is_approved": True,
        "literary_score": 78,
        "suggestion_type": "NONE",
        "critique": "",
    }


def _fake_extraction_gate_continue(_state, _context):
    return {
        "extraction_route": "continue",
        "pending_chapter_extraction": {"entities": [], "relations": []},
        "extraction_gate_error": "",
    }


def _fake_state_updater_passthrough(_state, _context):
    return {"mutations": [], "vector_documents": []}


def test_gate_passes_through_when_flag_disabled(tmp_path, monkeypatch) -> None:
    """When require_chapter_review is False the gate must not pause."""
    service = build_service(str(tmp_path / "review_gate_off.sqlite3"))
    story = _create_story(service, require_review=False)

    initial = build_initial_state(story["story_id"], 1, [], "trace-gate-off")
    initial["resume_from"] = "reader"
    initial["require_chapter_review"] = False
    run = service.workflow_repository.create_run(story["story_id"], 1, initial)

    monkeypatch.setattr("app.services.workflow.graph.run_reader", _fake_reader_approved)
    monkeypatch.setattr("app.services.workflow.graph.run_extraction_gate", _fake_extraction_gate_continue)
    monkeypatch.setattr("app.services.workflow.graph.run_state_updater", _fake_state_updater_passthrough)

    final = build_chapter_graph(service._build_context(run.run_id)).invoke(initial)

    assert final["workflow_status"] == "COMPLETED"
    assert not final.get("requires_hitl")
    assert final["reader_route"] == "chapter_review_gate"
    assert final["last_agent"] != "chapter_review_gate" or final.get("last_agent") == "commit_to_databases"


def test_gate_pauses_for_hitl_when_flag_enabled(tmp_path, monkeypatch) -> None:
    """When require_chapter_review is True the gate sets WAITING_HITL + CHAPTER_DRAFT_REVIEW."""
    service = build_service(str(tmp_path / "review_gate_on.sqlite3"))
    story = _create_story(service, require_review=True)

    initial = build_initial_state(story["story_id"], 1, [], "trace-gate-on")
    initial["resume_from"] = "reader"
    initial["require_chapter_review"] = True
    run = service.workflow_repository.create_run(story["story_id"], 1, initial)

    monkeypatch.setattr("app.services.workflow.graph.run_reader", _fake_reader_approved)

    final = build_chapter_graph(service._build_context(run.run_id)).invoke(initial)

    assert final["workflow_status"] == "WAITING_HITL"
    assert final["requires_hitl"] is True
    assert final["hitl_reason"] == HitlReason.CHAPTER_DRAFT_REVIEW
    assert final["hitl_decision_mode"] == "MANUAL_EDIT"
    assert final["resume_from"] == "chunker"
    option_ids = {row.get("id") for row in final["pending_hitl_options"]}
    assert option_ids == {"APPROVE_DRAFT", "RERUN_KEEP_DIRECTOR", "ABANDON_CHAPTER"}


def _setup_paused_review_state(service: WorkflowService) -> tuple[dict, str]:
    story = _create_story(service, require_review=True)
    state = build_initial_state(story["story_id"], 1, [], "trace-review-paused")
    state["require_chapter_review"] = True
    state["current_draft"] = "草稿正文版本 A。"
    state["best_draft_content"] = "草稿正文版本 A。"
    state["narrative_directive"] = "主角夜訪舊識追問線索"
    state["requires_hitl"] = True
    state["hitl_reason"] = HitlReason.CHAPTER_DRAFT_REVIEW
    state["hitl_decision_mode"] = "MANUAL_EDIT"
    state["workflow_status"] = "WAITING_HITL"
    state["pending_hitl_options"] = [
        {"id": "APPROVE_DRAFT", "label": "通過"},
        {"id": "RERUN_KEEP_DIRECTOR", "label": "重跑"},
        {"id": "ABANDON_CHAPTER", "label": "放棄"},
    ]
    state["resume_from"] = "chunker"
    run = service.workflow_repository.create_run(story["story_id"], 1, state)
    return state, run.run_id


def test_approve_draft_resumes_from_chunker(tmp_path, monkeypatch) -> None:
    service = build_service(str(tmp_path / "review_approve.sqlite3"))
    _, run_id = _setup_paused_review_state(service)

    # Block the background graph run so we only test the apply step.
    monkeypatch.setattr(service, "_execute_workflow", lambda _rid, _s: None)

    service.apply_hitl_decision(run_id, HitlDecisionRequest(option_id="APPROVE_DRAFT"))

    after = service.workflow_repository.get_run_state(run_id)
    assert after["resume_from"] == "chunker"
    assert after["workflow_status"] == "RUNNING"
    assert after["requires_hitl"] is False
    assert after["hitl_reason"] == ""
    assert after["current_draft"] == "草稿正文版本 A。"  # draft preserved


def test_draft_edit_overwrites_best_draft(tmp_path, monkeypatch) -> None:
    service = build_service(str(tmp_path / "review_edit.sqlite3"))
    _, run_id = _setup_paused_review_state(service)

    monkeypatch.setattr(service, "_execute_workflow", lambda _rid, _s: None)

    edited = "編輯後的草稿正文。\n\n第二段。"
    service.apply_hitl_draft_edit(
        run_id,
        HitlDraftEditRequest(
            chapter_content=edited,
            resume_from="chunker",
        ),
    )

    after = service.workflow_repository.get_run_state(run_id)
    assert after["resume_from"] == "chunker"
    assert after["current_draft"] == edited
    assert after["best_draft_content"] == edited
    assert after["workflow_status"] == "RUNNING"


def test_rerun_keep_director_resets_draft_and_resumes_planner(tmp_path, monkeypatch) -> None:
    service = build_service(str(tmp_path / "review_rerun.sqlite3"))
    _, run_id = _setup_paused_review_state(service)

    monkeypatch.setattr(service, "_execute_workflow", lambda _rid, _s: None)

    service.apply_hitl_decision(run_id, HitlDecisionRequest(option_id="RERUN_KEEP_DIRECTOR"))

    after = service.workflow_repository.get_run_state(run_id)
    assert after["resume_from"] == "planner"
    assert after["workflow_status"] == "RUNNING"
    assert after["requires_hitl"] is False
    assert after["hitl_reason"] == ""
    # ABORT_AND_RESTART semantics: draft wiped, director directive preserved, review flag carried over.
    assert after["current_draft"] == ""
    assert after["best_draft_content"] == ""
    assert after["narrative_directive"] == "主角夜訪舊識追問線索"
    assert bool(after.get("require_chapter_review")) is True


def test_abandon_chapter_marks_run_cancelled(tmp_path, monkeypatch) -> None:
    service = build_service(str(tmp_path / "review_abandon.sqlite3"))
    _, run_id = _setup_paused_review_state(service)

    # Even if execute_stored_run is scheduled, CANCELLED state must short-circuit it.
    monkeypatch.setattr(service, "_execute_workflow", lambda _rid, _s: pytest.fail("graph must not resume after abandon"))

    service.apply_hitl_decision(run_id, HitlDecisionRequest(option_id="ABANDON_CHAPTER"))
    service.execute_stored_run(run_id)  # must be a no-op

    after = service.workflow_repository.get_run_state(run_id)
    assert after["workflow_status"] == "CANCELLED"
    assert after["requires_hitl"] is False
    assert after["hitl_reason"] == ""
    assert after["resume_from"] == ""
    # Chapter row should not have been committed by the workflow.
    story_id = after["story_id"]
    chapter = service.story_repository.get_chapter(story_id, 1)
    assert chapter is None or (chapter.get("status") or "").lower() != "completed"


def test_chapter_review_payload_exposed_via_get_workflow(tmp_path) -> None:
    service = build_service(str(tmp_path / "review_payload.sqlite3"))
    _, run_id = _setup_paused_review_state(service)
    payload = service.get_workflow(run_id)
    hctx = payload["run"]["hitl_context"]
    assert hctx is not None
    assert hctx["context_metadata"]["payload_type"] == "chapter_review"
    assert hctx["problematic_draft_snippet"]


def test_start_run_chapter_per_run_override_beats_story_default(tmp_path) -> None:
    service = build_service(str(tmp_path / "review_override.sqlite3"))
    story = _create_story(service, require_review=False)
    service.macro_compile(story["story_id"])
    payload = service.start_run_chapter(
        story["story_id"],
        1,
        require_chapter_review=True,
    )
    state = payload["state"]
    assert bool(state.get("require_chapter_review")) is True
