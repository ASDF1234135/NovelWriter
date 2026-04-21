from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from time import sleep
from typing import Any, Iterable, Protocol

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from app.domain.schema import (
    CharacterNode,
    ConceptNode,
    EdgeMutation,
    EdgeType,
    EnforcedRuleContext,
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
    RuleNode,
)

RESERVED_CHARACTER_NODE_IDS: frozenset[str] = frozenset({"char_public_observer"})


def _tags_from_storage(props: dict[str, Any]) -> list[str]:
    raw = props.get("tags")
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _metadata_dict_from_json_prop(props: dict[str, Any], key: str = "metadata_json") -> dict[str, Any]:
    raw = props.get(key)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _dump_metadata_json(metadata: dict[str, Any] | None) -> str:
    if not metadata:
        return ""
    try:
        return json.dumps(metadata, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def _prepare_neo4j_node_properties(node: GraphNode, story_id: str) -> dict[str, Any]:
    props = node.model_dump(mode="json")
    props["story_id"] = story_id
    meta = props.pop("metadata", None) or {}
    props["metadata_json"] = _dump_metadata_json(meta if isinstance(meta, dict) else {})
    return props


def _prepare_neo4j_rel_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    out = dict(attributes)
    meta = out.pop("metadata", None)
    out["metadata_json"] = _dump_metadata_json(meta if isinstance(meta, dict) else {})
    return out


def _tags_and_metadata_from_properties(properties: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    raw_tags = properties.get("tags")
    tags: list[str] = []
    if isinstance(raw_tags, list):
        tags = [str(x).strip() for x in raw_tags if str(x).strip()]
    raw_meta = properties.get("metadata")
    meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    return tags, meta


class GraphStore(Protocol):
    def seed_story(self, story_id: str) -> None:
        ...

    def remove_story(self, story_id: str) -> None:
        """Remove all graph data for this story (in-memory, Neo4j, etc.)."""
        ...

    def query_context(self, request: GraphQueryRequest) -> GraphSnapshot:
        ...

    def dump_story_graph(self, story_id: str) -> GraphSnapshot:
        """Return all nodes and edges for the story (no POV / epoch / epistemic filtering)."""
        ...

    def apply_mutations(self, story_id: str, mutations: Iterable[NodeMutation | EdgeMutation]) -> None:
        ...

    def clear_macro_cast_characters(self, story_id: str, include_node_ids: Iterable[str] = ()) -> None:
        """Remove macro cast CHARACTER nodes by story prefix and explicit node ids."""
        ...

    def replace_cast_characters(self, story_id: str, keep_cast_node_ids: Iterable[str] = ()) -> None:
        """Keep only reserved + current cast CHARACTER nodes for this story."""
        ...

    def list_enforced_rules_for_context(
        self,
        story_id: str,
        location_node_id: str,
        epoch_id: str,
        pov_character_id: str,
    ) -> list[EnforcedRuleContext]:
        """RULE nodes enforced at the given location and/or epoch, excluding POV exemptions."""
        ...


def collect_enforced_rules_for_context(
    nodes: dict[str, GraphNode],
    edges: dict[str, GraphEdge],
    *,
    location_node_id: str,
    epoch_id: str,
    pov_character_id: str,
) -> list[EnforcedRuleContext]:
    if not epoch_id:
        return []
    scope_ids: list[str] = [epoch_id]
    loc = (location_node_id or "").strip()
    if loc and loc not in scope_ids:
        scope_ids.append(loc)
    scope_set = set(scope_ids)

    candidate_rules: set[str] = set()
    for edge in edges.values():
        if edge.relation_type != EdgeType.ENFORCED_IN:
            continue
        if edge.valid_epoch != epoch_id:
            continue
        if edge.target_id not in scope_set:
            continue
        src_node = nodes.get(edge.source_id)
        if src_node is None or src_node.node_type != NodeType.RULE:
            continue
        candidate_rules.add(edge.source_id)

    out: list[EnforcedRuleContext] = []
    for rid in sorted(candidate_rules):
        rule_node = nodes.get(rid)
        if rule_node is None or rule_node.node_type != NodeType.RULE:
            continue
        is_active = getattr(rule_node, "is_active", True)
        if not is_active:
            continue
        exempt_ids = {
            e.target_id
            for e in edges.values()
            if e.source_id == rid and e.relation_type == EdgeType.EXEMPT_FROM
        }
        if pov_character_id and pov_character_id in exempt_ids:
            continue
        restrict_names: list[str] = []
        seen_r: set[str] = set()
        for e in edges.values():
            if e.source_id != rid or e.relation_type != EdgeType.RESTRICTS:
                continue
            tgt = nodes.get(e.target_id)
            if tgt is None:
                continue
            name = (tgt.canonical_name or "").strip()
            if name and name not in seen_r:
                seen_r.add(name)
                restrict_names.append(name)
        exempt_names: list[str] = []
        seen_e: set[str] = set()
        for e in edges.values():
            if e.source_id != rid or e.relation_type != EdgeType.EXEMPT_FROM:
                continue
            tgt = nodes.get(e.target_id)
            if tgt is None:
                continue
            name = (tgt.canonical_name or "").strip()
            if name and name not in seen_e:
                seen_e.add(name)
                exempt_names.append(name)
        desc = getattr(rule_node, "description", "") or ""
        penalty = getattr(rule_node, "penalty", None)
        if penalty is not None:
            penalty = str(penalty).strip() or None
        out.append(
            EnforcedRuleContext(
                rule_id=rid,
                canonical_name=rule_node.canonical_name or rid,
                description=desc,
                penalty=penalty,
                restrict_target_names=restrict_names,
                exempt_character_names=exempt_names,
            )
        )
    return out


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

    def dump_story_graph(self, story_id: str) -> GraphSnapshot:
        self.seed_story(story_id)
        nodes = list(self.story_nodes[story_id].values())
        edges = list(self.story_edges[story_id].values())
        return GraphSnapshot(nodes=nodes, edges=edges)

    def clear_macro_cast_characters(self, story_id: str, include_node_ids: Iterable[str] = ()) -> None:
        self.seed_story(story_id)
        prefix = f"{story_id}_mc_"
        extra_ids = {str(nid).strip() for nid in include_node_ids if str(nid).strip()}
        nodes = self.story_nodes[story_id]
        for nid in list(nodes.keys()):
            if nid.startswith(prefix) or nid in extra_ids:
                del nodes[nid]
        edges = self.story_edges[story_id]
        for eid in list(edges.keys()):
            edge = edges[eid]
            if (
                edge.source_id.startswith(prefix)
                or edge.target_id.startswith(prefix)
                or edge.source_id in extra_ids
                or edge.target_id in extra_ids
            ):
                del edges[eid]

    def replace_cast_characters(self, story_id: str, keep_cast_node_ids: Iterable[str] = ()) -> None:
        self.seed_story(story_id)
        keep_ids = {str(nid).strip() for nid in keep_cast_node_ids if str(nid).strip()}
        keep_ids.update(RESERVED_CHARACTER_NODE_IDS)
        nodes = self.story_nodes[story_id]
        removed_ids: set[str] = set()
        for nid in list(nodes.keys()):
            node = nodes[nid]
            if node.node_type != NodeType.CHARACTER:
                continue
            if nid in keep_ids:
                continue
            removed_ids.add(nid)
            del nodes[nid]
        if not removed_ids:
            return
        edges = self.story_edges[story_id]
        for eid in list(edges.keys()):
            edge = edges[eid]
            if edge.source_id in removed_ids or edge.target_id in removed_ids:
                del edges[eid]

    def remove_story(self, story_id: str) -> None:
        self.story_nodes.pop(story_id, None)
        self.story_edges.pop(story_id, None)

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
                    raw_meta = mutation.attributes.get("metadata")
                    edge_meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
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
                        tags=_tags_from_storage(mutation.attributes),
                        metadata=edge_meta,
                    )

    def list_enforced_rules_for_context(
        self,
        story_id: str,
        location_node_id: str,
        epoch_id: str,
        pov_character_id: str,
    ) -> list[EnforcedRuleContext]:
        self.seed_story(story_id)
        return collect_enforced_rules_for_context(
            self.story_nodes[story_id],
            self.story_edges[story_id],
            location_node_id=location_node_id,
            epoch_id=epoch_id,
            pov_character_id=pov_character_id,
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
                    props = _prepare_neo4j_node_properties(node, story_id)
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

    def clear_macro_cast_characters(self, story_id: str, include_node_ids: Iterable[str] = ()) -> None:
        prefix = f"{story_id}_mc_"
        extra_ids = [str(nid).strip() for nid in include_node_ids if str(nid).strip()]

        def operation() -> None:
            with self.driver.session(database=self.database) as session:
                session.run(
                    """
                    MATCH (n:StoryNode {story_id: $story_id})
                    WHERE n.node_id STARTS WITH $prefix
                       OR n.node_id IN $extra_ids
                    DETACH DELETE n
                    """,
                    story_id=story_id,
                    prefix=prefix,
                    extra_ids=extra_ids,
                )

        self._run_with_retry(operation)

    def replace_cast_characters(self, story_id: str, keep_cast_node_ids: Iterable[str] = ()) -> None:
        keep_ids = {str(nid).strip() for nid in keep_cast_node_ids if str(nid).strip()}
        keep_ids.update(RESERVED_CHARACTER_NODE_IDS)

        def operation() -> None:
            with self.driver.session(database=self.database) as session:
                session.run(
                    """
                    MATCH (n:StoryNode:CHARACTER {story_id: $story_id})
                    WHERE NOT n.node_id IN $keep_ids
                    DETACH DELETE n
                    """,
                    story_id=story_id,
                    keep_ids=sorted(keep_ids),
                )

        self._run_with_retry(operation)

    def query_context(self, request: GraphQueryRequest) -> GraphSnapshot:
        self.seed_story(request.story_id)
        result: GraphSnapshot | None = None
        query_terms = _extract_query_terms(request.narrative_directive)
        hop_count = _determine_hop_count(query_terms)
        path_hops = max(1, min(3, hop_count))
        tier_cap = {0: 1, 1: 2, 2: 3}.get(int(request.context_hop_tier), 3)
        path_hops = min(path_hops, tier_cap)
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

    def dump_story_graph(self, story_id: str) -> GraphSnapshot:
        self.seed_story(story_id)
        result: GraphSnapshot | None = None

        def operation() -> None:
            nonlocal result
            with self.driver.session(database=self.database) as session:
                node_row = session.run(
                    "MATCH (n:StoryNode {story_id: $story_id}) RETURN collect(DISTINCT n) AS nodes",
                    story_id=story_id,
                ).single()
                edge_row = session.run(
                    """
                    MATCH (a:StoryNode {story_id: $story_id})-[r]->(b:StoryNode {story_id: $story_id})
                    RETURN collect(DISTINCT r) AS rels
                    """,
                    story_id=story_id,
                ).single()
                raw_nodes = node_row["nodes"] if node_row else []
                raw_rels = edge_row["rels"] if edge_row else []
                nodes = [GraphNodeAdapter.from_neo4j_node(n) for n in raw_nodes]
                edges = [_graph_edge_from_neo4j_relationship(rel) for rel in raw_rels]
                result = GraphSnapshot(nodes=nodes, edges=edges)

        self._run_with_retry(operation)
        return result or GraphSnapshot(nodes=[], edges=[])

    def remove_story(self, story_id: str) -> None:
        def operation() -> None:
            with self.driver.session(database=self.database) as session:
                session.run(
                    "MATCH (n:StoryNode {story_id: $story_id}) DETACH DELETE n",
                    story_id=story_id,
                )

        self._run_with_retry(operation)

    def apply_mutations(self, story_id: str, mutations: Iterable[NodeMutation | EdgeMutation]) -> None:
        self.seed_story(story_id)
        def operation() -> None:
            with self.driver.session(database=self.database) as session:
                for mutation in mutations:
                    if isinstance(mutation, NodeMutation):
                        node = GraphNodeAdapter.from_mutation(mutation)
                        label = node.node_type.value
                        props = _prepare_neo4j_node_properties(node, story_id)
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
                        attributes = _prepare_neo4j_rel_attributes(attributes)
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

    def list_enforced_rules_for_context(
        self,
        story_id: str,
        location_node_id: str,
        epoch_id: str,
        pov_character_id: str,
    ) -> list[EnforcedRuleContext]:
        if not epoch_id:
            return []
        scope_ids: list[str] = [epoch_id]
        loc = (location_node_id or "").strip()
        if loc and loc not in scope_ids:
            scope_ids.append(loc)
        rows: list[dict] = []

        def operation() -> None:
            nonlocal rows
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    """
                    MATCH (r:StoryNode:RULE {story_id: $story_id})
                    WHERE coalesce(r.is_active, true) = true
                    MATCH (r)-[e:ENFORCED_IN]->(t:StoryNode {story_id: $story_id})
                    WHERE e.story_id = $story_id AND e.valid_epoch = $epoch_id AND t.node_id IN $scope_ids
                    WITH DISTINCT r
                    OPTIONAL MATCH (r)-[ex:EXEMPT_FROM {story_id: $story_id}]->(xc:StoryNode {story_id: $story_id})
                    WITH r, collect(DISTINCT xc.node_id) AS exempt_ids
                    WHERE $pov_id = "" OR NOT $pov_id IN exempt_ids
                    OPTIONAL MATCH (r)-[rs:RESTRICTS {story_id: $story_id}]->(rt:StoryNode {story_id: $story_id})
                    OPTIONAL MATCH (r)-[ex2:EXEMPT_FROM {story_id: $story_id}]->(xc2:StoryNode {story_id: $story_id})
                    RETURN r.node_id AS rule_id,
                           r.canonical_name AS canonical_name,
                           coalesce(r.description, "") AS description,
                           r.penalty AS penalty,
                           collect(DISTINCT rt.canonical_name) AS restrict_names,
                           collect(DISTINCT xc2.canonical_name) AS exempt_names
                    """,
                    story_id=story_id,
                    epoch_id=epoch_id,
                    scope_ids=scope_ids,
                    pov_id=pov_character_id or "",
                )
                rows = [dict(record) for record in result]

        self._run_with_retry(operation)

        def _clean_names(raw: object) -> list[str]:
            if not isinstance(raw, list):
                return []
            out_names: list[str] = []
            seen: set[str] = set()
            for x in raw:
                if x is None:
                    continue
                s = str(x).strip()
                if s and s not in seen:
                    seen.add(s)
                    out_names.append(s)
            return out_names

        out: list[EnforcedRuleContext] = []
        for row in rows:
            rid = str(row.get("rule_id") or "").strip()
            if not rid:
                continue
            pen = row.get("penalty")
            if pen is not None:
                pen = str(pen).strip() or None
            out.append(
                EnforcedRuleContext(
                    rule_id=rid,
                    canonical_name=str(row.get("canonical_name") or rid).strip() or rid,
                    description=str(row.get("description") or "").strip(),
                    penalty=pen,
                    restrict_target_names=_clean_names(row.get("restrict_names")),
                    exempt_character_names=_clean_names(row.get("exempt_names")),
                )
            )
        out.sort(key=lambda x: x.rule_id)
        return out


class GraphNodeAdapter:
    @staticmethod
    def character(
        node_id: str,
        canonical_name: str,
        description: str,
        aliases: list[str] | None = None,
        is_alive: bool = True,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GraphNode:
        from app.domain.schema import CharacterNode

        return CharacterNode(
            node_id=node_id,
            canonical_name=canonical_name,
            aliases=aliases or [],
            description=description,
            is_alive=is_alive,
            tags=tags or [],
            metadata=metadata or {},
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
        tags, meta = _tags_and_metadata_from_properties(properties)
        if node_type == NodeType.ITEM:
            return ItemNode(
                node_id=node_id,
                canonical_name=properties.get("canonical_name", node_id),
                item_status=properties.get("item_status", "完好"),
                is_unique=properties.get("is_unique", False),
                tags=tags,
                metadata=meta,
            )
        if node_type == NodeType.CONCEPT:
            return ConceptNode(
                node_id=node_id,
                canonical_name=properties.get("canonical_name", node_id),
                aliases=properties.get("aliases", []) or [],
                tags=tags,
                metadata=meta,
            )
        if node_type == NodeType.RULE:
            pen = properties.get("penalty")
            if pen is not None:
                pen = str(pen).strip() or None
            return RuleNode(
                node_id=node_id,
                canonical_name=properties.get("canonical_name", node_id),
                aliases=properties.get("aliases", []) or [],
                description=str(properties.get("description", "") or ""),
                penalty=pen,
                is_active=bool(properties.get("is_active", True)),
                tags=tags,
                metadata=meta,
            )
        return GraphNodeAdapter.location(node_id, properties.get("canonical_name", node_id))

    @staticmethod
    def from_mutation(mutation: NodeMutation) -> GraphNode:
        tags, meta = _tags_and_metadata_from_properties(mutation.properties)
        if mutation.node_type == NodeType.CHARACTER:
            return GraphNodeAdapter.character(
                mutation.node_id,
                mutation.properties.get("canonical_name", mutation.node_id),
                mutation.properties.get("description", ""),
                aliases=mutation.properties.get("aliases", []),
                is_alive=mutation.properties.get("is_alive", True),
                tags=tags,
                metadata=meta,
            )
        if mutation.node_type == NodeType.PERSONA:
            return PersonaNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                description=mutation.properties.get("description", ""),
                aliases=mutation.properties.get("aliases", []),
                is_alive=mutation.properties.get("is_alive", True),
                tags=tags,
                metadata=meta,
            )
        if mutation.node_type == NodeType.LOCATION:
            return LocationNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                aliases=mutation.properties.get("aliases", []),
                environmental_condition=mutation.properties.get("environmental_condition", "正常"),
                is_accessible=mutation.properties.get("is_accessible", True),
                tags=tags,
                metadata=meta,
            )
        if mutation.node_type == NodeType.EPOCH:
            return EpochNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                aliases=mutation.properties.get("aliases", []),
                order_index=mutation.properties.get("order_index", 0),
                tags=tags,
                metadata=meta,
            )
        if mutation.node_type == NodeType.EVENT:
            return EventNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                aliases=mutation.properties.get("aliases", []),
                tags=tags,
                metadata=meta,
            )
        if mutation.node_type == NodeType.RULE:
            pen = mutation.properties.get("penalty")
            if pen is not None:
                pen = str(pen).strip() or None
            return RuleNode(
                node_id=mutation.node_id,
                canonical_name=mutation.properties.get("canonical_name", mutation.node_id),
                aliases=mutation.properties.get("aliases", []),
                description=str(mutation.properties.get("description", "") or ""),
                penalty=pen,
                is_active=bool(mutation.properties.get("is_active", True)),
                tags=tags,
                metadata=meta,
            )
        return GraphNodeAdapter.generic(mutation.node_id, mutation.node_type, mutation.properties)

    @staticmethod
    def from_neo4j_node(node: object) -> GraphNode:
        props = dict(node)
        node_type = NodeType(props["node_type"])
        base = {
            "node_id": props["node_id"],
            "canonical_name": props.get("canonical_name", props["node_id"]),
            "aliases": list(props.get("aliases", []) or []),
            "tags": _tags_from_storage(props),
            "metadata": _metadata_dict_from_json_prop(props),
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
        if node_type == NodeType.RULE:
            pen = props.get("penalty")
            if pen is not None:
                pen = str(pen).strip() or None
            return RuleNode(
                node_type=node_type,
                description=str(props.get("description", "") or ""),
                penalty=pen,
                is_active=bool(props.get("is_active", True)),
                **base,
            )
        return ConceptNode(node_type=node_type, **base)

    @staticmethod
    def edge_from_neo4j(rel: object) -> GraphEdge:
        return _graph_edge_from_neo4j_relationship(rel)


def _graph_edge_from_neo4j_relationship(rel: object) -> GraphEdge:
    """Build GraphEdge from a Neo4j relationship; tolerates missing optional props."""
    props = dict(rel)
    rel_type_raw = props.get("relation_type") or getattr(rel, "type", None)
    if rel_type_raw is None:
        rel_type_raw = "LOCATED_IN"
    relation_type = EdgeType(rel_type_raw) if isinstance(rel_type_raw, str) else rel_type_raw
    source_id = props.get("source_id", "")
    target_id = props.get("target_id", "")
    edge_id = props.get("edge_id") or f"{source_id}:{relation_type.value}:{target_id}"
    return GraphEdge(
        edge_id=edge_id,
        source_id=source_id,
        relation_type=relation_type,
        target_id=target_id,
        valid_epoch=props.get("valid_epoch", ""),
        start_event_id=props.get("start_event_id", ""),
        end_event_id=props.get("end_event_id"),
        is_truth=bool(props.get("is_truth", True)),
        is_public=bool(props.get("is_public", False)),
        known_by=list(props.get("known_by", []) or []),
        holder=list(props.get("holder", []) or []),
        context_details=str(props.get("context_details", "") or ""),
        tags=_tags_from_storage(props),
        metadata=_metadata_dict_from_json_prop(props),
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
