from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.plan_supervisor import run_plan_supervisor


def build_context(db_path: str) -> WorkflowContext:
    db = SQLiteDatabase(db_path)
    return WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="plan-supervisor-test",
    )


def test_plan_supervisor_allows_partial_convergence_before_anchor_chapter(tmp_path) -> None:
    context = build_context(str(tmp_path / "plan_supervisor.sqlite3"))
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [
            {
                "anchor_id": "anchor_06",
                "chapter_target": 6,
            }
        ],
        "ground_truth_events": [
            {
                "event_id": "e001",
                "description": "主角在穩定日常中發現異常，為遠期錨點鋪墊。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "本章建立穩定日常與微小異常，章末以召喚令迫使主角離開熟悉環境。",
        "chapter_start_location": "舊城區住處",
        "chapter_end_location_hint": "王都西門",
        "must_include_beats": ["發現異常", "離開住處"],
        "previous_chapter_summary": "主角暫時維持日常生活。",
        "recent_chapter_context": "第0章：主角暫時維持日常生活。",
        "last_known_location": "舊城區住處",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, payload = run_plan_supervisor(state, context)

    assert payload["partial_convergence_allowed"] is True
    assert output["is_approved"] is True
    assert output["anchor_achieved"] is False


def test_plan_supervisor_requires_anchor_completion_on_target_chapter(tmp_path) -> None:
    context = build_context(str(tmp_path / "plan_supervisor_target.sqlite3"))
    state = {
        "chapter_id": 6,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [
            {
                "anchor_id": "anchor_06",
                "chapter_target": 6,
            }
        ],
        "ground_truth_events": [
            {
                "event_id": "e006",
                "description": "主角已被迫踏上旅程。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "主角在城門前回望王都，正式離開原本的生活。",
        "chapter_start_location": "王都內城",
        "chapter_end_location_hint": "王都城門外驛道",
        "must_include_beats": ["正式離開王都"],
        "previous_chapter_summary": "主角在城門前猶豫。",
        "recent_chapter_context": "第5章：主角在城門前猶豫。",
        "last_known_location": "王都內城",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, payload = run_plan_supervisor(state, context)

    assert payload["partial_convergence_allowed"] is False
    assert output["is_approved"] is False
    assert "ANCHOR_DIVERGENCE" in output["violation_type"]


def test_plan_supervisor_blocks_timeline_rollback(tmp_path) -> None:
    context = build_context(str(tmp_path / "plan_supervisor_rollback.sqlite3"))
    state = {
        "chapter_id": 2,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [{"anchor_id": "anchor_06", "chapter_target": 6}],
        "ground_truth_events": [
            {
                "event_id": "e002",
                "description": "主角收到密信，決定回城調查。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "本章再次讓主角收到密信，並決定回城調查。",
        "chapter_start_location": "城外驛站",
        "chapter_end_location_hint": "城外驛站",
        "must_include_beats": ["收到密信", "決定回城"],
        "previous_chapter_summary": "主角收到密信，決定回城調查。",
        "recent_chapter_context": "第1章：主角收到密信，決定回城調查。",
        "last_known_location": "城外驛站",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_plan_supervisor(state, context)

    assert output["is_approved"] is False
    assert "INCONSISTENCY" in output["violation_type"]
    assert "重演上一章" in output["feedback_to_agent"]


def test_plan_supervisor_teleportation_is_llm_only_mock_does_not_block(tmp_path) -> None:
    """Location paradox is judged by the real plan_supervisor LLM; MockLLM has no teleport check."""
    context = build_context(str(tmp_path / "plan_supervisor_teleport.sqlite3"))
    state = {
        "chapter_id": 2,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [{"anchor_id": "anchor_06", "chapter_target": 6}],
        "ground_truth_events": [
            {
                "event_id": "e002",
                "description": "主角在黑塔密室開始搜查新文件。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "本章開場就在黑塔密室搜查，直接切入新線索。",
        "chapter_start_location": "黑塔密室",
        "chapter_end_location_hint": "黑塔密室",
        "must_include_beats": ["搜查文件"],
        "previous_chapter_summary": "主角留在港口旅店休息。",
        "recent_chapter_context": "第1章：主角留在港口旅店休息。",
        "last_known_location": "港口旅店",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_plan_supervisor(state, context)

    assert output["is_approved"] is True
    assert "PHYSICAL_CONFLICT" not in output["violation_type"]
