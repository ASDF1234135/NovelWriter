"""RULE nodes, geofenced rule query, and continuity helpers."""

from __future__ import annotations

from app.domain.schema import (
    EdgeMutation,
    EdgeType,
    EnforcedRuleContext,
    GraphEdge,
    GraphQueryRequest,
    GraphSnapshot,
    LocationNode,
    NodeMutation,
    NodeType,
    RuleNode,
)
from app.services.graph_store import InMemoryGraphStore, collect_enforced_rules_for_context
from app.services.workflow.continuity import (
    format_local_enforced_rules_block,
    resolve_pov_location_node_id,
)
from app.services.workflow.extraction import _relation_direction_valid


def test_collect_enforced_rules_location_and_epoch() -> None:
    store = InMemoryGraphStore()
    sid = "story_r1"
    store.seed_story(sid)
    store.apply_mutations(
        sid,
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="loc_bar",
                node_type=NodeType.LOCATION,
                properties={"canonical_name": "濾芯酒吧"},
            ),
            NodeMutation(
                action="CREATE_NODE",
                node_id="rule_no_trade",
                node_type=NodeType.RULE,
                properties={
                    "canonical_name": "禁記憶交易",
                    "description": "不准在此進行記憶交易",
                    "penalty": "列入黑名單",
                    "is_active": True,
                },
            ),
            NodeMutation(
                action="CREATE_NODE",
                node_id="rule_epoch",
                node_type=NodeType.RULE,
                properties={
                    "canonical_name": "時代協議",
                    "description": "全時代禁止未授權跳躍",
                    "is_active": True,
                },
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                source_id="rule_no_trade",
                relation_type=EdgeType.ENFORCED_IN,
                target_id="loc_bar",
                attributes={
                    "valid_epoch": "epoch_present",
                    "start_event_id": "e0",
                    "is_truth": True,
                    "is_public": True,
                    "context_details": "",
                },
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                source_id="rule_epoch",
                relation_type=EdgeType.ENFORCED_IN,
                target_id="epoch_present",
                attributes={
                    "valid_epoch": "epoch_present",
                    "start_event_id": "e0",
                    "is_truth": True,
                    "is_public": True,
                    "context_details": "",
                },
            ),
        ],
    )
    out = store.list_enforced_rules_for_context(sid, "loc_bar", "epoch_present", "char_public_observer")
    titles = {r.canonical_name for r in out}
    assert "禁記憶交易" in titles
    assert "時代協議" in titles


def test_collect_enforced_rules_exempt_pov() -> None:
    store = InMemoryGraphStore()
    sid = "story_r2"
    store.seed_story(sid)
    store.apply_mutations(
        sid,
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="loc_x",
                node_type=NodeType.LOCATION,
                properties={"canonical_name": "測試地點"},
            ),
            NodeMutation(
                action="CREATE_NODE",
                node_id="rule_a",
                node_type=NodeType.RULE,
                properties={"canonical_name": "規則A", "description": "測試", "is_active": True},
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                source_id="rule_a",
                relation_type=EdgeType.ENFORCED_IN,
                target_id="loc_x",
                attributes={
                    "valid_epoch": "epoch_present",
                    "start_event_id": "e0",
                    "is_truth": True,
                    "is_public": True,
                    "context_details": "",
                },
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                source_id="rule_a",
                relation_type=EdgeType.EXEMPT_FROM,
                target_id="char_public_observer",
                attributes={
                    "valid_epoch": "epoch_present",
                    "start_event_id": "e0",
                    "is_truth": True,
                    "is_public": True,
                    "context_details": "",
                },
            ),
        ],
    )
    out = store.list_enforced_rules_for_context(sid, "loc_x", "epoch_present", "char_public_observer")
    assert out == []


def test_collect_enforced_rules_inactive_skipped() -> None:
    nodes = {
        "loc_x": LocationNode(node_id="loc_x", canonical_name="X"),
        "rule_z": RuleNode(
            node_id="rule_z",
            canonical_name="Z",
            description="d",
            is_active=False,
        ),
    }
    edges = {
        "e1": GraphEdge(
            edge_id="e1",
            source_id="rule_z",
            relation_type=EdgeType.ENFORCED_IN,
            target_id="loc_x",
            valid_epoch="epoch_present",
            start_event_id="s",
            is_truth=True,
            is_public=True,
        ),
    }
    out = collect_enforced_rules_for_context(
        nodes,
        edges,
        location_node_id="loc_x",
        epoch_id="epoch_present",
        pov_character_id="c1",
    )
    assert out == []


def test_resolve_pov_location_node_id() -> None:
    snap = GraphSnapshot(
        nodes=[],
        edges=[
            GraphEdge(
                edge_id="e",
                source_id="char_public_observer",
                relation_type=EdgeType.LOCATED_IN,
                target_id="loc_bar",
                valid_epoch="epoch_present",
                start_event_id="s",
                end_event_id=None,
                is_truth=True,
                is_public=True,
            ),
        ],
    )
    assert resolve_pov_location_node_id(snap, "char_public_observer", "epoch_present") == "loc_bar"


def test_format_local_enforced_rules_block_empty() -> None:
    assert format_local_enforced_rules_block([], "地點") == ""


def test_format_local_enforced_rules_block_non_empty() -> None:
    block = format_local_enforced_rules_block(
        [
            EnforcedRuleContext(
                rule_id="r1",
                canonical_name="規則一",
                description="不可奔跑",
                penalty="罰款",
                restrict_target_names=["槍械"],
                exempt_character_names=["老闆"],
            )
        ],
        "濾芯酒吧",
    )
    assert "濾芯酒吧" in block
    assert "不可奔跑" in block
    assert "罰款" in block
    assert "槍械" in block
    assert "老闆" in block


def test_relation_direction_valid_rule_edges() -> None:
    nt = {
        "r": NodeType.RULE,
        "l": NodeType.LOCATION,
        "e": NodeType.EPOCH,
        "c": NodeType.CHARACTER,
        "i": NodeType.ITEM,
        "x": NodeType.CONCEPT,
        "p": NodeType.PERSONA,
    }
    assert _relation_direction_valid(EdgeType.ENFORCED_IN, "r", "l", nt)
    assert _relation_direction_valid(EdgeType.ENFORCED_IN, "r", "e", nt)
    assert not _relation_direction_valid(EdgeType.ENFORCED_IN, "l", "r", nt)
    assert _relation_direction_valid(EdgeType.RESTRICTS, "r", "c", nt)
    assert _relation_direction_valid(EdgeType.RESTRICTS, "r", "i", nt)
    assert _relation_direction_valid(EdgeType.RESTRICTS, "r", "x", nt)
    assert _relation_direction_valid(EdgeType.EXEMPT_FROM, "r", "p", nt)
    assert not _relation_direction_valid(EdgeType.EXEMPT_FROM, "r", "l", nt)


def test_query_context_request_inherits_list_enforced_rules() -> None:
    store = InMemoryGraphStore()
    store.seed_story("s_q")
    req = GraphQueryRequest(
        story_id="s_q",
        active_epoch_id="epoch_present",
        pov_character_id="char_public_observer",
        narrative_directive="test",
    )
    assert store.list_enforced_rules_for_context(req.story_id, "loc_unknown", req.active_epoch_id, req.pov_character_id) == []
