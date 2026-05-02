from app.domain.schema import HitlReason, StoryInput, WorkflowStatus
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


def test_director_cooldown_does_not_block_run_under_mock_director(tmp_path) -> None:
    service = build_service(str(tmp_path / "b_story_cooldown.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="主角在王都追查命案。",
            bible={},
            target_total_words=30000,
        )
    )

    anchors = [
        {"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "chapter_target": 6, "description": "離開原本安穩場域，正式捲入主線。"}
    ]
    state = build_initial_state(
        story["story_id"],
        2,
        anchors,
        "trace-cooldown",
    )
    state["distance_to_anchor"] = 3
    state["recent_b_story_types"] = ["FETCH_QUEST"]

    run = service.workflow_repository.create_run(story["story_id"], 2, state)
    final_state = build_chapter_graph(service._build_context(run.run_id)).invoke(state)

    assert final_state["workflow_status"] == WorkflowStatus.COMPLETED.value
    assert final_state["requires_hitl"] is False
    assert final_state["hitl_reason"] != HitlReason.B_STORY_COOLDOWN_VIOLATION

