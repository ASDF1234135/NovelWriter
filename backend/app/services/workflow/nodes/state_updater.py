from __future__ import annotations

import json

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
from app.services.workflow.extraction import (
    clip_event_description_for_storage,
    extract_chapter_artifacts,
    stable_entity_id,
)
from app.services.workflow.relation_direction_rules import relation_direction_is_valid
from app.services.workflow.continuity import chapter_content_tail_snippet
from app.services.workflow.context import WorkflowContext
from app.services.workflow.event_normalization import (
    coalesce_over_fragmented_events,
    is_standard_event_id,
    normalize_event_ai_flags,
    normalize_event_ids,
)
from app.services.workflow.chunking import build_chapter_chunks, extract_prev_tail


def run_state_updater(state: dict, context: WorkflowContext) -> dict:
    raw_events = [EventOutline.model_validate(event) for event in state["ground_truth_events"]]
    normalized_raw_events = normalize_event_ai_flags(raw_events)
    events = _coalesce_micro_events(normalized_raw_events)
    events = coalesce_over_fragmented_events(events)
    malformed_ids = [event.event_id for event in events if not is_standard_event_id(event.event_id, chapter_id=int(state["chapter_id"]))]
    if malformed_ids:
        events = normalize_event_ids(int(state["chapter_id"]), events).events
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

    # Chunk context for binding: prefer precomputed chapter_chunks (from workflow chunker),
    # else build a best-effort chunk set from current draft only.
    chunk_list = list(state.get("chapter_chunks") or [])
    if not chunk_list:
        prev_row = None
        if int(state["chapter_id"]) > 1:
            prev_row = context.story_repository.get_chapter(state["story_id"], int(state["chapter_id"]) - 1)
        prev_content = str(prev_row.get("content") or "") if isinstance(prev_row, dict) else ""
        prev_tail = extract_prev_tail(prev_content, output_language=context.output_language)
        chunks = build_chapter_chunks(
            story_id=state["story_id"],
            chapter_id=int(state["chapter_id"]),
            current_body=str(chapter_content or ""),
            prev_tail=prev_tail,
        )
        chunk_list = [c.__dict__ for c in chunks]
    chunk_text_by_id = {
        str(c.get("chunk_id") or "").strip(): str(c.get("text_chunk") or "")
        for c in chunk_list
        if isinstance(c, dict) and str(c.get("chunk_id") or "").strip()
    }
    new_ids: set[str] = set()
    mutations: list[NodeMutation | EdgeMutation] = []
    resolved_entities, resolved_name_index, extraction_node_id_remap = _resolve_extracted_entities(
        extracted.entities, existing_nodes_by_id
    )
    relations_resolved = _rewrite_relation_endpoints_after_entity_resolve(
        list(extracted.relations), extraction_node_id_remap
    )
    node_types = {node_id: node.node_type for node_id, node in existing_nodes_by_id.items()}
    node_types.update({node_id: resolved["node_type"] for node_id, resolved in resolved_entities.items()})
    extracted_event_node_ids = [nid for nid, r in resolved_entities.items() if r["node_type"] == NodeType.EVENT]
    primary_event_id = (
        extracted_event_node_ids[0] if extracted_event_node_ids else f"chapter_{state['chapter_id']}_memory"
    )
    active_location_edges = _index_active_location_edges(graph_snapshot.edges, state["active_epoch_id"])

    for node_id, resolved in resolved_entities.items():
        if resolved["node_type"] != NodeType.EVENT:
            continue
        props = resolved["properties"]
        desc = str(props.get("canonical_name") or "").strip()
        if not desc:
            continue
        key = desc[:30]
        ev_chunks: list[str] = []
        for cid, txt in chunk_text_by_id.items():
            if key and key in txt:
                ev_chunks.append(cid)
                if len(ev_chunks) >= 4:
                    break
        if ev_chunks:
            props["chunk_ids"] = ev_chunks

    for resolved in resolved_entities.values():
        new_ids.add(resolved["node_id"])
        mutations.append(
            NodeMutation(
                action="UPDATE_NODE" if resolved["node_id"] in existing_ids else "CREATE_NODE",
                node_id=resolved["node_id"],
                node_type=resolved["node_type"],
                properties=_sanitize_node_properties(resolved["node_type"], resolved["properties"]),
            )
        )

    known_ids = existing_ids | new_ids | required_reference_ids
    for relation in relations_resolved:
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
            # Promote chunk evidence into top-level attributes for graph_rag alignment.
            meta = dict(edge.attributes.get("metadata") or {}) if isinstance(edge.attributes.get("metadata"), dict) else {}
            ev_ids = meta.get("evidence_chunk_ids")
            if isinstance(ev_ids, list):
                cleaned = [str(x).strip() for x in ev_ids if str(x).strip()]
                if cleaned:
                    edge.attributes["chunk_ids"] = cleaned
            if edge.relation_type == EdgeType.LOCATED_IN:
                mutations.extend(_build_location_transition_mutations(edge, active_location_edges, primary_event_id))
                _register_active_location_edge(active_location_edges, edge)
            mutations.append(edge)

    # Resolve state updates after event granularity is stabilized to avoid dangling start_event_id.
    mutations.extend(
        _resolve_state_mutations(
            events=events,
            extracted_entities=resolved_entities,
            existing_nodes_by_id=existing_nodes_by_id,
        )
    )

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


def _rewrite_relation_endpoints_after_entity_resolve(
    relations: list[ExtractedRelation],
    extraction_node_id_remap: dict[str, str],
) -> list[ExtractedRelation]:
    """Align relation source/target node_ids with IDs chosen in _resolve_extracted_entities (e.g. slug -> cast)."""
    if not extraction_node_id_remap:
        return list(relations)

    def resolve_endpoint(node_id: str) -> str:
        raw = (node_id or "").strip()
        if not raw:
            return node_id
        y = raw
        visited: set[str] = set()
        while y in extraction_node_id_remap and y not in visited:
            visited.add(y)
            y = extraction_node_id_remap[y]
        return y

    out: list[ExtractedRelation] = []
    for rel in relations:
        r = rel.model_copy(deep=True)
        if r.source_node_id:
            r.source_node_id = resolve_endpoint(r.source_node_id)
        if r.target_node_id:
            r.target_node_id = resolve_endpoint(r.target_node_id)
        out.append(r)
    return out


def _resolve_extracted_entities(
    entities: list[ExtractedEntity],
    existing_nodes_by_id: dict[str, GraphNode],
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    existing_name_index: dict[str, GraphNode] = {}
    for node in existing_nodes_by_id.values():
        existing_name_index[node.canonical_name.casefold()] = node
        for alias in getattr(node, "aliases", []):
            existing_name_index[str(alias).casefold()] = node

    resolved_entities: dict[str, dict] = {}
    extraction_node_id_remap: dict[str, str] = {}
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
        raw_extrinsic_id = (entity.node_id or "").strip()
        if raw_extrinsic_id and raw_extrinsic_id != node_id:
            extraction_node_id_remap[raw_extrinsic_id] = node_id
        elif existing_node is not None and not raw_extrinsic_id:
            stable_key = stable_entity_id(entity.node_type, entity.canonical_name)
            if stable_key != node_id:
                extraction_node_id_remap[stable_key] = node_id
        node_type = existing_node.node_type if existing_node is not None else entity.node_type
        properties = _build_node_properties(entity, node_type)
        if existing_node is not None:
            if not entity.tags:
                properties["tags"] = list(getattr(existing_node, "tags", []) or [])
            if not entity.metadata:
                properties["metadata"] = dict(getattr(existing_node, "metadata", {}) or {})
        resolved_entities[node_id] = {
            "node_id": node_id,
            "node_type": node_type,
            "properties": properties,
        }
        resolved_name_index[entity.canonical_name.casefold()] = node_id
        for alias in entity.aliases:
            resolved_name_index[alias.casefold()] = node_id
    return resolved_entities, resolved_name_index, extraction_node_id_remap


def _build_node_properties(entity: ExtractedEntity, node_type: NodeType) -> dict:
    properties = {
        "canonical_name": entity.canonical_name,
        "aliases": entity.aliases,
        **entity.properties,
    }
    if entity.tags:
        properties["tags"] = list(entity.tags)
    if entity.metadata:
        properties["metadata"] = dict(entity.metadata)
    if node_type in {NodeType.CHARACTER, NodeType.PERSONA}:
        properties.setdefault("description", entity.summary or f"{entity.canonical_name} appears in this chapter.")
        properties.setdefault("is_alive", True)
    if node_type == NodeType.LOCATION:
        properties.setdefault("environmental_condition", "normal")
        properties.setdefault("is_accessible", True)
    if node_type == NodeType.ITEM:
        properties.setdefault("item_status", "intact")
        properties.setdefault("is_unique", False)
    if node_type == NodeType.EPOCH:
        properties.setdefault("order_index", 0)
    if node_type == NodeType.RULE:
        properties.setdefault("description", entity.summary or entity.properties.get("description") or "")
        if "penalty" not in properties and entity.properties.get("penalty") is not None:
            properties["penalty"] = entity.properties.get("penalty")
        properties.setdefault("is_active", True)
    return properties


def _coalesce_micro_events(events: list[EventOutline]) -> list[EventOutline]:
    if len(events) < 5:
        return events
    micro_markers = (
        "閃避",
        "揮拳",
        "出手",
        "反擊",
        "翻滾",
        "轉身",
        "格擋",
        "刺擊",
        "扣下",
        "躍起",
        "dodge",
        "punch",
        "strike",
        "counter",
        "roll",
        "parry",
        "thrust",
    )
    if sum(1 for e in events if any(tok in (e.description or "") for tok in micro_markers)) < 4:
        return events
    merged_desc = "; ".join((e.description or "").strip() for e in events if (e.description or "").strip())
    merged_event = EventOutline(
        event_id=events[-1].event_id,
        description=merged_desc[:300],
        caused_by_event_id=events[0].caused_by_event_id,
    )
    return [merged_event]


def _sanitize_tags_value(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _sanitize_metadata_value(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    try:
        json.dumps(raw, ensure_ascii=False)
    except (TypeError, ValueError):
        return {}
    return dict(raw)


def _sanitize_node_properties(node_type: NodeType, properties: dict) -> dict:
    allowed = {
        NodeType.CHARACTER: {"canonical_name", "aliases", "description", "is_alive"},
        NodeType.PERSONA: {"canonical_name", "aliases", "description", "is_alive"},
        NodeType.LOCATION: {"canonical_name", "aliases", "environmental_condition", "is_accessible"},
        NodeType.ITEM: {"canonical_name", "aliases", "item_status", "is_unique"},
        NodeType.EVENT: {"canonical_name", "aliases"},
        NodeType.EPOCH: {"canonical_name", "aliases", "order_index"},
        NodeType.CONCEPT: {"canonical_name", "aliases"},
        NodeType.RULE: {"canonical_name", "aliases", "description", "penalty", "is_active"},
    }[node_type]
    clean: dict = {}
    for k, v in (properties or {}).items():
        if k == "tags":
            clean["tags"] = _sanitize_tags_value(v)
        elif k == "metadata":
            clean["metadata"] = _sanitize_metadata_value(v)
        elif k == "chunk_ids":
            clean["chunk_ids"] = _sanitize_tags_value(v)
        elif k in allowed:
            clean[k] = v
    return clean


def _resolve_state_mutations(
    events: list[EventOutline],
    extracted_entities: dict[str, dict],
    existing_nodes_by_id: dict[str, GraphNode],
) -> list[NodeMutation]:
    by_name: dict[str, tuple[str, NodeType]] = {}
    for node_id, row in extracted_entities.items():
        cname = str(row["properties"].get("canonical_name") or "").strip()
        if cname:
            by_name[cname.casefold()] = (node_id, row["node_type"])
    for node in existing_nodes_by_id.values():
        by_name[node.canonical_name.casefold()] = (node.node_id, node.node_type)
    out: list[NodeMutation] = []
    death_tokens = ("死亡", "死去", "斷氣", "喪命", "died", "death", "killed", "fatal")
    for ev in events:
        desc = (ev.description or "").strip()
        if not desc:
            continue
        if any(t in desc for t in death_tokens):
            for name, (node_id, nt) in by_name.items():
                if nt not in {NodeType.CHARACTER, NodeType.PERSONA}:
                    continue
                if name and name in desc.casefold():
                    out.append(
                        NodeMutation(
                            action="UPDATE_NODE",
                            node_id=node_id,
                            node_type=nt,
                            properties={"is_alive": False},
                        )
                    )
    return out


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
    if not relation_direction_is_valid(relation.relation_type, source_id, target_id, node_types):
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
            "tags": _sanitize_tags_value(relation.tags),
            "metadata": _sanitize_metadata_value(relation.metadata),
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
    unresolved_chunk = "; ".join(memory.unresolved_threads)
    documents = [
        VectorDocument(
            text_chunk=f"Chapter {state['chapter_id']} summary: {summary_chunk}",
            metadata={**common_metadata, "memory_type": "chapter_summary"},
        ),
        VectorDocument(
            text_chunk=f"Chapter {state['chapter_id']} excerpt: {excerpt_chunk}",
            metadata={**common_metadata, "memory_type": "chapter_excerpt"},
        ),
    ]
    if unresolved_chunk:
        documents.append(
            VectorDocument(
                text_chunk=f"Chapter {state['chapter_id']} unresolved threads: {unresolved_chunk}",
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
                    "tags": list(edge.tags),
                    "metadata": dict(edge.metadata),
                },
            )
        )
    return retirements


def _register_active_location_edge(
    active_location_edges: dict[str, list[GraphEdge]],
    edge: EdgeMutation,
) -> None:
    edge_id = edge.edge_id or f"{edge.source_id}:{edge.relation_type}:{edge.target_id}"
    raw_em = edge.attributes.get("metadata")
    em = dict(raw_em) if isinstance(raw_em, dict) else {}
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
            tags=_sanitize_tags_value(edge.attributes.get("tags")),
            metadata=_sanitize_metadata_value(em),
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
        return "unknown_location"
    entity = resolved_entities.get(location_id)
    if entity:
        return str(entity["properties"].get("canonical_name", location_id))
    existing = existing_nodes_by_id.get(location_id)
    if existing is not None:
        return existing.canonical_name
    return location_id
