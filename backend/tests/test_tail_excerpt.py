from app.domain.schema import StoryInput
from app.services.workflow.service import WorkflowService, _extract_tail_excerpt
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore


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


def test_extract_tail_excerpt_uses_last_paragraphs_within_budget() -> None:
    paras = [
        "A" * 52,
        "B" * 52,
        "C" * 52,
        "D" * 52,
    ]
    content = "第1章\n\n" + "\n\n".join(paras)
    excerpt = _extract_tail_excerpt(content, min_chars=150, max_chars=220, max_paragraphs=3, max_total_paragraphs=3)
    expected = "\n\n".join(paras[-3:])
    assert excerpt == expected
    assert len(excerpt) <= 220


def test_start_run_chapter_injects_previous_chapter_tail_excerpt(tmp_path) -> None:
    service = build_service(str(tmp_path / "tail_excerpt.sqlite3"))
    story = service.create_story(
        StoryInput(title="測試故事", premise="主角在首章結束時留下線索。", bible={}, target_total_words=30000)
    )

    # Seed chapter 1 as completed with deterministic content.
    paras = [
        "A" * 52,
        "B" * 52,
        "C" * 52,
        "D" * 52,
    ]
    content = "第1章\n\n" + "\n\n".join(paras)
    service.story_repository.upsert_chapter_content(story["story_id"], 1, "第1章", content, status="completed")

    wf2 = service.start_run_chapter(story["story_id"], 2)
    state = wf2["state"]
    assert state["previous_chapter_tail_excerpt"] == _extract_tail_excerpt(content)
    assert len(state["previous_chapter_tail_excerpt"]) <= 220

