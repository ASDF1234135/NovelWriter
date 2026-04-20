from __future__ import annotations

import re

from app.domain.schema import EnforcedRuleContext, GraphSnapshot, NodeType, EdgeType, VectorDocument
from app.services.workflow.output_language import chapter_context_line, normalize_output_language
from app.services.workflow.utils import latin_word_boundary_search, looks_like_latin_word


def build_continuity_packet(
    chapters: list[dict],
    graph_snapshot: GraphSnapshot,
    vector_hits: list[VectorDocument],
    pov_character_id: str = "",
    active_epoch_id: str = "",
    *,
    output_language: str | None = None,
) -> dict:
    if not chapters:
        return {
            "previous_chapter_summary": "",
            "recent_chapter_context": "",
            "last_known_location": "",
            "continuity_notes": [],
            "recent_entity_names": [],
        }

    chapter_summaries = [
        _build_chapter_summary(chapter, vector_hits, active_epoch_id=active_epoch_id, max_chars=320)
        for chapter in chapters
    ]
    previous_summary = chapter_summaries[-1]
    continuity_notes = [f"延續上一章局勢：{previous_summary}"] if previous_summary else []
    continuity_notes.extend(_collect_unresolved_threads(vector_hits))
    recent_entity_names = _collect_recent_entities(chapters, graph_snapshot, vector_hits)
    last_known_location = _collect_last_known_location(
        graph_snapshot,
        vector_hits,
        pov_character_id,
        active_epoch_id,
    )

    ol = normalize_output_language(output_language)
    recent_context_lines = []
    for chapter, summary in zip(chapters, chapter_summaries, strict=False):
        cid = int(chapter["chapter_id"])
        recent_context_lines.append(chapter_context_line(cid, summary, ol))

    return {
        "previous_chapter_summary": previous_summary,
        "recent_chapter_context": "\n".join(recent_context_lines),
        "last_known_location": last_known_location,
        "continuity_notes": continuity_notes[:4],
        "recent_entity_names": recent_entity_names[:8],
    }


def resolve_pov_character_id(pov_character_id: str, graph_snapshot: GraphSnapshot) -> str:
    if not pov_character_id:
        return pov_character_id

    candidates = [
        node for node in graph_snapshot.nodes if node.node_type in {NodeType.CHARACTER, NodeType.PERSONA}
    ]
    if any(node.node_id == pov_character_id for node in candidates):
        return pov_character_id

    normalized_input = _normalize_lookup_value(pov_character_id)
    if not normalized_input:
        return pov_character_id

    for node in candidates:
        if normalized_input in {
            _normalize_lookup_value(node.node_id),
            _normalize_lookup_value(node.canonical_name),
            *[_normalize_lookup_value(str(alias)) for alias in getattr(node, "aliases", [])],
        }:
            return node.node_id

    input_tokens = _tokenize_lookup_value(pov_character_id)
    if not input_tokens:
        return pov_character_id

    best_node_id = pov_character_id
    best_score = 0.0
    for node in candidates:
        candidate_tokens = _tokenize_lookup_value(node.node_id)
        candidate_tokens.update(_tokenize_lookup_value(node.canonical_name))
        for alias in getattr(node, "aliases", []):
            candidate_tokens.update(_tokenize_lookup_value(str(alias)))
        overlap_score = _token_overlap_score(input_tokens, candidate_tokens)
        if overlap_score <= 0:
            continue
        score = overlap_score / max(len(input_tokens), 1)
        if score > best_score:
            best_score = score
            best_node_id = node.node_id
    return best_node_id if best_score >= 0.6 else pov_character_id


def chapter_content_tail_snippet(content: str, max_chars: int = 320) -> str:
    """Last up to max_chars of normalized text; aligns vector summary fallback with chapter-end continuity."""
    text = _normalize_text(content or "")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _build_chapter_summary(
    chapter: dict,
    vector_hits: list[VectorDocument],
    active_epoch_id: str,
    max_chars: int = 220,
) -> str:
    chapter_id = chapter.get("chapter_id")
    for hit in _iter_recent_vector_hits(vector_hits, active_epoch_id):
        metadata = hit.metadata
        if metadata.get("chapter_id") != chapter_id:
            continue
        mem_type = str(metadata.get("memory_type") or "").strip()
        # Excerpts and unresolved-thread docs are not 「上一章摘要」; their text_chunk is often chapter opening.
        if mem_type in {"chapter_excerpt", "unresolved_threads"}:
            continue
        summary = _normalize_text(str(metadata.get("chapter_summary", "")).strip())
        if summary:
            return summary[:max_chars]
        # chapter_summary vector rows with empty metadata used to fall back to text_chunk (often 正文開頭).
        if mem_type == "chapter_summary":
            continue
    return _summarize_chapter_record(chapter, max_chars=max_chars)


def _summarize_chapter_record(chapter: dict, max_chars: int = 220) -> str:
    content = _normalize_text(chapter.get("content", ""))
    title = _normalize_text(chapter.get("title", ""))
    if title and content.startswith(title):
        content = content[len(title) :].lstrip()
    if len(content) <= max_chars:
        return content
    return content[-max_chars:]


def _collect_unresolved_threads(vector_hits: list[VectorDocument]) -> list[str]:
    notes: list[str] = []
    for hit in vector_hits:
        metadata = hit.metadata
        if metadata.get("memory_type") != "unresolved_threads":
            continue
        text = _normalize_text(hit.text_chunk)
        if text:
            notes.append(text[:220])
    return notes


def _collect_recent_entities(
    chapters: list[dict],
    graph_snapshot: GraphSnapshot,
    vector_hits: list[VectorDocument],
) -> list[str]:
    chapter_text = "\n".join(_normalize_text(chapter.get("content", "")) for chapter in chapters)
    names: list[str] = []

    for hit in vector_hits:
        entity_names = hit.metadata.get("entity_names", [])
        if isinstance(entity_names, list):
            names.extend(str(name) for name in entity_names if str(name).strip())

    lowered_text = chapter_text.lower()
    for node in graph_snapshot.nodes:
        canonical_name = node.canonical_name.strip()
        # Guard short names from substring pollution (e.g. "Li" matching inside unrelated words).
        if len(canonical_name) < 3:
            continue
        if canonical_name and (
            (looks_like_latin_word(canonical_name) and latin_word_boundary_search(canonical_name, chapter_text))
            or (not looks_like_latin_word(canonical_name) and canonical_name.lower() in lowered_text)
        ):
            names.append(canonical_name)
        for alias in getattr(node, "aliases", []):
            alias = str(alias).strip()
            if len(alias) < 3:
                continue
            if alias and (
                (looks_like_latin_word(alias) and latin_word_boundary_search(alias, chapter_text))
                or (not looks_like_latin_word(alias) and alias.lower() in lowered_text)
            ):
                names.append(canonical_name or alias)

    seen: set[str] = set()
    deduped: list[str] = []
    for raw_name in names:
        normalized = _normalize_text(raw_name)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def resolve_pov_location_node_id(
    graph_snapshot: GraphSnapshot,
    pov_character_id: str,
    active_epoch_id: str,
) -> str:
    """POV 當前開放 LOCATED_IN 的目標地點 node_id；無則空字串。"""
    if not pov_character_id:
        return ""
    for edge in graph_snapshot.edges:
        if (
            edge.relation_type == EdgeType.LOCATED_IN
            and edge.source_id == pov_character_id
            and edge.end_event_id is None
            and (not active_epoch_id or edge.valid_epoch == active_epoch_id)
        ):
            return edge.target_id
    return ""


def format_local_enforced_rules_block(
    rules: list[EnforcedRuleContext],
    location_display_name: str,
) -> str:
    if not rules:
        return ""
    loc = (location_display_name or "").strip() or "（當前場域）"
    lines: list[str] = [
        "【當前場域絕對法則 (Local Enforced Rules)】",
        f"地點：{loc}",
        "",
    ]
    for i, r in enumerate(rules, start=1):
        body = (r.description or "").strip() or (r.canonical_name or "").strip() or r.rule_id
        lines.append(f"- 規則 {i}：{body}")
        if r.penalty and str(r.penalty).strip():
            lines.append(f"  違規代價：{str(r.penalty).strip()}")
        extra_bits: list[str] = []
        if r.restrict_target_names:
            extra_bits.append("限制標的：" + "、".join(r.restrict_target_names[:8]))
        if r.exempt_character_names:
            extra_bits.append("豁免角色：" + "、".join(r.exempt_character_names[:8]))
        if extra_bits:
            lines.append(f"  （{'；'.join(extra_bits)}）")
    lines.extend(
        [
            "",
            "【生成約束】本章情節推演必須嚴格遵守上述法則。若角色意圖違背，必須描寫其如何承擔代價，或如何利用漏洞／豁免合理解釋繞過。",
        ]
    )
    return "\n".join(lines)


def _collect_last_known_location(
    graph_snapshot: GraphSnapshot,
    vector_hits: list[VectorDocument],
    pov_character_id: str,
    active_epoch_id: str,
) -> str:
    node_names = {node.node_id: node.canonical_name for node in graph_snapshot.nodes}
    if pov_character_id:
        for edge in graph_snapshot.edges:
            if (
                edge.relation_type == EdgeType.LOCATED_IN
                and edge.source_id == pov_character_id
                and edge.end_event_id is None
                and (not active_epoch_id or edge.valid_epoch == active_epoch_id)
            ):
                return node_names.get(edge.target_id, edge.target_id)

    for hit in _iter_recent_vector_hits(vector_hits, active_epoch_id):
        location_name = str(hit.metadata.get("location_name", "")).strip()
        if location_name:
            return location_name
        location_id = str(hit.metadata.get("location_id", "")).strip()
        if location_id and location_id in node_names:
            return node_names[location_id]
    return ""


def _iter_recent_vector_hits(vector_hits: list[VectorDocument], active_epoch_id: str) -> list[VectorDocument]:
    filtered: list[VectorDocument] = []
    for hit in vector_hits:
        epoch_id = str(hit.metadata.get("epoch_id", "")).strip()
        if active_epoch_id and epoch_id and epoch_id != active_epoch_id:
            continue
        filtered.append(hit)
    return sorted(
        filtered,
        key=lambda hit: (
            int(hit.metadata.get("chapter_id", -1)) if str(hit.metadata.get("chapter_id", "")).isdigit() else -1,
            1 if hit.metadata.get("memory_type") == "chapter_summary" else 0,
        ),
        reverse=True,
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_lookup_value(text: str) -> str:
    return "".join(_tokenize_lookup_value(text))


def _tokenize_lookup_value(text: str) -> set[str]:
    raw_tokens = [part for part in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text.casefold()) if part]
    tokens: set[str] = set()
    ignored = {"char", "persona", "loc", "item", "concept", "event", "epoch"}
    for raw in raw_tokens:
        token = raw
        if token in ignored:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if len(token) > len(suffix) + 2 and token.endswith(suffix):
                token = token[: -len(suffix)]
                break
        if token:
            tokens.add(token)
    return tokens


def _token_overlap_score(left: set[str], right: set[str]) -> int:
    score = 0
    for left_token in left:
        for right_token in right:
            if left_token == right_token:
                score += 1
                break
            if min(len(left_token), len(right_token)) >= 4 and (
                left_token.startswith(right_token) or right_token.startswith(left_token)
            ):
                score += 1
                break
    return score
