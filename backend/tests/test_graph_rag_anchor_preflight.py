from __future__ import annotations

from dataclasses import dataclass

from app.domain.schema import GraphRAGEvaluateOutput, StoryInput
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.anchor_graph_eval import CACHE_SOURCE_ANCHOR_RESOLVE
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.graph_rag import run_graph_rag
from app.services.workflow.profiles import AgentPromptProfile


@dataclass
class LLMResultStub:
    content: str
    token_usage: int = 1
    latency_ms: int = 1


class CountingGraphRAGLLM:
    evaluate_calls = 0

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResultStub:
        return LLMResultStub(content="【背景摘要】")

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        if profile.agent_name == "graph_rag_evaluate":
            type(self).evaluate_calls += 1
            payload = {
                "resolved": False,
                "confidence": 0.8,
                "reasoning": "證據不足，尚未完成。",
            }
            return response_model.model_validate(payload), LLMResultStub(content="")
        raise AssertionError(f"unexpected agent {profile.agent_name}")


def _base_context(tmp_path, llm) -> tuple[WorkflowContext, dict, str]:
    db = SQLiteDatabase(str(tmp_path / "preflight.sqlite3"))
    story_repo = StoryRepository(db)
    story = story_repo.create_story(
        "story_preflight",
        StoryInput(title="T", premise="p", bible={}, target_total_words=5000),
    )
    graph_store = InMemoryGraphStore()
    graph_store.seed_story(story["story_id"])
    context = WorkflowContext(
        story_repository=story_repo,
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=graph_store,
        vector_store=InMemoryVectorStore(),
        llm_client=llm,
        run_id="run_preflight",
    )
    state = {
        "story_id": story["story_id"],
        "chapter_id": 6,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "推進主線",
        "chapter_outline": "本章目標",
        "selected_anchor_ids": ["anchor_a", "anchor_b"],
        "next_anchor_ids": ["anchor_b"],
        "resolved_anchors": [],
        "anchor_nodes": [
            {
                "id": "anchor_a",
                "title": "取得密信",
                "description": "主角在城門取得密信。",
                "node_kind": "NORMAL",
                "depends_on": [],
                "status": "UNLOCKED",
            },
            {
                "id": "anchor_b",
                "title": "下一節點",
                "description": "後續事件。",
                "node_kind": "NORMAL",
                "depends_on": ["anchor_a"],
                "status": "LOCKED",
            },
        ],
    }
    return context, state, story["story_id"]


def test_graph_rag_preflight_includes_section_and_excludes_next(tmp_path) -> None:
    CountingGraphRAGLLM.evaluate_calls = 0
    llm = CountingGraphRAGLLM()
    context, state, _ = _base_context(tmp_path, llm)
    out = run_graph_rag(state, context)
    gc = out.get("graph_context") or ""
    assert "本章錨點前置狀態" in gc
    assert "anchor_a" in gc
    assert CountingGraphRAGLLM.evaluate_calls == 1
    evals = out.get("anchor_preflight_evaluations") or []
    assert len(evals) == 1
    assert evals[0]["anchor_id"] == "anchor_a"


def test_graph_rag_reuses_prev_chapter_cache_without_evaluate(tmp_path) -> None:
    CountingGraphRAGLLM.evaluate_calls = 0
    llm = CountingGraphRAGLLM()
    context, state, _ = _base_context(tmp_path, llm)
    state["anchor_unresolved_eval_cache"] = {
        "anchor_a": {
            "chapter_id": 5,
            "resolved": False,
            "reasoning": "第5章判定尚未完成。",
            "source": CACHE_SOURCE_ANCHOR_RESOLVE,
        }
    }
    out = run_graph_rag(state, context)
    assert CountingGraphRAGLLM.evaluate_calls == 0
    gc = out.get("graph_context") or ""
    assert "沿用第 5 章" in gc
    assert "第5章判定尚未完成" in gc
    evals = out.get("anchor_preflight_evaluations") or []
    assert evals[0]["source"] == "cache"
