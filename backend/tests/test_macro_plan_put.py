"""Manual macro plan PUT and optional author chapter plan on run start."""

import pytest

from app.domain.schema import (
    MacroPlanAnchorBody,
    MacroPlanPut,
    StoryCastMemberStored,
    StoryInput,
    VolumePlan,
)
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.service import (
    MacroPlanValidationError,
    StoryConfigurationLockedError,
    WorkflowService,
)


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


def _macro_to_put(macro: dict) -> MacroPlanPut:
    return MacroPlanPut(
        bible=dict(macro.get("bible") or {}),
        volumes=[VolumePlan.model_validate(v) for v in macro["volumes"]],
        anchors=[MacroPlanAnchorBody.model_validate(a) for a in macro["anchors"]],
        cast=[StoryCastMemberStored.model_validate(c) for c in macro["cast"]],
        protagonist_character_id=(macro.get("protagonist_character_id") or "").strip() or None,
    )


def test_put_macro_plan_edits_volume_title(tmp_path) -> None:
    svc = _service(str(tmp_path / "put.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    macro = svc.macro_compile(sid)
    body = _macro_to_put(macro)
    new_vol = body.volumes[0].model_copy(update={"title": "手改卷名"})
    new_body = body.model_copy(update={"volumes": [new_vol, *body.volumes[1:]]})
    out = svc.put_macro_plan(sid, new_body)
    assert out["volumes"][0]["title"] == "手改卷名"


def test_put_macro_plan_locked_after_workflow_run(tmp_path) -> None:
    svc = _service(str(tmp_path / "lock.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    macro = svc.macro_compile(sid)
    body = _macro_to_put(macro)
    svc.workflow_repository.create_run(sid, 1, {"story_id": sid, "chapter_id": 1})
    with pytest.raises(StoryConfigurationLockedError):
        svc.put_macro_plan(sid, body)


def test_put_macro_plan_validates_anchor_volume(tmp_path) -> None:
    svc = _service(str(tmp_path / "bad.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    macro = svc.macro_compile(sid)
    body = _macro_to_put(macro)
    bad_anchor = body.anchors[0].model_copy(update={"volume_id": "no_such_vol"})
    bad_body = body.model_copy(update={"anchors": [bad_anchor, *body.anchors[1:]]})
    with pytest.raises(MacroPlanValidationError):
        svc.put_macro_plan(sid, bad_body)


def test_start_run_chapter_author_plan_in_state(tmp_path) -> None:
    svc = _service(str(tmp_path / "plan.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    svc.macro_compile(sid)
    wf = svc.start_run_chapter(sid, 1, author_chapter_plan="  本章著重伏筆  ")
    assert wf["state"]["author_chapter_plan"] == "本章著重伏筆"
    assert wf["state"]["chapter_outline"] == "本章著重伏筆"


def test_start_run_chapter_author_plan_truncated(tmp_path) -> None:
    svc = _service(str(tmp_path / "long.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    svc.macro_compile(sid)
    long_text = "x" * 5000
    wf = svc.start_run_chapter(sid, 1, author_chapter_plan=long_text)
    assert len(wf["state"]["author_chapter_plan"]) == 2000
    assert len(wf["state"]["chapter_outline"]) == 2000
