"""R6 mandatory planned-node validation and b-story resolution evidence (R2c)."""

from __future__ import annotations

from app.domain.schema import ExtractedEntity, NodeType, ProposedGraphNode
from app.services.workflow.chapter_pipeline import (
    apply_manual_entity_remap,
    extraction_substantiated_event_ids,
    remap_planned_entities,
    validate_b_story_resolution,
    validate_mandatory_planned_nodes,
)


def test_r6_flags_missing_mandatory_after_remap() -> None:
    planned = [
        ProposedGraphNode(
            node_id="char_slot",
            node_type=NodeType.CHARACTER,
            role="商人",
            canonical_name="黑市商人",
            mandatory=True,
        ).model_dump(mode="json")
    ]
    entities = [
        ExtractedEntity(
            node_id="char_other",
            node_type=NodeType.CHARACTER,
            canonical_name="路人甲",
            aliases=[],
        )
    ]
    remapped, _ = remap_planned_entities(entities, planned)
    ok, missing = validate_mandatory_planned_nodes(remapped, planned)
    assert ok is False
    assert "char_slot" in missing


def test_remap_uses_author_surfaces_when_canonical_differs() -> None:
    """R6 helper: validated author surfaces can merge an extracted id onto planned slot."""
    planned = [
        ProposedGraphNode(
            node_id="char_slot",
            node_type=NodeType.CHARACTER,
            role="研究員",
            canonical_name="陳博士",
            mandatory=True,
        ).model_dump(mode="json")
    ]
    entities = [
        ExtractedEntity(
            node_id="char_llm",
            node_type=NodeType.CHARACTER,
            canonical_name="隔壁的老王",
            aliases=[],
        )
    ]
    remapped_none, _ = remap_planned_entities(entities, planned, author_surfaces=None)
    assert remapped_none[0].node_id == "char_llm"

    author_surfaces = {"char_slot": ["隔壁的老王"]}
    remapped, warns = remap_planned_entities(entities, planned, author_surfaces=author_surfaces)
    assert remapped[0].node_id == "char_slot"
    assert any(w.get("to_id") == "char_slot" for w in warns)


def test_r6_skips_waived_mandatory_ids() -> None:
    planned = [
        ProposedGraphNode(
            node_id="char_slot",
            node_type=NodeType.CHARACTER,
            role="商人",
            canonical_name="黑市商人",
            mandatory=True,
        ).model_dump(mode="json")
    ]
    entities = [
        ExtractedEntity(
            node_id="char_other",
            node_type=NodeType.CHARACTER,
            canonical_name="路人",
            aliases=[],
        )
    ]
    ok, missing = validate_mandatory_planned_nodes(
        entities, planned, skip_mandatory_node_ids={"char_slot"}
    )
    assert ok is True
    assert missing == []


def test_apply_manual_entity_remap_rewrites_node_id() -> None:
    entities = [
        ExtractedEntity(
            node_id="ghost",
            node_type=NodeType.CHARACTER,
            canonical_name="x",
            aliases=[],
        )
    ]
    out = apply_manual_entity_remap(entities, [{"from_node_id": "ghost", "to_node_id": "planned_1"}])
    assert out[0].node_id == "planned_1"


def test_r6_passes_when_mandatory_id_present() -> None:
    planned = [
        ProposedGraphNode(
            node_id="char_slot",
            node_type=NodeType.CHARACTER,
            role="商人",
            canonical_name="黑市商人",
            mandatory=True,
        ).model_dump(mode="json")
    ]
    entities = [
        ExtractedEntity(
            node_id="char_slot",
            node_type=NodeType.CHARACTER,
            canonical_name="黑市商人",
            aliases=[],
        )
    ]
    remapped, _ = remap_planned_entities(entities, planned)
    ok, missing = validate_mandatory_planned_nodes(remapped, planned)
    assert ok is True
    assert missing == []


def test_validate_b_story_resolution_rejects_unknown_evidence_event() -> None:
    ok, err = validate_b_story_resolution(
        {"resolution_evidence_event_ids": ["evt_phantom"], "resolved_b_stories": ["b_01"]},
        {"evt_real"},
    )
    assert ok is False
    assert "evt_phantom" in err
    assert "substantiated" in err


def test_validate_b_story_resolution_accepts_known_evidence() -> None:
    ok, err = validate_b_story_resolution(
        {"resolution_evidence_event_ids": ["evt_real"], "resolved_b_stories": ["b_01"]},
        {"evt_real"},
    )
    assert ok is True
    assert err == ""


def test_validate_b_story_resolution_requires_evidence_when_resolved() -> None:
    ok, err = validate_b_story_resolution(
        {"resolution_evidence_event_ids": [], "resolved_b_stories": ["b_01"]},
        {"evt_real"},
    )
    assert ok is False
    assert "non-empty" in err.lower() or "evidence" in err.lower()


def test_extraction_substantiated_event_ids_from_entities_and_relations() -> None:
    pending = {
        "entities": [{"node_id": "evt_a", "node_type": "EVENT", "canonical_name": "a"}],
        "relations": [{"source_node_id": "char_1", "target_node_id": "evt_b"}],
    }
    gt = {"evt_a", "evt_b", "evt_c"}
    got = extraction_substantiated_event_ids(pending, gt)
    assert got == {"evt_a", "evt_b"}


def test_extraction_substantiated_ignores_planner_only_events() -> None:
    pending = {"entities": [{"node_id": "char_x", "node_type": "CHARACTER"}], "relations": []}
    got = extraction_substantiated_event_ids(pending, {"evt_only_in_planner"})
    assert got == set()
