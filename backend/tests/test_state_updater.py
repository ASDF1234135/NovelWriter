import pytest

from app.domain.schema import EdgeMutation, EdgeType, EventOutline, ExtractedRelation, GraphQueryRequest, GraphSnapshot, NodeMutation, NodeType
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.state_updater import (
    _build_location_transition_mutations,
    _build_relation_mutation,
    _is_valid_relation_direction,
    run_state_updater,
)


class SparseGraphStore(InMemoryGraphStore):
    def query_context(self, request: GraphQueryRequest) -> GraphSnapshot:
        self.seed_story(request.story_id)
        return GraphSnapshot(nodes=[], edges=[])


@pytest.fixture
def workflow_context(tmp_path):
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


def test_state_updater_uses_whitelisted_ids(workflow_context: WorkflowContext) -> None:
    workflow_context.graph_store.seed_story("story_1")
    state = {
        "story_id": "story_1",
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "測試",
        "ground_truth_events": [
            EventOutline(event_id="event_ch1_01", description="測試事件", caused_by_event_id=None).model_dump(mode="json")
        ],
        "current_draft": "草稿",
        "best_draft_content": "",
    }

    output = run_state_updater(state, workflow_context)

    metadata = output["vector_documents"][0]["metadata"]
    belongs_to_epoch_edge = next(
        mutation
        for mutation in output["mutations"]
        if mutation["action"] == "CREATE_EDGE" and mutation["relation_type"] == "BELONGS_TO_EPOCH"
    )
    assert metadata["epoch_id"] == "epoch_present"
    assert metadata["location_id"] == "loc_unknown"
    assert metadata["characters_involved"] == ["char_public_observer"]
    assert belongs_to_epoch_edge["attributes"]["known_by"] == []
    assert belongs_to_epoch_edge["attributes"]["is_public"] is True


def test_state_updater_allows_required_reference_ids_when_query_context_is_sparse(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "sparse.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=SparseGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-sparse",
    )
    context.graph_store.seed_story("story_sparse")
    state = {
        "story_id": "story_sparse",
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "只查到事件相關節點",
        "ground_truth_events": [
            EventOutline(event_id="event_sparse_01", description="稀疏圖譜事件", caused_by_event_id=None).model_dump(mode="json")
        ],
        "current_draft": "草稿",
        "best_draft_content": "",
    }

    output = run_state_updater(state, context)

    metadata = output["vector_documents"][0]["metadata"]
    assert metadata["epoch_id"] == "epoch_present"
    assert metadata["location_id"] == "loc_unknown"
    assert metadata["characters_involved"] == ["char_public_observer"]


def test_state_updater_extracts_entities_relations_and_memory_chunks(workflow_context: WorkflowContext) -> None:
    workflow_context.graph_store.seed_story("story_entities")
    workflow_context.graph_store.apply_mutations(
        "story_entities",
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="char_kaelen",
                node_type=NodeType.CHARACTER,
                properties={
                    "canonical_name": "Kaelen",
                    "aliases": [],
                    "description": "被流放的騎士。",
                },
            ),
            NodeMutation(
                action="CREATE_NODE",
                node_id="loc_capital",
                node_type=NodeType.LOCATION,
                properties={
                    "canonical_name": "王都",
                    "aliases": [],
                },
            ),
        ],
    )
    state = {
        "story_id": "story_entities",
        "chapter_id": 2,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "Kaelen 回到王都調查命案",
        "ground_truth_events": [
            EventOutline(event_id="event_ch2_01", description="Kaelen 回到王都追查命案", caused_by_event_id=None).model_dump(mode="json"),
            EventOutline(event_id="event_ch2_02", description="Kaelen 取得新線索", caused_by_event_id="event_ch2_01").model_dump(mode="json"),
        ],
        "current_draft": "Kaelen 回到王都，在城門前重整線索，準備追查命案。",
        "best_draft_content": "",
    }

    output = run_state_updater(state, workflow_context)

    caused_edge = next(
        mutation
        for mutation in output["mutations"]
        if mutation["action"] == "CREATE_EDGE" and mutation["relation_type"] == "CAUSED"
    )
    participated_edge = next(
        mutation
        for mutation in output["mutations"]
        if mutation["action"] == "CREATE_EDGE" and mutation["relation_type"] == "PARTICIPATED_IN"
    )
    memory_types = {document["metadata"]["memory_type"] for document in output["vector_documents"]}
    summary_doc = next(
        document
        for document in output["vector_documents"]
        if document["metadata"]["memory_type"] == "chapter_summary"
    )

    assert caused_edge["source_id"] == "event_ch2_01"
    assert caused_edge["target_id"] == "event_ch2_02"
    assert participated_edge["source_id"] == "char_kaelen"
    assert participated_edge["target_id"] == "event_ch2_01"
    assert "chapter_summary" in memory_types
    assert "chapter_excerpt" in memory_types
    assert "unresolved_threads" in memory_types
    assert summary_doc["metadata"]["location_id"] == "loc_capital"
    assert "Kaelen" in summary_doc["metadata"]["entity_names"]


def test_private_truth_edge_includes_pov_in_known_by() -> None:
    edge = _build_relation_mutation(
        relation=ExtractedRelation(
            source_node_id="char_elian",
            target_node_id="evt_hidden",
            relation_type=EdgeType.PARTICIPATED_IN,
            context_details="Elian participated in a hidden action.",
            is_truth=True,
            is_public=False,
        ),
        resolved_name_index={},
        known_ids={"char_elian", "evt_hidden"},
        node_types={"char_elian": NodeType.CHARACTER, "evt_hidden": NodeType.EVENT},
        active_epoch_id="epoch_present",
        primary_event_id="evt_hidden",
        pov_character_id="char_elian",
    )

    assert edge is not None
    assert edge.attributes["known_by"] == ["char_elian"]
    assert edge.attributes["holder"] == []


def test_private_false_edge_includes_pov_in_holder() -> None:
    edge = _build_relation_mutation(
        relation=ExtractedRelation(
            source_node_id="char_elian",
            target_node_id="concept_false_belief",
            relation_type=EdgeType.BELIEVED_AS,
            context_details="Elian privately believes the wrong thing.",
            is_truth=False,
            is_public=False,
        ),
        resolved_name_index={},
        known_ids={"char_elian", "concept_false_belief"},
        node_types={"char_elian": NodeType.CHARACTER, "concept_false_belief": NodeType.CONCEPT},
        active_epoch_id="epoch_present",
        primary_event_id="evt_hidden",
        pov_character_id="char_elian",
    )

    assert edge is not None
    assert edge.attributes["known_by"] == []
    assert edge.attributes["holder"] == ["char_elian"]


@pytest.mark.parametrize(
    ("relation_type", "source_type", "target_type"),
    [
        (EdgeType.HAS_ITEM, NodeType.CHARACTER, NodeType.ITEM),
        (EdgeType.LOCATED_IN, NodeType.ITEM, NodeType.LOCATION),
        (EdgeType.PARTICIPATED_IN, NodeType.PERSONA, NodeType.EVENT),
        (EdgeType.BELONGS_TO_EPOCH, NodeType.EVENT, NodeType.EPOCH),
        (EdgeType.CAUSED, NodeType.EVENT, NodeType.EVENT),
    ],
)
def test_direction_rules_allow_expected_pairs(
    relation_type: EdgeType,
    source_type: NodeType,
    target_type: NodeType,
) -> None:
    assert _is_valid_relation_direction(
        relation_type,
        "source",
        "target",
        {"source": source_type, "target": target_type},
    )


@pytest.mark.parametrize(
    ("relation_type", "source_type", "target_type"),
    [
        (EdgeType.HAS_ITEM, NodeType.ITEM, NodeType.CHARACTER),
        (EdgeType.LOCATED_IN, NodeType.LOCATION, NodeType.ITEM),
        (EdgeType.PARTICIPATED_IN, NodeType.EVENT, NodeType.CHARACTER),
        (EdgeType.BELONGS_TO_EPOCH, NodeType.EPOCH, NodeType.EVENT),
        (EdgeType.CAUSED, NodeType.CHARACTER, NodeType.EVENT),
    ],
)
def test_direction_rules_reject_reversed_pairs(
    relation_type: EdgeType,
    source_type: NodeType,
    target_type: NodeType,
) -> None:
    assert not _is_valid_relation_direction(
        relation_type,
        "source",
        "target",
        {"source": source_type, "target": target_type},
    )


def test_invalid_direction_relation_is_dropped() -> None:
    edge = _build_relation_mutation(
        relation=ExtractedRelation(
            source_node_id="item_dagger",
            target_node_id="char_elian",
            relation_type=EdgeType.HAS_ITEM,
            context_details="invalid reversed ownership",
            is_truth=True,
            is_public=True,
        ),
        resolved_name_index={},
        known_ids={"item_dagger", "char_elian"},
        node_types={"item_dagger": NodeType.ITEM, "char_elian": NodeType.CHARACTER},
        active_epoch_id="epoch_present",
        primary_event_id="evt_hidden",
        pov_character_id="char_elian",
    )

    assert edge is None


def test_located_in_transition_retires_old_location(workflow_context: WorkflowContext) -> None:
    workflow_context.graph_store.seed_story("story_move")
    workflow_context.graph_store.apply_mutations(
        "story_move",
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="char_elian",
                node_type=NodeType.CHARACTER,
                properties={"canonical_name": "Elian", "aliases": [], "description": "調查者"},
            ),
            NodeMutation(
                action="CREATE_NODE",
                node_id="loc_old",
                node_type=NodeType.LOCATION,
                properties={"canonical_name": "南門缺口", "aliases": []},
            ),
            NodeMutation(
                action="CREATE_NODE",
                node_id="loc_new",
                node_type=NodeType.LOCATION,
                properties={"canonical_name": "北坡", "aliases": []},
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                source_id="char_elian",
                relation_type=EdgeType.LOCATED_IN,
                target_id="loc_old",
                attributes={
                    "valid_epoch": "epoch_present",
                    "start_event_id": "evt_old",
                    "is_truth": True,
                    "is_public": False,
                    "known_by": ["char_elian"],
                    "holder": [],
                    "context_details": "Elian 原本位於南門缺口。",
                },
            ),
        ],
    )

    new_edge = EdgeMutation(
        action="CREATE_EDGE",
        source_id="char_elian",
        relation_type=EdgeType.LOCATED_IN,
        target_id="loc_new",
        attributes={
            "valid_epoch": "epoch_present",
            "start_event_id": "evt_new",
            "is_truth": True,
            "is_public": False,
            "known_by": ["char_elian"],
            "holder": [],
            "context_details": "Elian 抵達北坡。",
        },
    )
    active_edges = {
        "char_elian": list(workflow_context.graph_store.story_edges["story_move"].values()),
    }

    retirements = _build_location_transition_mutations(new_edge, active_edges, "evt_new")

    assert len(retirements) == 1
    assert retirements[0].action == "UPDATE_EDGE"
    assert retirements[0].target_id == "loc_old"
    assert retirements[0].attributes["end_event_id"] == "evt_new"


def test_query_context_hides_ended_located_in_edge() -> None:
    store = InMemoryGraphStore()
    store.seed_story("story_query")
    store.apply_mutations(
        "story_query",
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="char_elian",
                node_type=NodeType.CHARACTER,
                properties={"canonical_name": "Elian", "aliases": [], "description": "調查者"},
            ),
            NodeMutation(
                action="CREATE_NODE",
                node_id="loc_old",
                node_type=NodeType.LOCATION,
                properties={"canonical_name": "南門缺口", "aliases": []},
            ),
            NodeMutation(
                action="CREATE_NODE",
                node_id="loc_new",
                node_type=NodeType.LOCATION,
                properties={"canonical_name": "霜徑裂谷", "aliases": []},
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                source_id="char_elian",
                relation_type=EdgeType.LOCATED_IN,
                target_id="loc_old",
                attributes={
                    "valid_epoch": "epoch_present",
                    "start_event_id": "evt_old",
                    "end_event_id": "evt_move",
                    "is_truth": True,
                    "is_public": False,
                    "known_by": ["char_elian"],
                    "holder": [],
                    "context_details": "舊位置",
                },
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                source_id="char_elian",
                relation_type=EdgeType.LOCATED_IN,
                target_id="loc_new",
                attributes={
                    "valid_epoch": "epoch_present",
                    "start_event_id": "evt_move",
                    "is_truth": True,
                    "is_public": False,
                    "known_by": ["char_elian"],
                    "holder": [],
                    "context_details": "新位置",
                },
            ),
        ],
    )

    snapshot = store.query_context(
        GraphQueryRequest(
            story_id="story_query",
            active_epoch_id="epoch_present",
            pov_character_id="char_elian",
            narrative_directive="查詢 Elian 目前位置",
        )
    )

    location_edges = [edge for edge in snapshot.edges if edge.relation_type == EdgeType.LOCATED_IN]
    assert len(location_edges) == 1
    assert location_edges[0].target_id == "loc_new"
