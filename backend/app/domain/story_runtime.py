"""Story execution-time state split from static bible_json / anchor skeleton."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Keys that must not live in bible_json (stored in stories.story_runtime_json).
BIBLE_RUNTIME_KEYS: frozenset[str] = frozenset(
    {"resolved_anchors", "anchor_candidates", "lore_mysteries_progression"}
)

DEFAULT_STORY_RUNTIME: dict[str, Any] = {
    "resolved_anchors": [],
    "anchor_candidates": [],
    "lore_mysteries_progression": [],
    "anchor_properties": {},
}


def strip_runtime_keys_from_bible(bible: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(bible or {})
    for k in BIBLE_RUNTIME_KEYS:
        out.pop(k, None)
    return out


def extract_runtime_from_bible(bible: dict[str, Any] | None) -> dict[str, Any]:
    """Pull runtime keys out of a bible dict into a normalized runtime payload."""
    b = bible or {}
    runtime = deepcopy(DEFAULT_STORY_RUNTIME)
    ra = b.get("resolved_anchors")
    if isinstance(ra, list):
        runtime["resolved_anchors"] = [str(x).strip() for x in ra if str(x).strip()]
    ac = b.get("anchor_candidates")
    if isinstance(ac, list):
        runtime["anchor_candidates"] = [str(x).strip() for x in ac if str(x).strip()]
    lore = b.get("lore_mysteries_progression")
    if isinstance(lore, list):
        runtime["lore_mysteries_progression"] = list(lore)
    return runtime


def parse_story_runtime(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        base = deepcopy(DEFAULT_STORY_RUNTIME)
        base.update(raw)
        if not isinstance(base.get("resolved_anchors"), list):
            base["resolved_anchors"] = []
        if not isinstance(base.get("anchor_candidates"), list):
            base["anchor_candidates"] = []
        if not isinstance(base.get("lore_mysteries_progression"), list):
            base["lore_mysteries_progression"] = []
        ap = base.get("anchor_properties")
        base["anchor_properties"] = dict(ap) if isinstance(ap, dict) else {}
        return base
    return deepcopy(DEFAULT_STORY_RUNTIME)


def _is_terminal_anchor(row: dict) -> bool:
    return str(row.get("node_kind") or "").upper() in {"CHECKPOINT", "ENDING"}


def recompute_anchor_unlocks(anchor_nodes: list[dict], resolved: set[str]) -> tuple[list[dict], list[str]]:
    """Mutates copies of rows: set status from resolved set + depends_on; return candidates."""
    by_id = {str(n.get("id") or ""): deepcopy(dict(n)) for n in anchor_nodes if str(n.get("id") or "").strip()}
    resolved = set(resolved)
    changed = True
    while changed:
        changed = False
        for node_id, row in by_id.items():
            if node_id in resolved or not _is_terminal_anchor(row):
                continue
            deps = [str(x) for x in (row.get("depends_on") or []) if str(x).strip()]
            if all(dep in resolved for dep in deps):
                resolved.add(node_id)
                changed = True

    candidates: list[str] = []
    for node_id, row in by_id.items():
        deps = [str(x) for x in (row.get("depends_on") or []) if str(x).strip()]
        if node_id in resolved:
            row["status"] = "RESOLVED"
            continue
        if all(dep in resolved for dep in deps):
            row["status"] = "UNLOCKED"
            if not _is_terminal_anchor(row):
                candidates.append(node_id)
        else:
            row["status"] = "LOCKED"
    return list(by_id.values()), sorted(set(candidates))


def anchor_properties_from_runtime(runtime: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ap = runtime.get("anchor_properties")
    return dict(ap) if isinstance(ap, dict) else {}


def apply_anchor_properties_to_nodes(nodes: list[dict], anchor_properties: dict[str, dict[str, Any]]) -> None:
    for n in nodes:
        aid = str(n.get("id") or "").strip()
        if not aid:
            continue
        props_runtime = anchor_properties.get(aid) or {}
        if props_runtime.get("hitl_deferred"):
            props = dict(n.get("properties") or {})
            props["hitl_deferred"] = True
            n["properties"] = props


def anchor_nodes_to_skeleton_rows(nodes: list[dict]) -> tuple[list[dict], dict[str, dict[str, Any]]]:
    """Strip status and lift hitl_deferred into anchor_properties updates."""
    skeleton: list[dict] = []
    prop_updates: dict[str, dict[str, Any]] = {}
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        row = deepcopy(raw)
        row.pop("status", None)
        props = dict(row.get("properties") or {})
        if props.get("hitl_deferred"):
            aid = str(row.get("id") or "").strip()
            if aid:
                prop_updates[aid] = {"hitl_deferred": True}
            props.pop("hitl_deferred", None)
        if props:
            row["properties"] = props
        elif "properties" in row:
            row.pop("properties", None)
        skeleton.append(row)
    return skeleton, prop_updates


def hydrate_anchor_nodes(
    skeleton: list[dict],
    *,
    resolved_anchors: list[str],
    anchor_properties: dict[str, dict[str, Any]],
) -> list[dict]:
    """Build workflow/UI anchor rows with status from skeleton + runtime."""
    sk = [deepcopy(dict(n)) for n in skeleton if isinstance(n, dict)]
    node_ids = {str(n.get("id") or "").strip() for n in sk if str(n.get("id") or "").strip()}
    resolved_set = {str(x).strip() for x in resolved_anchors if str(x).strip() in node_ids}
    nodes, _derived = recompute_anchor_unlocks(sk, set(resolved_set))
    apply_anchor_properties_to_nodes(nodes, anchor_properties)
    return nodes


def normalize_anchor_candidates_from_hydrated(
    anchor_candidates_stored: list[str] | None,
    *,
    nodes: list[dict],
    resolved_anchors: list[str],
) -> list[str]:
    """Filter stored candidates against hydrated nodes; fallback to derived UNLOCKED frontier."""
    node_by_id = {str(n.get("id") or "").strip(): n for n in nodes if str(n.get("id") or "").strip()}
    node_ids = set(node_by_id.keys())
    resolved_set = {str(x).strip() for x in resolved_anchors if str(x).strip() in node_ids}
    if anchor_candidates_stored:
        out = []
        for cid in anchor_candidates_stored:
            s = str(cid).strip()
            if s not in node_ids or s in resolved_set:
                continue
            row = node_by_id[s]
            if str(row.get("status") or "").upper() == "RESOLVED":
                continue
            if _is_terminal_anchor(row):
                continue
            out.append(s)
        if out:
            return out
    return [
        str(n.get("id") or "").strip()
        for n in nodes
        if str(n.get("status") or "").upper() == "UNLOCKED" and not _is_terminal_anchor(n)
    ]


def merge_runtime_resolved_anchors_for_commit(
    persisted: list[str] | None,
    from_state: list[str] | None,
    *,
    node_ids: set[str] | None = None,
) -> tuple[list[str], bool]:
    """Union persisted and workflow resolved ids; block wiping progress with an empty state list.

    Returns (merged_ids, blocked_regression). ``blocked_regression`` is True when the state
    carried no resolved ids but SQLite already had progress (chapter-review rerun bug).
    """
    prev = [str(x).strip() for x in (persisted or []) if str(x).strip()]
    new = [str(x).strip() for x in (from_state or []) if str(x).strip()]
    if node_ids is not None:
        prev = [x for x in prev if x in node_ids]
        new = [x for x in new if x in node_ids]
    if prev and not new:
        return sorted(dict.fromkeys(prev)), True
    return sorted(dict.fromkeys(prev + new)), False


def resolved_anchors_from_skeleton_and_legacy(
    *,
    bible_resolved: list[str] | None,
    nodes_skeleton_or_full: list[dict],
) -> list[str]:
    """Union bible resolved_anchors with nodes marked RESOLVED (legacy rows)."""
    acc: list[str] = []
    if bible_resolved:
        acc.extend(str(x).strip() for x in bible_resolved if str(x).strip())
    for n in nodes_skeleton_or_full:
        if not isinstance(n, dict):
            continue
        if str(n.get("status") or "").upper() == "RESOLVED":
            aid = str(n.get("id") or "").strip()
            if aid:
                acc.append(aid)
    return sorted(dict.fromkeys(acc))
