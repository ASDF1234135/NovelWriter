from __future__ import annotations

from app.domain.schema import (
    ChapterExtractionOutput,
    ChapterMemory,
    EdgeMutation,
    EdgeType,
    EventOutline,
    ExtractedEntity,
    ExtractedRelation,
    GraphEdge,
    GraphNode,
    GraphQueryRequest,
    NodeMutation,
    NodeType,
    StateUpdaterOutput,
    VectorDocument,
)
from app.services.workflow.extraction import extract_chapter_artifacts, stable_entity_id
from app.services.workflow.continuity import chapter_content_tail_snippet
from app.services.workflow.context import WorkflowContext


def run_state_updater(state: dict, context: WorkflowContext) -> dict:
    events = [EventOutline.model_validate(event) for event in state["ground_truth_events"]]
    chapter_content = state["best_draft_content"] or state["current_draft"]
    graph_snapshot = context.graph_store.query_context(
        GraphQueryRequest(
            story_id=state["story_id"],
            active_epoch_id=state["active_epoch_id"],
            pov_character_id=state["pov_character_id"],
            narrative_directive=state["narrative_directive"],
        )
    )
    existing_nodes_by_id = {node.node_id: node for node in graph_snapshot.nodes}
    existing_ids = set(existing_nodes_by_id)
    required_reference_ids = {
        state["active_epoch_id"],
        state["pov_character_id"],
        "loc_unknown",
    }
    pending_raw = state.get("pending_chapter_extraction") or {}
    if pending_raw:
        extracted = ChapterExtractionOutput.model_validate(pending_raw)
    else:
        extracted, _ = extract_chapter_artifacts(state, context, graph_snapshot, chapter_content, events)
    new_ids: set[str] = set()
    mutations: list[NodeMutation | EdgeMutation] = []
    resolved_entities, resolved_name_index = _resolve_extracted_entities(extracted.entities, existing_nodes_by_id)
    node_types = {node_id: node.node_type for node_id, node in existing_nodes_by_id.items()}
    node_types.update({node_id: resolved["node_type"] for node_id, resolved in resolved_entities.items()})
    primary_event_id = events[0].event_id if events else f"chapter_{state['chapter_id']}_memory"
    active_location_edges = _index_active_location_edges(graph_snapshot.edges, state["active_epoch_id"])

    for event in events:
        new_ids.add(event.event_id)
        node_types[event.event_id] = NodeType.EVENT
        mutations.append(
            NodeMutation(
                action="UPDATE_NODE" if event.event_id in existing_ids else "CREATE_NODE",
                node_id=event.event_id,
                node_type=NodeType.EVENT,
                properties={
                    "canonical_name": event.description[:40],
                    "aliases": [],
                },
            )
        )
        mutations.append(
            EdgeMutation(
                action="CREATE_EDGE",
                source_id=event.event_id,
                relation_type=EdgeType.BELONGS_TO_EPOCH,
                target_id=state["active_epoch_id"],
                attributes={
                    "valid_epoch": state["active_epoch_id"],
                    "start_event_id": event.event_id,
                    "is_truth": True,
                    "is_public": True,
                    "known_by": [],
                    "holder": [],
                    "context_details": "章節結算所屬時代",
                },
            )
        )
        if event.caused_by_event_id:
            mutations.append(
                EdgeMutation(
                    action="CREATE_EDGE",
                    source_id=event.caused_by_event_id,
                    relation_type=EdgeType.CAUSED,
                    target_id=event.event_id,
                    attributes={
                        "valid_epoch": state["active_epoch_id"],
                        "start_event_id": event.caused_by_event_id,
                        "end_event_id": event.event_id,
                        "is_truth": True,
                        "is_public": True,
                        "known_by": [],
                        "holder": [],
                        "context_details": f"{event.caused_by_event_id} 造成了 {event.event_id}",
                    },
                )
            )

    for resolved in resolved_entities.values():
        new_ids.add(resolved["node_id"])
        mutations.append(
            NodeMutation(
                action="UPDATE_NODE" if resolved["node_id"] in existing_ids else "CREATE_NODE",
                node_id=resolved["node_id"],
                node_type=resolved["node_type"],
                properties=resolved["properties"],
            )
        )

    known_ids = existing_ids | new_ids | required_reference_ids
    for relation in extracted.relations:
        edge = _build_relation_mutation(
            relation,
            resolved_name_index,
            known_ids,
            node_types,
            state["active_epoch_id"],
            primary_event_id,
            state["pov_character_id"],
        )
        if edge is not None:
            if edge.relation_type == EdgeType.LOCATED_IN:
                mutations.extend(_build_location_transition_mutations(edge, active_location_edges, primary_event_id))
                _register_active_location_edge(active_location_edges, edge)
            mutations.append(edge)

    # `query_context()` may return a filtered epistemic view and omit baseline nodes
    # that are still valid references for vector metadata.
    whitelist = known_ids
    vector_documents = _build_vector_documents(
        state,
        chapter_content,
        extracted.chapter_memory,
        resolved_entities,
        resolved_name_index,
        existing_nodes_by_id,
    )
    for vector_doc in vector_documents:
        id_candidates = [
            vector_doc.metadata["epoch_id"],
            vector_doc.metadata["location_id"],
            *vector_doc.metadata["characters_involved"],
        ]
        for candidate in id_candidates:
            if candidate not in whitelist:
                raise ValueError("Vector metadata IDs must come from existing or newly created IDs.")

    output = StateUpdaterOutput(mutations=mutations, vector_documents=vector_documents)
    return output.model_dump(mode="json")


def _resolve_extracted_entities(
    entities: list[ExtractedEntity],
    existing_nodes_by_id: dict[str, GraphNode],
) -> tuple[dict[str, dict], dict[str, str]]:
    existing_name_index: dict[str, GraphNode] = {}
    for node in existing_nodes_by_id.values():
        existing_name_index[node.canonical_name.casefold()] = node
        for alias in getattr(node, "aliases", []):
            existing_name_index[str(alias).casefold()] = node

    resolved_entities: dict[str, dict] = {}
    resolved_name_index: dict[str, str] = {
        name: node.node_id
        for name, node in existing_name_index.items()
    }
    for entity in entities:
        existing_node = None
        if entity.node_id and entity.node_id in existing_nodes_by_id:
            existing_node = existing_nodes_by_id[entity.node_id]
        elif entity.canonical_name.casefold() in existing_name_index:
            existing_node = existing_name_index[entity.canonical_name.casefold()]
        else:
            for alias in entity.aliases:
                match = existing_name_index.get(alias.casefold())
                if match is not None:
                    existing_node = match
                    break

        node_id = existing_node.node_id if existing_node is not None else (entity.node_id or stable_entity_id(entity.node_type, entity.canonical_name))
        node_type = existing_node.node_type if existing_node is not None else entity.node_type
        properties = _build_node_properties(entity, node_type)
        resolved_entities[node_id] = {
            "node_id": node_id,
            "node_type": node_type,
            "properties": properties,
        }
        resolved_name_index[entity.canonical_name.casefold()] = node_id
        for alias in entity.aliases:
            resolved_name_index[alias.casefold()] = node_id
    return resolved_entities, resolved_name_index


def _build_node_properties(entity: ExtractedEntity, node_type: NodeType) -> dict:
    properties = {
        "canonical_name": entity.canonical_name,
        "aliases": entity.aliases,
        **entity.properties,
    }
    if node_type in {NodeType.CHARACTER, NodeType.PERSONA}:
        properties.setdefault("description", entity.summary or f"{entity.canonical_name} 在章節中出現。")
        properties.setdefault("is_alive", True)
    if node_type == NodeType.LOCATION:
        properties.setdefault("environmental_condition", "正常")
        properties.setdefault("is_accessible", True)
    if node_type == NodeType.ITEM:
        properties.setdefault("item_status", "完好")
        properties.setdefault("is_unique", False)
    if node_type == NodeType.EPOCH:
        properties.setdefault("order_index", 0)
    return properties


def _build_relation_mutation(
    relation: ExtractedRelation,
    resolved_name_index: dict[str, str],
    known_ids: set[str],
    node_types: dict[str, NodeType],
    active_epoch_id: str,
    primary_event_id: str,
    pov_character_id: str,
) -> EdgeMutation | None:
    source_id = _resolve_relation_node_id(relation.source_node_id, relation.source_name, resolved_name_index)
    target_id = _resolve_relation_node_id(relation.target_node_id, relation.target_name, resolved_name_index)
    if not source_id or not target_id:
        return None
    if source_id not in known_ids or target_id not in known_ids or source_id == target_id:
        return None
    if not _is_valid_relation_direction(relation.relation_type, source_id, target_id, node_types):
        return None
    known_by, holder = _resolve_epistemic_audience(
        relation=relation,
        source_id=source_id,
        target_id=target_id,
        node_types=node_types,
        pov_character_id=pov_character_id,
    )
    return EdgeMutation(
        action="CREATE_EDGE",
        source_id=source_id,
        relation_type=relation.relation_type,
        target_id=target_id,
        attributes={
            "valid_epoch": active_epoch_id,
            "start_event_id": primary_event_id,
            "is_truth": relation.is_truth,
            "is_public": relation.is_public,
            "known_by": known_by,
            "holder": holder,
            "context_details": relation.context_details,
        },
    )


def _resolve_epistemic_audience(
    relation: ExtractedRelation,
    source_id: str,
    target_id: str,
    node_types: dict[str, NodeType],
    pov_character_id: str,
) -> tuple[list[str], list[str]]:
    if relation.is_public:
        return [], []

    audience = [
        node_id
        for node_id in (source_id, target_id)
        if node_types.get(node_id) in {NodeType.CHARACTER, NodeType.PERSONA}
    ]
    if pov_character_id and pov_character_id not in audience:
        audience.append(pov_character_id)

    # Hidden truths are tracked in known_by; hidden false beliefs use holder.
    if relation.is_truth:
        return audience, []
    return [], audience


def _is_valid_relation_direction(
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
    }
    allowed_types = direction_rules.get(relation_type)
    if allowed_types is None:
        return True

    allowed_source, allowed_target = allowed_types
    return source_type in allowed_source and target_type in allowed_target


def _resolve_relation_node_id(node_id: str, node_name: str, resolved_name_index: dict[str, str]) -> str:
    if node_id:
        return node_id
    if node_name:
        return resolved_name_index.get(node_name.casefold(), "")
    return ""


def _build_vector_documents(
    state: dict,
    chapter_content: str,
    memory: ChapterMemory,
    resolved_entities: dict[str, dict],
    resolved_name_index: dict[str, str],
    existing_nodes_by_id: dict[str, GraphNode],
) -> list[VectorDocument]:
    character_ids = [
        node_id
        for node_id, entity in resolved_entities.items()
        if entity["node_type"] in {NodeType.CHARACTER, NodeType.PERSONA}
    ] or [state["pov_character_id"]]
    location_id = _resolve_current_location_id(state, memory, resolved_entities, resolved_name_index)
    location_name = _resolve_location_name(location_id, resolved_entities, existing_nodes_by_id)
    notable_entities = memory.notable_entities or [
        entity["properties"].get("canonical_name", node_id)
        for node_id, entity in resolved_entities.items()
    ]
    common_metadata = {
        "epoch_id": state["active_epoch_id"],
        "characters_involved": character_ids,
        "location_id": location_id,
        "location_name": location_name,
        "story_id": state["story_id"],
        "chapter_id": state["chapter_id"],
        "entity_names": notable_entities[:8],
        "chapter_summary": memory.summary,
    }
    summary_chunk = memory.summary or chapter_content_tail_snippet(chapter_content, 320)
    excerpt_chunk = chapter_content[:1200]
    unresolved_chunk = "；".join(memory.unresolved_threads)
    documents = [
        VectorDocument(
            text_chunk=f"第{state['chapter_id']}章摘要：{summary_chunk}",
            metadata={**common_metadata, "memory_type": "chapter_summary"},
        ),
        VectorDocument(
            text_chunk=f"第{state['chapter_id']}章片段：{excerpt_chunk}",
            metadata={**common_metadata, "memory_type": "chapter_excerpt"},
        ),
    ]
    if unresolved_chunk:
        documents.append(
            VectorDocument(
                text_chunk=f"第{state['chapter_id']}章未解線索：{unresolved_chunk}",
                metadata={**common_metadata, "memory_type": "unresolved_threads"},
            )
        )
    return documents


def _index_active_location_edges(edges: list[GraphEdge], active_epoch_id: str) -> dict[str, list[GraphEdge]]:
    indexed: dict[str, list[GraphEdge]] = {}
    for edge in edges:
        if edge.valid_epoch != active_epoch_id:
            continue
        if edge.relation_type != EdgeType.LOCATED_IN or edge.end_event_id is not None:
            continue
        indexed.setdefault(edge.source_id, []).append(edge)
    return indexed


def _build_location_transition_mutations(
    new_edge: EdgeMutation,
    active_location_edges: dict[str, list[GraphEdge]],
    primary_event_id: str,
) -> list[EdgeMutation]:
    retirements: list[EdgeMutation] = []
    for edge in active_location_edges.get(new_edge.source_id, []):
        if edge.target_id == new_edge.target_id or edge.end_event_id is not None:
            continue
        retirements.append(
            EdgeMutation(
                action="UPDATE_EDGE",
                edge_id=edge.edge_id,
                source_id=edge.source_id,
                relation_type=edge.relation_type,
                target_id=edge.target_id,
                attributes={
                    "valid_epoch": edge.valid_epoch,
                    "start_event_id": edge.start_event_id,
                    "end_event_id": primary_event_id,
                    "is_truth": edge.is_truth,
                    "is_public": edge.is_public,
                    "known_by": edge.known_by,
                    "holder": edge.holder,
                    "context_details": edge.context_details,
                },
            )
        )
    return retirements


def _register_active_location_edge(
    active_location_edges: dict[str, list[GraphEdge]],
    edge: EdgeMutation,
) -> None:
    edge_id = edge.edge_id or f"{edge.source_id}:{edge.relation_type}:{edge.target_id}"
    active_location_edges[edge.source_id] = [
        GraphEdge(
            edge_id=edge_id,
            source_id=edge.source_id,
            relation_type=edge.relation_type,
            target_id=edge.target_id,
            valid_epoch=edge.attributes["valid_epoch"],
            start_event_id=edge.attributes["start_event_id"],
            end_event_id=edge.attributes.get("end_event_id"),
            is_truth=edge.attributes["is_truth"],
            is_public=edge.attributes.get("is_public", False),
            known_by=edge.attributes.get("known_by", []),
            holder=edge.attributes.get("holder", []),
            context_details=edge.attributes.get("context_details", ""),
        )
    ]


def _resolve_current_location_id(
    state: dict,
    memory: ChapterMemory,
    resolved_entities: dict[str, dict],
    resolved_name_index: dict[str, str],
) -> str:
    preferred_names = [
        memory.latest_location,
        state.get("chapter_end_location_hint", ""),
        state.get("last_known_location", ""),
    ]
    for raw_name in preferred_names:
        normalized = raw_name.strip()
        if not normalized:
            continue
        node_id = resolved_name_index.get(normalized.casefold())
        if node_id:
            return node_id

    return next(
        (node_id for node_id, entity in resolved_entities.items() if entity["node_type"] == NodeType.LOCATION),
        "loc_unknown",
    )


def _resolve_location_name(
    location_id: str,
    resolved_entities: dict[str, dict],
    existing_nodes_by_id: dict[str, GraphNode],
) -> str:
    if location_id == "loc_unknown":
        return "未明地點"
    entity = resolved_entities.get(location_id)
    if entity:
        return str(entity["properties"].get("canonical_name", location_id))
    existing = existing_nodes_by_id.get(location_id)
    if existing is not None:
        return existing.canonical_name
    return location_id
