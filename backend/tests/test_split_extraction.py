"""Tests for multi-step chapter extraction (entity / memory / relation)."""

from __future__ import annotations

import pytest

from app.domain.schema import (
    ChapterExtractionOutput,
    EventLink,
    EventLinkType,
    ChapterMemory,
    ChapterMemoryExtractionOutput,
    EntityExtractionOutput,
    EventOutline,
    ExtractedEntity,
    ExtractedEntityCandidate,
    ExtractedRelation,
    GraphQueryRequest,
    GraphSnapshot,
    NodeType,
    EdgeType,
    RelationExtractionOutput,
)
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import LLMResult
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.core.config import get_settings
from app.services.workflow.extraction import (
    _validation_gate,
    build_extraction_context,
    canonicalize_entity_candidates,
    extract_chapter_artifacts,
    stable_entity_id,
)
from app.services.workflow.profiles import AgentPromptProfile, get_profile


class FakeSplitLLMClient:
    def invoke(self, prompt: str) -> LLMResult:
        raise NotImplementedError

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResult:
        raise NotImplementedError

    def invoke_json(self, prompt, response_model, profile: AgentPromptProfile):
        if profile.agent_name == "entity_extractor":
            out = EntityExtractionOutput(
                entities=[
                    ExtractedEntityCandidate(
                        node_type=NodeType.CHARACTER,
                        canonical_name="Kaelen",
                        aliases=[],
                        summary="主角",
                        suggested_node_id="",
                    ),
                    ExtractedEntityCandidate(
                        node_type=NodeType.LOCATION,
                        canonical_name="北門",
                        aliases=[],
                        summary="地點",
                    ),
                ]
            )
        elif profile.agent_name == "chapter_memory_extractor":
            out = ChapterMemoryExtractionOutput(
                summary="Kaelen 抵達北門。",
                unresolved_threads=["守衛為何盤查"],
                notable_entities=["Kaelen", "北門"],
                latest_location="北門",
            )
        elif profile.agent_name == "relation_extractor":
            out = RelationExtractionOutput(
                relations=[
                    ExtractedRelation(
                        source_name="Kaelen",
                        relation_type=EdgeType.LOCATED_IN,
                        target_name="北門",
                        context_details="停留",
                        is_truth=True,
                        is_public=False,
                    )
                ]
            )
        else:
            raise AssertionError(f"unexpected agent {profile.agent_name}")
        return response_model.model_validate(out.model_dump(mode="json")), LLMResult(
            content="{}", token_usage=10, latency_ms=5
        )


@pytest.fixture
def split_workflow_context(tmp_path):
    db = SQLiteDatabase(str(tmp_path / "split_extract.sqlite3"))
    return WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=FakeSplitLLMClient(),
        run_id="run-split",
    )


def test_canonicalize_ignores_hallucinated_suggested_node_id() -> None:
    snapshot = GraphSnapshot(nodes=[], edges=[])
    candidates = [
        ExtractedEntityCandidate(
            suggested_node_id="totally_fake_id",
            node_type=NodeType.CHARACTER,
            canonical_name="Zara",
            aliases=[],
        )
    ]
    entities, name_index = canonicalize_entity_candidates(candidates, snapshot)
    assert len(entities) == 1
    assert entities[0].node_id == stable_entity_id(NodeType.CHARACTER, "Zara")
    assert name_index["zara"] == entities[0].node_id
    assert entities[0].node_id == "char_zara"


def test_build_extraction_context_uses_full_text_for_short_chapter() -> None:
    state = {
        "story_id": "s1",
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_x",
        "must_include_beats": [],
        "reader_visible_facts": [],
    }
    short = "短章" * 20
    ctx = build_extraction_context(state, GraphSnapshot(nodes=[], edges=[]), short, [])
    assert ctx.chapter_text_for_memory == short
    assert len(ctx.chapter_text_for_entities) == len(short)
    assert len(ctx.entity_glossary) <= get_settings().extraction_entity_glossary_cap


def test_extract_chapter_artifacts_runs_three_steps_with_fake_llm(split_workflow_context: WorkflowContext) -> None:
    split_workflow_context.graph_store.seed_story("story_split")
    state = {
        "story_id": "story_split",
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "測試",
        "reader_visible_facts": [],
        "private_facts_or_secret_actions": [],
        "reader_unresolved_questions": [],
        "chapter_end_location_hint": "北門",
        "last_known_location": "",
        "ground_truth_events": [],
    }
    events = [
        EventOutline(event_id="evt_01", description="Kaelen 在北門被盤查", caused_by_event_id=None),
    ]
    snap = split_workflow_context.graph_store.query_context(
        GraphQueryRequest(
            story_id="story_split",
            active_epoch_id="epoch_present",
            pov_character_id="char_public_observer",
            narrative_directive="測試",
        )
    )
    content = "第1章\n\nKaelen 站在北門前，守衛上前盤查。"
    output, diag = extract_chapter_artifacts(state, split_workflow_context, snap, content, events)

    assert isinstance(output, ChapterExtractionOutput)
    assert diag is not None
    assert "entity_extractor" in diag["steps"]
    assert "chapter_memory_extractor" in diag["steps"]
    assert "relation_extractor" in diag["steps"]
    names = {e.canonical_name for e in output.entities}
    assert "Kaelen" in names or any("Kaelen" in e.aliases for e in output.entities)
    assert output.chapter_memory.summary


def test_new_extractor_profiles_exist() -> None:
    for name in ("entity_extractor", "chapter_memory_extractor", "relation_extractor"):
        p = get_profile(name)
        assert p.agent_name == name
        assert p.model


def test_relation_extractor_batches_canonical_entities_with_small_batch_size(monkeypatch, tmp_path) -> None:
    """With N=2, five entities should trigger three relation_extractor JSON calls."""
    monkeypatch.setenv("NOVEL_BUILDER_EXTRACTION_RELATION_ENTITY_BATCH_SIZE", "2")
    get_settings.cache_clear()
    class MultiEntityCountingFake(FakeSplitLLMClient):
        def __init__(self) -> None:
            self.relation_calls = 0

        def invoke_json(self, prompt, response_model, profile: AgentPromptProfile):
            if profile.agent_name == "relation_extractor":
                self.relation_calls += 1
                out = RelationExtractionOutput(
                    relations=[
                        ExtractedRelation(
                            source_name="Char0",
                            relation_type=EdgeType.PARTICIPATED_IN,
                            target_node_id="evt_01",
                            target_name="",
                            context_details="batch",
                            is_truth=True,
                            is_public=True,
                        )
                    ]
                )
                return response_model.model_validate(out.model_dump(mode="json")), LLMResult(
                    content="{}", token_usage=10, latency_ms=5
                )
            if profile.agent_name == "entity_extractor":
                ents = [
                    ExtractedEntityCandidate(
                        node_type=NodeType.EVENT,
                        canonical_name="多人同行",
                        aliases=[],
                        summary="",
                        suggested_node_id="evt_01",
                    ),
                    *[
                        ExtractedEntityCandidate(
                            node_type=NodeType.CHARACTER,
                            canonical_name=f"Char{i}",
                            aliases=[],
                            summary="",
                            suggested_node_id="",
                        )
                        for i in range(5)
                    ],
                ]
                out = EntityExtractionOutput(entities=ents)
                return response_model.model_validate(out.model_dump(mode="json")), LLMResult(
                    content="{}", token_usage=10, latency_ms=5
                )
            return super().invoke_json(prompt, response_model, profile)

    db = SQLiteDatabase(str(tmp_path / "batch_rel.sqlite3"))
    ctx = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MultiEntityCountingFake(),
        run_id="run-batch-rel",
    )
    ctx.graph_store.seed_story("story_batch_rel")
    state = {
        "story_id": "story_batch_rel",
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "測試",
        "reader_visible_facts": [],
        "private_facts_or_secret_actions": [],
        "reader_unresolved_questions": [],
        "chapter_end_location_hint": "",
        "last_known_location": "",
        "ground_truth_events": [],
    }
    events = [EventOutline(event_id="evt_01", description="多人同行", caused_by_event_id=None)]
    snap = ctx.graph_store.query_context(
        GraphQueryRequest(
            story_id="story_batch_rel",
            active_epoch_id="epoch_present",
            pov_character_id="char_public_observer",
            narrative_directive="測試",
        )
    )
    content = "第1章\n\nChar0 與 Char1、Char2、Char3、Char4 在廣場會合。"
    output, diag = extract_chapter_artifacts(state, ctx, snap, content, events)

    client = ctx.llm_client
    assert isinstance(client, MultiEntityCountingFake)
    # Phase1 batches (3) + Phase2 (1) = 4 relation calls
    assert client.relation_calls == 4
    assert diag is not None
    rel_step = diag["steps"]["relation_extractor"]
    assert rel_step["batch_count"] == 3
    assert rel_step["batched"] is True
    # 3 Phase1 batches + 1 Phase2 call record
    assert len(rel_step["batches"]) == 4
    assert len(output.entities) == 6
    # Same relation from each batch → deduped to one
    assert len(output.relations) == 1

    get_settings.cache_clear()


def test_validation_gate_rejects_unbacked_caused_between_ground_truth_events() -> None:
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
    }
    events = [
        EventOutline(event_id="event_ch1_01", description="A"),
        EventOutline(
            event_id="event_ch1_02",
            description="B",
            links=[
                EventLink(
                    target_event_id="event_ch1_01",
                    link_type=EventLinkType.TEMPORAL,
                )
            ],
        ),
    ]
    output = ChapterExtractionOutput(
        entities=[
            ExtractedEntity(node_id="event_ch1_01", node_type=NodeType.EVENT, canonical_name="a", summary="A"),
            ExtractedEntity(node_id="event_ch1_02", node_type=NodeType.EVENT, canonical_name="b", summary="B"),
        ],
        relations=[
            ExtractedRelation(
                source_node_id="event_ch1_01",
                relation_type=EdgeType.CAUSED,
                target_node_id="event_ch1_02",
                context_details="unsupported causal edge",
                is_truth=True,
                is_public=True,
            )
        ],
        chapter_memory=ChapterMemory(
            summary="s",
            unresolved_threads=[],
            notable_entities=[],
            latest_location="",
        ),
    )
    validated = _validation_gate(output, state, GraphSnapshot(nodes=[], edges=[]), events)
    assert validated.relations == []


def test_validation_gate_allows_caused_when_ai_invention_involved() -> None:
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
    }
    events = [
        EventOutline(event_id="event_ch1_01", description="A"),
        EventOutline(
            event_id="event_ch1_02",
            description="B",
            is_ai_invention=True,
        ),
    ]
    output = ChapterExtractionOutput(
        entities=[
            ExtractedEntity(node_id="event_ch1_01", node_type=NodeType.EVENT, canonical_name="a", summary="A"),
            ExtractedEntity(node_id="event_ch1_02", node_type=NodeType.EVENT, canonical_name="b", summary="B"),
        ],
        relations=[
            ExtractedRelation(
                source_node_id="event_ch1_01",
                relation_type=EdgeType.CAUSED,
                target_node_id="event_ch1_02",
                context_details="ai invention branch",
                is_truth=True,
                is_public=False,
            )
        ],
        chapter_memory=ChapterMemory(
            summary="s",
            unresolved_threads=[],
            notable_entities=[],
            latest_location="",
        ),
    )
    validated = _validation_gate(output, state, GraphSnapshot(nodes=[], edges=[]), events)
    assert len(validated.relations) == 1
