"""B-story resolver node: payload shape and LLM failure handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes import b_story_resolve as bsr


@pytest.fixture
def workflow_context(tmp_path) -> WorkflowContext:
    db = SQLiteDatabase(str(tmp_path / "test.sqlite3"))
    return WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-test",
    )


def test_compact_extraction_includes_relations_for_prompt_contract() -> None:
    state = {
        "pending_chapter_extraction": {
            "entities": [{"node_id": "c1", "canonical_name": "A", "node_type": "CHARACTER"}],
            "relations": [
                {"source_node_id": "c1", "target_node_id": "evt_1", "relation_type": "PARTICIPATED_IN"}
            ],
        },
        "ground_truth_events": [{"event_id": "evt_1", "description": "beat"}],
    }
    raw = bsr._compact_extraction_for_resolve(state)
    data = json.loads(raw)
    assert "relations" in data
    assert data["relations"] and data["relations"][0]["target_node_id"] == "evt_1"


def test_run_b_story_resolve_llm_failure_returns_safe_empty(workflow_context: WorkflowContext) -> None:
    failing = MagicMock()
    failing.invoke_json.side_effect = RuntimeError("upstream unavailable")
    workflow_context.llm_client = failing  # type: ignore[assignment]
    state = {
        "ground_truth_events": [{"event_id": "evt_1", "description": "x"}],
        "pending_chapter_extraction": {"entities": [], "relations": []},
        "active_b_stories": [{"id": "b1", "desc": "thread", "type": "X", "resolution_condition": "done"}],
    }
    out = bsr.run_b_story_resolve(state, workflow_context)
    assert out["b_story_hitl_required"] is False
    assert out["b_story_resolution"]["resolved_b_stories"] == []
    assert "llm call failed" in out["b_story_resolution"]["resolution_analysis"].lower()
