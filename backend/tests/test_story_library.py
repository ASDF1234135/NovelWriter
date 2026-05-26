"""Story list and read-only macro snapshot (Library feature)."""

import pytest

from app.domain.schema import ConflictType, ResolutionMethod, StoryInput, VectorDocument
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.service import MacroCompileAlreadyRunningError, WorkflowService


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


def test_list_stories_order_newest_first(tmp_path) -> None:
    db_path = str(tmp_path / "lib.sqlite3")
    service = build_service(db_path)
    repo = service.story_repository
    assert repo.list_stories() == []

    s1 = service.create_story(
        StoryInput(title="First", premise="one", bible={}, target_total_words=1000),
    )
    s2 = service.create_story(
        StoryInput(title="Second", premise="two", bible={}, target_total_words=2000),
    )
    rows = repo.list_stories()
    assert len(rows) == 2
    assert rows[0]["story_id"] == s2["story_id"]
    assert rows[0]["title"] == "Second"
    assert rows[1]["story_id"] == s1["story_id"]
    assert rows[1]["premise"] == "one"
    for r in rows:
        assert "bible_json" not in r
        assert set(r.keys()) >= {"story_id", "title", "premise", "target_total_words", "created_at"}


def test_macro_snapshot_not_compiled(tmp_path) -> None:
    service = build_service(str(tmp_path / "snap1.sqlite3"))
    story = service.create_story(
        StoryInput(title="X", premise="y", bible={}, target_total_words=5000),
    )
    snap = service.get_macro_snapshot(story["story_id"])
    assert snap["story_id"] == story["story_id"]
    assert snap["compiled"] is False
    assert snap["volumes"] == []
    assert snap["anchor_nodes"] == []
    assert snap["cast"] == []
    assert snap["protagonist_character_id"] == ""
    assert snap["bible"] == {}
    assert snap["macro_author_notes"] == ""
    assert snap.get("bible") == {}
    assert snap.get("macro_author_notes") == ""
    assert snap.get("macro_compile_status") == "IDLE"


def test_begin_macro_compile_twice_raises(tmp_path) -> None:
    service = build_service(str(tmp_path / "macro_lock.sqlite3"))
    sid = service.create_story(
        StoryInput(title="L", premise="p", bible={}, target_total_words=1000),
    )["story_id"]
    service.begin_macro_compile_async(sid)
    assert service.story_repository.get_story(sid)["macro_compile_status"] == "RUNNING"
    with pytest.raises(MacroCompileAlreadyRunningError):
        service.begin_macro_compile_async(sid)


def test_macro_snapshot_matches_after_compile(tmp_path) -> None:
    service = build_service(str(tmp_path / "snap2.sqlite3"))
    story = service.create_story(
        StoryInput(title="Compile Me", premise="p", bible={}, target_total_words=30000),
    )
    sid = story["story_id"]
    macro = service.macro_compile(sid)
    snap = service.get_macro_snapshot(sid)
    assert snap["compiled"] is True
    assert len(snap["volumes"]) == len(macro["volumes"])
    assert len(snap["anchor_nodes"]) == len(macro["anchor_nodes"])
    assert snap["protagonist_character_id"] == macro["protagonist_character_id"]
    assert snap["cast"] == macro["cast"]
    expected_bible = dict(macro["bible"])
    expected_bible.pop("storylines", None)
    expected_bible.pop("anchor_nodes", None)
    assert snap["bible"] == expected_bible
    assert snap["macro_author_notes"] == macro["macro_author_notes"]
    for a in snap["anchor_nodes"]:
        assert "depends_on" in a
        assert "storyline_ids" in a


def test_get_macro_snapshot_missing_story(tmp_path) -> None:
    service = build_service(str(tmp_path / "snap3.sqlite3"))
    with pytest.raises(KeyError, match="Story not found"):
        service.get_macro_snapshot("story_nonexistent")


def test_api_get_story_detail_and_configuration_locked(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.dependencies import get_story_repository, get_workflow_repository
    from app.domain.schema import StoryInput
    from app.main import app

    service = build_service(str(tmp_path / "detail_api.sqlite3"))
    created = service.create_story(
        StoryInput(
            title="Detail",
            premise="p",
            bible={"k": "v"},
            target_total_words=5000,
            plan_retry_limit=2,
            draft_loop_retry_limit=1,
        ),
    )
    sid = created["story_id"]

    app.dependency_overrides[get_story_repository] = lambda: service.story_repository
    app.dependency_overrides[get_workflow_repository] = lambda: service.workflow_repository
    try:
        client = TestClient(app)
        r = client.get(f"/api/stories/{sid}")
        assert r.status_code == 200
        data = r.json()
        assert data["story_id"] == sid
        assert data["title"] == "Detail"
        assert data["premise"] == "p"
        assert data["bible"] == {"k": "v"}
        assert data["storylines"] == []
        assert data["anchor_nodes"] == []
        assert data["target_total_words"] == 5000
        assert data["plan_retry_limit"] == 2
        assert data["draft_loop_retry_limit"] == 1
        assert data["output_language"] == "zh-Hant"
        assert data["macro_author_notes"] == ""
        assert data["macro_compile_status"] == "IDLE"
        assert data["macro_compile_updated_at"] == ""
        assert data["macro_compile_error"] == ""
        assert data["configuration_locked"] is False

        service.workflow_repository.create_run(sid, 1, {"story_id": sid, "chapter_id": 1})
        r2 = client.get(f"/api/stories/{sid}")
        assert r2.status_code == 200
        assert r2.json()["configuration_locked"] is False

        r404 = client.get("/api/stories/story_missing_xyz")
        assert r404.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_api_story_detail_normalizes_output_language_alias(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.dependencies import get_story_repository, get_workflow_repository
    from app.main import app

    service = build_service(str(tmp_path / "detail_lang_alias_api.sqlite3"))
    created = service.create_story(
        StoryInput(title="Lang Alias", premise="p", bible={}, target_total_words=3000),
    )
    sid = created["story_id"]
    with service.story_repository.db.connection() as conn:
        conn.execute("UPDATE stories SET output_language = ? WHERE story_id = ?", ("zh-CN", sid))

    app.dependency_overrides[get_story_repository] = lambda: service.story_repository
    app.dependency_overrides[get_workflow_repository] = lambda: service.workflow_repository
    try:
        client = TestClient(app)
        r = client.get(f"/api/stories/{sid}")
        assert r.status_code == 200
        assert r.json()["output_language"] == "zh-Hans"
    finally:
        app.dependency_overrides.clear()


def test_api_macro_snapshot_returns_404() -> None:
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from app.dependencies import get_workflow_service
    from app.main import app

    mock_svc = MagicMock()
    mock_svc.get_macro_snapshot.side_effect = KeyError("Story not found: story_x")
    app.dependency_overrides[get_workflow_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        r = client.get("/api/stories/story_x/macro-snapshot")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_delete_story_removes_sqlite_workflow_graph_vector(tmp_path) -> None:
    service = build_service(str(tmp_path / "delete_story.sqlite3"))
    story = service.create_story(
        StoryInput(title="ToDelete", premise="x", bible={}, target_total_words=1000),
    )
    sid = story["story_id"]
    service.story_repository.upsert_chapter_content(sid, 1, "第一章", "正文", "completed")
    service.story_repository.upsert_chapter_summary(
        sid,
        1,
        plot_summary="summary",
        conflict_type=ConflictType.OTHER,
        resolution_method=ResolutionMethod.OTHER,
    )
    run = service.workflow_repository.create_run(sid, 1, {"story_id": sid, "chapter_id": 1})
    service.graph_store.seed_story(sid)
    assert sid in service.graph_store.story_nodes
    service.vector_store.add_documents(sid, [VectorDocument(text_chunk="chunk", metadata={"chapter_id": 1})])

    service.delete_story(sid)

    assert service.story_repository.get_story(sid) is None
    assert service.story_repository.list_chapters(sid) == []
    assert service.story_repository.get_recent_chapter_summaries(sid, before_chapter_id=99, limit=3) == []
    with pytest.raises(KeyError):
        service.workflow_repository.get_run(run.run_id)
    assert sid not in service.graph_store.story_nodes
    assert sid not in service.vector_store.story_documents


def test_delete_story_missing_raises(tmp_path) -> None:
    service = build_service(str(tmp_path / "delete_missing.sqlite3"))
    with pytest.raises(KeyError, match="Story not found"):
        service.delete_story("story_does_not_exist")


def test_api_patch_story_before_and_after_workflow_run(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.dependencies import get_workflow_service
    from app.domain.schema import StoryInput
    from app.main import app

    service = build_service(str(tmp_path / "patch_story.sqlite3"))
    sid = service.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=5000))["story_id"]

    app.dependency_overrides[get_workflow_service] = lambda: service
    try:
        client = TestClient(app)
        r = client.patch(
            f"/api/stories/{sid}",
            json={"macro_author_notes": "hint", "premise": "p2", "output_language": "zh-Hans"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["premise"] == "p2"
        assert body["macro_author_notes"] == "hint"
        assert body["output_language"] == "zh-Hans"
        assert service.story_repository.get_story(sid)["premise"] == "p2"

        service.workflow_repository.create_run(sid, 1, {"story_id": sid, "chapter_id": 1})
        r_after_run = client.patch(f"/api/stories/{sid}", json={"premise": "after_run"})
        assert r_after_run.status_code == 200
        assert r_after_run.json()["premise"] == "after_run"
    finally:
        app.dependency_overrides.clear()


def test_workflow_repository_latest_active_run(tmp_path) -> None:
    service = build_service(str(tmp_path / "latest_active.sqlite3"))
    sid = service.create_story(StoryInput(title="Act", premise="p", bible={}, target_total_words=2000))["story_id"]
    wr = service.workflow_repository
    assert wr.get_latest_active_run_for_story(sid) is None

    base_state = {"story_id": sid, "chapter_id": 1, "workflow_status": "RUNNING", "requires_hitl": False}
    run = wr.create_run(sid, 1, base_state)
    row = wr.get_latest_active_run_for_story(sid)
    assert row is not None
    assert row["run_id"] == run.run_id
    assert row["chapter_id"] == 1
    assert row["status"] == "RUNNING"

    wr.update_run(
        run.run_id,
        {**base_state, "workflow_status": "WAITING_HITL", "requires_hitl": True, "hitl_reason": "x"},
    )
    row2 = wr.get_latest_active_run_for_story(sid)
    assert row2 is not None
    assert row2["run_id"] == run.run_id
    assert row2["status"] == "WAITING_HITL"

    wr.update_run(run.run_id, {**base_state, "workflow_status": "COMPLETED", "requires_hitl": False})
    assert wr.get_latest_active_run_for_story(sid) is None


def test_api_workflows_latest_active(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.dependencies import get_workflow_service
    from app.main import app

    service = build_service(str(tmp_path / "latest_active_api.sqlite3"))
    sid = service.create_story(StoryInput(title="Api", premise="p", bible={}, target_total_words=2000))["story_id"]

    app.dependency_overrides[get_workflow_service] = lambda: service
    try:
        client = TestClient(app)
        r0 = client.get(f"/api/stories/{sid}/workflows/latest-active")
        assert r0.status_code == 200
        assert r0.json() is None

        st = {"story_id": sid, "chapter_id": 2, "workflow_status": "RUNNING", "requires_hitl": False}
        created = service.workflow_repository.create_run(sid, 2, st)
        r1 = client.get(f"/api/stories/{sid}/workflows/latest-active")
        assert r1.status_code == 200
        body = r1.json()
        assert body["run_id"] == created.run_id
        assert body["story_id"] == sid
        assert body["chapter_id"] == 2
        assert body["status"] == "RUNNING"

        r404 = client.get("/api/stories/missing_story/workflows/latest-active")
        assert r404.status_code == 404
    finally:
        app.dependency_overrides.clear()
