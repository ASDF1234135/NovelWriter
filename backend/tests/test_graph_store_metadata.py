import json

from app.domain.schema import ItemNode, NodeMutation, NodeType
from app.services.graph_store import (
    Neo4jGraphStore,
    GraphNodeAdapter,
    InMemoryGraphStore,
    _metadata_dict_from_json_prop,
    _prepare_neo4j_node_properties,
)


def test_prepare_neo4j_node_properties_serializes_metadata_json() -> None:
    node = ItemNode(
        node_id="item_1",
        canonical_name="手槍",
        tags=["weapon"],
        metadata={"bullets": 7, "maker": "ACME"},
    )
    props = _prepare_neo4j_node_properties(node, "story_a")
    assert "metadata" not in props
    assert props["metadata_json"]
    assert json.loads(props["metadata_json"]) == {"bullets": 7, "maker": "ACME"}
    assert props["story_id"] == "story_a"
    assert props["tags"] == ["weapon"]


def test_metadata_dict_from_json_prop_roundtrip() -> None:
    payload = json.dumps({"a": 1, "nested": {"b": 2}}, ensure_ascii=False)
    assert _metadata_dict_from_json_prop({"metadata_json": payload}) == {"a": 1, "nested": {"b": 2}}
    assert _metadata_dict_from_json_prop({}) == {}
    assert _metadata_dict_from_json_prop({"metadata_json": "not-json"}) == {}


def test_inmemory_apply_mutations_preserves_tags_metadata() -> None:
    store = InMemoryGraphStore()
    store.seed_story("s1")
    store.apply_mutations(
        "s1",
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="item_gun",
                node_type=NodeType.ITEM,
                properties={
                    "canonical_name": "手槍",
                    "aliases": [],
                    "item_status": "完好",
                    "is_unique": False,
                    "tags": ["weapon", "illegal"],
                    "metadata": {"count": 12},
                },
            ),
        ],
    )
    node = store.story_nodes["s1"]["item_gun"]
    assert node.tags == ["weapon", "illegal"]
    assert node.metadata == {"count": 12}


def test_from_neo4j_node_reads_metadata_json() -> None:
    class _FakeNode(dict):
        pass

    fake = _FakeNode(
        {
            "node_id": "i1",
            "node_type": "ITEM",
            "canonical_name": "槍",
            "aliases": [],
            "item_status": "完好",
            "is_unique": False,
            "tags": ["weapon"],
            "metadata_json": '{"rounds":3}',
        }
    )
    node = GraphNodeAdapter.from_neo4j_node(fake)
    assert node.metadata == {"rounds": 3}
    assert node.tags == ["weapon"]


def test_neo4j_seed_story_serializes_metadata_json(monkeypatch) -> None:
    calls: list[dict] = []

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def run(self, _query: str, **kwargs):
            calls.append(kwargs)
            return None

    class _FakeDriver:
        def session(self, database: str | None = None):
            return _FakeSession()

    monkeypatch.setattr("app.services.graph_store.GraphDatabase.driver", lambda *_a, **_k: _FakeDriver())
    store = Neo4jGraphStore("bolt://fake", "u", "p", "neo4j")
    store.seed_story("story_seed")

    assert len(calls) == 3
    for row in calls:
        props = row["props"]
        assert props["story_id"] == "story_seed"
        assert "metadata" not in props
        assert "metadata_json" in props
