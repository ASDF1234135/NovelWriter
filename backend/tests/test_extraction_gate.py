"""extraction_gate R6 feedback clarity and structured missing entities."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.domain.schema import (
    ChapterExtractionOutput,
    ExtractedEntity,
    NodeType,
    ProposedGraphNode,
)
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.extraction_gate import run_extraction_gate


@pytest.fixture
def wf_context(tmp_path) -> WorkflowContext:
    db = SQLiteDatabase(str(tmp_path / "extraction_gate_test.sqlite3"))
    return WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-extraction-gate-test",
    )


def test_extraction_gate_message_includes_planned_labels_and_fallback_notice(wf_context: WorkflowContext) -> None:
    planned = [
        ProposedGraphNode(
            node_id="char_slot",
            node_type=NodeType.CHARACTER,
            role="商人",
            canonical_name="黑市商人",
            mandatory=True,
        ).model_dump(mode="json"),
    ]
    extracted = ChapterExtractionOutput(
        entities=[
            ExtractedEntity(
                node_id="wrong_id",
                node_type=NodeType.CHARACTER,
                canonical_name="路人",
                aliases=[],
            )
        ]
    )
    diag = {"steps": {"entity_extractor": {"fallback": True}}}

    state = {
        "story_id": "s1",
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "",
        "ground_truth_events": [],
        "planned_graph_nodes": planned,
        "best_draft_content": "正文",
        "draft_retry_count": 0,
        "author_extraction_surface_hints": [],
    }

    with patch(
        "app.services.workflow.nodes.extraction_gate.extract_chapter_artifacts",
        return_value=(extracted, diag),
    ):
        out = run_extraction_gate(state, wf_context)

    assert out["post_polish_route"] == "author"
    msg = out["extraction_gate_error"]
    assert "char_slot" in msg
    assert "黑市商人" in msg
    assert "商人" in msg
    assert "【系統提示】" in msg
    assert "後備流程" in msg

    entry = out["extraction_gate_feedback_entry"]
    assert entry["missing_mandatory_entities"]
    row = entry["missing_mandatory_entities"][0]
    assert row["node_id"] == "char_slot"
    assert row["canonical_name"] == "黑市商人"
    assert row["role"] == "商人"


def test_extraction_gate_unknown_node_id_in_missing_list(wf_context: WorkflowContext) -> None:
    extracted = ChapterExtractionOutput(entities=[])
    planned = [
        ProposedGraphNode(
            node_id="orphan_id",
            node_type=NodeType.LOCATION,
            role="地點",
            canonical_name="廢棄倉庫",
            mandatory=True,
        ).model_dump(mode="json"),
    ]
    state = {
        "story_id": "s1",
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "",
        "ground_truth_events": [],
        "planned_graph_nodes": planned,
        "best_draft_content": "x",
        "draft_retry_count": 0,
        "author_extraction_surface_hints": [],
    }

    with patch(
        "app.services.workflow.nodes.extraction_gate.extract_chapter_artifacts",
        return_value=(extracted, None),
    ):
        out = run_extraction_gate(state, wf_context)

    detail = out["extraction_gate_feedback_entry"]["missing_mandatory_entities"]
    assert len(detail) == 1
    assert detail[0]["node_id"] == "orphan_id"
    assert detail[0]["canonical_name"] == "廢棄倉庫"
