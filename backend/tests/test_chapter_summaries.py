import pytest

from app.domain.schema import (
    ChapterType,
    ConflictType,
    PlotSummarySource,
    ResolutionMethod,
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
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.chapter_summarizer import run_chapter_summarizer
from app.services.workflow.service import ChapterSummaryRegenerateFailed, WorkflowService


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


def test_story_repository_upsert_and_get_recent_chapter_summaries(tmp_path) -> None:
    service = build_service(str(tmp_path / "chapter_summaries.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]

    service.story_repository.upsert_chapter_summary(
        sid, 1, plot_summary="P1", conflict_type=ConflictType.MYSTERY, resolution_method=ResolutionMethod.DISCOVERY
    )
    service.story_repository.upsert_chapter_summary(
        sid, 2, plot_summary="P2", conflict_type=ConflictType.MYSTERY, resolution_method=ResolutionMethod.DISCOVERY
    )
    service.story_repository.upsert_chapter_summary(
        sid, 3, plot_summary="P3", conflict_type=ConflictType.POLITICAL, resolution_method=ResolutionMethod.NEGOTIATION
    )
    service.story_repository.upsert_chapter_summary(
        sid, 4, plot_summary="P4", conflict_type=ConflictType.SOCIAL, resolution_method=ResolutionMethod.ALLIANCE
    )

    recent = service.story_repository.get_recent_chapter_summaries(sid, before_chapter_id=5, limit=3)
    assert [r["chapter_id"] for r in recent] == [2, 3, 4]
    assert recent[0]["plot_summary"] == "P2"
    assert recent[-1]["resolution_method"] == ResolutionMethod.ALLIANCE.value
    assert recent[-1]["ending_vibe"] == "ON_THE_MOVE"


def test_story_repository_list_all_milestones(tmp_path) -> None:
    service = build_service(str(tmp_path / "milestones.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]

    service.story_repository.upsert_milestone_summary(
        sid, chapter_start=1, chapter_end=5, milestone_summary="M(1-5)"
    )
    service.story_repository.upsert_milestone_summary(
        sid, chapter_start=6, chapter_end=10, milestone_summary="M(6-10)"
    )

    all_milestones = service.story_repository.list_all_milestones(sid)
    assert [(m["chapter_start"], m["chapter_end"]) for m in all_milestones] == [(1, 5), (6, 10)]
    assert all_milestones[0]["milestone_summary"] == "M(1-5)"


def test_story_repository_global_top3_aggregations(tmp_path) -> None:
    service = build_service(str(tmp_path / "global_top3.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]

    # conflict_type counts: MYSTERY=3, POLITICAL=2, SOCIAL=1
    service.story_repository.upsert_chapter_summary(sid, 1, plot_summary="P1", conflict_type=ConflictType.MYSTERY, resolution_method=ResolutionMethod.DISCOVERY)
    service.story_repository.upsert_chapter_summary(sid, 2, plot_summary="P2", conflict_type=ConflictType.MYSTERY, resolution_method=ResolutionMethod.DISCOVERY)
    service.story_repository.upsert_chapter_summary(sid, 3, plot_summary="P3", conflict_type=ConflictType.MYSTERY, resolution_method=ResolutionMethod.NEGOTIATION)
    service.story_repository.upsert_chapter_summary(sid, 4, plot_summary="P4", conflict_type=ConflictType.POLITICAL, resolution_method=ResolutionMethod.NEGOTIATION)
    service.story_repository.upsert_chapter_summary(sid, 5, plot_summary="P5", conflict_type=ConflictType.POLITICAL, resolution_method=ResolutionMethod.NEGOTIATION)
    service.story_repository.upsert_chapter_summary(sid, 6, plot_summary="P6", conflict_type=ConflictType.SOCIAL, resolution_method=ResolutionMethod.ALLIANCE)

    top_conf = service.story_repository.global_top_conflict_type(sid, top_k=3)
    assert top_conf[0]["conflict_type"] == ConflictType.MYSTERY.value
    assert top_conf[0]["cnt"] == 3

    # resolution_method counts: DISCOVERY=2, NEGOTIATION=3, ALLIANCE=1
    top_res = service.story_repository.global_top_resolution_method(sid, top_k=3)
    assert top_res[0]["resolution_method"] == ResolutionMethod.NEGOTIATION.value
    assert top_res[0]["cnt"] == 3


def test_chapter_summarizer_node_writes_chapter_and_milestone_mock(tmp_path) -> None:
    service = build_service(str(tmp_path / "chapter_summarizer.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]

    context = WorkflowContext(
        story_repository=service.story_repository,
        workflow_repository=service.workflow_repository,
        bible_service=service.bible_service,
        anchor_service=service.anchor_service,
        graph_store=service.graph_store,
        vector_store=service.vector_store,
        llm_client=service.llm_client,
        run_id="test",
    )

    state = {
        "story_id": sid,
        "chapter_id": 5,
        "chapter_type": ChapterType.PLOT_DRIVEN,
        "b_story_directive": "副線推進",
        "best_draft_content": "本章正文（mock）",
        "ground_truth_events": [],
        "pending_chapter_extraction": {
            "chapter_memory": {
                "summary": "摘要（mock）",
                "unresolved_threads": [],
                "notable_entities": [],
                "latest_location": "",
            },
            "entities": [],
        },
    }

    run_chapter_summarizer(state, context)

    recent = service.story_repository.get_recent_chapter_summaries(sid, before_chapter_id=6, limit=3)
    assert len(recent) == 1
    assert recent[0]["chapter_id"] == 5
    assert recent[0]["conflict_type"] == ConflictType.OTHER.value
    assert recent[0]["plot_summary_source"] == PlotSummarySource.CHAPTER_SUMMARIZER_LLM.value

    all_milestones = service.story_repository.list_all_milestones(sid)
    assert len(all_milestones) == 1
    assert all_milestones[0]["chapter_start"] == 1
    assert all_milestones[0]["chapter_end"] == 5


def test_chapter_summarizer_node_fails_open_without_writing(tmp_path) -> None:
    class FailingLLM:
        def invoke_json(self, *args, **kwargs):  # noqa: ANN001, D401
            raise RuntimeError("boom")

    service = build_service(str(tmp_path / "chapter_summarizer_fail.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]

    context = WorkflowContext(
        story_repository=service.story_repository,
        workflow_repository=service.workflow_repository,
        bible_service=service.bible_service,
        anchor_service=service.anchor_service,
        graph_store=service.graph_store,
        vector_store=service.vector_store,
        llm_client=FailingLLM(),
        run_id="test",
    )

    state = {
        "story_id": sid,
        "chapter_id": 5,
        "chapter_type": ChapterType.PLOT_DRIVEN,
        "b_story_directive": "",
        "best_draft_content": "本章正文（fail）",
        "ground_truth_events": [],
        "pending_chapter_extraction": {
            "chapter_memory": {
                "summary": "摘要（fail）",
                "unresolved_threads": [],
                "notable_entities": [],
                "latest_location": "",
            },
            "entities": [],
        },
    }

    # Should not raise; upsert extraction-memory fallback summary.
    run_chapter_summarizer(state, context)

    recent = service.story_repository.get_recent_chapter_summaries(sid, before_chapter_id=6, limit=3)
    assert len(recent) == 1
    assert recent[0]["chapter_id"] == 5
    assert recent[0]["conflict_type"] == ConflictType.OTHER.value
    assert recent[0]["plot_summary"] == "摘要（fail）"
    assert recent[0]["plot_summary_source"] == PlotSummarySource.FALLBACK_EXTRACTION.value
    assert service.story_repository.list_all_milestones(sid) == []


def test_chapter_summarizer_fallback_draft_when_no_extraction_summary(tmp_path) -> None:
    class FailingLLM:
        def invoke_json(self, *args, **kwargs):  # noqa: ANN001, D401
            raise RuntimeError("boom")

    service = build_service(str(tmp_path / "chapter_summarizer_draft_fb.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]

    context = WorkflowContext(
        story_repository=service.story_repository,
        workflow_repository=service.workflow_repository,
        bible_service=service.bible_service,
        anchor_service=service.anchor_service,
        graph_store=service.graph_store,
        vector_store=service.vector_store,
        llm_client=FailingLLM(),
        run_id="test",
    )

    long_draft = "本章正文開頭" + ("x" * 800)
    state = {
        "story_id": sid,
        "chapter_id": 2,
        "chapter_type": ChapterType.PLOT_DRIVEN,
        "b_story_directive": "",
        "narrative_directive": "",
        "best_draft_content": long_draft,
        "ground_truth_events": [],
        "pending_chapter_extraction": {
            "chapter_memory": {
                "summary": "",
                "unresolved_threads": [],
                "notable_entities": [],
                "latest_location": "",
            },
            "entities": [],
        },
    }

    run_chapter_summarizer(state, context)

    recent = service.story_repository.get_recent_chapter_summaries(sid, before_chapter_id=3, limit=3)
    assert len(recent) == 1
    assert recent[0]["plot_summary_source"] == PlotSummarySource.FALLBACK_DRAFT.value
    assert recent[0]["plot_summary"].startswith("[備援摘要]")


def test_regenerate_chapter_plot_summary_mock(tmp_path) -> None:
    service = build_service(str(tmp_path / "regen_summary.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]
    body = "章節內文用於重新產生摘要。" * 20
    service.story_repository.upsert_chapter_content(sid, 3, title="C3", content=body, status="completed")

    out = service.regenerate_chapter_plot_summary(sid, 3)
    assert out["regenerated"] is True
    assert out["plot_summary_source"] == PlotSummarySource.CHAPTER_SUMMARIZER_LLM.value

    rows = service.story_repository.get_chapter_summaries_in_range(sid, 3, 3)
    assert len(rows) == 1
    assert rows[0]["plot_summary_source"] == PlotSummarySource.CHAPTER_SUMMARIZER_LLM.value


def test_regenerate_chapter_plot_summary_empty_body(tmp_path) -> None:
    service = build_service(str(tmp_path / "regen_empty.sqlite3"))
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]
    service.story_repository.upsert_chapter_content(sid, 2, title="C2", content="   ", status="draft")
    with pytest.raises(ValueError, match="Chapter has no content"):
        service.regenerate_chapter_plot_summary(sid, 2)


def test_regenerate_chapter_plot_summary_failing_llm(tmp_path) -> None:
    class FailingLLM:
        def invoke_json(self, *args, **kwargs):  # noqa: ANN001, D401
            raise RuntimeError("boom")

    db = SQLiteDatabase(str(tmp_path / "regen_fail.sqlite3"))
    service = WorkflowService(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=FailingLLM(),
    )
    story = service.create_story(
        StoryInput(
            title="測試故事",
            premise="副本測試用。",
            bible={},
            target_total_words=30000,
        )
    )
    sid = story["story_id"]
    service.story_repository.upsert_chapter_content(sid, 1, title="C1", content="正文" * 50, status="completed")
    with pytest.raises(ChapterSummaryRegenerateFailed):
        service.regenerate_chapter_plot_summary(sid, 1)

