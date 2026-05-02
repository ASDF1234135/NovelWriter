"""Writing preamble aggregate (read-only, no LangGraph)."""

import pytest

from app.domain.schema import ConflictType, EndingVibe, PlotSummarySource, ResolutionMethod, StoryInput
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.writing_preamble import build_writing_preamble
from app.services.workflow.service import WorkflowService


def _service(db_path: str) -> WorkflowService:
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


def test_build_writing_preamble_keyerror(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "x.sqlite3"))
    repo = StoryRepository(db)
    with pytest.raises(KeyError):
        build_writing_preamble(repo, "missing", 1)


def test_build_writing_preamble_bad_chapter(tmp_path) -> None:
    svc = _service(str(tmp_path / "bad_ch.sqlite3"))
    sid = svc.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=30_000))["story_id"]
    with pytest.raises(ValueError):
        build_writing_preamble(svc.story_repository, sid, 0)


def test_milestones_filtered_and_counts(tmp_path) -> None:
    svc = _service(str(tmp_path / "ms.sqlite3"))
    sid = svc.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=30_000))["story_id"]
    repo = svc.story_repository
    repo.upsert_milestone_summary(sid, chapter_start=1, chapter_end=2, milestone_summary="M12")
    repo.upsert_milestone_summary(sid, chapter_start=3, chapter_end=10, milestone_summary="M310")

    for i in 1, 2, 3, 4:
        repo.upsert_chapter_summary(
            sid,
            i,
            plot_summary=f"P{i}",
            conflict_type=ConflictType.MYSTERY,
            resolution_method=ResolutionMethod.DISCOVERY,
        )

    out = build_writing_preamble(repo, sid, chapter_id=4)
    ms = out["plot_progress"]["milestones"]
    assert len(ms) == 1
    assert ms[0]["milestone_summary"] == "M12"
    assert out["plot_progress"]["earlier_chapters_with_summary_count"] == 3
    recent = out["plot_progress"]["recent_summaries"]
    assert [r["chapter_id"] for r in recent] == [1, 2, 3]
    assert all(r["plot_summary_source"] == PlotSummarySource.CHAPTER_SUMMARIZER_LLM.value for r in recent)


def test_previous_chapter_summary_and_status(tmp_path) -> None:
    svc = _service(str(tmp_path / "prev.sqlite3"))
    sid = svc.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=30_000))["story_id"]
    repo = svc.story_repository
    repo.upsert_chapter_summary(
        sid,
        1,
        plot_summary="Prev plot",
        conflict_type=ConflictType.MYSTERY,
        resolution_method=ResolutionMethod.DISCOVERY,
    )
    repo.upsert_chapter_content(sid, 1, title="C1", content="body", status="completed")

    out = build_writing_preamble(repo, sid, chapter_id=2)
    prev = out["plot_progress"]["previous_chapter"]
    assert prev["chapter_id"] == 1
    assert prev["plot_summary"] == "Prev plot"
    assert prev["plot_summary_source"] == PlotSummarySource.CHAPTER_SUMMARIZER_LLM.value
    assert prev["status"] == "completed"


def test_count_skips_blank_plot_summary(tmp_path) -> None:
    svc = _service(str(tmp_path / "blank_count.sqlite3"))
    sid = svc.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=30_000))["story_id"]
    repo = svc.story_repository
    repo.upsert_chapter_summary(
        sid,
        1,
        plot_summary="   ",
        conflict_type=ConflictType.MYSTERY,
        resolution_method=ResolutionMethod.DISCOVERY,
    )
    repo.upsert_chapter_summary(
        sid,
        2,
        plot_summary="Real",
        conflict_type=ConflictType.MYSTERY,
        resolution_method=ResolutionMethod.DISCOVERY,
    )
    assert repo.count_chapter_summaries_before(sid, 4) == 1


def test_resolution_pacing_hints_human_readable(tmp_path) -> None:
    svc = _service(str(tmp_path / "pace.sqlite3"))
    sid = svc.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=30_000))["story_id"]
    repo = svc.story_repository
    for i in (2, 3, 4):
        repo.upsert_chapter_summary(
            sid,
            i,
            plot_summary=f"P{i}",
            conflict_type=ConflictType.MYSTERY,
            resolution_method=ResolutionMethod.DISCOVERY,
        )

    out = build_writing_preamble(repo, sid, chapter_id=5)
    hints = out["writing_hints"]["pacing_hints"]
    assert len(hints) >= 1
    joined = "\n".join(hints)
    assert "嚴禁" not in joined
    assert "必須" not in joined
    assert "破局" in joined or "收束" in joined


def test_ending_vibe_pacing_hint(tmp_path) -> None:
    svc = _service(str(tmp_path / "vibe.sqlite3"))
    sid = svc.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=30_000))["story_id"]
    repo = svc.story_repository
    repo.upsert_chapter_summary(
        sid,
        1,
        plot_summary="P1",
        conflict_type=ConflictType.MYSTERY,
        resolution_method=ResolutionMethod.NEGOTIATION,
        ending_vibe=EndingVibe.SAFE_ROOM_EXPOSITION,
    )

    out = build_writing_preamble(repo, sid, chapter_id=2)
    hints = out["writing_hints"]["pacing_hints"]
    assert any("安全空間" in h or "盤點" in h for h in hints)
    assert "嚴禁" not in "\n".join(hints)


def test_anchor_distance_and_writing_notes(tmp_path) -> None:
    svc = _service(str(tmp_path / "anchor.sqlite3"))
    sid = svc.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=30_000))["story_id"]
    svc.macro_compile(sid)
    repo = svc.story_repository
    story_nodes = [dict(n) for n in ((repo.get_story(sid) or {}).get("anchor_nodes_json") or []) if isinstance(n, dict)]
    assert story_nodes
    first = story_nodes[0]
    target_ct = int(first.get("estimated_chapter") or 1)

    story_row = repo.get_story(sid)
    assert story_row
    bible = dict(story_row.get("bible_json") or {})
    # macro compile may set general_world_lore; use legacy writing_note only if lore is cleared
    bible.pop("general_world_lore", None)
    bible["writing_note"] = ["自訂筆記 A"]
    repo.update_story_bible_json(sid, bible)

    at_anchor = build_writing_preamble(repo, sid, chapter_id=target_ct)
    assert "chapters_until_next_anchor" not in at_anchor["writing_hints"]
    assert at_anchor["writing_hints"]["next_focus_anchor"] is not None
    assert at_anchor["writing_hints"]["next_focus_anchor"]["anchor_id"] == str(first.get("id") or "")

    one_before = build_writing_preamble(repo, sid, chapter_id=max(1, target_ct - 1))
    if target_ct > 1:
        assert one_before["writing_hints"]["chapters_until_next_anchor"] == 1

    notes = at_anchor["writing_hints"]["writing_notes"]
    assert any("自訂筆記 A" in line for line in notes)
