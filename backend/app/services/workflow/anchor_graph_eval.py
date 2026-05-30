"""Shared GraphRAG anchor evaluation helpers (preflight + anchor_resolve)."""

from __future__ import annotations

from concurrent.futures import as_completed
from typing import Any, Literal

from app.core.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor
from app.core.config import get_settings
from app.domain.schema import GraphRAGEvaluateOutput
from app.services.graph_rag_service import GraphRAGService

CACHE_SOURCE_ANCHOR_RESOLVE = "anchor_resolve_graph_rag"
PREFLIGHT_REASONING_MAX_CHARS = 600

PreflightSource = Literal["live_eval", "cache", "already_resolved", "evaluation_error"]


def ids_to_evaluate(selected: list[str], next_ids: list[str]) -> list[str]:
    """Selected anchor ids for this chapter, excluding next-chapter carry-over ids."""
    next_set = {str(x).strip() for x in next_ids if str(x).strip()}
    out: list[str] = []
    seen: set[str] = set()
    for raw in selected:
        aid = str(raw).strip()
        if not aid or aid in next_set or aid in seen:
            continue
        seen.add(aid)
        out.append(aid)
    return out


def build_anchor_condition_desc(aid: str, node: dict[str, Any]) -> str:
    title = str(node.get("title") or "").strip()
    desc = str(node.get("description") or "").strip()
    kind = str(node.get("node_kind") or "").strip()
    deps = [str(x).strip() for x in (node.get("depends_on") or []) if str(x).strip()]
    return (
        "You are judging anchor completion.\n"
        f"Anchor id: {aid}\n"
        f"Anchor kind: {kind}\n"
        f"Anchor title: {title}\n"
        f"Anchor description: {desc}\n"
        f"Dependencies (must already be resolved): {deps}\n\n"
        "Question: Is this anchor already achieved/resolved given the current story state?\n"
        "Return resolved=true ONLY if the evidence pack contains objective facts proving completion.\n"
    )


def _clip_reasoning(text: str, *, max_chars: int = PREFLIGHT_REASONING_MAX_CHARS) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _cache_entry_for_reuse(
    cache: dict[str, Any],
    aid: str,
    *,
    chapter_id: int,
) -> dict[str, Any] | None:
    entry = cache.get(aid)
    if not isinstance(entry, dict):
        return None
    if str(entry.get("source") or "") != CACHE_SOURCE_ANCHOR_RESOLVE:
        return None
    try:
        cached_ch = int(entry.get("chapter_id"))
    except (TypeError, ValueError):
        return None
    if cached_ch != chapter_id - 1:
        return None
    if bool(entry.get("resolved")):
        return None
    reasoning = str(entry.get("reasoning") or "").strip()
    if not reasoning:
        return None
    return entry


def partition_preflight_ids(
    ids: list[str],
    *,
    resolved_anchors: set[str] | list[str],
    cache: dict[str, Any] | None,
    chapter_id: int,
    node_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (ordered preflight rows for non-LLM paths, ids needing live evaluate)."""
    resolved_set = {str(x).strip() for x in resolved_anchors if str(x).strip()}
    cache_map = cache if isinstance(cache, dict) else {}
    reuse_rows: list[dict[str, Any]] = []
    eval_ids: list[str] = []

    for aid in ids:
        node = node_by_id.get(aid) or {}
        title = str(node.get("title") or "").strip()
        if aid in resolved_set:
            reuse_rows.append(
                {
                    "anchor_id": aid,
                    "title": title,
                    "resolved": True,
                    "reasoning": "此錨點已在故事進度中標記為已達成（resolved_anchors）。",
                    "source": "already_resolved",
                    "cache_chapter_id": None,
                }
            )
            continue
        cached = _cache_entry_for_reuse(cache_map, aid, chapter_id=chapter_id)
        if cached is not None:
            reuse_rows.append(
                {
                    "anchor_id": aid,
                    "title": title,
                    "resolved": False,
                    "reasoning": _clip_reasoning(str(cached.get("reasoning") or "")),
                    "source": "cache",
                    "cache_chapter_id": int(cached.get("chapter_id")),
                }
            )
            continue
        eval_ids.append(aid)

    return reuse_rows, eval_ids


def evaluate_anchor_graph_rag(
    graph_rag: GraphRAGService,
    aid: str,
    node: dict[str, Any],
    *,
    story_id: str,
    active_epoch_id: str,
    pov_character_id: str,
) -> GraphRAGEvaluateOutput:
    condition_desc = build_anchor_condition_desc(aid, node)
    return graph_rag.evaluate_condition(
        condition_desc,
        story_id=story_id,
        active_epoch_id=active_epoch_id,
        pov_character_id=pov_character_id,
        response_model=GraphRAGEvaluateOutput,
    )


def evaluate_anchors_parallel(
    graph_rag: GraphRAGService,
    anchor_ids: list[str],
    node_by_id: dict[str, dict[str, Any]],
    *,
    story_id: str,
    active_epoch_id: str,
    pov_character_id: str,
) -> list[dict[str, Any]]:
    if not anchor_ids:
        return []
    workers = max(1, min(len(anchor_ids), get_settings().side_slot_fill_max_workers))
    rows_by_id: dict[str, dict[str, Any]] = {}

    def _run_one(aid: str) -> tuple[str, dict[str, Any]]:
        node = node_by_id.get(aid) or {}
        title = str(node.get("title") or "").strip()
        try:
            verdict = evaluate_anchor_graph_rag(
                graph_rag,
                aid,
                node,
                story_id=story_id,
                active_epoch_id=active_epoch_id,
                pov_character_id=pov_character_id,
            )
            return aid, {
                "anchor_id": aid,
                "title": title,
                "resolved": bool(verdict.resolved),
                "reasoning": _clip_reasoning(str(verdict.reasoning or "")),
                "source": "live_eval",
                "cache_chapter_id": None,
            }
        except Exception as exc:
            return aid, {
                "anchor_id": aid,
                "title": title,
                "resolved": False,
                "reasoning": f"GraphRAG evaluate failed: {exc}",
                "source": "evaluation_error",
                "cache_chapter_id": None,
            }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_run_one, aid) for aid in anchor_ids]
        for fut in as_completed(futs):
            aid, row = fut.result()
            rows_by_id[aid] = row

    return [rows_by_id[aid] for aid in anchor_ids if aid in rows_by_id]


def merge_preflight_rows(
    ids: list[str],
    reuse_rows: list[dict[str, Any]],
    live_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(r.get("anchor_id") or ""): r for r in reuse_rows + live_rows}
    return [by_id[aid] for aid in ids if aid in by_id]


def format_anchor_preflight_markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines = ["## 本章錨點前置狀態（GraphRAG）", ""]
    for row in rows:
        aid = str(row.get("anchor_id") or "").strip()
        title = str(row.get("title") or "").strip()
        source = str(row.get("source") or "")
        resolved = bool(row.get("resolved"))
        reasoning = _clip_reasoning(str(row.get("reasoning") or ""))
        header = f"### {aid}"
        if title:
            header += f"｜{title}"
        lines.append(header)
        if resolved:
            status = "已完成"
        else:
            status = "未完成"
        if source == "cache":
            ch = row.get("cache_chapter_id")
            status += f"（沿用第 {ch} 章 anchor_resolve 結果）"
        elif source == "already_resolved":
            status += "（故事進度已標記達成）"
        elif source == "evaluation_error":
            status += "（評估失敗）"
        lines.append(f"- 狀態：{status}")
        if reasoning:
            lines.append(f"- 說明：{reasoning}")
        lines.append("")
    return "\n".join(lines).strip()


def build_cache_from_anchor_resolution(
    chapter_id: int,
    anchor_resolution: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Extract GraphRAG unresolved rows for persistence (excludes fallback token-overlap rows)."""
    if not isinstance(anchor_resolution, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in anchor_resolution.get("evidence_summary") or []:
        if not isinstance(row, dict):
            continue
        if "resolved" not in row:
            continue
        if bool(row.get("resolved")):
            continue
        aid = str(row.get("anchor_id") or "").strip()
        if not aid:
            continue
        reasoning = str(row.get("reasoning") or "").strip()
        if not reasoning:
            continue
        out[aid] = {
            "chapter_id": int(chapter_id),
            "resolved": False,
            "reasoning": reasoning[:4000],
            "source": CACHE_SOURCE_ANCHOR_RESOLVE,
        }
    return out


def merge_cache_into_runtime(
    rt: dict[str, Any],
    new_entries: dict[str, dict[str, Any]],
    *,
    clear_anchor_ids: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    cache = dict(rt.get("anchor_unresolved_eval_cache") or {})
    if not isinstance(cache, dict):
        cache = {}
    for aid in clear_anchor_ids or []:
        cache.pop(str(aid).strip(), None)
    for aid, entry in (new_entries or {}).items():
        key = str(aid).strip()
        if key and isinstance(entry, dict):
            cache[key] = dict(entry)
    rt["anchor_unresolved_eval_cache"] = cache
    return rt


def anchor_unresolved_eval_cache_from_runtime(rt: dict[str, Any] | None) -> dict[str, Any]:
    raw = (rt or {}).get("anchor_unresolved_eval_cache")
    return dict(raw) if isinstance(raw, dict) else {}


def run_anchor_preflight(
    *,
    graph_rag: GraphRAGService,
    state: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    resolved_pov_character_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Evaluate selected anchors (minus next) and return markdown section + row list."""
    selected = list(state.get("selected_anchor_ids") or [])
    next_ids = list(state.get("next_anchor_ids") or [])
    ids = ids_to_evaluate(selected, next_ids)
    if not ids:
        return "", []

    chapter_id = int(state.get("chapter_id") or 0)
    cache = anchor_unresolved_eval_cache_from_runtime(
        {"anchor_unresolved_eval_cache": state.get("anchor_unresolved_eval_cache")}
    )
    reuse_rows, eval_ids = partition_preflight_ids(
        ids,
        resolved_anchors=list(state.get("resolved_anchors") or []),
        cache=cache,
        chapter_id=chapter_id,
        node_by_id=node_by_id,
    )
    live_rows: list[dict[str, Any]] = []
    if eval_ids:
        live_rows = evaluate_anchors_parallel(
            graph_rag,
            eval_ids,
            node_by_id,
            story_id=str(state.get("story_id") or "").strip(),
            active_epoch_id=str(state.get("active_epoch_id") or "epoch_present").strip() or "epoch_present",
            pov_character_id=resolved_pov_character_id,
        )
    merged = merge_preflight_rows(ids, reuse_rows, live_rows)
    return format_anchor_preflight_markdown(merged), merged
