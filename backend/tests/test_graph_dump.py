"""Tests for dump_story_graph (full story graph without query_context filtering)."""

from __future__ import annotations

from app.domain.schema import EdgeMutation, EdgeType, GraphQueryRequest, NodeMutation, NodeType
from app.services.graph_store import InMemoryGraphStore


def test_dump_story_graph_returns_all_edges_unfiltered() -> None:
    store = InMemoryGraphStore()
    store.seed_story("s1")
    store.apply_mutations(
        "s1",
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="evt_x",
                node_type=NodeType.EVENT,
                properties={"canonical_name": "Test event", "aliases": []},
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                source_id="evt_x",
                relation_type=EdgeType.BELONGS_TO_EPOCH,
                target_id="epoch_present",
                attributes={
                    "valid_epoch": "other_epoch",
                    "start_event_id": "evt_x",
                    "is_truth": True,
                    "is_public": False,
                    "known_by": ["char_secret"],
                    "holder": [],
                    "context_details": "",
                },
            ),
        ],
    )
    ctx = store.query_context(
        GraphQueryRequest(
            story_id="s1",
            active_epoch_id="epoch_present",
            pov_character_id="char_public_observer",
            narrative_directive="x",
        )
    )
    assert len(ctx.edges) == 0

    full = store.dump_story_graph("s1")
    assert len(full.edges) == 1
    assert full.edges[0].relation_type == EdgeType.BELONGS_TO_EPOCH
    assert any(n.node_id == "evt_x" for n in full.nodes)
