"""Shared relation endpoint direction checks for extraction validation and state updater."""

from __future__ import annotations

from app.domain.schema import EdgeType, NodeType


def relation_direction_is_valid(
    relation_type: EdgeType,
    source_id: str,
    target_id: str,
    node_types: dict[str, NodeType],
) -> bool:
    source_type = node_types.get(source_id)
    target_type = node_types.get(target_id)
    if source_type is None or target_type is None:
        return True

    direction_rules: dict[EdgeType, tuple[set[NodeType], set[NodeType]]] = {
        EdgeType.HAS_ITEM: (
            {NodeType.CHARACTER, NodeType.PERSONA, NodeType.LOCATION},
            {NodeType.ITEM},
        ),
        EdgeType.LOCATED_IN: (
            {NodeType.CHARACTER, NodeType.PERSONA, NodeType.ITEM, NodeType.EVENT},
            {NodeType.LOCATION},
        ),
        EdgeType.PARTICIPATED_IN: (
            {NodeType.CHARACTER, NodeType.PERSONA},
            {NodeType.EVENT},
        ),
        EdgeType.BELONGS_TO_EPOCH: (
            {NodeType.EVENT},
            {NodeType.EPOCH},
        ),
        EdgeType.CAUSED: (
            {NodeType.EVENT},
            {NodeType.EVENT},
        ),
        EdgeType.ENFORCED_IN: (
            {NodeType.RULE},
            {NodeType.LOCATION, NodeType.EPOCH},
        ),
        EdgeType.RESTRICTS: (
            {NodeType.RULE},
            {NodeType.CHARACTER, NodeType.PERSONA, NodeType.ITEM, NodeType.CONCEPT},
        ),
        EdgeType.EXEMPT_FROM: (
            {NodeType.RULE},
            {NodeType.CHARACTER, NodeType.PERSONA},
        ),
    }
    allowed_types = direction_rules.get(relation_type)
    if allowed_types is None:
        return True

    allowed_source, allowed_target = allowed_types
    return source_type in allowed_source and target_type in allowed_target
