import pytest

from app.services.workflow.nodes.anchor_resolve import _recompute_unlocks
from app.services.workflow.service import _validate_anchor_selection_guardrails


def test_checkpoint_and_ending_auto_resolve_without_becoming_candidates() -> None:
    resolved = {"main_1"}
    nodes = [
        {"id": "main_1", "node_kind": "NORMAL", "depends_on": [], "status": "RESOLVED"},
        {"id": "checkpoint_1", "node_kind": "CHECKPOINT", "depends_on": ["main_1"], "status": "LOCKED"},
        {"id": "ending_1", "node_kind": "ENDING", "depends_on": ["checkpoint_1"], "status": "LOCKED"},
        {"id": "next_normal", "node_kind": "NORMAL", "depends_on": ["checkpoint_1"], "status": "LOCKED"},
    ]

    next_nodes, candidates = _recompute_unlocks(nodes, resolved)
    statuses = {str(n["id"]): str(n["status"]) for n in next_nodes}

    assert statuses["checkpoint_1"] == "RESOLVED"
    assert statuses["ending_1"] == "RESOLVED"
    assert statuses["next_normal"] == "UNLOCKED"
    assert "checkpoint_1" not in candidates
    assert "ending_1" not in candidates
    assert candidates == ["next_normal"]
    assert {"checkpoint_1", "ending_1"}.issubset(resolved)


def test_selected_anchor_rejects_checkpoint_and_ending_nodes() -> None:
    nodes = [
        {"id": "normal_1", "node_kind": "NORMAL", "depends_on": [], "status": "UNLOCKED"},
        {"id": "checkpoint_1", "node_kind": "CHECKPOINT", "depends_on": ["normal_1"], "status": "LOCKED"},
    ]

    with pytest.raises(ValueError, match="cannot directly target checkpoint/ending"):
        _validate_anchor_selection_guardrails(
            anchor_nodes=nodes,
            resolved_anchors=["normal_1"],
            selected=["checkpoint_1"],
            nxt=["normal_1"],
        )
