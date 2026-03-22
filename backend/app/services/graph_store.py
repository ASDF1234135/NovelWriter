from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import sleep
from typing import Iterable, Protocol

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from app.domain.schema import (
    CharacterNode,
    ConceptNode,
    EdgeMutation,
    EdgeType,
    EpochNode,
    EventNode,
    GraphEdge,
    GraphNode,
    GraphQueryRequest,
    GraphSnapshot,
    ItemNode,
    LocationNode,
    NodeMutation,
    NodeType,
    PersonaNode,
)


class GraphStore(Protocol):
    def seed_story(self, story_id: str) -> None:
        ...

    def query_context(self, request: GraphQueryRequest) -> GraphSnapshot:
        ...

    def apply_mutations(self, story_id: str, mutations: Iterable[NodeMutation | EdgeMutation]) -> None:
        ...

    def clear_macro_cast_characters(self, story_id: str) -> None:
        """Remove CHARACTER nodes created by macro compile (node_id prefix story_id_mc_)."""
        ...


@dataclass
class InMemoryGraphStore:
    story_nodes: dict[str, dict[str, GraphNode]] = field(default_factory=lambda: defaultdict(dict))
    story_edges: dict[str, dict[str, GraphEdge]] = field(default_factory=lambda: defaultdict(dict))

    def seed_story(self, story_id: str) -> None:
        nodes = self.story_nodes[story_id]
        if nodes:
            return
        nodes["epoch_present"] = GraphNodeAdapter.epoch("epoch_present", "現代", 1)
        nodes["loc_unknown"] = GraphNodeAdapter.location("loc_unknown", "未明地點")
        nodes["char_public_observer"] = GraphNodeAdapter.character(
            "char_public_observer",
            "旁觀者",
            "作為預設視角的敘事角色。",
        )

    def query_context(self, request: GraphQueryRequest) -> GraphSnapshot:
        self.seed_story(request.story_id)
        nodes = list(self.story_nodes[request.story_id].values())
        edges = [
            edge
            for edge in self.story_edges[request.story_id].values()
            if edge.valid_epoch == request.active_epoch_id
            and _is_visible_to_pov(edge, request.pov_character_id)
            and _is_active_edge(edge)
        ]
        return GraphSnapshot(nodes=nodes, edges=edges)

    def clear_macro_cast_characters(self, story_id: str) -> None:
        self.seed_story(story_id)
        prefix = f"{story_id}_mc_"
        nodes = self.story_nodes[story_id]
        for nid in list(nodes.keys()):
            if nid.startswith(prefix):
                del nodes[nid]
        edges = self.story_edges[story_id]
        for eid in list(edges.keys()):
            edge = edges[eid]
            if edge.source_id.startswith(prefix) or edge.target_id.startswith(prefix):
                del edges[eid]

    def apply_mutations(self, story_id: str, mutations: Iterable[NodeMutation | EdgeMutation]) -> None:
        self.seed_story(story_id)
        for mutation in mutations:
            if isinstance(mutation, NodeMutation):
                self.story_nodes[story_id][mutation.node_id] = GraphNodeAdapter.from_mutation(mutation)
            else:
                edge_id = mutation.edge_id or f"{mutation.source_id}:{mutation.relation_type}:{mutation.target_id}"
                if mutation.action == "DELETE_EDGE":
                    self.story_edges[story_id].pop(edge_id, None)
                else:
                    self.story_edges[story_id][edge_id] = GraphEdge(
                        edge_id=edge_id,
                        source_id=mutation.source_id,
                        relation_type=mutation.relation_type,
                        target_id=mutation.target_id,
                        valid_epoch=mutation.attributes["valid_epoch"],
                        start_event_id=mutation.attributes["start_event_id"],
                        end_event_id=mutation.attributes.get("end_event_id"),
                        is_truth=mutation.attributes["is_truth"],
                        is_public=mutation.attributes.get("is_public", False),
                        known_by=mutation.attributes.get("known_by", []),
                        holder=mutation.attributes.get("holder", []),
                        context_details=mutation.attributes.get("context_details", ""),
                    )


class Neo4jGraphStore:
    def __init__(self, uri: str, username: str, password: str, database: str) -> None:
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.database = database
        self.max_retries = 10
        self.retry_delay_seconds = 1.0

    def _run_with_retry(self, operation) -> None:
        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                return operation()
            except ServiceUnavailable as exc:
                last_error = exc
                sleep(self.retry_delay_seconds)
        if last_error is not None:
            raise last_error

    def seed_story(self, story_id: str) -> None:
        nodes = [
            GraphNodeAdapter.epoch("epoch_present", "現代", 1),
            GraphNodeAdapter.location("loc_unknown", "未明地點"),
            GraphNodeAdapter.character("char_public_observer", "旁觀者", "作為預設視角的敘事角色。"),
        ]
        def operation() -> None:
            with self.driver.session(database=self.database) as session:
                for node in nodes:
                    label = node.node_type.value
                    props = node.model_dump(mode="json")
                    props["story_id"] = story_id
                    session.run(
                        f"""
                        MERGE (n:StoryNode:{label} {{story_id: $story_id, node_id: $node_id}})
                        SET n += $props
                        """,
                        story_id=story_id,
                        node_id=node.node_id,
                        props=props,
                    )
        self._run_with_retry(operation)

    def clear_macro_cast_characters(self, story_id: str) -> None:
        prefix = f"{story_id}_mc_"

        def operation() -> None:
            with self.driver.session(database=self.database) as session:
                session.run(
                    """
                    MATCH (n:StoryNode {story_id: $story_id})
                    WHERE n.node_id STARTS WITH $prefix
                    DETACH DELETE n
                    """,
                    story_id=story_id,
                    prefix=prefix,
                )

        self._run_with_retry(operation)

    def query_context(self, request: GraphQueryRequest) -> GraphSnapshot:
        self.seed_story(request.story_id)
        result: GraphSnapshot | None = None
        query_terms = _extract_query_terms(request.narrative_directive)
        hop_count = _determine_hop_count(query_terms)
        path_hops = max(1, min(3, hop_count))
        def operation() -> None:
            nonlocal result
            with self.driver.session(database=self.database) as session:
                query = f"""
                    MATCH (seed:StoryNode {{story_id: $story_id}})
                    WHERE size($query_terms) = 0
                       OR any(term IN $query_terms WHERE toLower(coalesce(seed.canonical_name, '')) CONTAINS term)
                       OR any(alias IN coalesce(seed.aliases, []) WHERE any(term IN $query_terms WHERE toLower(alias) CONTAINS term))
                    WITH collect(DISTINCT seed) AS seeds
                    CALL (seeds) {{
                      UNWIND seeds AS seed
                      OPTIONAL MATCH path = (seed)-[rels*1..{path_hops}]-(neighbor:StoryNode {{story_id: $story_id}})
                      WHERE all(r IN rels WHERE coalesce(r.valid_epoch, $active_epoch_id) = $active_epoch_id
                        AND (type(r) <> 'LOCATED_IN' OR r.end_event_id IS NULL)
                        AND (
                          (coalesce(r.is_truth, true) = true AND
                            (coalesce(r.is_public, false) = true OR $pov_character_id IN coalesce(r.known_by, [])))
                          OR
                          (coalesce(r.is_truth, true) = false AND
                            (coalesce(r.is_public, false) = true OR $pov_character_id IN coalesce(r.holder, [])))
                        ))
                      RETURN collect(path) AS paths
                    }}
                    WITH [p IN paths WHERE p IS NOT NULL] AS filtered_paths, seeds
                    UNWIND CASE WHEN size(filtered_paths) = 0 THEN [null] ELSE filtered_paths END AS path
                    WITH seeds, path
                    UNWIND CASE
                      WHEN path IS NULL THEN seeds
                      ELSE nodes(path)
                    END AS n
                    WITH DISTINCT n, seeds, path
                    RETURN collect(DISTINCT n) AS nodes
                """
                node_records = session.run(
                    query,
                    story_id=request.story_id,
                    active_epoch_id=request.active_epoch_id,
                    pov_character_id=request.pov_character_id,
                    query_terms=query_terms,
                ).single()
                edge_records = session.run(
                    f"""
                    MATCH (seed:StoryNode {{story_id: $story_id}})
                    WHERE size($query_terms) = 0
                       OR any(term IN $query_terms WHERE toLower(coalesce(seed.canonical_name, '')) CONTAINS term)
                       OR any(alias IN coalesce(seed.aliases, []) WHERE any(term IN $query_terms WHERE toLower(alias) CONTAINS term))
                    WITH collect(DISTINCT seed) AS seeds
                    UNWIND seeds AS seed
                    OPTIONAL MATCH path = (seed)-[rels*1..{path_hops}]-(neighbor:StoryNode {{story_id: $story_id}})
                    WHERE all(r IN rels WHERE coalesce(r.valid_epoch, $active_epoch_id) = $active_epoch_id
                      AND (type(r) <> 'LOCATED_IN' OR r.end_event_id IS NULL)
                      AND (
                        (coalesce(r.is_truth, true) = true AND
                          (coalesce(r.is_public, false) = true OR $pov_character_id IN coalesce(r.known_by, [])))
                        OR
                        (coalesce(r.is_truth, true) = false AND
                          (coalesce(r.is_public, false) = true OR $pov_character_id IN coalesce(r.holder, [])))
                      ))
                    UNWIND CASE WHEN path IS NULL THEN [] ELSE relationships(path) END AS r
                    RETURN collect(DISTINCT r) AS rels
                    """,
                    story_id=request.story_id,
                    active_epoch_id=request.active_epoch_id,
                    pov_character_id=request.pov_character_id,
                    query_terms=query_terms,
                ).single()
                raw_nodes = node_records["nodes"] if node_records else []
                raw_edges = edge_records["rels"] if edge_records else []
                if not raw_nodes:
                    fallback_nodes = session.run(
                        """
                        MATCH (n:StoryNode {story_id: $story_id})
                        RETURN collect(DISTINCT n) AS nodes
                        """,
                        story_id=request.story_id,
                    ).single()
                    raw_nodes = fallback_nodes["nodes"] if fallback_nodes else []
                nodes = [GraphNodeAdapter.from_neo4j_node(node) for node in raw_nodes]
                edges = [GraphNodeAdapter.edge_from_neo4j(edge) for edge in raw_edges]
                result = GraphSnapshot(nodes=nodes, edges=edges)
        self._run_with_retry(operation)
        return result or GraphSnapshot(nodes=[], edges=[])

    def apply_mutations(self, story_id: str, mutations: Iterable[NodeMutation | EdgeMutation]) -> None:
        self.seed_story(story_id)
        def operation() -> None:
            with self.driver.session(database=self.database) as session:
                for mutation in mutations:
                    if isinstance(mutation, NodeMutation):
                        node = GraphNodeAdapter.from_mutation(mutation)
                        label = node.node_type.value
                        props = node.model_dump(mode="json")
                        props["story_id"] = story_id
                        session.run(
                            f"""
                            MERGE (n:StoryNode:{label} {{story_id: $story_id, node_id: $node_id}})
                            SET n += $props
                            """,
                            story_id=story_id,
                            node_id=node.node_id,
                            props=props,
                        )
                    else:
                        edge_id = mutation.edge_id or f"{mutation.source_id}:{mutation.relation_type}:{mutation.target_id}"
                        if mutation.action == "DELETE_EDGE":
                            session.run(
                                """
                                MATCH (:StoryNode {story_id: $story_id, node_id: $source_id})-[r {story_id: $story_id, edge_id: $edge_id}]->(:StoryNode {story_id: $story_id, node_id: $target_id})
                                DELETE r
                                """,
                                story_id=story_id,
                                source_id=mutation.source_id,
                                target_id=mutation.target_id,
                                edge_id=edge_id,
                            )
                            continue

                        rel_type = mutation.relation_type.value
                        attributes = dict(mutation.attributes)
                        attributes["edge_id"] = edge_id
                        attributes["story_id"] = story_id
                        attributes["source_id"] = mutation.source_id
                        attributes["target_id"] = mutation.target_id
                        attributes["relation_type"] = rel_type
                        session.run(
                            f"""
                            MATCH (s:StoryNode {{story_id: $story_id, node_id: $source_id}})
                            MATCH (t:StoryNode {{story_id: $story_id, node_id: $target_id}})
                            MERGE (s)-[r:{rel_type} {{story_id: $story_id, edge_id: $edge_id}}]->(t)
                            SET r += $attributes
                            """,
                            story_id=story_id,
                            source_id=mutation.source_id,
                            target_id=mutation.target_id,
                            edge_id=edge_id,
                            attributes=attributes,
                        )
        self._run_with_retry(operation)


class GraphNodeAdapter:
    @staticmethod
    def character(
        node_id: str,
        canonical_name: str,
        description: str,
        aliases: list[str] | None = None,
        is_alive: bool = True,
    ) -> GraphNode:
        from app.domain.schema import CharacterNode

        return CharacterNode(
            node_id=node_id,
            canonical_name=canonical_name,
            aliases=aliases or [],
            description=description,
            is_alive=is_alive,
        )

    @staticmethod
    def epoch(node_id: str, canonical_name: str, order_index: int) -> GraphNode:
        from app.domain.schema import EpochNode

        return EpochNode(node_id=node_id, canonical_name=canonical_name, order_index=order_index)

    @staticmethod
    def location(node_id: str, canonical_name: str) -> GraphNode:
        from app.domain.schema import LocationNode

        return LocationNode(node_id=node_id, canonical_name=canonical_name)

    @staticmethod
    def event(node_id: str, canonical_name: str) -> GraphNode:
        from app.domain.schema import EventNode

        return EventNode(node_id=node_id, canonical_name=canonical_name)

    @staticmethod
    def generic(node_id: str, node_type: NodeType, properties: dict) -> GraphNode:
        if node_type == NodeType.ITEM:
            return ItemNode(
                node_id=node_id,
                canonical_name=properties.get("canonical_name", node_id),
                item_status=properties.get("item_status", "完好"),
                is_unique=properties.get("is_unique", False),
            )
        if node_type == NodeType.CONCEPT:
            return ConceptNode(
                node_id=node_id,
                canonical_name=properties.get("canonical_name", node_id),
            )
        return GraphNodeAdapter.location(node_id, properties.get("canonical_name", node_id))

    @staticmethod
    def from_mutation(mutation: NodeMutation) -> GraphNode:
        if mutation.node_type == NodeType.CHARACTER:
            return GraphNodeAdapter.character(
                mutation.node_id,
                mutation.properties.get("canonical_name", mutation.node_id),
                mutation.properties.get("description", ""),
                aliases=mutation.properties.get("aliases", []),
                is_alive=mutation.properties.get("is_alive", True),
            )
        if mutation.node_type == NodeType.PERSONA:
            return PersonaNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                description=mutation.properties.get("description", ""),
                aliases=mutation.properties.get("aliases", []),
                is_alive=mutation.properties.get("is_alive", True),
            )
        if mutation.node_type == NodeType.LOCATION:
            return LocationNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                aliases=mutation.properties.get("aliases", []),
                environmental_condition=mutation.properties.get("environmental_condition", "正常"),
                is_accessible=mutation.properties.get("is_accessible", True),
            )
        if mutation.node_type == NodeType.EPOCH:
            return EpochNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                aliases=mutation.properties.get("aliases", []),
                order_index=mutation.properties.get("order_index", 0),
            )
        if mutation.node_type == NodeType.EVENT:
            return EventNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                aliases=mutation.properties.get("aliases", []),
            )
        return GraphNodeAdapter.generic(mutation.node_id, mutation.node_type, mutation.properties)

    @staticmethod
    def from_neo4j_node(node: object) -> GraphNode:
        props = dict(node)
        node_type = NodeType(props["node_type"])
        base = {
            "node_id": props["node_id"],
            "canonical_name": props.get("canonical_name", props["node_id"]),
            "aliases": props.get("aliases", []),
        }
        if node_type == NodeType.CHARACTER:
            return CharacterNode(node_type=node_type, description=props.get("description", ""), is_alive=props.get("is_alive", True), **base)
        if node_type == NodeType.PERSONA:
            return PersonaNode(node_type=node_type, description=props.get("description", ""), is_alive=props.get("is_alive", True), **base)
        if node_type == NodeType.LOCATION:
            return LocationNode(
                node_type=node_type,
                environmental_condition=props.get("environmental_condition", "正常"),
                is_accessible=props.get("is_accessible", True),
                **base,
            )
        if node_type == NodeType.ITEM:
            return ItemNode(
                node_type=node_type,
                item_status=props.get("item_status", "完好"),
                is_unique=props.get("is_unique", False),
                **base,
            )
        if node_type == NodeType.EPOCH:
            return EpochNode(node_type=node_type, order_index=props.get("order_index", 0), **base)
        if node_type == NodeType.EVENT:
            return EventNode(node_type=node_type, **base)
        return ConceptNode(node_type=node_type, **base)

    @staticmethod
    def edge_from_neo4j(rel: object) -> GraphEdge:
        props = dict(rel)
        return GraphEdge(
            edge_id=props["edge_id"],
            source_id=props["source_id"],
            relation_type=props["relation_type"],
            target_id=props["target_id"],
            valid_epoch=props["valid_epoch"],
            start_event_id=props["start_event_id"],
            end_event_id=props.get("end_event_id"),
            is_truth=props["is_truth"],
            is_public=props.get("is_public", False),
            known_by=props.get("known_by", []),
            holder=props.get("holder", []),
            context_details=props.get("context_details", ""),
        )


def _extract_query_terms(narrative_directive: str) -> list[str]:
    cleaned = narrative_directive.lower().replace("，", " ").replace("。", " ").replace(":", " ")
    terms = [token.strip() for token in cleaned.split() if len(token.strip()) >= 2]
    return terms[:8]


def _determine_hop_count(query_terms: list[str]) -> int:
    if len(query_terms) >= 4:
        return 3
    if len(query_terms) >= 2:
        return 2
    return 1


def _is_visible_to_pov(edge: GraphEdge, pov_character_id: str) -> bool:
    return edge.is_public or pov_character_id in edge.known_by or pov_character_id in edge.holder


def _is_active_edge(edge: GraphEdge) -> bool:
    if edge.relation_type == EdgeType.LOCATED_IN:
        return edge.end_event_id is None
    return True
