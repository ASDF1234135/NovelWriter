from app.domain.schema import EventOutline, HitlOutlineEditRequest, StoryInput
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
            {"chapter_content": f"第1章\n\n草稿版本 {author_calls['count']}"},
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
    assert final_state["reader_route"] == "state_updater"
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
            {"chapter_content": "第1章\n\n完成稿。"},
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
    assert final_state["reader_route"] == "state_updater"
    assert final_state["reader_feedback"] == []


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
