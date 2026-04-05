from __future__ import annotations

import hashlib
import json
import re
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
from app.services.workflow.profiles import get_profile

logger = get_logger(__name__)


# Shared guideline strings (relation step + legacy test prompt)
RELATION_EXTRACTION_GUIDELINES: list[str] = [
    "只抽取章節正文中明確出現或可直接由章節確認的實體與關係。",
    "relation_type 只能使用既有枚舉值。",
    "若無法確定 relation 的方向或語義，寧可不輸出該 relation。",
    "【權限標籤鐵律】is_truth 與 is_public 是不同維度：真實不代表公開。",
    "只有大眾皆可直接觀察到的客觀現象、公開互動、公開持有、公開位置，才能設為 is_public=true。",
    "任何秘密行動、獨自發現的線索、暗中監視、私下知情、內心誤認或隱密移動，is_public 必須為 false。",
    "若 relation 僅能由單一 POV、少數知情者或參與者得知，預設用 is_public=false，不要因為它真實存在就設成公開。",
    "LOCATED_IN：表示某角色、人格、物品或事件位於某地點；方向必須是 CHARACTER/PERSONA/ITEM/EVENT -> LOCATION。",
    "HAS_ITEM：表示角色、人格或地點持有/收藏某物品；方向必須是 CHARACTER/PERSONA/LOCATION -> ITEM。",
    "HAS_RELATION：表示角色/人格/組織概念之間存在一般關聯；若使用此關係，source 與 target 必須都是非 EVENT、非 EPOCH 的穩定節點，且 context_details 要寫清楚關係內容。",
    "PARTICIPATED_IN：表示角色或人格參與事件；方向必須是 CHARACTER/PERSONA -> EVENT。",
    "IS_ACTUALLY：表示表層身份/偽裝身份實際對應到底層真實身份；方向必須是 PERSONA -> CHARACTER，不能反過來。",
    "HAS_ATTRIBUTE：表示某節點具有可直接觀察的屬性概念；方向建議是 CHARACTER/PERSONA/ITEM/LOCATION/EVENT -> CONCEPT，且 target 應是屬性或狀態概念，不要拿角色或地點充當屬性。",
    "BELIEVED_AS：表示某角色/人格把某人或某物誤認為某種身份/概念；方向建議是 CHARACTER/PERSONA -> CHARACTER/PERSONA/CONCEPT，context_details 必須寫明誤認內容。",
    "KNOWS_ABOUT：表示某角色/人格知道某個角色、物品、地點、事件或概念；方向必須是 CHARACTER/PERSONA -> ANY_NODE。",
    "BELONGS_TO_EPOCH：表示事件屬於某個時代；方向必須是 EVENT -> EPOCH。",
    "HAPPENED_BEFORE：表示事件或狀態在時間上早於另一事件或狀態；方向建議是 EVENT/CONCEPT -> EVENT/CONCEPT，且 source 較早、target 較晚。",
    "CAUSED：表示因果關係；方向必須是 EVENT -> EVENT，且 source 是原因、target 是結果。",
    "【空間移動鐵律】若正文清楚寫出角色移動到新地點，必須抽出新 LOCATION（若不存在）與新的 LOCATED_IN 關係。",
    "端點請使用 canonical_entities 中的 node_id 或 canonical_name，或 ground_truth_events 的 event_id。",
]

ENTITY_EXTRACTION_GUIDELINES: list[str] = [
    "只抽取章節正文可直接支持的實體，不得臆測。",
    "若與 existing_node_candidates 中節點同名或別名相符，請在 suggested_node_id 填寫該 node_id；否則 suggested_node_id 留空。",
    "不要自行發明 node_id；最終 ID 由系統決定。",
    "canonical_name 必須簡短、可作為圖譜主名稱。",
]

MEMORY_EXTRACTION_GUIDELINES: list[str] = [
    "chapter_memory.summary 必須是安全的表層摘要，不可寫入底層真相或 planner 的 private_facts。",
    "latest_location 用讀者可理解的地點描述，不需輸出 node_id。",
    "若章節有多場景，標出主要角色章末停留的有效位置；不明確則 latest_location 可留空。",
    "ending_vibe 必須在 ACTION_CLIFFHANGER / SAFE_ROOM_EXPOSITION / ON_THE_MOVE / DEVASTATING_LOSS 中擇一。",
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
    author_surface_hints: list[dict[str, Any]] = field(default_factory=list)
    settings_snapshot: dict = field(default_factory=dict)


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
    summary = _build_graph_summary(graph_snapshot, {n.node_id for n in candidates}, settings.extraction_graph_summary_max_chars)
    ent_text = _chapter_text_for_entities(full, settings.extraction_entity_text_budget)
    mem_text = _chapter_text_for_memory(full, settings.extraction_memory_full_text_budget)
    rel_text = _chapter_text_for_relations(full, events, ent_text, settings.extraction_relation_text_budget)
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
        planner_visibility_contract=contract,
        author_surface_hints=author_hints[:80],
        settings_snapshot={
            "entity_budget": settings.extraction_entity_text_budget,
            "memory_budget": settings.extraction_memory_full_text_budget,
            "relation_budget": settings.extraction_relation_text_budget,
            "relation_entity_batch_size": settings.extraction_relation_entity_batch_size,
        },
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
        "[以下為節選，摘要請保守、勿臆測未出現內容]\n\n"
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
        score += sum(1 for kw in ("王都", "城門", "巷", "宮", "門", "街", "屋", "站") if kw in p)
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


def canonicalize_entity_candidates(
    candidates: list[ExtractedEntityCandidate],
    graph_snapshot: GraphSnapshot,
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
            summary=c.summary or f"章節提及 {display_name}。",
            properties=dict(c.properties),
        )
        if node_id in seen_ids_map:
            prev = seen_ids_map[node_id]
            prev.aliases = _dedupe(list(prev.aliases) + list(ent.aliases))
            if not prev.summary and ent.summary:
                prev.summary = ent.summary
            prev.properties = {**ent.properties, **prev.properties}
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


def _relation_direction_valid(
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
    allowed = direction_rules.get(relation_type)
    if allowed is None:
        return True
    allowed_source, allowed_target = allowed
    return source_type in allowed_source and target_type in allowed_target


def _validation_gate(
    output: ChapterExtractionOutput,
    state: dict,
    graph_snapshot: GraphSnapshot,
    events: list[EventOutline],
) -> ChapterExtractionOutput:
    existing_ids = {n.node_id for n in graph_snapshot.nodes}
    entity_ids = {e.node_id for e in output.entities}
    event_ids = {ev.event_id for ev in events}
    required = {
        state.get("active_epoch_id", ""),
        state.get("pov_character_id", ""),
        "loc_unknown",
    }
    known_ids = existing_ids | entity_ids | event_ids | {x for x in required if x}

    resolved_name_index: dict[str, str] = {}
    for ent in output.entities:
        resolved_name_index[ent.canonical_name.casefold()] = ent.node_id
        for al in ent.aliases:
            resolved_name_index[al.casefold()] = ent.node_id

    node_types: dict[str, NodeType] = {n.node_id: n.node_type for n in graph_snapshot.nodes}
    for ent in output.entities:
        node_types[ent.node_id] = ent.node_type
    for ev in events:
        node_types[ev.event_id] = NodeType.EVENT

    kept: list[ExtractedRelation] = []
    for rel in output.relations:
        sid = _resolve_relation_endpoint(
            rel.source_node_id, rel.source_name, resolved_name_index, event_ids, entity_ids, existing_ids
        )
        tid = _resolve_relation_endpoint(
            rel.target_node_id, rel.target_name, resolved_name_index, event_ids, entity_ids, existing_ids
        )
        if not sid or not tid or sid == tid:
            continue
        if sid not in known_ids or tid not in known_ids:
            continue
        if not _relation_direction_valid(rel.relation_type, sid, tid, node_types):
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
    existing = [
        {
            "node_id": n.node_id,
            "node_type": str(n.node_type),
            "canonical_name": n.canonical_name,
            "aliases": list(getattr(n, "aliases", []) or []),
        }
        for n in ctx.candidate_nodes
    ]
    return json.dumps(
        {
            "story_id": ctx.state["story_id"],
            "chapter_id": ctx.state["chapter_id"],
            "existing_node_candidates": existing,
            "author_surface_hints": ctx.author_surface_hints,
            "guidelines": ENTITY_EXTRACTION_GUIDELINES
            + [
                "author_surface_hints 為主筆登記的 node_id 與正文中「精確子字串」稱呼；"
                "抽取時應把對應實體對齊到該 node_id，並可把這些字串納入 aliases。",
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
        return _fallback_extract(graph_snapshot, chapter_content, events), None

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
        profile = get_profile("entity_extractor")
        prompt = _build_entity_prompt(ctx)
        out, res = context.llm_client.invoke_json(prompt, EntityExtractionOutput, profile)
        return out, res.latency_ms, res.token_usage

    def run_memory() -> tuple[ChapterMemoryExtractionOutput, int, int]:
        profile = get_profile("chapter_memory_extractor")
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

    fb = _fallback_extract(graph_snapshot, chapter_content, events)

    if entity_out is None or not entity_out.entities:
        entities = fb.entities
        resolved_name_index: dict[str, str] = {}
        for ent in entities:
            resolved_name_index[ent.canonical_name.casefold()] = ent.node_id
            for al in ent.aliases:
                resolved_name_index[al.casefold()] = ent.node_id
        diagnostics["steps"]["entity_extractor"] = {**(diagnostics["steps"].get("entity_extractor") or {}), "fallback": True}
    else:
        entities, resolved_name_index = canonicalize_entity_candidates(entity_out.entities, graph_snapshot)

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
    rel_profile = get_profile("relation_extractor")

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
        merged: list[ExtractedRelation] = []
        batch_records: list[dict[str, object]] = []
        all_failed = True

        for idx, batch_rows in enumerate(batches):
            try:
                rel_prompt = _build_relation_prompt(ctx, batch_rows)
                rel_out, rel_res = context.llm_client.invoke_json(
                    rel_prompt, RelationExtractionOutput, rel_profile
                )
                merged.extend(list(rel_out.relations or []))
                all_failed = False
                batch_records.append(
                    {
                        "index": idx,
                        "entity_count": len(batch_rows),
                        "latency_ms": rel_res.latency_ms,
                        "token_usage": rel_res.token_usage,
                    }
                )
            except Exception as exc:
                logger.error(
                    "relation_extractor batch failed",
                    extra={"extra_payload": {"batch_index": idx, "error": str(exc)}},
                )
                batch_records.append(
                    {
                        "index": idx,
                        "entity_count": len(batch_rows),
                        "error": str(exc),
                        "fallback": True,
                    }
                )

        if all_failed:
            relations = list(fb.relations)
            diagnostics["steps"]["relation_extractor"] = {
                "fallback": True,
                "batch_size": batch_size,
                "batched": batched,
                "batches": batch_records,
                "prompt_chars": len(ctx.chapter_text_for_relations),
            }
        else:
            relations = _dedupe_extracted_relations(merged)
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
                    summary=f"章節明確提及 {node.canonical_name}。",
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
                summary=f"{candidate} 在本章被提及。",
                properties={"description": f"{candidate} 在本章參與情節。"},
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
                    summary=f"{location_name} 是本章主要場景。",
                )
            )
            entity_names.append(location_name)

    for event in events:
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
                        target_name=event.description[:40],
                        context_details=f"{entity.canonical_name} 參與了事件：{event.description[:80]}",
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
                    context_details=f"{entity.canonical_name} 在本章章末停留於 {location_name}。",
                    is_truth=True,
                    is_public=False,
                )
            )

    summary = normalized_content[:240]
    unresolved_threads = [events[-1].description[:120]] if events else []
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
    match = re.search(r"(王都|城門|聖所|邊境|西區|北坡)", text)
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
    }[node_type]
    digest = hashlib.sha1(canonical_name.strip().lower().encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


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
