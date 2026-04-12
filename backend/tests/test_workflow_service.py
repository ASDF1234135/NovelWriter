import pytest

from app.domain.schema import (
    EventOutline,
    HitlAnchorDelayRequest,
    HitlDecisionRequest,
    HitlOutlineEditRequest,
    HitlReason,
    HitlStateInjectionRequest,
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
from app.services.workflow.service import ChapterAlreadyCompletedError, HitlNotWaitingError, WorkflowService


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


def test_full_workflow_runs_end_to_end(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )

    macro = service.macro_compile(story["story_id"])
    assert len(macro["anchors"]) >= 1
    assert macro.get("protagonist_character_id")
    assert macro.get("cast")
    assert macro["protagonist_character_id"] in service.graph_store.story_nodes[story["story_id"]]

    result = service.run_chapter(story["story_id"], 1)

    assert result["run"]["status"] == "COMPLETED"
    assert result["state"]["workflow_status"] == "COMPLETED"
    assert result["state"]["current_draft"]
    assert result["steps"]
    assert result["state"]["pov_character_id"] == macro["protagonist_character_id"]


def test_run_chapter_rejects_when_chapter_already_completed(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_dup_chapter.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    service.run_chapter(story["story_id"], 1)
    with pytest.raises(ChapterAlreadyCompletedError):
        service.run_chapter(story["story_id"], 1)


def test_story_persists_retry_limits(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_limits.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
            plan_retry_limit=5,
            draft_loop_retry_limit=2,
        )
    )

    assert story["plan_retry_limit"] == 5
    assert story["draft_loop_retry_limit"] == 2


def test_draft_and_reader_share_combined_retry_limit(tmp_path, monkeypatch) -> None:
    service = build_service(str(tmp_path / "workflow_combined_retry.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
            draft_loop_retry_limit=1,
        )
    )
    initial_state = build_initial_state(
        story["story_id"],
        1,
        [],
        "trace-combined",
        draft_loop_retry_limit=1,
    )
    initial_state["resume_from"] = "author"
    run = service.workflow_repository.create_run(story["story_id"], 1, initial_state)

    author_calls = {"count": 0}
    draft_supervisor_calls = {"count": 0}

    def fake_run_author(state, context):
        author_calls["count"] += 1
        return (
            {
                "chapter_content": f"第1章\n\n草稿版本 {author_calls['count']}",
                "author_extraction_surface_hints": [],
                "word_count": 12,
            },
            {"safe": True},
            0,
            0,
        )

    def fake_run_draft_supervisor(state, context):
        draft_supervisor_calls["count"] += 1
        if draft_supervisor_calls["count"] == 1:
            return (
                {
                    "is_approved": False,
                    "violation_type": ["INCONSISTENCY"],
                    "suggestion_type": "REWRITE",
                    "feedback_to_agent": "草稿需要重寫。",
                },
                {"safe": True},
            )
        return (
            {
                "is_approved": True,
                "violation_type": ["NONE"],
                "suggestion_type": "NONE",
                "feedback_to_agent": "",
            },
            {"safe": True},
        )

    def fake_run_reader(state, context):
        return {
            "is_approved": False,
            "literary_score": 55,
            "suggestion_type": "MODIFY",
            "critique": "讀者評審要求再修一次。",
        }

    def fake_run_state_updater(state, context):
        return {"mutations": [], "vector_documents": []}

    monkeypatch.setattr("app.services.workflow.graph.run_author", fake_run_author)
    monkeypatch.setattr("app.services.workflow.graph.run_draft_supervisor", fake_run_draft_supervisor)
    monkeypatch.setattr("app.services.workflow.graph.run_reader", fake_run_reader)
    monkeypatch.setattr("app.services.workflow.graph.run_state_updater", fake_run_state_updater)

    final_state = build_chapter_graph(service._build_context(run.run_id)).invoke(initial_state)

    assert final_state["workflow_status"] == "COMPLETED"
    assert final_state["draft_retry_count"] == 1
    assert final_state["reader_retry_count"] == 1
    assert final_state["draft_loop_retry_count"] == 2
    assert final_state["reader_route"] == "extraction_gate"
    assert final_state["reader_feedback"] == [
        {
            "score": 55,
            "message": "讀者評審要求再修一次。",
            "suggestion": "MODIFY",
        }
    ]


def test_reader_pass_does_not_append_feedback_or_return_author(tmp_path, monkeypatch) -> None:
    service = build_service(str(tmp_path / "workflow_reader_pass.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    initial_state = build_initial_state(story["story_id"], 1, [], "trace-reader-pass")
    initial_state["resume_from"] = "author"
    run = service.workflow_repository.create_run(story["story_id"], 1, initial_state)

    def fake_run_author(state, context):
        return (
            {
                "chapter_content": "第1章\n\n完成稿。",
                "author_extraction_surface_hints": [],
                "word_count": 8,
            },
            {"safe": True},
            0,
            0,
        )

    def fake_run_draft_supervisor(state, context):
        return (
            {
                "is_approved": True,
                "violation_type": ["NONE"],
                "suggestion_type": "NONE",
                "feedback_to_agent": "",
            },
            {"safe": True},
        )

    def fake_run_reader(state, context):
        return {
            "is_approved": True,
            "literary_score": 82,
            "suggestion_type": "NONE",
            "critique": "可再微調，但已達通過標準。",
        }

    def fake_run_state_updater(state, context):
        return {"mutations": [], "vector_documents": []}

    monkeypatch.setattr("app.services.workflow.graph.run_author", fake_run_author)
    monkeypatch.setattr("app.services.workflow.graph.run_draft_supervisor", fake_run_draft_supervisor)
    monkeypatch.setattr("app.services.workflow.graph.run_reader", fake_run_reader)
    monkeypatch.setattr("app.services.workflow.graph.run_state_updater", fake_run_state_updater)

    final_state = build_chapter_graph(service._build_context(run.run_id)).invoke(initial_state)

    assert final_state["workflow_status"] == "COMPLETED"
    assert final_state["reader_route"] == "extraction_gate"
    assert final_state["reader_feedback"] == []


def test_resume_from_reader_does_not_crash_keyerror(tmp_path, monkeypatch) -> None:
    """
    Regression test for LangGraph crash:
    KeyError('reader') when START conditional edges ends mapping is missing 'reader'.
    """
    service = build_service(str(tmp_path / "workflow_resume_reader.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )

    initial_state = build_initial_state(story["story_id"], 1, [], "trace-resume-reader")
    initial_state["resume_from"] = "reader"

    run = service.workflow_repository.create_run(story["story_id"], 1, initial_state)

    def fake_run_reader(state, context):
        # Ensure reader is approved so graph proceeds to extraction_gate.
        return {
            "is_approved": True,
            "literary_score": 80,
            "suggestion_type": "NONE",
            "critique": "",
        }

    def fake_run_extraction_gate(state, context):
        # Skip heavy extraction; drive the graph into b_story_resolve and then state_updater.
        return {
            "post_polish_route": "resolve_subplots",
            "pending_chapter_extraction": {"entities": [], "relations": []},
            "extraction_gate_error": "",
        }

    def fake_run_state_updater(state, context):
        return {"mutations": [], "vector_documents": []}

    monkeypatch.setattr("app.services.workflow.graph.run_reader", fake_run_reader)
    monkeypatch.setattr("app.services.workflow.graph.run_extraction_gate", fake_run_extraction_gate)
    monkeypatch.setattr("app.services.workflow.graph.run_state_updater", fake_run_state_updater)

    final_state = build_chapter_graph(service._build_context(run.run_id)).invoke(initial_state)

    assert final_state["workflow_status"] == "COMPLETED"


def test_hitl_outline_edit_auto_resumes(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_hitl.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    anchors = service.story_repository.list_anchors(story["story_id"])
    story_row = service.story_repository.get_story(story["story_id"])
    state = build_initial_state(
        story["story_id"],
        1,
        anchors,
        "trace-hitl",
        pov_character_id=story_row.get("protagonist_character_id") or "char_public_observer",
    )
    state["requires_hitl"] = True
    state["workflow_status"] = "WAITING_HITL"
    state["hitl_reason"] = "Plan_Loop_Exceeded"
    state["hitl_decision_mode"] = "MANUAL_EDIT"
    state["resume_from"] = "planner"
    run = service.workflow_repository.create_run(story["story_id"], 1, state)

    response = service.handle_hitl_outline_edit(
        run.run_id,
        HitlOutlineEditRequest(
            ground_truth_events=[
                EventOutline(event_id="event_manual_01", description="主角獲得新線索", caused_by_event_id=None)
            ],
            narrative_script="主角在夜色中追查新線索，氣氛必須懸疑。",
        ),
    )

    assert response["run"]["status"] == "COMPLETED"
    assert response["state"]["workflow_status"] == "COMPLETED"
    assert response["state"]["state_transaction_id"]


def test_hitl_decision_resets_counters_after_draft_loop(monkeypatch, tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_hitl_draft_reset.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    anchors = service.story_repository.list_anchors(story["story_id"])
    story_row = service.story_repository.get_story(story["story_id"])
    state = build_initial_state(
        story["story_id"],
        1,
        anchors,
        "trace-hitl-draft",
        pov_character_id=story_row.get("protagonist_character_id") or "char_public_observer",
    )
    state["requires_hitl"] = True
    state["workflow_status"] = "WAITING_HITL"
    state["hitl_reason"] = "Draft_Loop_Exceeded"
    state["draft_loop_retry_count"] = 9
    state["draft_retry_count"] = 9
    state["reader_retry_count"] = 4
    state["resume_from"] = "author"
    run = service.workflow_repository.create_run(story["story_id"], 1, state)
    monkeypatch.setattr(service, "_execute_workflow", lambda _rid, _s: _s)

    service.handle_hitl_decision(run.run_id, HitlDecisionRequest(option_id="relax_word_count"))
    st = service.workflow_repository.get_run_state(run.run_id)
    assert st["draft_loop_retry_count"] == 0
    assert st["draft_retry_count"] == 0
    assert st["reader_retry_count"] == 0


def test_hitl_outline_sets_resume_from_by_reason(monkeypatch, tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_hitl_resume.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    anchors = service.story_repository.list_anchors(story["story_id"])
    story_row = service.story_repository.get_story(story["story_id"])
    base = build_initial_state(
        story["story_id"],
        1,
        anchors,
        "trace-resume",
        pov_character_id=story_row.get("protagonist_character_id") or "char_public_observer",
    )
    monkeypatch.setattr(service, "_execute_workflow", lambda _rid, _s: _s)

    for reason, expected in (
        ("Plan_Loop_Exceeded", "planner"),
        ("Draft_Loop_Exceeded", "author"),
    ):
        state = {**base, "requires_hitl": True, "workflow_status": "WAITING_HITL", "hitl_reason": reason}
        run = service.workflow_repository.create_run(story["story_id"], 1, state)
        service.handle_hitl_outline_edit(
            run.run_id,
            HitlOutlineEditRequest(
                ground_truth_events=[
                    EventOutline(event_id="event_manual_01", description="手動事件", caused_by_event_id=None)
                ],
            ),
        )
        st = service.workflow_repository.get_run_state(run.run_id)
        assert st["resume_from"] == expected


def test_alignment_hitl_state_injection_sets_rules_and_resumes_alignment(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_align_hitl_state.sqlite3"))
    story = service.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=12000))
    base = build_initial_state(story["story_id"], 1, [], "trace-align-hitl")
    base["requires_hitl"] = True
    base["workflow_status"] = "WAITING_HITL"
    base["hitl_reason"] = HitlReason.ALIGNMENT_RULES_REQUIRED
    base["resume_from"] = "logic_alignment"
    run = service.workflow_repository.create_run(story["story_id"], 1, base)

    req = HitlStateInjectionRequest(
        mutations=[],
        chapter_hard_rules="每回合只能行動一次；失敗方失去全部籌碼。",
        resume_from="logic_alignment",
    )
    service.apply_hitl_state_injection(run.run_id, req)
    st = service.workflow_repository.get_run_state(run.run_id)
    assert st["requires_hitl"] is False
    assert st["hitl_reason"] == ""
    assert st["resume_from"] == "logic_alignment"
    assert st["chapter_hard_rules"] == "每回合只能行動一次；失敗方失去全部籌碼。"


def test_logic_alignment_routes_to_hitl_when_rules_missing_and_draft_complex(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_align_route.sqlite3"))
    story = service.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=12000))
    base = build_initial_state(story["story_id"], 1, [], "trace-align-route")
    base["resume_from"] = "logic_alignment"
    base["chapter_hard_rules"] = ""
    base["narrative_script"] = "啟動俄羅斯輪盤變體，依回合判定與籌碼結算決定生死。"
    base["must_include_beats"] = ["宣告勝利條件", "回合判定", "籌碼結算"]
    base["ground_truth_events"] = [{"event_id": "E1", "description": "開局與判定機制"}]
    run = service.workflow_repository.create_run(story["story_id"], 1, base)
    service.execute_stored_run(run.run_id)
    st = service.workflow_repository.get_run_state(run.run_id)
    assert st["workflow_status"] == "WAITING_HITL"
    assert st["requires_hitl"] is True
    assert st["hitl_reason"] == HitlReason.ALIGNMENT_RULES_REQUIRED
    assert st["resume_from"] == "logic_alignment"


def test_logic_alignment_retry_limit_force_passes_with_warning(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_align_retry.sqlite3"))
    story = service.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=12000))
    base = build_initial_state(story["story_id"], 1, [], "trace-align-retry")
    base["resume_from"] = "logic_alignment"
    base["chapter_hard_rules"] = ""
    base["narrative_script"] = "進入俄羅斯輪盤變體，採回合制與籌碼談判。"
    base["must_include_beats"] = ["回合判定", "籌碼談判"]
    base["ground_truth_events"] = [{"event_id": "E1", "description": "高複雜博弈"}]
    base["alignment_hitl_retry_count"] = 1
    run = service.workflow_repository.create_run(story["story_id"], 1, base)
    service.execute_stored_run(run.run_id)
    st = service.workflow_repository.get_run_state(run.run_id)
    # Should not get stuck in infinite HITL loop.
    assert st["requires_hitl"] is False
    assert "force-pass" in str(st.get("alignment_log") or "").lower() or st["workflow_status"] in ("RUNNING", "COMPLETED")


def test_hitl_force_approve_plan_sets_resume_author(monkeypatch, tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_hitl_force_approve.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    anchors = service.story_repository.list_anchors(story["story_id"])
    story_row = service.story_repository.get_story(story["story_id"])
    state = build_initial_state(
        story["story_id"],
        1,
        anchors,
        "trace-fa",
        pov_character_id=story_row.get("protagonist_character_id") or "char_public_observer",
    )
    state["requires_hitl"] = True
    state["workflow_status"] = "WAITING_HITL"
    state["hitl_reason"] = HitlReason.PLAN_LOOP_EXCEEDED
    state["resume_from"] = "planner"
    run = service.workflow_repository.create_run(story["story_id"], 1, state)
    monkeypatch.setattr(service, "_execute_workflow", lambda _rid, _s: None)

    service.handle_hitl_decision(run.run_id, HitlDecisionRequest(option_id="force_approve_plan"))
    st = service.workflow_repository.get_run_state(run.run_id)
    assert st["resume_from"] == "author"
    assert st["manual_plan_force_approve"] is True


def test_hitl_anchor_delay_updates_anchor_row(monkeypatch, tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_hitl_anchor.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    anchors = service.story_repository.list_anchors(story["story_id"])
    story_row = service.story_repository.get_story(story["story_id"])
    aid = str(anchors[0]["anchor_id"])
    old_ct = int(anchors[0]["chapter_target"])
    state = build_initial_state(
        story["story_id"],
        1,
        anchors,
        "trace-ad",
        pov_character_id=story_row.get("protagonist_character_id") or "char_public_observer",
    )
    state["requires_hitl"] = True
    state["workflow_status"] = "WAITING_HITL"
    state["hitl_reason"] = HitlReason.PLAN_LOOP_EXCEEDED
    run = service.workflow_repository.create_run(story["story_id"], 1, state)
    monkeypatch.setattr(service, "_execute_workflow", lambda _rid, _s: None)

    service.handle_hitl_anchor_delay(
        run.run_id,
        HitlAnchorDelayRequest(anchor_id=aid, new_chapter_target=old_ct + 4),
    )
    rows = service.story_repository.list_anchors(story["story_id"])
    match = next(r for r in rows if str(r["anchor_id"]) == aid)
    assert int(match["chapter_target"]) == old_ct + 4


def test_hitl_decision_raises_when_not_paused(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_hitl_guard.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    result = service.run_chapter(story["story_id"], 1)
    run_id = result["run"]["run_id"]

    with pytest.raises(HitlNotWaitingError):
        service.handle_hitl_decision(run_id, HitlDecisionRequest(option_id="relax_word_count"))


def test_state_transaction_replay(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_replay.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    result = service.run_chapter(story["story_id"], 1)
    transaction_id = result["state"]["state_transaction_id"]

    service.workflow_repository.update_state_transaction(
        transaction_id,
        status=type(service.workflow_repository.get_state_transaction(transaction_id).status).FAILED,
        sqlite_applied=False,
        error_text="simulated failure",
    )
    replayed = service.replay_state_transaction(transaction_id)

    assert replayed["status"] == "COMMITTED"


def test_chapter_can_be_listed_and_loaded_after_run(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_chapter_read.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    service.run_chapter(story["story_id"], 1)

    chapters = service.list_chapters(story["story_id"])
    chapter = service.get_chapter(story["story_id"], 1)

    assert len(chapters) == 1
    assert chapters[0]["chapter_id"] == 1
    assert chapter["chapter_id"] == 1
    assert chapter["status"] == "completed"
    assert chapter["content"]


def test_author_step_logs_masked_input_only(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_author_mask.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])

    result = service.run_chapter(story["story_id"], 1)
    author_step = next(step for step in result["steps"] if step["agent_name"] == "author")
    logged_input = author_step["input_payload_json"]

    assert "narrative_script" in logged_input
    assert "must_include_beats" in logged_input
    assert "reader_unresolved_questions" in logged_input
    assert "normalized_length_min" in logged_input
    assert "chapter_end_location_hint" in logged_input
    assert "ending_boundary_rule" in logged_input
    assert "ground_truth_events" not in logged_input
    assert "graph_context" not in logged_input


def test_chapter_two_receives_safe_continuity_packet(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_continuity.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"rules": ["秘密不能無代價揭露"]},
            target_total_words=30000,
        )
    )
    service.macro_compile(story["story_id"])
    service.run_chapter(story["story_id"], 1)

    result = service.run_chapter(story["story_id"], 2)
    planner_step = next(step for step in result["steps"] if step["agent_name"] == "planner")
    author_step = next(step for step in result["steps"] if step["agent_name"] == "author")

    assert planner_step["masked_payload_json"]["previous_chapter_summary"]
    assert planner_step["masked_payload_json"]["recent_chapter_context"]
    assert "last_known_location" in planner_step["masked_payload_json"]
    assert "chapter_start_location" in planner_step["output_payload_json"]
    assert author_step["input_payload_json"]["previous_chapter_summary"]
    assert "normalized_length_min" in author_step["input_payload_json"]
    assert "ground_truth_events" not in author_step["input_payload_json"]


def test_start_run_bootstraps_lore_and_cooldown_constraints(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_lore_cooldown.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={
                "lore_mysteries_progression": [
                    {
                        "mystery_id": "noah_memory_001",
                        "description": "諾亞失去的關鍵記憶",
                        "pending_stages": [{"stage": 3, "content": "揭露追殺者真面目"}],
                    }
                ]
            },
            target_total_words=30000,
        )
    )
    service.story_repository.upsert_chapter_summary(
        story["story_id"], 1, plot_summary="P1", conflict_type="MYSTERY", resolution_method="DISCOVERY"
    )
    service.story_repository.upsert_chapter_summary(
        story["story_id"], 2, plot_summary="P2", conflict_type="MYSTERY", resolution_method="DISCOVERY"
    )
    service.story_repository.upsert_chapter_summary(
        story["story_id"], 3, plot_summary="P3", conflict_type="MYSTERY", resolution_method="DISCOVERY"
    )
    wf = service.start_run_chapter(story["story_id"], 4)
    st = wf["state"]
    assert st["lore_mysteries_progression"]
    assert st["resolution_cooldown_constraint"].get("active") is True


def test_start_run_bootstraps_writing_note_from_bible(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_writing_note.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角回到王都追查命案。",
            bible={"writing_note": ["短句優先", "避免過度抒情", ""]},
            target_total_words=30000,
        )
    )
    wf = service.start_run_chapter(story["story_id"], 1)
    st = wf["state"]
    assert "短句優先" in st["writing_note"]
    assert "避免過度抒情" in st["writing_note"]
    assert any("命名節制" in line for line in st["writing_note"])
    assert any("去標籤化" in line for line in st["writing_note"])
