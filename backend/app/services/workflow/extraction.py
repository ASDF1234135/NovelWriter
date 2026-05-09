from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.schema import (
    ChapterExtractionOutput,
    ChapterMemory,
    ChapterMemoryExtractionOutput,
    EntityExtractionOutput,
    EventOutline,
    EventLinkType,
    ExtractedEntity,
    ExtractedEntityCandidate,
    ExtractedRelation,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    NodeType,
    EdgeType,
    RelationExtractionOutput,
)
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.event_normalization import is_standard_event_id
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile
from app.services.workflow.relation_direction_rules import relation_direction_is_valid

logger = get_logger(__name__)

# Max chars for EVENT human-readable labels in graph mutations and fallback relations (replaces harsh :40 cuts).
EVENT_DESCRIPTION_DISPLAY_MAX = 500


def clip_event_description_for_storage(text: str, max_len: int = EVENT_DESCRIPTION_DISPLAY_MAX) -> str:
    """Trim long planner/event descriptions for storage while keeping full sentences when possible."""
    d = (text or "").strip()
    if not d:
        return ""
    if len(d) <= max_len:
        return d
    return d[: max_len - 1] + "…"


# Shared guideline strings (relation step + legacy test prompt)
RELATION_EXTRACTION_GUIDELINES: list[str] = [
    "Extract only entities and relations explicitly present in or directly confirmable from the chapter text.",
    "relation_type must use only existing enum values.",
    "If direction or semantics are uncertain, omit the relation. Allowed relation_type tokens and usage:\n",
    "LOCATED_IN: a character, persona, item, or event is at a location; direction must be CHARACTER/PERSONA/ITEM/EVENT -> LOCATION.",
    "HAS_ITEM: a character, persona, or location holds/stores an item; direction must be CHARACTER/PERSONA/LOCATION -> ITEM.",
    "HAS_RELATION: general association; if used, source and target must be stable non-EVENT, non-EPOCH nodes, and context_details must explain the relation.",
    "PARTICIPATED_IN: a character or persona participates in an event; direction must be CHARACTER/PERSONA -> EVENT.",
    "IS_ACTUALLY: surface/disguise maps to underlying true identity; direction must be PERSONA -> CHARACTER, never reversed.",
    "HAS_ATTRIBUTE: a node has an observable attribute concept; direction should be CHARACTER/PERSONA/ITEM/LOCATION/EVENT -> CONCEPT; target must be an attribute/state concept, not a character/location posing as an attribute.",
    "BELIEVED_AS: only mistaken identity / misread-as-label-or-persona-mask; target should prefer CONCEPT or PERSONA (wrong label); context_details must spell out the misbelief.",
    "KNOWS_ABOUT: a character/persona knows another node; direction must be CHARACTER/PERSONA -> ANY_NODE. KNOWS_ABOUT only for major secrets, intel, hidden identities, or rules—not casual chat, seeing, or acquaintance.",
    "BELONGS_TO_EPOCH: an event belongs to an era; direction must be EVENT -> EPOCH.",
    "HAPPENED_BEFORE: one event/state is earlier than another; direction should be EVENT/CONCEPT -> EVENT/CONCEPT with source earlier and target later.",
    "CAUSED: causality; direction must be EVENT -> EVENT with source cause and target effect.",
    "ENFORCED_IN: where a rule applies; direction must be RULE -> LOCATION or RULE -> EPOCH, consistent with narrative valid_epoch (system-filled).",
    "RESTRICTS: what a rule constrains; direction must be RULE -> CHARACTER / PERSONA / ITEM / CONCEPT.",
    "EXEMPT_FROM: characters exempt from a rule; direction must be RULE -> CHARACTER or RULE -> PERSONA (exemption list).\n\n",
    "Notes:"
    "Truth vs publicity: is_truth and is_public are different axes—true does not imply public.",
    "BELIEVED_AS discipline: do not label trust, dependency, enmity, or emotion as BELIEVED_AS—use HAS_RELATION with context_details. For disguise/doubles with both sides named, prefer IS_ACTUALLY (PERSONA→CHARACTER) or a CONCEPT for the wrong label; avoid ambiguous CHARACTER→CHARACTER BELIEVED_AS.",
    "Causality: use CAUSED only when A is a direct physical/logical prerequisite for B (e.g., switch flip CAUSED explosion). For mere temporal order, never use CAUSED—use HAPPENED_BEFORE or omit.",
    "Planner typed-link policy: between ground_truth_events, obey provided links strictly (CAUSAL vs TEMPORAL). If relation involves AI-invented event/entity, you may extract a new structurally valid relation.",
    "HAS_ITEM filter: no HAS_ITEM for mundane consumables or meaningless background props.",
    "Public facts: is_public=true only for objectively observable public interaction, possession, or position.",
    "Secret moves, solo clues, surveillance, private knowledge, inner misbelief, or covert travel must use is_public=false.",
    "If only one POV or few participants could know it, default is_public=false—do not mark public just because it is true.",
    "Movement: if the text clearly moves a character to a new place, emit a new LOCATION if needed and a new LOCATED_IN relation.",
    "Rhetoric filter: ignore metaphor/personification/hyperbole/symbolism; extract only literal verifiable facts and character-true beliefs.",
    "If a sentence uses simile triggers, unless the same paragraph has a verifiable factual anchor, omit that relation.",
    "IDs: endpoints must use node_id from canonical_entities or event_id from ground_truth_events.",
    "tags: optional short labels (e.g. secret, combat); never invent a new relation_type string.",
    "metadata: optional JSON-compatible key-values; longer narrative belongs in context_details.",
    "Chunk evidence: put supporting chunk ids into metadata.evidence_chunk_ids (array of chunk_id strings).",
]

PHASE1_RELATION_GUIDELINES: list[str] = [
    "PHASE 1 (entity/event relations): Focus on relations between characters/personas/items/locations/concepts and events.",
    "Prefer: PARTICIPATED_IN, HAS_ITEM, LOCATED_IN, KNOWS_ABOUT, BELIEVED_AS, HAS_RELATION, HAS_ATTRIBUTE.",
    "Epoch binding (phase 1 only): for every EVENT node listed in canonical_entities that you treat as substantiated in this chapter, "
    "emit BELONGS_TO_EPOCH from that EVENT node_id to active_epoch_id (exact id). Do not defer BELONGS_TO_EPOCH to phase 2.",
    "Avoid emitting event↔event order/causal links unless they are necessary to support a retained plot-driving relation.",
    "Prev-tail policy: if evidence comes from a chunk with source_role=prev_tail, prefer creating only edges that LINK to existing graph events; do not invent new events.",
]

PHASE2_RELATION_GUIDELINES: list[str] = [
    "PHASE 2 (event links only): Extract ONLY event↔event links: HAPPENED_BEFORE and CAUSED.",
    "Each link must have direct textual support in the provided chunks; include metadata.evidence_chunk_ids.",
    "Prev-tail policy: if evidence comes from a chunk with source_role=prev_tail, try to LINK current chapter events to prior existing events, not create new events.",
]

ENTITY_EXTRACTION_GUIDELINES: list[str] = [
    "Extract only entities directly supported by the chapter text—no guessing.",
    "If a name/alias matches existing_node_candidates, set suggested_node_id to that node_id; otherwise leave suggested_node_id empty.",
    "Do not invent node_id values; the system assigns final ids.",
    "canonical_name must be short (within ~10 graphemes) for CHARACTER/LOCATION/ITEM/RULE/PERSONA; put longer prose in summary/metadata.",
    "ground_truth_events lists expected beats. However, characters often take unexpected actions in the prose. You MUST extract ANY objectively verifiable plot-driving event (combat, discoveries, rule-breaking) present in the text, EVEN IF it is not listed in ground_truth_events.",
    "When matching an extracted event to a ground_truth_events beat, rely on semantic meaning, not exact wording. If the text says 'two shadows leaped out', it matches the beat 'assassin attack'. Map it to the corresponding suggested_node_id.",
    "When you extract an EVENT as a graph candidate, use a short intentional title for canonical_name and put the full beat meaning in summary—do not copy arbitrary mid-sentence fragments as the title.",
    "If an existing_node_candidates row matches a ground_truth_events.event_id, set suggested_node_id to that node_id.",
    "Zero-noise rule: do not extract background decor, mundane consumables (cans, cigarettes), ambient traces (bloody fingerprints), or abstract narrative viewpoints ('the observer'). Only plot-driving entities with special function or repeated use.",
    "CONCEPT is only for worldbuilding terms, factions, institutions, or sci-fi/fantasy laws.",
    "RULE extraction: laws/game rules/area restrictions/system protocols with must/forbid/if/then/penalty must become RULE; pure glossaries, power-system names, or faction labels stay CONCEPT.",
    "Each RULE needs at least one ENFORCED_IN edge to a LOCATION identifiable in text; if none, link to loc_unknown and explain briefly in that edge's context_details.",
    "RULE.description holds the full rule text; penalty is the cost of violation (may be empty); is_active defaults true.",
    "Do not extract generic emotion, body parts, transient discomfort, adjectives, or literary images as CONCEPT.",
    "If no CONCEPT qualifies, leave the slot empty—do not force one.",
    "Prefer aligning to existing_node_candidates; create a new candidate only when clearly absent from the dictionary.",
    "If the prose uses descriptive epithets ('the dark-haired youth'), map to an existing character node_id when possible and put the epithet in aliases.",
    "Strict schema: never invent a new node_type string; subtype with tags (e.g. ITEM + tags [\"weapon\",\"illegal\"]).",
    "metadata: optional numeric/structured detail (bullet_count, temperature); must be JSON-serializable; long prose goes in summary or other allowed fields.",
    "If classification is unstable across CHARACTER/LOCATION/ITEM/EPOCH/EVENT/RULE, use CONCEPT and disambiguate with tags/metadata.",
]

MEMORY_EXTRACTION_GUIDELINES: list[str] = [
    "chapter_memory.summary must be a safe surface summary—no ground-truth leaks or planner private_facts.",
    "latest_location is a reader-understandable place description; no node_id required.",
    "If multiple scenes, capture the main characters' effective end position; leave latest_location blank if unclear.",
    "ending_vibe must be one of ACTION_CLIFFHANGER / SAFE_ROOM_EXPOSITION / ON_THE_MOVE / DEVASTATING_LOSS.",
]


@dataclass
class ExtractionContext:
    state: dict
    graph_snapshot: GraphSnapshot
    chapter_content_full: str
    events: list[EventOutline]
    candidate_nodes: list[GraphNode]
    graph_summary_json: str
    chapter_text_for_entities: str
    chapter_text_for_memory: str
    chapter_text_for_relations: str
    planner_visibility_contract: dict
    chapter_chunks_for_prompt: list[dict[str, Any]] = field(default_factory=list)
    author_surface_hints: list[dict[str, Any]] = field(default_factory=list)
    settings_snapshot: dict = field(default_factory=dict)
    entity_glossary: list[dict[str, Any]] = field(default_factory=list)


def build_extraction_context(
    state: dict,
    graph_snapshot: GraphSnapshot,
    chapter_content: str,
    events: list[EventOutline],
) -> ExtractionContext:
    settings = get_settings()
    full = chapter_content or ""
    cap_nodes = settings.extraction_candidate_nodes_cap
    candidates = _select_candidate_nodes(graph_snapshot.nodes, full, events, state, cap_nodes)
    glossary = _build_entity_glossary(candidates, state, settings.extraction_entity_glossary_cap)
    summary = _build_graph_summary(graph_snapshot, {n.node_id for n in candidates}, settings.extraction_graph_summary_max_chars)
    ent_text = _chapter_text_for_entities(full, settings.extraction_entity_text_budget)
    mem_text = _chapter_text_for_memory(full, settings.extraction_memory_full_text_budget)
    rel_text = _chapter_text_for_relations(full, events, ent_text, settings.extraction_relation_text_budget)
    raw_chunks = state.get("chapter_chunks") or []
    chunk_rows: list[dict[str, Any]] = []
    if isinstance(raw_chunks, list):
        for raw in raw_chunks:
            if not isinstance(raw, dict):
                continue
            cid = str(raw.get("chunk_id") or "").strip()
            txt = str(raw.get("text_chunk") or "")
            role = str(raw.get("source_role") or "").strip()
            if not cid or not txt.strip():
                continue
            chunk_rows.append(
                {
                    "chunk_id": cid,
                    "chunk_index": int(raw.get("chunk_index") or 0),
                    "source_role": role,
                    "source_chapter_id": int(raw.get("source_chapter_id") or state.get("chapter_id") or 0),
                    "text_chunk": txt[:1600],
                }
            )
    contract = {
        "reader_visible_facts": state.get("reader_visible_facts", []),
        "private_facts_or_secret_actions": state.get("private_facts_or_secret_actions", []),
        "reader_unresolved_questions": state.get("reader_unresolved_questions", []),
        "chapter_end_location_hint": state.get("chapter_end_location_hint", ""),
        "last_known_location": state.get("last_known_location", ""),
    }
    hints_raw = state.get("author_extraction_surface_hints") or []
    author_hints = [h for h in hints_raw if isinstance(h, dict)]
    return ExtractionContext(
        state=state,
        graph_snapshot=graph_snapshot,
        chapter_content_full=full,
        events=events,
        candidate_nodes=candidates,
        graph_summary_json=summary,
        chapter_text_for_entities=ent_text,
        chapter_text_for_memory=mem_text,
        chapter_text_for_relations=rel_text,
        chapter_chunks_for_prompt=chunk_rows[:24],
        planner_visibility_contract=contract,
        author_surface_hints=author_hints[:80],
        settings_snapshot={
            "entity_budget": settings.extraction_entity_text_budget,
            "memory_budget": settings.extraction_memory_full_text_budget,
            "relation_budget": settings.extraction_relation_text_budget,
            "relation_entity_batch_size": settings.extraction_relation_entity_batch_size,
            "entity_glossary_cap": settings.extraction_entity_glossary_cap,
            "entity_glossary_count": len(glossary),
        },
        entity_glossary=glossary,
    )


def _select_candidate_nodes(
    nodes: list[GraphNode],
    chapter_content: str,
    events: list[EventOutline],
    state: dict,
    cap: int,
) -> list[GraphNode]:
    normalized = _normalize_text(chapter_content).lower()
    event_blob = " ".join(e.description for e in events).lower()
    beats = " ".join(str(x) for x in state.get("must_include_beats", [])).lower()
    facts = " ".join(str(x) for x in state.get("reader_visible_facts", [])).lower()
    recent_names = " ".join(str(x) for x in state.get("recent_entity_names", [])).lower()

    def score_node(node: GraphNode) -> int:
        s = 0
        names = [node.canonical_name, *list(getattr(node, "aliases", []) or [])]
        for name in names:
            if not name:
                continue
            n = str(name).lower()
            if n and n in normalized:
                s += 5
            if n and n in event_blob:
                s += 4
            if n and n in beats:
                s += 3
            if n and n in facts:
                s += 2
            if n and n in recent_names:
                s += 3
        if node.node_id in (state.get("pov_character_id"), state.get("active_epoch_id")):
            s += 6
        return s

    scored = sorted(((score_node(n), n) for n in nodes), key=lambda x: (-x[0], x[1].node_id))
    picked: list[GraphNode] = []
    seen: set[str] = set()
    for sc, node in scored:
        if node.node_id in seen:
            continue
        if sc > 0 or len(picked) < min(12, cap):
            picked.append(node)
            seen.add(node.node_id)
        if len(picked) >= cap:
            break
    for node in nodes:
        if node.node_id == state.get("pov_character_id") and node.node_id not in seen:
            picked.append(node)
            seen.add(node.node_id)
        if node.node_id == state.get("active_epoch_id") and node.node_id not in seen:
            picked.append(node)
            seen.add(node.node_id)
    return picked[:cap]


def _build_graph_summary(snapshot: GraphSnapshot, candidate_ids: set[str], max_chars: int) -> str:
    cand_edges: list[GraphEdge] = [
        e
        for e in snapshot.edges
        if e.source_id in candidate_ids or e.target_id in candidate_ids
    ][:24]
    payload = {
        "node_count": len(snapshot.nodes),
        "edge_count": len(snapshot.edges),
        "sample_edges": [
            {
                "source_id": e.source_id,
                "relation_type": e.relation_type.value if hasattr(e.relation_type, "value") else str(e.relation_type),
                "target_id": e.target_id,
            }
            for e in cand_edges
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False)
    return raw if len(raw) <= max_chars else raw[: max_chars - 3] + "..."


def _build_entity_glossary(candidates: list[GraphNode], state: dict, cap: int) -> list[dict[str, Any]]:
    if cap <= 0:
        return []
    recent = {str(x).strip().casefold() for x in (state.get("recent_entity_names") or []) if str(x).strip()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in candidates:
        if node.node_id in seen:
            continue
        seen.add(node.node_id)
        aliases = list(getattr(node, "aliases", []) or [])
        out.append(
            {
                "node_id": node.node_id,
                "node_type": str(node.node_type),
                "canonical_name": node.canonical_name,
                "aliases": aliases[:8],
                "recent_chapters_seen": 1 if node.canonical_name.casefold() in recent else 0,
            }
        )
        if len(out) >= cap:
            break
    return out


def _chapter_text_for_entities(full: str, budget: int) -> str:
    if len(full) <= budget:
        return full
    head = full[: min(2500, len(full) // 3)]
    tail = full[-min(2500, len(full) // 3) :]
    mid_budget = max(0, budget - len(head) - len(tail) - 40)
    mid = _highest_signal_middle_window(full, mid_budget)
    parts = [p for p in (head.strip(), mid.strip(), tail.strip()) if p]
    return "\n\n---\n\n".join(parts)


def _chapter_text_for_memory(full: str, budget: int) -> str:
    if len(full) <= budget:
        return full
    n = len(full)
    head_end = max(1, int(n * 0.25))
    tail_start = max(0, int(n * 0.65))
    head = full[:head_end]
    tail = full[tail_start:]
    mid_budget = max(0, budget - len(head) - len(tail) - 80)
    mid = _paragraph_sample_middle(full, mid_budget)
    return (
        "[Excerpt below—keep summaries conservative; do not infer unseen content.]\n\n"
        + head
        + "\n\n---\n\n"
        + mid
        + "\n\n---\n\n"
        + tail
    )


def _chapter_text_for_relations(full: str, events: list[EventOutline], fallback_excerpt: str, budget: int) -> str:
    chunks: list[str] = []
    for ev in events:
        desc = (ev.description or "").strip()
        if len(desc) < 8:
            continue
        key = desc[:40]
        idx = full.find(key)
        if idx < 0:
            idx = full.find(desc[:20])
        if idx < 0 and len(desc) > 40:
            idx = full.find(desc[: min(120, len(desc))])
        if idx >= 0:
            start = max(0, idx - 800)
            end = min(len(full), idx + len(desc) + 800)
            chunks.append(full[start:end])
    merged = "\n\n---\n\n".join(_dedupe(chunks))
    if len(merged) < 400:
        merged = fallback_excerpt
    if len(merged) > budget:
        merged = merged[: budget - 3] + "..."
    return merged


def _highest_signal_middle_window(full: str, budget: int) -> str:
    if budget <= 0 or not full:
        return ""
    paras = [p.strip() for p in full.split("\n\n") if p.strip()]
    if not paras:
        return full[len(full) // 3 : len(full) // 3 + budget]
    scored: list[tuple[int, str]] = []
    for p in paras:
        score = sum(1 for m in re.finditer(r"\b[A-Z][a-zA-Z]{2,}\b", p))
        score += len(re.findall(r"[「『\"]", p))
        score += sum(
            1
            for kw in (
                "王都",
                "城門",
                "巷",
                "宮",
                "門",
                "街",
                "屋",
                "站",
                "capital",
                "harbor",
                "manor",
                "gate",
                "street",
            )
            if kw in p
        )
        scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    picked: list[str] = []
    used = 0
    for _, p in scored[:3]:
        if used + len(p) > budget:
            break
        picked.append(p)
        used += len(p) + 4
    text = "\n\n".join(picked)
    return text[:budget]


def _paragraph_sample_middle(full: str, budget: int) -> str:
    if budget <= 0:
        return ""
    paras = [p.strip() for p in full.split("\n\n") if p.strip()]
    if not paras:
        return full[len(full) // 4 : len(full) // 4 + budget][:budget]
    step = max(1, len(paras) // 6)
    sample = paras[step : step * 5 : step]
    text = "\n\n".join(sample)
    return text[:budget]


def _merge_tag_lists(a: list[str], b: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in list(a) + list(b):
        s = str(t).strip()
        if not s:
            continue
        k = s.casefold()
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def canonicalize_entity_candidates(
    candidates: list[ExtractedEntityCandidate],
    graph_snapshot: GraphSnapshot,
    *,
    trusted_extrinsic_ids: set[str] | None = None,
) -> tuple[list[ExtractedEntity], dict[str, str]]:
    existing_by_id = {n.node_id: n for n in graph_snapshot.nodes}
    name_index: dict[str, GraphNode] = {}
    for node in graph_snapshot.nodes:
        name_index[node.canonical_name.casefold()] = node
        for alias in getattr(node, "aliases", []) or []:
            name_index[str(alias).casefold()] = node

    resolved_name_to_id: dict[str, str] = {}
    entities: list[ExtractedEntity] = []
    seen_ids_map: dict[str, ExtractedEntity] = {}
    trusted_ids = trusted_extrinsic_ids or set()

    for c in candidates:
        cname = (c.canonical_name or "").strip()
        if not cname:
            continue
        existing: GraphNode | None = None
        if c.suggested_node_id and c.suggested_node_id in existing_by_id:
            existing = existing_by_id[c.suggested_node_id]
        elif cname.casefold() in name_index:
            existing = name_index[cname.casefold()]
        else:
            for al in c.aliases:
                if al.casefold() in name_index:
                    existing = name_index[al.casefold()]
                    break

        if existing is not None:
            node_id = existing.node_id
            nt = existing.node_type
            display_name = existing.canonical_name
            base_aliases = list(getattr(existing, "aliases", []) or [])
        else:
            sug = (c.suggested_node_id or "").strip()
            if sug and sug not in seen_ids_map and sug in trusted_ids:
                node_id = sug
                nt = c.node_type
                display_name = cname
                base_aliases = list(c.aliases)
            else:
                node_id = stable_entity_id(c.node_type, cname)
                nt = c.node_type
                display_name = cname
                base_aliases = []

        merged_aliases = _dedupe(list(base_aliases) + list(c.aliases))
        ent = ExtractedEntity(
            node_id=node_id,
            node_type=nt,
            canonical_name=display_name,
            aliases=merged_aliases,
            summary=c.summary or f"Mentioned in chapter: {display_name}.",
            properties=dict(c.properties),
            tags=list(c.tags),
            metadata=dict(c.metadata),
        )
        if node_id in seen_ids_map:
            prev = seen_ids_map[node_id]
            prev.aliases = _dedupe(list(prev.aliases) + list(ent.aliases))
            if not prev.summary and ent.summary:
                prev.summary = ent.summary
            prev.properties = {**ent.properties, **prev.properties}
            prev.tags = _merge_tag_lists(prev.tags, ent.tags)
            prev.metadata = {**ent.metadata, **prev.metadata}
        else:
            seen_ids_map[node_id] = ent
            entities.append(ent)

        resolved_name_to_id[cname.casefold()] = node_id
        for al in merged_aliases:
            resolved_name_to_id[al.casefold()] = node_id
        resolved_name_to_id[display_name.casefold()] = node_id

    return entities, resolved_name_to_id


def _align_chapter_memory(
    mem: ChapterMemoryExtractionOutput,
    entities: list[ExtractedEntity],
    resolved_name_index: dict[str, str],
) -> ChapterMemory:
    by_id = {e.node_id: e for e in entities}

    def canon_display(s: str) -> str:
        raw = (s or "").strip()
        if not raw:
            return raw
        nid = resolved_name_index.get(raw.casefold())
        if nid and nid in by_id:
            return by_id[nid].canonical_name
        return raw

    notable = [canon_display(x) for x in mem.notable_entities if str(x).strip()]
    latest = (mem.latest_location or "").strip()
    if latest:
        nid = resolved_name_index.get(latest.casefold())
        if nid and nid in by_id and by_id[nid].node_type == NodeType.LOCATION:
            latest = by_id[nid].canonical_name

    return ChapterMemory(
        summary=(mem.summary or "")[:2000],
        unresolved_threads=[t[:500] for t in (mem.unresolved_threads or [])][:12],
        notable_entities=_dedupe(notable)[:20],
        latest_location=latest[:500],
        ending_vibe=mem.ending_vibe,
    )


def _resolve_relation_endpoint(
    node_id: str,
    name: str,
    resolved_name_index: dict[str, str],
    event_ids: set[str],
    entity_ids: set[str],
    existing_ids: set[str],
) -> str:
    nid = (node_id or "").strip()
    if nid and (nid in existing_ids or nid in entity_ids or nid in event_ids):
        return nid
    nm = (name or "").strip()
    if nm:
        return resolved_name_index.get(nm.casefold(), "")
    return ""


def _validation_gate(
    output: ChapterExtractionOutput,
    state: dict,
    graph_snapshot: GraphSnapshot,
    events: list[EventOutline],
) -> ChapterExtractionOutput:
    existing_ids = {n.node_id for n in graph_snapshot.nodes}
    entity_ids = {e.node_id for e in output.entities}
    chapter_id = int(state.get("chapter_id") or 0)
    standard_event_ids = {ev.event_id for ev in events if is_standard_event_id(ev.event_id, chapter_id=chapter_id)}
    planner_event_ids = standard_event_ids or {ev.event_id for ev in events}
    extracted_event_ids = {e.node_id for e in output.entities if e.node_type == NodeType.EVENT}
    event_by_id = {ev.event_id: ev for ev in events}
    allowed_causal_pairs: set[tuple[str, str]] = set()
    allowed_temporal_pairs: set[tuple[str, str]] = set()
    for ev in events:
        prev_id = ev.caused_by_event_id
        if prev_id:
            allowed_temporal_pairs.add((prev_id, ev.event_id))
        for link in ev.links:
            pair = (link.target_event_id, ev.event_id)
            if link.link_type == EventLinkType.CAUSAL:
                allowed_causal_pairs.add(pair)
            else:
                allowed_temporal_pairs.add(pair)
    malformed_event_ids = [ev.event_id for ev in events if ev.event_id not in planner_event_ids]
    if malformed_event_ids:
        logger.warning("validation_gate_nonstandard_event_ids", extra={"chapter_id": chapter_id, "event_ids": malformed_event_ids})
    required = {
        state.get("active_epoch_id", ""),
        state.get("pov_character_id", ""),
        "loc_unknown",
    }
    known_ids = existing_ids | entity_ids | {x for x in required if x}

    resolved_name_index: dict[str, str] = {}
    for ent in output.entities:
        resolved_name_index[ent.canonical_name.casefold()] = ent.node_id
        for al in ent.aliases:
            resolved_name_index[al.casefold()] = ent.node_id

    node_types: dict[str, NodeType] = {n.node_id: n.node_type for n in graph_snapshot.nodes}
    for ent in output.entities:
        node_types[ent.node_id] = ent.node_type

    kept: list[ExtractedRelation] = []
    figurative_tokens = ("像", "彷彿", "宛如", "如同", "好似", "仿佛", "as if", "like a")
    for rel in output.relations:
        sid = _resolve_relation_endpoint(
            rel.source_node_id,
            rel.source_name,
            resolved_name_index,
            extracted_event_ids,
            entity_ids,
            existing_ids,
        )
        tid = _resolve_relation_endpoint(
            rel.target_node_id,
            rel.target_name,
            resolved_name_index,
            extracted_event_ids,
            entity_ids,
            existing_ids,
        )
        if not sid or not tid or sid == tid:
            continue
        if sid not in known_ids or tid not in known_ids:
            continue
        if not relation_direction_is_valid(rel.relation_type, sid, tid, node_types):
            continue
        if (
            rel.relation_type in {EdgeType.CAUSED, EdgeType.HAPPENED_BEFORE}
            and sid in extracted_event_ids
            and tid in extracted_event_ids
            and sid in planner_event_ids
            and tid in planner_event_ids
        ):
            src_event = event_by_id.get(sid)
            tgt_event = event_by_id.get(tid)
            involves_ai_invention = bool(
                (src_event and src_event.is_ai_invention)
                or (tgt_event and tgt_event.is_ai_invention)
            )
            if not involves_ai_invention:
                pair = (sid, tid)
                if rel.relation_type == EdgeType.CAUSED and pair not in allowed_causal_pairs:
                    continue
                if rel.relation_type == EdgeType.HAPPENED_BEFORE and pair not in allowed_temporal_pairs:
                    continue
        details = (rel.context_details or "").casefold()
        if rel.relation_type in {EdgeType.BELIEVED_AS, EdgeType.HAS_ATTRIBUTE} and any(t in details for t in figurative_tokens):
            continue
        if rel.relation_type == EdgeType.HAS_ATTRIBUTE and node_types.get(tid) != NodeType.CONCEPT:
            continue
        kept.append(
            ExtractedRelation(
                source_node_id=sid,
                source_name=rel.source_name,
                relation_type=rel.relation_type,
                target_node_id=tid,
                target_name=rel.target_name,
                context_details=rel.context_details,
                is_truth=rel.is_truth,
                is_public=rel.is_public,
            )
        )

    mem = output.chapter_memory
    latest = (mem.latest_location or "").strip()
    if latest:
        nid = resolved_name_index.get(latest.casefold())
        loc_ok = nid and node_types.get(nid) == NodeType.LOCATION
        if not loc_ok:
            hint = (state.get("chapter_end_location_hint") or "").strip()
            if hint and hint.casefold() in resolved_name_index:
                latest = next(
                    (e.canonical_name for e in output.entities if e.node_id == resolved_name_index[hint.casefold()]),
                    hint,
                )
            elif hint:
                latest = hint
            else:
                latest = ""
    else:
        hint = (state.get("chapter_end_location_hint") or "").strip()
        if hint:
            latest = hint

    return ChapterExtractionOutput(
        entities=output.entities,
        relations=kept,
        chapter_memory=ChapterMemory(
            summary=mem.summary,
            unresolved_threads=mem.unresolved_threads,
            notable_entities=mem.notable_entities,
            latest_location=latest,
            ending_vibe=mem.ending_vibe,
        ),
    )


def _build_entity_prompt(ctx: ExtractionContext) -> str:
    existing = ctx.entity_glossary
    return json.dumps(
        {
            "story_id": ctx.state["story_id"],
            "chapter_id": ctx.state["chapter_id"],
            "existing_node_candidates": existing,
            "ground_truth_events": [e.model_dump(mode="json") for e in ctx.events],
            "author_surface_hints": ctx.author_surface_hints,
            "guidelines": ENTITY_EXTRACTION_GUIDELINES
            + [
                "author_surface_hints lists node_id values and exact substring surface forms from the author; "
                "align extracted entities to those node_id values when matched, and you may add those strings to aliases.",
                "existing_node_candidates is the Entity Glossary—match before creating new candidates.",
            ],
            "chapter_excerpt": ctx.chapter_text_for_entities,
            "prompt_char_budget": len(ctx.chapter_text_for_entities),
        },
        ensure_ascii=False,
    )


def _build_memory_prompt(ctx: ExtractionContext) -> str:
    return json.dumps(
        {
            "story_id": ctx.state["story_id"],
            "chapter_id": ctx.state["chapter_id"],
            "planner_visibility_contract": ctx.planner_visibility_contract,
            "guidelines": MEMORY_EXTRACTION_GUIDELINES,
            "chapter_excerpt": ctx.chapter_text_for_memory,
            "prompt_char_budget": len(ctx.chapter_text_for_memory),
        },
        ensure_ascii=False,
    )


def _safe_json_dict(raw: str) -> dict:
    if not raw or raw == "{}":
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {"raw": raw[:500]}
    except json.JSONDecodeError:
        return {"raw_truncated": raw[:500]}


def _build_relation_prompt(ctx: ExtractionContext, canonical_rows: list[dict[str, str]]) -> str:
    return json.dumps(
        {
            "story_id": ctx.state["story_id"],
            "chapter_id": ctx.state["chapter_id"],
            "active_epoch_id": ctx.state["active_epoch_id"],
            "pov_character_id": ctx.state["pov_character_id"],
            "ground_truth_events": [e.model_dump(mode="json") for e in ctx.events],
            "canonical_entities": canonical_rows,
            "graph_summary": _safe_json_dict(ctx.graph_summary_json),
            "guidelines": RELATION_EXTRACTION_GUIDELINES,
            "chapter_excerpt": ctx.chapter_text_for_relations,
            "prompt_char_budget": len(ctx.chapter_text_for_relations),
        },
        ensure_ascii=False,
    )


def _build_phase1_relation_prompt(ctx: ExtractionContext, canonical_rows: list[dict[str, str]]) -> str:
    # Phase 1 prefers full chapter text for higher recall; only apply excerpting when the chapter is unusually long.
    chapter_text = (
        ctx.chapter_content_full
        if len(ctx.chapter_content_full or "") <= 20000
        else ctx.chapter_text_for_relations
    )
    return json.dumps(
        {
            "story_id": ctx.state["story_id"],
            "chapter_id": ctx.state["chapter_id"],
            "active_epoch_id": ctx.state["active_epoch_id"],
            "pov_character_id": ctx.state["pov_character_id"],
            "ground_truth_events": [e.model_dump(mode="json") for e in ctx.events],
            "canonical_entities": canonical_rows,
            "graph_summary": _safe_json_dict(ctx.graph_summary_json),
            "guidelines": RELATION_EXTRACTION_GUIDELINES + PHASE1_RELATION_GUIDELINES,
            "chapter_chunks": ctx.chapter_chunks_for_prompt,
            "chapter_excerpt": chapter_text,
            "prompt_char_budget": len(chapter_text),
        },
        ensure_ascii=False,
    )


def _build_phase2_relation_prompt(
    ctx: ExtractionContext,
    *,
    canonical_rows: list[dict[str, str]],
    phase1_relations: list[ExtractedRelation],
) -> str:
    phase1_hint = [
        {
            "source_node_id": r.source_node_id,
            "relation_type": r.relation_type.value if hasattr(r.relation_type, "value") else str(r.relation_type),
            "target_node_id": r.target_node_id,
            "evidence_chunk_ids": list((r.metadata or {}).get("evidence_chunk_ids") or []),
        }
        for r in phase1_relations[:80]
    ]
    return json.dumps(
        {
            "story_id": ctx.state["story_id"],
            "chapter_id": ctx.state["chapter_id"],
            "active_epoch_id": ctx.state["active_epoch_id"],
            "pov_character_id": ctx.state["pov_character_id"],
            "ground_truth_events": [e.model_dump(mode="json") for e in ctx.events],
            "canonical_entities": canonical_rows,
            "graph_summary": _safe_json_dict(ctx.graph_summary_json),
            "guidelines": RELATION_EXTRACTION_GUIDELINES + PHASE2_RELATION_GUIDELINES,
            "chapter_chunks": ctx.chapter_chunks_for_prompt,
            "phase1_relation_hints": phase1_hint,
        },
        ensure_ascii=False,
    )


def _chunk_entity_rows(rows: list[dict[str, str]], batch_size: int) -> list[list[dict[str, str]]]:
    if batch_size <= 0:
        return [rows]
    return [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]


def _relation_dedupe_key(rel: ExtractedRelation) -> tuple:
    src = (rel.source_node_id or rel.source_name or "").strip().casefold()
    tgt = (rel.target_node_id or rel.target_name or "").strip().casefold()
    return (src, rel.relation_type, tgt)


def _dedupe_extracted_relations(relations: list[ExtractedRelation]) -> list[ExtractedRelation]:
    seen: set[tuple] = set()
    out: list[ExtractedRelation] = []
    for rel in relations:
        key = _relation_dedupe_key(rel)
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out


def extract_chapter_artifacts(
    state: dict,
    context: WorkflowContext,
    graph_snapshot: GraphSnapshot,
    chapter_content: str,
    events: list[EventOutline],
) -> tuple[ChapterExtractionOutput, dict | None]:
    if isinstance(context.llm_client, MockLLMClient):
        return (
            _fallback_extract(
                graph_snapshot,
                chapter_content,
                events,
                active_epoch_id=str(state.get("active_epoch_id") or ""),
            ),
            None,
        )

    ctx = build_extraction_context(state, graph_snapshot, chapter_content, events)
    diagnostics: dict[str, object] = {
        "steps": {},
        "settings": ctx.settings_snapshot,
    }

    entity_out: EntityExtractionOutput | None = None
    memory_out: ChapterMemoryExtractionOutput | None = None
    entity_latency = 0
    memory_latency = 0

    def run_entity() -> tuple[EntityExtractionOutput, int, int]:
        profile = augment_profile_system_prompt(
            get_profile("entity_extractor"), context.output_language
        )
        prompt = _build_entity_prompt(ctx)
        out, res = context.llm_client.invoke_json(prompt, EntityExtractionOutput, profile)
        return out, res.latency_ms, res.token_usage

    def run_memory() -> tuple[ChapterMemoryExtractionOutput, int, int]:
        profile = augment_profile_system_prompt(
            get_profile("chapter_memory_extractor"), context.output_language
        )
        prompt = _build_memory_prompt(ctx)
        out, res = context.llm_client.invoke_json(prompt, ChapterMemoryExtractionOutput, profile)
        return out, res.latency_ms, res.token_usage

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_entity = pool.submit(run_entity)
        future_memory = pool.submit(run_memory)
        future_kind = {future_entity: "entity", future_memory: "memory"}
        for future in as_completed(future_kind):
            kind = future_kind[future]
            try:
                if kind == "entity":
                    entity_out, entity_latency, entity_tok = future.result()
                    diagnostics["steps"]["entity_extractor"] = {
                        "latency_ms": entity_latency,
                        "token_usage": entity_tok,
                        "prompt_chars": len(ctx.chapter_text_for_entities),
                    }
                else:
                    memory_out, memory_latency, memory_tok = future.result()
                    diagnostics["steps"]["chapter_memory_extractor"] = {
                        "latency_ms": memory_latency,
                        "token_usage": memory_tok,
                        "prompt_chars": len(ctx.chapter_text_for_memory),
                    }
            except Exception as exc:
                logger.error(
                    "extraction step failed",
                    extra={"extra_payload": {"step": kind, "error": str(exc)}},
                )
                if kind == "entity":
                    entity_out = None
                else:
                    memory_out = None

    fb = _fallback_extract(
        graph_snapshot,
        chapter_content,
        events,
        active_epoch_id=str(state.get("active_epoch_id") or ""),
    )

    if entity_out is None or not entity_out.entities:
        entities = fb.entities
        resolved_name_index: dict[str, str] = {}
        for ent in entities:
            resolved_name_index[ent.canonical_name.casefold()] = ent.node_id
            for al in ent.aliases:
                resolved_name_index[al.casefold()] = ent.node_id
        diagnostics["steps"]["entity_extractor"] = {**(diagnostics["steps"].get("entity_extractor") or {}), "fallback": True}
    else:
        raw_count = len(entity_out.entities)
        filtered_candidates = _filter_entity_candidates_by_scope(entity_out.entities, ctx.chapter_text_for_entities)
        diagnostics["quality_metrics"] = {
            "entity_candidates_raw": raw_count,
            "entity_candidates_kept": len(filtered_candidates),
            "concept_candidates_dropped": raw_count - len(filtered_candidates),
        }
        planner_event_ids = {ev.event_id for ev in events}
        entities, resolved_name_index = canonicalize_entity_candidates(
            filtered_candidates,
            graph_snapshot,
            trusted_extrinsic_ids=planner_event_ids,
        )

    if memory_out is None:
        memory = fb.chapter_memory
        diagnostics["steps"]["chapter_memory_extractor"] = {**(diagnostics["steps"].get("chapter_memory_extractor") or {}), "fallback": True}
    else:
        memory = _align_chapter_memory(memory_out, entities, resolved_name_index)

    canonical_rows = [
        {"node_id": e.node_id, "canonical_name": e.canonical_name, "node_type": str(e.node_type)}
        for e in entities
    ]
    settings = get_settings()
    batch_size = settings.extraction_relation_entity_batch_size
    relations: list[ExtractedRelation] = []
    rel_profile = augment_profile_system_prompt(get_profile("relation_extractor"), context.output_language)

    if not canonical_rows:
        relations = []
        diagnostics["steps"]["relation_extractor"] = {
            "skipped": True,
            "reason": "no_canonical_entities",
            "batch_size": batch_size,
        }
    else:
        batches = _chunk_entity_rows(canonical_rows, batch_size)
        batched = batch_size > 0 and len(batches) > 1
        phase1_merged: list[ExtractedRelation] = []
        phase2_merged: list[ExtractedRelation] = []
        batch_records: list[dict[str, object]] = []

        # Phase 1: entity↔event/thing relations (chunk-evidenced); batches run in parallel (capped).
        phase1_batch_records: list[dict[str, object]] = []

        def _phase1_batch_job(idx: int, batch_rows: list[dict[str, Any]]) -> tuple[int, list[ExtractedRelation], dict[str, object]]:
            try:
                rel_prompt = _build_phase1_relation_prompt(ctx, batch_rows)
                rel_out, rel_res = context.llm_client.invoke_json(rel_prompt, RelationExtractionOutput, rel_profile)
                rec: dict[str, object] = {
                    "phase": 1,
                    "index": idx,
                    "entity_count": len(batch_rows),
                    "latency_ms": rel_res.latency_ms,
                    "token_usage": rel_res.token_usage,
                }
                return idx, list(rel_out.relations or []), rec
            except Exception as exc:
                logger.error(
                    "relation_extractor phase1 batch failed",
                    extra={"extra_payload": {"batch_index": idx, "error": str(exc)}},
                )
                rec = {
                    "phase": 1,
                    "index": idx,
                    "entity_count": len(batch_rows),
                    "error": str(exc),
                    "fallback": True,
                }
                return idx, [], rec

        _p1_workers = max(1, min(len(batches), settings.side_slot_fill_max_workers))
        with ThreadPoolExecutor(max_workers=_p1_workers) as pool:
            futs = [pool.submit(_phase1_batch_job, idx, br) for idx, br in enumerate(batches)]
            for fut in as_completed(futs):
                _, rels, rec = fut.result()
                phase1_merged.extend(rels)
                phase1_batch_records.append(rec)

        phase1_batch_records.sort(key=lambda r: int(r.get("index", 0)))
        batch_records.extend(phase1_batch_records)
        phase1_failed = not any("latency_ms" in r for r in phase1_batch_records)

        # Phase 2: event↔event links only (single pass over full canonical list)
        phase2_failed = True
        try:
            phase2_prompt = _build_phase2_relation_prompt(
                ctx,
                canonical_rows=canonical_rows,
                phase1_relations=_dedupe_extracted_relations(phase1_merged),
            )
            rel_out2, rel_res2 = context.llm_client.invoke_json(phase2_prompt, RelationExtractionOutput, rel_profile)
            phase2_merged.extend(list(rel_out2.relations or []))
            phase2_failed = False
            batch_records.append(
                {
                    "phase": 2,
                    "index": 0,
                    "entity_count": len(canonical_rows),
                    "latency_ms": rel_res2.latency_ms,
                    "token_usage": rel_res2.token_usage,
                }
            )
        except Exception as exc:
            logger.error("relation_extractor phase2 failed", extra={"extra_payload": {"error": str(exc)}})
            batch_records.append({"phase": 2, "index": 0, "entity_count": len(canonical_rows), "error": str(exc), "fallback": True})

        if phase1_failed and phase2_failed:
            relations = list(fb.relations)
            diagnostics["steps"]["relation_extractor"] = {
                "fallback": True,
                "batch_size": batch_size,
                "batched": batched,
                "batches": batch_records,
                "prompt_chars": len(ctx.chapter_text_for_relations),
            }
        else:
            merged_all = list(phase1_merged) + list(phase2_merged)
            relations = _dedupe_extracted_relations(merged_all)
            total_latency = sum(int(b.get("latency_ms", 0) or 0) for b in batch_records if "latency_ms" in b)
            total_tokens = sum(int(b.get("token_usage", 0) or 0) for b in batch_records if "token_usage" in b)
            diagnostics["steps"]["relation_extractor"] = {
                "batch_size": batch_size,
                "batched": batched,
                "batch_count": len(batches),
                "batches": batch_records,
                "latency_ms": total_latency,
                "token_usage": total_tokens,
                "prompt_chars": len(ctx.chapter_text_for_relations),
            }

    output = ChapterExtractionOutput(entities=entities, relations=relations, chapter_memory=memory)
    output = _validation_gate(output, state, graph_snapshot, events)

    rel_step = diagnostics["steps"].get("relation_extractor") or {}
    if isinstance(rel_step.get("batches"), list):
        rel_ms = sum(int(b.get("latency_ms", 0) or 0) for b in rel_step["batches"] if isinstance(b, dict))
    else:
        rel_ms = int(rel_step.get("latency_ms", 0) or 0)
    total_latency = max(entity_latency, memory_latency) + rel_ms
    diagnostics["model"] = get_profile("entity_extractor").model
    diagnostics["latency_ms"] = total_latency
    return output, diagnostics


def _build_extraction_prompt(
    state: dict,
    graph_snapshot: GraphSnapshot,
    chapter_content: str,
    events: list[EventOutline],
) -> str:
    """Legacy prompt for tests: must include all relation guideline tokens."""
    return json.dumps(
        {
            "story_id": state["story_id"],
            "chapter_id": state["chapter_id"],
            "active_epoch_id": state["active_epoch_id"],
            "pov_character_id": state["pov_character_id"],
            "guidelines": RELATION_EXTRACTION_GUIDELINES,
            "planner_visibility_contract": {
                "reader_visible_facts": state.get("reader_visible_facts", []),
                "private_facts_or_secret_actions": state.get("private_facts_or_secret_actions", []),
                "reader_unresolved_questions": state.get("reader_unresolved_questions", []),
                "chapter_end_location_hint": state.get("chapter_end_location_hint", ""),
                "last_known_location": state.get("last_known_location", ""),
            },
            "existing_nodes": [],
            "ground_truth_events": [event.model_dump(mode="json") for event in events],
            "chapter_content": chapter_content[:9000],
            "graph_context": "{}",
        },
        ensure_ascii=False,
    )


def _fallback_extract(
    graph_snapshot: GraphSnapshot,
    chapter_content: str,
    events: list[EventOutline],
    *,
    active_epoch_id: str,
) -> ChapterExtractionOutput:
    entities: list[ExtractedEntity] = []
    relations: list[ExtractedRelation] = []
    entity_names: list[str] = []
    matched_node_ids: set[str] = set()
    normalized_content = _normalize_text(chapter_content)
    lowered_content = normalized_content.lower()

    for node in graph_snapshot.nodes:
        aliases = [node.canonical_name, *getattr(node, "aliases", [])]
        if any(alias and str(alias).lower() in lowered_content for alias in aliases):
            matched_node_ids.add(node.node_id)
            entities.append(
                ExtractedEntity(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    canonical_name=node.canonical_name,
                    aliases=list(getattr(node, "aliases", [])),
                    summary=f"Explicitly mentioned in chapter: {node.canonical_name}.",
                )
            )
            entity_names.append(node.canonical_name)

    for candidate in _infer_capitalized_names(chapter_content):
        if any(entity.canonical_name == candidate for entity in entities):
            continue
        entities.append(
            ExtractedEntity(
                node_type=NodeType.CHARACTER,
                canonical_name=candidate,
                summary=f"{candidate} is mentioned in this chapter.",
                properties={"description": f"{candidate} participates in the chapter plot."},
            )
        )
        entity_names.append(candidate)

    location_name = ""
    for node in graph_snapshot.nodes:
        if node.node_type == NodeType.LOCATION and node.node_id in matched_node_ids:
            location_name = node.canonical_name
            break

    if not location_name:
        location_name = _infer_location_name(chapter_content)
        if location_name and not any(entity.canonical_name == location_name for entity in entities):
            entities.append(
                ExtractedEntity(
                    node_type=NodeType.LOCATION,
                    canonical_name=location_name,
                    summary=f"{location_name} is a primary scene in this chapter.",
                )
            )
            entity_names.append(location_name)

    emitted_event_ids: set[str] = set()
    for event in events:
        desc = (event.description or "").strip()
        key = desc[: min(40, len(desc))] if desc else ""
        mentions_content = bool(key and len(key) >= 2 and key.lower() in lowered_content)
        mentions_via_character = False
        if not mentions_content:
            for entity in entities:
                if entity.node_type not in {NodeType.CHARACTER, NodeType.PERSONA}:
                    continue
                nm = (entity.canonical_name or "").strip()
                if nm and nm in desc:
                    mentions_via_character = True
                    break
        if not (mentions_content or mentions_via_character):
            continue
        entities.append(
            ExtractedEntity(
                node_id=event.event_id,
                node_type=NodeType.EVENT,
                canonical_name=clip_event_description_for_storage(desc),
                summary=f"Heuristic EVENT grounded in chapter vs planner beat: {desc[:220]}",
            )
        )
        entity_names.append(clip_event_description_for_storage(desc))
        emitted_event_ids.add(event.event_id)

    if active_epoch_id.strip():
        for eid in emitted_event_ids:
            relations.append(
                ExtractedRelation(
                    source_node_id=eid,
                    source_name="",
                    relation_type=EdgeType.BELONGS_TO_EPOCH,
                    target_node_id=active_epoch_id.strip(),
                    target_name="",
                    context_details="Heuristic: extracted EVENT belongs to active epoch.",
                    is_truth=True,
                    is_public=True,
                )
            )

    for ev in events:
        if ev.event_id not in emitted_event_ids:
            continue
        prev_id = ev.caused_by_event_id
        if prev_id and prev_id in emitted_event_ids:
            relations.append(
                ExtractedRelation(
                    source_node_id=prev_id,
                    relation_type=EdgeType.HAPPENED_BEFORE,
                    target_node_id=ev.event_id,
                    context_details="Planner temporal chain (caused_by_event_id).",
                    is_truth=True,
                    is_public=True,
                )
            )
        for link in ev.links or []:
            other = link.target_event_id
            if other not in emitted_event_ids:
                continue
            if link.link_type == EventLinkType.CAUSAL:
                relations.append(
                    ExtractedRelation(
                        source_node_id=other,
                        relation_type=EdgeType.CAUSED,
                        target_node_id=ev.event_id,
                        context_details="Planner causal link.",
                        is_truth=True,
                        is_public=True,
                    )
                )
            else:
                relations.append(
                    ExtractedRelation(
                        source_node_id=other,
                        relation_type=EdgeType.HAPPENED_BEFORE,
                        target_node_id=ev.event_id,
                        context_details="Planner temporal link.",
                        is_truth=True,
                        is_public=True,
                    )
                )

    for event in events:
        if event.event_id not in emitted_event_ids:
            continue
        for entity in entities:
            if entity.node_type not in {NodeType.CHARACTER, NodeType.PERSONA}:
                continue
            if entity.canonical_name and entity.canonical_name in event.description:
                relations.append(
                    ExtractedRelation(
                        source_node_id=entity.node_id,
                        source_name=entity.canonical_name,
                        relation_type=EdgeType.PARTICIPATED_IN,
                        target_node_id=event.event_id,
                        target_name=clip_event_description_for_storage(event.description),
                        context_details=(
                            f"{entity.canonical_name} participated in event: "
                            f"{clip_event_description_for_storage(event.description)}"
                        ),
                        is_truth=True,
                        is_public=False,
                    )
                )

    if location_name:
        for entity in entities:
            if entity.node_type not in {NodeType.CHARACTER, NodeType.PERSONA}:
                continue
            relations.append(
                ExtractedRelation(
                    source_node_id=entity.node_id,
                    source_name=entity.canonical_name,
                    relation_type=EdgeType.LOCATED_IN,
                    target_name=location_name,
                    context_details=f"{entity.canonical_name} ends the chapter at {location_name}.",
                    is_truth=True,
                    is_public=False,
                )
            )

    summary = normalized_content[:240]
    unresolved_threads = (
        [clip_event_description_for_storage(events[-1].description, max_len=600)] if events else []
    )
    return ChapterExtractionOutput(
        entities=entities,
        relations=relations,
        chapter_memory=ChapterMemory(
            summary=summary,
            unresolved_threads=unresolved_threads,
            notable_entities=_dedupe(entity_names),
            latest_location=location_name,
        ),
    )


def _infer_capitalized_names(text: str) -> list[str]:
    pattern = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
    return _dedupe(pattern.findall(text))


def _infer_location_name(text: str) -> str:
    match = re.search(
        r"(王都|城門|聖所|邊境|西區|北坡|capital|harbor|sanctuary|border|district)",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def stable_entity_id(node_type: NodeType, canonical_name: str) -> str:
    prefix = {
        NodeType.CHARACTER: "char",
        NodeType.PERSONA: "persona",
        NodeType.LOCATION: "loc",
        NodeType.ITEM: "item",
        NodeType.CONCEPT: "concept",
        NodeType.EVENT: "event",
        NodeType.EPOCH: "epoch",
        NodeType.RULE: "rule",
    }[node_type]
    slug = _slugify(canonical_name)
    if slug:
        return f"{prefix}_{slug}"
    digest = hashlib.sha1(canonical_name.strip().lower().encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _slugify(raw: str) -> str:
    normalized = unicodedata.normalize("NFKC", (raw or "").strip().lower())
    ascii_only = re.sub(r"[^a-z0-9]+", "_", normalized)
    ascii_only = re.sub(r"_+", "_", ascii_only).strip("_")
    return ascii_only[:36]


def _filter_entity_candidates_by_scope(
    candidates: list[ExtractedEntityCandidate],
    chapter_excerpt: str,
) -> list[ExtractedEntityCandidate]:
    allowed: list[ExtractedEntityCandidate] = []
    excerpt = chapter_excerpt or ""
    for c in candidates:
        if c.node_type != NodeType.CONCEPT:
            allowed.append(c)
            continue
        if _is_valid_world_concept(c.canonical_name, c.summary, excerpt):
            allowed.append(c)
    return allowed


def _is_valid_world_concept(name: str, summary: str, excerpt: str) -> bool:
    nm = (name or "").strip()
    if not nm:
        return False
    # Reject obvious figurative / body / emotion-only concepts.
    blocked = (
        "肌肉",
        "恐懼",
        "驚訝",
        "悲傷",
        "白沫",
        "痛苦",
        "不適",
        "緊張",
        "瞳孔",
        "眼淚",
        "muscle",
        "fear",
        "grief",
        "foam",
        "pain",
        "tension",
        "pupil",
        "tear",
    )
    if any(tok in nm for tok in blocked):
        return False
    evidence_text = f"{summary or ''} {excerpt[:1200]}"
    # Keep only concepts with definitional signal in nearby text.
    definitional_signals = (
        "稱為",
        "被稱為",
        "是一種",
        "規則",
        "法則",
        "機制",
        "組織",
        "陣營",
        "能力",
        "代號",
        "known as",
        "called",
        "refers to",
        "rule",
        "law",
        "mechanism",
        "faction",
        "protocol",
        "codename",
    )
    return any(sig in evidence_text for sig in definitional_signals)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        cleaned = raw.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
