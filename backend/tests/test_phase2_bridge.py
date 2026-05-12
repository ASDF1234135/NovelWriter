"""Phase 2 bridge expansion: hub 1-hop, epoch filter, vector similarity + overlap."""

from types import SimpleNamespace

from app.domain.schema import (
    CharacterNode,
    EpochNode,
    EventNode,
    ExtractedEntity,
    ExtractedRelation,
    EdgeType,
    GraphEdge,
    GraphSnapshot,
    NodeType,
)
from app.services.workflow.extraction import _phase2_canonical_with_bridge_events


class _MapVectorStore:
    """Minimal VectorStore stub mapping chunk_id -> vector."""

    def __init__(self, vectors_by_chunk: dict[str, list[float]]) -> None:
        self._m = vectors_by_chunk

    def retrieve_vectors_by_chunk_ids(self, story_id: str, chunk_ids: list[str]) -> dict[str, list[float]]:
        return {c: self._m[c] for c in chunk_ids if c in self._m}


def _vec(fill: float = 1.0, dim: int = 64) -> list[float]:
    return [fill] * dim


def test_bridge_injects_ranked_event_after_epoch_filter() -> None:
    epoch_a = "epoch_a"
    evt_ch = "event_ch01_01"
    br_ok = "event_ch01_old_ok"
    br_bad = "event_ch01_old_bad"
    char_c = "char_link"

    nodes = [
        EpochNode(node_id=epoch_a, canonical_name="Present", order_index=0),
        CharacterNode(node_id=char_c, canonical_name="Hero", description="", is_alive=True),
        EventNode(node_id=evt_ch, canonical_name="FightAtTheGateFightAtTheGate", chunk_ids=[]),
        EventNode(node_id=br_ok, canonical_name="EarlierFightEarlierFightEarlier", chunk_ids=["chunk_old_ok"]),
        EventNode(node_id=br_bad, canonical_name="WrongWrongWrongWrongWrongWrongWrong", chunk_ids=["chunk_bad"]),
    ]
    edges = [
        GraphEdge(
            edge_id=f"{char_c}:pi:{evt_ch}",
            source_id=char_c,
            relation_type=EdgeType.PARTICIPATED_IN,
            target_id=evt_ch,
            valid_epoch=epoch_a,
            start_event_id=evt_ch,
            is_truth=True,
        ),
        GraphEdge(
            edge_id=f"{char_c}:pi:{br_ok}",
            source_id=char_c,
            relation_type=EdgeType.PARTICIPATED_IN,
            target_id=br_ok,
            valid_epoch=epoch_a,
            start_event_id=br_ok,
            is_truth=True,
        ),
        GraphEdge(
            edge_id=f"{char_c}:pi:{br_bad}",
            source_id=char_c,
            relation_type=EdgeType.PARTICIPATED_IN,
            target_id=br_bad,
            valid_epoch="epoch_other",
            start_event_id=br_bad,
            is_truth=True,
        ),
        GraphEdge(
            edge_id=f"{br_ok}:belongs:{epoch_a}",
            source_id=br_ok,
            relation_type=EdgeType.BELONGS_TO_EPOCH,
            target_id=epoch_a,
            valid_epoch=epoch_a,
            start_event_id=br_ok,
            is_truth=True,
        ),
    ]
    snapshot = GraphSnapshot(nodes=nodes, edges=edges)

    entities = [
        ExtractedEntity(
            node_id=evt_ch,
            node_type=NodeType.EVENT,
            canonical_name="FightAtTheGateFightAtTheGate",
            summary="fight",
        ),
    ]
    canonical_rows = [{"node_id": ent.node_id, "canonical_name": ent.canonical_name, "node_type": "NodeType.EVENT"} for ent in entities]

    phase1 = [
        ExtractedRelation(
            source_node_id=char_c,
            target_node_id=evt_ch,
            relation_type=EdgeType.PARTICIPATED_IN,
            context_details="",
            is_truth=True,
            is_public=True,
        ),
    ]

    chunk_new = "chunk_new_body"
    state = {
        "story_id": "story_1",
        "chapter_id": 5,
        "active_epoch_id": epoch_a,
        "chapter_chunks": [
            {
                "chunk_id": chunk_new,
                "source_role": "current_body",
                "source_chapter_id": 5,
                "text_chunk": "Some prelude FightAtTheGateFightAtTheGate continues.",
            },
        ],
    }

    vs = _MapVectorStore(
        {
            chunk_new: _vec(1.0),
            "chunk_old_ok": _vec(1.0),
            "chunk_bad": _vec(-1.0),
        }
    )

    settings = SimpleNamespace(
        extraction_phase2_bridge_top_k=2,
        extraction_phase2_bridge_pool_cap=50,
        extraction_phase2_bridge_sim_weight=0.9,
        extraction_phase2_bridge_overlap_weight=0.1,
    )

    rows, diag = _phase2_canonical_with_bridge_events(
        state=state,
        entities=entities,
        canonical_rows=canonical_rows,
        graph_snapshot=snapshot,
        phase1_relations=phase1,
        vector_store=vs,
        settings=settings,
    )

    ids = [r["node_id"] for r in rows]
    assert evt_ch in ids
    assert br_ok in ids
    assert br_bad not in ids
    assert diag.get("after_epoch_filter") == 1
    assert diag.get("injected_bridge_events") == 1


def test_bridge_skipped_when_top_k_zero() -> None:
    snapshot = GraphSnapshot(nodes=[], edges=[])
    entities: list[ExtractedEntity] = []
    canonical_rows: list[dict[str, str]] = []
    settings = SimpleNamespace(
        extraction_phase2_bridge_top_k=0,
        extraction_phase2_bridge_pool_cap=50,
        extraction_phase2_bridge_sim_weight=0.5,
        extraction_phase2_bridge_overlap_weight=0.5,
    )
    rows, diag = _phase2_canonical_with_bridge_events(
        state={"story_id": "s", "chapter_id": 1, "active_epoch_id": "e", "chapter_chunks": []},
        entities=entities,
        canonical_rows=canonical_rows,
        graph_snapshot=snapshot,
        phase1_relations=[],
        vector_store=_MapVectorStore({}),
        settings=settings,
    )
    assert rows == canonical_rows
    assert diag.get("enabled") is False
