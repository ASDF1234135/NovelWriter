"""Copyeditor node: mock passthrough, previous-chapter tail context, heading."""

from __future__ import annotations

from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.copyeditor import run_copyeditor
from app.services.workflow.profiles import get_profile


def _ctx(tmp_path, story_id: str) -> WorkflowContext:
    db = SQLiteDatabase(str(tmp_path / "copyeditor.sqlite3"))
    return WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-copyeditor-test",
    )


def test_run_copyeditor_mock_preserves_substring_and_heading(tmp_path) -> None:
    ctx = _ctx(tmp_path, "s1")
    draft = "第3章\n\n他在地上撿到了一把生鏽的鑰匙。\n"
    state = {
        "story_id": "s1",
        "chapter_id": 3,
        "current_draft": draft,
        "best_draft_content": draft,
    }
    out = run_copyeditor(state, ctx)
    assert "生鏽的鑰匙" in (out["current_draft"] or "")
    assert out["current_draft"] == out["best_draft_content"]
    assert out["current_draft"].strip().startswith("第3章")


def test_run_copyeditor_includes_completed_prev_tails_in_prompt(monkeypatch, tmp_path) -> None:
    ctx = _ctx(tmp_path, "s1")
    sid = "story-copyeditor-tails"
    ctx.story_repository.upsert_chapter_content(
        sid, 1, "第 1 章", "AAAA_OPEN" + "中" * 600 + "AAAA_CLOSE", status="completed"
    )
    ctx.story_repository.upsert_chapter_content(
        sid, 2, "第 2 章", "BBBB_OPEN" + "乙" * 600 + "BBBB_CLOSE", status="completed"
    )
    draft = "第3章\n\n正文。\n"
    state = {
        "story_id": sid,
        "chapter_id": 3,
        "current_draft": draft,
        "best_draft_content": draft,
    }

    captured: dict[str, str] = {}

    def fake_invoke_text(prompt, profile):
        captured["prompt"] = prompt
        from app.services.llm import LLMResult

        return LLMResult(content=draft, token_usage=1, latency_ms=1)

    # Non-mock client so run_copyeditor invokes the real invoke_text path
    class _NonMock:
        def invoke_text(self, prompt, profile):
            return fake_invoke_text(prompt, profile)

    ctx2 = WorkflowContext(
        story_repository=ctx.story_repository,
        workflow_repository=ctx.workflow_repository,
        bible_service=ctx.bible_service,
        anchor_service=ctx.anchor_service,
        graph_store=ctx.graph_store,
        vector_store=ctx.vector_store,
        llm_client=_NonMock(),
        run_id=ctx.run_id,
    )
    run_copyeditor(state, ctx2)
    pr = captured.get("prompt", "")
    assert "AAAA_CLOSE" in pr or "AAAA" in pr
    assert "BBBB_CLOSE" in pr or "BBBB" in pr
    assert "第3章" in pr
    assert "Jargon Pruning" in pr
    assert "虛空節點：坍塌區" in pr


def test_get_profile_copyeditor_registered() -> None:
    p = get_profile("copyeditor")
    assert p.agent_name == "copyeditor"
    assert "校閱" in p.system_prompt


def test_copyeditor_redacts_forbidden_identity_in_output(tmp_path) -> None:
    ctx = _ctx(tmp_path, "s1")
    draft = "第3章\n\n主角在雨幕裡終於確認線人就是夜鴉。\n"
    state = {
        "story_id": "s1",
        "chapter_id": 3,
        "current_draft": draft,
        "best_draft_content": draft,
        "forbidden_reveals": ["不要揭露「夜鴉」的真身分"],
        "allowed_identity_reveals_this_chapter": [],
    }
    out = run_copyeditor(state, ctx)
    assert "夜鴉" not in (out["current_draft"] or "")
    assert "[REDACTED_IDENTITY]" in (out["current_draft"] or "")
