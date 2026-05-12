from __future__ import annotations

from copy import deepcopy
import logging
import re
import sqlite3
from uuid import uuid4

from app.domain.schema import (
    AnchorNode,
    AnchorStatus,
    Storyline,
    AuthorExtractionSurfaceHintEntry,
    HitlAnchorDelayRequest,
    HitlBStoryJudgementRequest,
    HitlAnchorResolutionRequest,
    HitlContextPruneRequest,
    HitlDecisionRequest,
    HitlDirectorPatchRequest,
    HitlDraftEditRequest,
    HitlExtractionHintsRequest,
    HitlExtractionRemapRequest,
    HitlOutlineEditRequest,
    HitlReason,
    HitlStateInjectionRequest,
    MacroPlanPut,
    NodeMutation,
    NodeType,
    StateTransactionStatus,
    StateUpdaterOutput,
    StoryCastMemberStored,
    StoryInput,
    StoryOutputLanguage,
    StoryPatch,
    StorylineTier,
    VolumePlan,
    WorkflowStatus,
)
from app.domain.state import (
    apply_length_bounds_to_state,
    build_initial_state,
    canonicalize_workflow_state_contract,
    normalize_workflow_state,
)
from app.services.workflow.constants import AUTHOR_CHAPTER_PLAN_MAX_CHARS, CHAPTER_HARD_RULES_MAX_CHARS
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import GraphStore
from app.services.llm import LLMClient
from app.services.vector_store import VectorStore
from app.domain.story_runtime import normalize_anchor_candidates_from_hydrated
from app.services.workflow.bible_general_lore import effective_general_world_lore
from app.services.workflow.chapter_pacing import (
    build_ending_vibe_cooldown_constraint,
    build_resolution_cooldown_constraint,
)
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.chapter_summarizer import (
    build_minimal_state_for_regenerate,
    persist_chapter_summary,
)
from app.services.workflow.output_language import (
    default_chapter_target_words,
    normalize_output_language,
    strip_leading_chapter_heading_line,
)
from app.services.workflow.graph import build_chapter_graph
from app.services.workflow.graph import WorkflowNodeTimeoutError
from app.services.workflow.hitl_payload import build_hitl_context_payload, should_expose_hitl_context
from app.services.workflow.metrics import WorkflowMetricsResponse, build_single_run_metrics, rollup_metrics
from app.services.workflow.outline_binding import compute_outline_binding_mode

_ALLOWED_HITL_RESUME_NODES = frozenset(
    {
        "director",
        "planner",
        "logic_alignment",
        "author",
        "draft_supervisor",
        "reader",
        "chapter_review_gate",
        "chunker",
        "vectorize_chunks",
        "graph_rag",
        "extraction_gate",
        "copyeditor",
        "output_language_gate",
        "anchor_resolve",
        "profile_expander",
        "state_updater",
    }
)


def _is_terminal_anchor_node(row: dict) -> bool:
    return str(row.get("node_kind") or "").upper() in {"CHECKPOINT", "ENDING"}


def _refresh_anchor_runtime_state(story_repository: StoryRepository, state: dict) -> None:
    story_id = str(state["story_id"])
    story = story_repository.get_story(story_id) or {}
    nodes = [dict(n) for n in (story.get("anchor_nodes_json") or []) if isinstance(n, dict)]
    state["anchor_nodes"] = nodes
    node_ids = {str(n.get("id") or "").strip() for n in nodes if str(n.get("id") or "").strip()}
    rt = story.get("story_runtime_json") if isinstance(story.get("story_runtime_json"), dict) else {}
    resolved_raw = state.get("resolved_anchors")
    if resolved_raw is None:
        resolved_raw = rt.get("resolved_anchors") or []
    resolved = [str(x).strip() for x in resolved_raw if str(x).strip() in node_ids]
    state["resolved_anchors"] = sorted(dict.fromkeys(resolved))
    candidates_raw = state.get("anchor_candidates")
    if not candidates_raw:
        candidates_raw = rt.get("anchor_candidates") or []
    state["anchor_candidates"] = normalize_anchor_candidates_from_hydrated(
        list(candidates_raw) if candidates_raw else None,
        nodes=nodes,
        resolved_anchors=state["resolved_anchors"],
    )
    canonicalize_workflow_state_contract(state)


def _topo_sort_unresolved_anchor_dicts(nodes: list[dict]) -> list[dict]:
    pending = [n for n in nodes if isinstance(n, dict) and str(n.get("status") or "").upper() != "RESOLVED"]
    id_set = {str(n.get("id") or "").strip() for n in pending if str(n.get("id") or "").strip()}
    if not id_set:
        return []
    by_id = {str(n.get("id") or "").strip(): n for n in pending if str(n.get("id") or "").strip()}
    indeg: dict[str, int] = {nid: 0 for nid in id_set}
    children: dict[str, list[str]] = {nid: [] for nid in id_set}
    for n in pending:
        nid = str(n.get("id") or "").strip()
        if not nid:
            continue
        for dep in n.get("depends_on") or []:
            ds = str(dep).strip()
            if ds in id_set:
                indeg[nid] += 1
                children[ds].append(nid)
    q = sorted([nid for nid in id_set if indeg[nid] == 0])
    order_ids: list[str] = []
    while q:
        cur = q.pop(0)
        order_ids.append(cur)
        for nxt in children.get(cur, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
        q.sort()
    if len(order_ids) != len(id_set):
        return pending
    return [by_id[i] for i in order_ids]


def _unachieved_from_anchor_nodes(story_row: dict, chapter_id: int) -> list[dict]:
    nodes = [n for n in (story_row.get("anchor_nodes_json") or []) if isinstance(n, dict)]
    if not nodes:
        bible = story_row.get("bible_json") if isinstance(story_row.get("bible_json"), dict) else {}
        nodes = [n for n in (bible.get("anchor_nodes") or []) if isinstance(n, dict)]
    ordered = _topo_sort_unresolved_anchor_dicts(nodes)
    return [
        {
            "anchor_id": str(n.get("id") or ""),
            "title": str(n.get("title") or ""),
            "description": str(n.get("description") or ""),
        }
        for n in ordered
    ]


def _merge_surface_hints(state: dict, entries: list) -> None:
    by_id: dict[str, list[str]] = {}
    for h in state.get("author_extraction_surface_hints") or []:
        if not isinstance(h, dict):
            continue
        nid = str(h.get("node_id") or "").strip()
        if not nid:
            continue
        forms = [s for s in (h.get("surface_forms") or []) if isinstance(s, str) and s]
        by_id[nid] = forms
    for ent in entries:
        nid = str(ent.node_id).strip()
        if not nid:
            continue
        forms = [s for s in ent.surface_forms if isinstance(s, str) and s]
        prev = by_id.get(nid, [])
        merged = list(dict.fromkeys(prev + forms))
        by_id[nid] = merged
    state["author_extraction_surface_hints"] = [{"node_id": k, "surface_forms": v} for k, v in by_id.items()]


def _internal_graph_rag_tier_from_product(product_tier: int) -> int:
    """Map UI tier 0=full .. 2=aggressive to graph_rag internal (higher = wider caps)."""
    return max(0, min(2, 2 - int(product_tier)))


def _pick_volume_id_for_chapter(story_repository: StoryRepository, story_id: str, chapter_id: int) -> str:
    vols = story_repository.list_volumes(story_id)
    for v in vols:
        cs, ce = int(v["chapter_start"]), int(v["chapter_end"])
        if cs <= chapter_id <= ce:
            return str(v["volume_id"])
    return str(vols[0]["volume_id"]) if vols else "vol_unknown"


def _validate_anchor_selection_guardrails(
    anchor_nodes: list[dict], resolved_anchors: list[str], selected: list[str], nxt: list[str]
) -> None:
    by_id = {str(n.get("id") or ""): n for n in anchor_nodes if str(n.get("id") or "").strip()}
    resolved = {str(x).strip() for x in resolved_anchors if str(x).strip()}
    selected_ids = [x for x in selected if x in by_id]
    next_ids = [x for x in nxt if x in by_id]
    if selected and len(selected_ids) != len(selected):
        raise ValueError("invalid selected_anchor_ids: unknown anchor id")
    if nxt and len(next_ids) != len(nxt):
        raise ValueError("invalid next_anchor_ids: unknown anchor id")
    if selected_ids and not next_ids:
        raise ValueError("next_anchor_ids is required when selected_anchor_ids is provided")
    for nid in selected_ids:
        if _is_terminal_anchor_node(by_id[nid]):
            raise ValueError(f"selected_anchor {nid} cannot directly target checkpoint/ending")

    children: dict[str, list[str]] = {nid: [] for nid in by_id.keys()}
    for node in by_id.values():
        nid = str(node.get("id") or "")
        for dep in node.get("depends_on") or []:
            dep_id = str(dep).strip()
            if dep_id in children:
                children[dep_id].append(nid)

    def _reachable_to_any(start: str, targets: set[str]) -> bool:
        stack = [start]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in targets:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(children.get(cur, []))
        return False

    for nid in next_ids:
        node = by_id[nid]
        deps = [str(x).strip() for x in (node.get("depends_on") or []) if str(x).strip()]
        if any(dep not in resolved and dep not in selected_ids for dep in deps):
            raise ValueError(f"next_anchor {nid} has unmet dependencies")
        if str(node.get("node_kind") or "").upper() in {"CHECKPOINT", "ENDING"}:
            raise ValueError(f"next_anchor {nid} cannot directly target checkpoint/ending")
        if nid in resolved:
            raise ValueError(f"next_anchor {nid} already resolved")

    ending_targets = {
        str(n.get("id") or "")
        for n in by_id.values()
        if str(n.get("node_kind") or "").upper() == "ENDING" or "ending" in str(n.get("title") or "").lower()
    }
    if not ending_targets and by_id:
        ending_targets = {next(reversed(by_id.keys()))}
    for nid in next_ids:
        if not _reachable_to_any(nid, ending_targets):
            raise ValueError(f"next_anchor {nid} has no path to ending")


def _merge_hitl_future_anchor(
    story_repository: StoryRepository,
    story_id: str,
    chapter_id: int,
    title: str,
    description: str,
    chapters_to_delay: int | None,
) -> None:
    if not (title or "").strip() and not (description or "").strip():
        return
    delay = 0 if chapters_to_delay is None else int(chapters_to_delay)
    t = (title or "").strip() or (description or "").strip()[:120] or "未命名錨點"
    d = (description or "").strip()
    anchor_id = f"{story_id}_hitl_anchor_{uuid4().hex[:10]}"
    volume_id = _pick_volume_id_for_chapter(story_repository, story_id, chapter_id)
    story = story_repository.get_story(story_id) or {}
    storylines = list(story.get("storylines_json") or [])
    nodes = [dict(n) for n in (story.get("anchor_nodes_json") or []) if isinstance(n, dict)]
    nodes.append(
        {
            "id": anchor_id,
            "storyline_ids": [],
            "volume_id": volume_id,
            "node_kind": "NORMAL",
            "title": t,
            "description": d,
            "depends_on": [],
            "status": "UNLOCKED",
            "properties": {"source": "hitl_future_anchor", "deferred_chapters": delay},
        }
    )
    story_repository.update_story_macro_topology(
        story_id,
        storylines=[dict(x) for x in storylines if isinstance(x, dict)],
        anchor_nodes=nodes,
    )


def _apply_abort_and_restart_chapter_state(story_repository: StoryRepository, state: dict) -> None:
    """Discard AI chapter progress and restart planning; keep human outline/hard rules."""
    outline = str(state.get("chapter_outline") or "").strip()
    hard = str(state.get("chapter_hard_rules") or "").strip()
    freedom = str(state.get("ai_freedom_level") or "balanced").strip().lower()
    if freedom not in ("strict", "balanced", "wild"):
        freedom = "balanced"
    binding = str(state.get("outline_binding_mode") or "ABSENT").strip() or "ABSENT"

    story_id = str(state["story_id"])
    chapter_id = int(state["chapter_id"])
    trace_id = str(state.get("trace_id") or uuid4())
    story = story_repository.get_story(story_id) or {}
    pov_raw = (story.get("protagonist_character_id") or "").strip()
    pov_character_id = pov_raw if pov_raw else "char_public_observer"

    fresh = build_initial_state(
        story_id=story_id,
        chapter_id=chapter_id,
        trace_id=trace_id,
        plan_retry_limit=int(story.get("plan_retry_limit", 3)),
        draft_loop_retry_limit=int(story.get("draft_loop_retry_limit", 3)),
        pov_character_id=pov_character_id,
        author_chapter_plan=outline[:AUTHOR_CHAPTER_PLAN_MAX_CHARS],
        chapter_outline=outline[:AUTHOR_CHAPTER_PLAN_MAX_CHARS],
        chapter_hard_rules=hard[:CHAPTER_HARD_RULES_MAX_CHARS],
        ai_freedom_level=freedom,
        outline_binding_mode=binding,
    )
    # Carry over run bootstrap context that start_run_chapter would recompute.
    for key in (
        "previous_chapter_tail_excerpt",
        "recent_b_story_types",
        "all_milestone_summaries",
        "recent_chapter_summaries",
        "global_conflict_type_top3",
        "global_resolution_method_top3",
        "resolution_cooldown_constraint",
        "ending_vibe_cooldown_constraint",
        "narrative_directive",
        "tone_direction",
        "target_word_count",
    ):
        if key in state and state[key] not in (None, "", [], {}):
            fresh[key] = deepcopy(state[key]) if isinstance(state[key], (dict, list)) else state[key]
    # Preserve per-run human review toggle so reruns continue to pause when the user opted in.
    if "require_chapter_review" in state:
        fresh["require_chapter_review"] = bool(state.get("require_chapter_review"))

    bible = story.get("bible_json") or {}
    rt = story.get("story_runtime_json") if isinstance(story.get("story_runtime_json"), dict) else {}
    fresh["lore_mysteries_progression"] = list(rt.get("lore_mysteries_progression") or [])
    fresh["general_world_lore"] = effective_general_world_lore(bible)
    _refresh_anchor_runtime_state(story_repository, fresh)
    normalize_workflow_state(fresh)
    canonicalize_workflow_state_contract(fresh)
    fresh["story_output_language"] = normalize_output_language(str(story.get("output_language") or ""))
    apply_length_bounds_to_state(fresh)
    state.clear()
    state.update(fresh)


class HitlNotWaitingError(RuntimeError):
    """Raised when HITL APIs are called but the run is not paused for human input."""


class HitlExtractionHintsDisabledError(RuntimeError):
    """Surface hints must be sent on chapter run (ChapterRunRequest); /hitl/extraction-hints is disabled."""


class ChapterAlreadyCompletedError(RuntimeError):
    """Raised when attempting to run the full agent pipeline for a chapter already committed as completed."""


class StoryConfigurationLockedError(RuntimeError):
    """Raised when PATCH story is forbidden after workflow runs exist."""


class MacroCompileAlreadyRunningError(RuntimeError):
    """Raised when macro compile is requested while a compile is already in progress."""


class MacroPlanValidationError(ValueError):
    """Raised when manual macro plan payload fails structural checks."""


class MacroPlanCompletedChapterLockError(RuntimeError):
    """Raised when macro compile / disallowed macro edits are attempted after a chapter has been committed.

    Once any chapter is `completed`, only the plot DAG (anchor_nodes) remains editable
    for LOCKED / UNLOCKED nodes, plus addition of new nodes. Bible / volumes / cast / storyline
    metadata / protagonist must stay frozen so the committed manuscript stays consistent with
    its macro plan.
    """


class ChapterSummaryRegenerateFailed(RuntimeError):
    """Raised when POST regenerate-summary cannot persist an LLM-backed chapter summary."""


logger = logging.getLogger(__name__)


def _main_storyline_id(body: MacroPlanPut) -> str | None:
    for s in body.storylines:
        if s.type == StorylineTier.MAIN:
            return s.id
    for s in body.storylines:
        if str(s.id).endswith("_main"):
            return s.id
    return None


def _repair_macro_plan_mainline_cross_volume(body: MacroPlanPut) -> MacroPlanPut:
    """
    Ensure each volume's first MAIN-spine NORMAL node depends on the previous volume's last MAIN node.
    Fixes manual imports / edited plans that left a new root at each volume boundary.
    """
    main_id = _main_storyline_id(body)
    if not main_id:
        return body
    vol_order = sorted(body.volumes, key=lambda v: v.chapter_start)
    prev_last_id: str | None = None
    updates: dict[str, AnchorNode] = {}
    for vol in vol_order:
        mains_ordered: list[AnchorNode] = []
        for n in body.anchor_nodes:
            if n.volume_id != vol.volume_id:
                continue
            if str(n.node_kind).upper() != "NORMAL":
                continue
            if main_id not in (n.storyline_ids or []):
                continue
            mains_ordered.append(n)
        if not mains_ordered:
            continue
        if prev_last_id is not None:
            first = mains_ordered[0]
            deps = list(first.depends_on or [])
            if prev_last_id not in deps:
                new_deps = [prev_last_id, *[d for d in deps if d != prev_last_id]]
                new_status = AnchorStatus.LOCKED if new_deps else first.status
                updates[first.id] = first.model_copy(update={"depends_on": new_deps, "status": new_status})
        prev_last_id = mains_ordered[-1].id
    if not updates:
        return body
    new_nodes = [updates.get(n.id, n) for n in body.anchor_nodes]
    return body.model_copy(update={"anchor_nodes": new_nodes})


def _macro_anchor_graph_has_cycle(nodes: list[AnchorNode]) -> bool:
    ids = {str(n.id).strip() for n in nodes}
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for n in nodes:
        nid = str(n.id).strip()
        for d in n.depends_on:
            ds = str(d).strip()
            if ds in ids and nid in ids:
                adj[ds].append(nid)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {i: WHITE for i in ids}

    def dfs(u: str) -> bool:
        color[u] = GREY
        for v in adj.get(u, []):
            c = color.get(v, WHITE)
            if c == GREY:
                return True
            if c == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    for i in ids:
        if color[i] == WHITE and dfs(i):
            return True
    return False


def _macro_anchor_graph_weakly_connected(nodes: list[AnchorNode]) -> bool:
    """All anchor nodes must lie in one undirected connected component (no stranded islands)."""
    ids = [str(n.id).strip() for n in nodes]
    id_set = set(ids)
    if len(id_set) <= 1:
        return True
    adj: dict[str, set[str]] = {i: set() for i in id_set}
    for n in nodes:
        nid = str(n.id).strip()
        for d in n.depends_on:
            ds = str(d).strip()
            if ds in id_set:
                adj[nid].add(ds)
                adj[ds].add(nid)
    start = next(iter(id_set))
    seen: set[str] = set()
    stack = [start]
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        for v in adj[u]:
            if v not in seen:
                stack.append(v)
    return len(seen) == len(id_set)


def _macro_storyline_refs_ok(body: MacroPlanPut) -> None:
    allowed = {str(s.id).strip() for s in body.storylines}
    for n in body.anchor_nodes:
        nid = str(n.id).strip()
        for sid in n.storyline_ids:
            s = str(sid).strip()
            if s not in allowed:
                raise MacroPlanValidationError(f"Anchor node {nid}: unknown storyline id {s}")


def _validate_macro_plan_put(body: MacroPlanPut) -> None:
    vol_by_id = {v.volume_id: v for v in body.volumes}
    if len(vol_by_id) != len(body.volumes):
        raise MacroPlanValidationError("Duplicate volume_id in volumes")
    for v in body.volumes:
        if v.chapter_end < v.chapter_start:
            raise MacroPlanValidationError(
                f"Volume {v.volume_id}: chapter_end must be >= chapter_start"
            )
        if v.chapter_start < 1:
            raise MacroPlanValidationError(f"Volume {v.volume_id}: chapter_start must be >= 1")
    if not body.anchor_nodes:
        raise MacroPlanValidationError("anchor_nodes must not be empty")
    known_ids: set[str] = set()
    for node in body.anchor_nodes:
        nid = str(node.id or "").strip()
        if not nid:
            raise MacroPlanValidationError("anchor_nodes contains empty id")
        if nid in known_ids:
            raise MacroPlanValidationError(f"Duplicate anchor node id: {nid}")
        known_ids.add(nid)
        vol = vol_by_id.get(node.volume_id)
        if not vol:
            raise MacroPlanValidationError(f"Anchor node {nid}: unknown volume_id {node.volume_id}")
    for node in body.anchor_nodes:
        nid = str(node.id or "").strip()
        for dep in node.depends_on:
            if dep not in known_ids:
                raise MacroPlanValidationError(f"Anchor node {nid}: unknown depends_on id {dep}")
    prot = (body.protagonist_character_id or "").strip()
    if prot:
        cast_ids = {c.node_id for c in body.cast}
        if prot not in cast_ids:
            raise MacroPlanValidationError("protagonist_character_id must match a cast member node_id")
    if _macro_anchor_graph_has_cycle(list(body.anchor_nodes)):
        raise MacroPlanValidationError("anchor_nodes depends_on contains a cycle")
    _macro_storyline_refs_ok(body)
    if not _macro_anchor_graph_weakly_connected(list(body.anchor_nodes)):
        raise MacroPlanValidationError(
            "anchor_nodes form disconnected subgraphs (multiple weakly connected components)"
        )


def _normalize_for_compare(value: object) -> object:
    """Order-insensitive, JSON-friendly normalization used for completed-chapter lock diffs."""
    if isinstance(value, dict):
        return {str(k): _normalize_for_compare(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [_normalize_for_compare(v) for v in value]
    if isinstance(value, tuple):
        return [_normalize_for_compare(v) for v in value]
    return value


# Bible payload fields that are populated by compile / runtime (not user-editable in the bible UI),
# stored in dedicated DB columns or derived state. The frontend may round-trip them inside
# `bible` (e.g. straight from a macro_compile response) so they must be stripped before diffing.
_BIBLE_NON_USER_KEYS = (
    "storylines",
    "anchor_nodes",
    "branch_count_final",
    "llm_weave_debug",
    "compile_warnings",
    "compile_config",
    "resolved_anchors",
    "anchor_candidates",
    "lore_mysteries_progression",
)


def _bible_user_view(bible: dict) -> dict:
    out = dict(bible or {})
    for key in _BIBLE_NON_USER_KEYS:
        out.pop(key, None)
    return out


def _volume_compare_key(v: dict) -> dict:
    """Volume identity for diff: id, title, summary, chapter range, target words."""
    return {
        "volume_id": str(v.get("volume_id") or ""),
        "title": str(v.get("title") or ""),
        "summary": str(v.get("summary") or ""),
        "chapter_start": int(v.get("chapter_start") or 0),
        "chapter_end": int(v.get("chapter_end") or 0),
        "target_volume_words": int(v.get("target_volume_words") or 0),
    }


def _cast_compare_key(c: dict) -> dict:
    """Cast member identity for diff: drop volatile / derived fields, keep authored profile."""
    fields = (
        "node_id",
        "canonical_name",
        "role",
        "short_bio",
        "aliases",
        "age",
        "personality",
        "speech_style",
        "core_motivation",
        "core_value",
        "fatal_flaw",
        "quirks_and_habits",
    )
    out: dict = {}
    for f in fields:
        out[f] = c.get(f)
    return out


def _storyline_compare_key(s: dict) -> dict:
    return {
        "id": str(s.get("id") or ""),
        "type": str(s.get("type") or ""),
        "title": str(s.get("title") or ""),
        "overall_goal": str(s.get("overall_goal") or ""),
        "involved_entities": list(s.get("involved_entities") or []),
    }


def _anchor_node_resolved_key(n: dict) -> dict:
    """RESOLVED anchor identity: every authored field that downstream chapters depend on."""
    return {
        "id": str(n.get("id") or ""),
        "storyline_ids": sorted(str(x) for x in (n.get("storyline_ids") or [])),
        "volume_id": str(n.get("volume_id") or ""),
        "node_kind": str(n.get("node_kind") or "NORMAL"),
        "title": str(n.get("title") or ""),
        "description": str(n.get("description") or ""),
        "depends_on": sorted(str(x) for x in (n.get("depends_on") or [])),
        "status": str(n.get("status") or ""),
    }


def _build_macro_lock_error(detail: str) -> MacroPlanCompletedChapterLockError:
    return MacroPlanCompletedChapterLockError(
        "Story is locked because at least one chapter is completed: "
        + detail
        + " Only LOCKED/UNLOCKED plot DAG nodes can be edited, deleted, or added."
    )


def _validate_macro_plan_put_under_completed_lock(
    body: MacroPlanPut, current_snapshot: dict
) -> None:
    """Reject changes to bible / volumes / cast / storylines / protagonist or to RESOLVED anchor nodes.

    LOCKED / UNLOCKED anchor nodes may be added, removed, or edited freely (subject to the
    structural validation in `_validate_macro_plan_put`). New USER_EDIT storylines may be added
    when they are referenced by newly created anchor nodes.
    """
    body_bible = _normalize_for_compare(_bible_user_view(dict(body.bible or {})))
    cur_bible = _normalize_for_compare(_bible_user_view(dict(current_snapshot.get("bible") or {})))
    if body_bible != cur_bible:
        raise _build_macro_lock_error("bible cannot be edited.")

    body_vols = sorted(
        (_volume_compare_key(v.model_dump(mode="json")) for v in body.volumes),
        key=lambda v: v["volume_id"],
    )
    cur_vols = sorted(
        (_volume_compare_key(dict(v)) for v in (current_snapshot.get("volumes") or [])),
        key=lambda v: v["volume_id"],
    )
    if body_vols != cur_vols:
        raise _build_macro_lock_error("volumes cannot be edited.")

    body_cast = sorted(
        (_cast_compare_key(c.model_dump(mode="json")) for c in body.cast),
        key=lambda c: str(c.get("node_id") or ""),
    )
    cur_cast = sorted(
        (_cast_compare_key(dict(c)) for c in (current_snapshot.get("cast") or [])),
        key=lambda c: str(c.get("node_id") or ""),
    )
    if _normalize_for_compare(body_cast) != _normalize_for_compare(cur_cast):
        raise _build_macro_lock_error("cast cannot be edited.")

    body_prot = (body.protagonist_character_id or "").strip()
    cur_prot = str(current_snapshot.get("protagonist_character_id") or "").strip()
    if body_prot != cur_prot:
        raise _build_macro_lock_error("POV protagonist cannot be changed.")

    cur_storylines_by_id = {
        str(s.get("id") or ""): _storyline_compare_key(dict(s))
        for s in (current_snapshot.get("storylines") or [])
    }
    body_storylines_by_id = {
        str(s.id): _storyline_compare_key(s.model_dump(mode="json")) for s in body.storylines
    }
    for sid, prev in cur_storylines_by_id.items():
        nxt = body_storylines_by_id.get(sid)
        if nxt is None:
            raise _build_macro_lock_error(
                f"existing storyline {sid!r} cannot be removed."
            )
        if _normalize_for_compare(prev) != _normalize_for_compare(nxt):
            raise _build_macro_lock_error(
                f"existing storyline {sid!r} cannot be modified."
            )
    for sid, nxt in body_storylines_by_id.items():
        if sid in cur_storylines_by_id:
            continue
        if str(nxt.get("type") or "").upper() != "USER_EDIT":
            raise _build_macro_lock_error(
                f"new storyline {sid!r} must be USER_EDIT (only user-edit branches can be added)."
            )

    resolved_ids = {
        str(x).strip()
        for x in (current_snapshot.get("story_runtime") or {}).get("resolved_anchors", [])
        if str(x).strip()
    }
    cur_nodes_by_id = {
        str(n.get("id") or ""): dict(n) for n in (current_snapshot.get("anchor_nodes") or [])
    }
    body_nodes_by_id = {str(n.id): n.model_dump(mode="json") for n in body.anchor_nodes}
    for nid, prev in cur_nodes_by_id.items():
        prev_resolved = nid in resolved_ids
        nxt = body_nodes_by_id.get(nid)
        if prev_resolved:
            if nxt is None:
                raise _build_macro_lock_error(
                    f"resolved plot node {nid!r} cannot be deleted."
                )
            if _anchor_node_resolved_key(prev) != _anchor_node_resolved_key(nxt):
                raise _build_macro_lock_error(
                    f"resolved plot node {nid!r} cannot be edited."
                )
        else:
            if nxt is not None and str(nxt.get("status") or "").upper() == "RESOLVED":
                raise _build_macro_lock_error(
                    f"plot node {nid!r} cannot be promoted to RESOLVED via macro PUT."
                )
    for nid, nxt in body_nodes_by_id.items():
        if nid in cur_nodes_by_id:
            continue
        new_status = str(nxt.get("status") or "").upper()
        if new_status == "RESOLVED":
            raise _build_macro_lock_error(
                f"new plot node {nid!r} cannot start as RESOLVED."
            )


def _cast_graph_description(member: StoryCastMemberStored) -> str:
    lines: list[str] = []
    if (member.short_bio or "").strip():
        lines.append(f"【故事身分】{member.short_bio.strip()}")
    if (member.age or "").strip():
        lines.append(f"【年齡】{member.age.strip()}")
    core = (member.core_motivation or "").strip()
    if core:
        lines.append(f"【核心動機】{core}")
    if (member.personality or "").strip():
        lines.append(f"【個性】{member.personality.strip()}")
    if (member.core_value or "").strip():
        lines.append(f"【核心價值】{member.core_value.strip()}")
    if (member.speech_style or "").strip():
        lines.append(f"【語感】{member.speech_style.strip()}")
    if (member.fatal_flaw or "").strip():
        lines.append(f"【致命缺陷】{member.fatal_flaw.strip()}")
    if (member.quirks_and_habits or "").strip():
        lines.append(f"【小習慣】{member.quirks_and_habits.strip()}")
    return "\n".join(lines) if lines else member.canonical_name


def _trim_to_sentence_boundary(text: str, max_chars: int) -> str:
    """Trim to <= max_chars, preferring punctuation boundaries to avoid chopping mid-sentence."""
    if len(text) <= max_chars:
        return text.strip()

    chunk = text[:max_chars]
    end_punct = ["。", "！", "？", "；", "…"]
    last_end = max((chunk.rfind(p) for p in end_punct), default=-1)
    if last_end > int(max_chars * 0.5):
        chunk = chunk[: last_end + 1]
    return chunk.strip()


def _extract_tail_excerpt(
    content: str,
    *,
    min_chars: int = 150,
    max_chars: int = 220,
    max_paragraphs: int = 3,
    max_total_paragraphs: int = 5,
) -> str:
    """
    Extract a trailing tail context excerpt from chapter content.

    Primary selection: last `max_paragraphs` paragraphs.
    If the excerpt is too short, we may include a few earlier paragraphs up to `max_total_paragraphs`.
    """
    if not content:
        return ""

    cleaned = strip_leading_chapter_heading_line(content)
    if not cleaned:
        return ""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", cleaned) if p.strip()]
    if not paragraphs:
        return ""

    start_idx = max(0, len(paragraphs) - max_paragraphs)
    excerpt_paras = paragraphs[start_idx:]
    excerpt = "\n\n".join(excerpt_paras).strip()

    if len(excerpt) < min_chars and len(paragraphs) > len(excerpt_paras):
        start_idx2 = max(0, len(paragraphs) - max_total_paragraphs)
        excerpt_paras2 = paragraphs[start_idx2:]
        excerpt = "\n\n".join(excerpt_paras2).strip()

    excerpt = _trim_to_sentence_boundary(excerpt, max_chars=max_chars)
    return excerpt


def _ensure_hitl_waiting(state: dict) -> None:
    """Normalize minor drift between requires_hitl and workflow_status before applying HITL input."""
    ws = str(state.get("workflow_status") or "")
    req = bool(state.get("requires_hitl"))
    if ws == WorkflowStatus.WAITING_HITL.value:
        if not req:
            state["requires_hitl"] = True
        return
    if req:
        state["workflow_status"] = WorkflowStatus.WAITING_HITL.value
        return
    raise HitlNotWaitingError("Workflow is not waiting for HITL")


class WorkflowService:
    def __init__(
        self,
        story_repository: StoryRepository,
        workflow_repository: WorkflowRepository,
        bible_service: BibleService,
        anchor_service: AnchorService,
        graph_store: GraphStore,
        vector_store: VectorStore,
        llm_client: LLMClient,
    ) -> None:
        self.story_repository = story_repository
        self.workflow_repository = workflow_repository
        self.bible_service = bible_service
        self.anchor_service = anchor_service
        self.graph_store = graph_store
        self.vector_store = vector_store
        self.llm_client = llm_client

    def _build_context(self, run_id: str) -> WorkflowContext:
        wf_run = self.workflow_repository.get_run(run_id)
        story_row = self.story_repository.get_story(wf_run.story_id)
        ol = normalize_output_language(str(story_row.get("output_language") or "") if story_row else None)
        return WorkflowContext(
            story_repository=self.story_repository,
            workflow_repository=self.workflow_repository,
            bible_service=self.bible_service,
            anchor_service=self.anchor_service,
            graph_store=self.graph_store,
            vector_store=self.vector_store,
            llm_client=self.llm_client,
            run_id=run_id,
            output_language=ol,
        )

    def _execute_workflow(self, run_id: str, state: dict) -> dict:
        context = self._build_context(run_id)
        graph = build_chapter_graph(context)
        final_state = graph.invoke(state)
        if final_state.get("volume_stretch_required"):
            story_id = str(final_state.get("story_id") or "")
            volumes = self.story_repository.list_volumes(story_id)
            if volumes:
                stretched: list[VolumePlan] = []
                max_end = 0
                for i, v in enumerate(volumes):
                    end = int(v["chapter_end"])
                    if i == len(volumes) - 1:
                        end += 1
                    max_end = max(max_end, end)
                    stretched.append(
                        VolumePlan(
                            volume_id=str(v["volume_id"]),
                            title=str(v["title"]),
                            summary=str(v["summary"]),
                            chapter_start=int(v["chapter_start"]),
                            chapter_end=end,
                            target_volume_words=int(v.get("target_volume_words") or 0),
                        )
                    )
                self.story_repository.store_volumes(story_id, stretched)
                final_state["volume_stretch_applied_to_chapter"] = max_end
        self.workflow_repository.update_run(run_id, final_state)
        return final_state

    def create_story(self, story_input: StoryInput) -> dict:
        story_id = f"story_{uuid4().hex[:10]}"
        story = self.story_repository.create_story(story_id, story_input)
        self.graph_store.seed_story(story_id)
        return story

    def patch_story(self, story_id: str, patch: StoryPatch) -> dict:
        return self.story_repository.patch_story(story_id, patch)

    def delete_story(self, story_id: str) -> None:
        """Remove story from SQLite, workflow tables, in-memory/Neo4j graph, and vector index."""
        if not self.story_repository.get_story(story_id):
            raise KeyError(f"Story not found: {story_id}")
        self.workflow_repository.delete_all_for_story(story_id)
        self.story_repository.delete_story_cascade(story_id)
        self.graph_store.remove_story(story_id)
        self.vector_store.remove_story(story_id)

    def macro_compile(self, story_id: str) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        if self.story_repository.has_completed_chapter(story_id):
            raise MacroPlanCompletedChapterLockError(
                "Macro compile is disabled because at least one chapter is already completed. "
                "Editing the plot DAG (LOCKED/UNLOCKED nodes) remains available."
            )
        raw_lang = str(story.get("output_language") or "").strip()
        ol: StoryOutputLanguage = normalize_output_language(raw_lang)
        story_input = StoryInput(
            title=story["title"],
            premise=story["premise"],
            bible={},
            macro_author_notes=str(story.get("macro_author_notes") or ""),
            cast_seed=list(story.get("cast_seed") or []),
            target_total_words=story["target_total_words"],
            branch_count_override=story.get("branch_count_override"),
            plan_retry_limit=int(story.get("plan_retry_limit", 3)),
            draft_loop_retry_limit=int(story.get("draft_loop_retry_limit", 3)),
            output_language=ol,
        )
        compile_out = self.anchor_service.compile_macro_plan(story_id, story_input, self.llm_client)
        if len(compile_out) == 5:
            volumes, _anchors_legacy, cast, _b_seed_unused, bible_generated = compile_out
        else:
            volumes, cast, _b_seed_unused, bible_generated = compile_out
        storylines = list((bible_generated or {}).get("storylines") or [])
        anchor_nodes = list((bible_generated or {}).get("anchor_nodes") or [])
        protagonist_id = next((c.node_id for c in cast if c.role == "protagonist"), "")
        self.story_repository.store_macro_plan_snapshot(
            story_id,
            bible=bible_generated or {},
            storylines=[
                s.model_dump(mode="json") if hasattr(s, "model_dump") else dict(s)
                for s in storylines
                if isinstance(s, dict) or hasattr(s, "model_dump")
            ],
            anchor_nodes=[
                n.model_dump(mode="json") if hasattr(n, "model_dump") else dict(n)
                for n in anchor_nodes
                if isinstance(n, dict) or hasattr(n, "model_dump")
            ],
            volumes=volumes,
            cast=list(cast),
            protagonist_character_id=protagonist_id,
        )
        cast_mutations = [
            NodeMutation(
                action="CREATE_NODE",
                node_id=member.node_id,
                node_type=NodeType.CHARACTER,
                properties={
                    "canonical_name": member.canonical_name,
                    "description": _cast_graph_description(member),
                    "aliases": member.aliases,
                    "is_alive": True,
                },
            )
            for member in cast
        ]
        self.graph_store.replace_cast_characters_and_apply_mutations(
            story_id,
            keep_cast_node_ids=[member.node_id for member in cast],
            mutations=cast_mutations,
        )
        story_after = self.story_repository.get_story(story_id) or {}
        storylines = list(story_after.get("storylines_json") or [])
        anchor_nodes = list(story_after.get("anchor_nodes_json") or [])
        has_completed = self.story_repository.has_completed_chapter(story_id)
        return {
            "story_id": story_id,
            "bible": bible_generated,
            "macro_author_notes": str(story_after.get("macro_author_notes") or ""),
            "cast_seed": [
                s.model_dump(mode="json") for s in (story_after.get("cast_seed") or [])
            ],
            "volumes": [volume.model_dump(mode="json") for volume in volumes],
            "cast": [member.model_dump(mode="json") for member in cast],
            "protagonist_character_id": protagonist_id,
            "storylines": storylines,
            "anchor_nodes": anchor_nodes,
            "macro_topology_mode": "fixed_fishbone",
            "topology_locked": True,
            "has_completed_chapter": has_completed,
            "macro_edit_locked": has_completed,
        }

    def get_macro_snapshot(self, story_id: str) -> dict:
        """Read macro plan (volumes, anchor_nodes, cast) from SQLite without calling the LLM."""
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        vol_rows = self.story_repository.list_volumes(story_id)
        volumes = [
            VolumePlan(
                volume_id=str(row["volume_id"]),
                title=str(row["title"]),
                summary=str(row["summary"]),
                chapter_start=int(row["chapter_start"]),
                chapter_end=int(row["chapter_end"]),
                target_volume_words=int(row.get("target_volume_words") or 0),
            ).model_dump(mode="json")
            for row in vol_rows
        ]
        cast_out: list[dict] = []
        for raw in story.get("cast_json") or []:
            if not isinstance(raw, dict):
                continue
            try:
                cast_out.append(StoryCastMemberStored.model_validate(raw).model_dump(mode="json"))
            except Exception:
                continue
        protagonist_id = str(story.get("protagonist_character_id") or "").strip()
        bible_out = story.get("bible_json") if isinstance(story.get("bible_json"), dict) else {}
        has_completed = self.story_repository.has_completed_chapter(story_id)
        rt_out = dict(story.get("story_runtime_json") or {}) if isinstance(story.get("story_runtime_json"), dict) else {}
        return {
            "story_id": story_id,
            "bible": bible_out,
            "story_runtime": rt_out,
            "macro_author_notes": str(story.get("macro_author_notes") or ""),
            "cast_seed": [s.model_dump(mode="json") for s in (story.get("cast_seed") or [])],
            "volumes": volumes,
            "cast": cast_out,
            "protagonist_character_id": protagonist_id,
            "storylines": list(story.get("storylines_json") or []),
            "anchor_nodes": list(story.get("anchor_nodes_json") or []),
            "compiled": len(vol_rows) > 0,
            "macro_compile_status": str(story.get("macro_compile_status") or "IDLE"),
            "macro_compile_updated_at": str(story.get("macro_compile_updated_at") or ""),
            "macro_compile_error": str(story.get("macro_compile_error") or ""),
            "macro_topology_mode": "fixed_fishbone",
            "topology_locked": True,
            "has_completed_chapter": has_completed,
            "macro_edit_locked": has_completed,
        }

    def put_macro_plan(self, story_id: str, body: MacroPlanPut) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        body = _repair_macro_plan_mainline_cross_volume(body)
        _validate_macro_plan_put(body)
        if self.story_repository.has_completed_chapter(story_id):
            current_snapshot = self.get_macro_snapshot(story_id)
            _validate_macro_plan_put_under_completed_lock(body, current_snapshot)
        try:
            bible_out = dict(body.bible or {})
            protagonist_id = (body.protagonist_character_id or "").strip()
            if not protagonist_id:
                protagonist_id = next((c.node_id for c in body.cast if c.role == "protagonist"), "")
            self.story_repository.store_macro_plan_snapshot(
                story_id,
                bible=bible_out,
                storylines=[s.model_dump(mode="json") for s in body.storylines],
                anchor_nodes=[n.model_dump(mode="json") for n in body.anchor_nodes],
                volumes=list(body.volumes),
                cast=list(body.cast),
                protagonist_character_id=protagonist_id,
            )
            cast_mutations = [
                NodeMutation(
                    action="CREATE_NODE",
                    node_id=member.node_id,
                    node_type=NodeType.CHARACTER,
                    properties={
                        "canonical_name": member.canonical_name,
                        "description": _cast_graph_description(member),
                        "aliases": member.aliases,
                        "is_alive": True,
                    },
                )
                for member in body.cast
            ]
            self.graph_store.replace_cast_characters_and_apply_mutations(
                story_id,
                keep_cast_node_ids=[member.node_id for member in body.cast],
                mutations=cast_mutations,
            )
        except sqlite3.IntegrityError as exc:
            raise MacroPlanValidationError(
                "Macro plan contains IDs that violate DB uniqueness constraints "
                "(likely duplicated volume_id/anchor_id across stories)."
            ) from exc
        return self.get_macro_snapshot(story_id)

    def begin_macro_compile_async(self, story_id: str) -> None:
        """Acquire RUNNING lock or raise KeyError / MacroCompileAlreadyRunningError / MacroPlanCompletedChapterLockError."""
        if not self.story_repository.get_story(story_id):
            raise KeyError(f"Story not found: {story_id}")
        if self.story_repository.has_completed_chapter(story_id):
            raise MacroPlanCompletedChapterLockError(
                "Macro compile is disabled because at least one chapter is already completed. "
                "Editing the plot DAG (LOCKED/UNLOCKED nodes) remains available."
            )
        if not self.story_repository.try_begin_macro_compile(story_id):
            raise MacroCompileAlreadyRunningError(
                "Macro compile is already running for this story."
            )

    def execute_macro_compile_background(self, story_id: str) -> None:
        """Run macro_compile and persist terminal status (BackgroundTasks entry point)."""
        try:
            self.macro_compile(story_id)
        except Exception as exc:
            self.story_repository.finish_macro_compile(
                story_id, success=False, error_message=str(exc)[:500]
            )
            logger.exception("macro_compile background failed for %s", story_id)
            return
        self.story_repository.finish_macro_compile(story_id, success=True)

    def run_chapter(
        self,
        story_id: str,
        chapter_id: int,
        *,
        author_chapter_plan: str = "",
        chapter_outline: str = "",
        chapter_hard_rules: str = "",
        ai_freedom_level: str = "balanced",
        extraction_surface_hints: list[AuthorExtractionSurfaceHintEntry] | None = None,
        waive_mandatory_node_ids: list[str] | None = None,
        selected_anchor_ids: list[str] | None = None,
        next_anchor_ids: list[str] | None = None,
    ) -> dict:
        """Blocking: create run and execute graph to completion (tests / scripts)."""
        wf = self.start_run_chapter(
            story_id,
            chapter_id,
            author_chapter_plan=author_chapter_plan,
            chapter_outline=chapter_outline,
            chapter_hard_rules=chapter_hard_rules,
            ai_freedom_level=ai_freedom_level,
            extraction_surface_hints=extraction_surface_hints,
            waive_mandatory_node_ids=waive_mandatory_node_ids,
            selected_anchor_ids=selected_anchor_ids,
            next_anchor_ids=next_anchor_ids,
        )
        self.execute_stored_run(wf["run"]["run_id"])
        return self.get_workflow(wf["run"]["run_id"])

    def start_run_chapter(
        self,
        story_id: str,
        chapter_id: int,
        author_chapter_plan: str = "",
        chapter_outline: str = "",
        chapter_hard_rules: str = "",
        ai_freedom_level: str = "balanced",
        extraction_surface_hints: list[AuthorExtractionSurfaceHintEntry] | None = None,
        waive_mandatory_node_ids: list[str] | None = None,
        selected_anchor_ids: list[str] | None = None,
        next_anchor_ids: list[str] | None = None,
        require_chapter_review: bool | None = None,
    ) -> dict:
        """Create workflow run and persist initial state only (graph not executed yet)."""
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        existing = self.story_repository.get_chapter(story_id, chapter_id)
        if existing and (existing.get("status") or "").lower() == "completed":
            raise ChapterAlreadyCompletedError(
                f"Chapter {chapter_id} is already generated and stored (status=completed); "
                "full agent run is not allowed for this chapter."
            )
        pov_raw = (story.get("protagonist_character_id") or "").strip()
        pov_character_id = pov_raw if pov_raw else "char_public_observer"
        # Backward compatible:
        # - Prefer chapter_outline, fallback to legacy author_chapter_plan.
        outline = (chapter_outline or "").strip() or (author_chapter_plan or "").strip()
        outline = outline[:AUTHOR_CHAPTER_PLAN_MAX_CHARS]
        hard_rules = (chapter_hard_rules or "").strip()[:CHAPTER_HARD_RULES_MAX_CHARS]
        freedom = str(ai_freedom_level or "balanced").strip().lower()
        if freedom not in ("strict", "balanced", "wild"):
            freedom = "balanced"
        binding_mode = compute_outline_binding_mode(outline, outline)
        initial_state = build_initial_state(
            story_id=story_id,
            chapter_id=chapter_id,
            trace_id=str(uuid4()),
            plan_retry_limit=int(story.get("plan_retry_limit", 3)),
            draft_loop_retry_limit=int(story.get("draft_loop_retry_limit", 3)),
            pov_character_id=pov_character_id,
            author_chapter_plan=outline,
            chapter_outline=outline,
            chapter_hard_rules=hard_rules,
            ai_freedom_level=freedom,
            outline_binding_mode=binding_mode,
        )
        initial_state["workflow_thread_id"] = str(uuid4())
        initial_state["thread_reset_done"] = False
        initial_state["commit_executed"] = False
        initial_state["failure_type"] = ""
        initial_state["timeout_bucket"] = ""
        _ol = normalize_output_language(str(story.get("output_language") or ""))
        initial_state["story_output_language"] = _ol
        initial_state["target_word_count"] = default_chapter_target_words(_ol)
        # Per-run override beats story default; falls back to False when nothing is set.
        if require_chapter_review is not None:
            initial_state["require_chapter_review"] = bool(require_chapter_review)
        else:
            initial_state["require_chapter_review"] = bool(story.get("require_chapter_review") or False)

        # Tail-End Context Injection: provide the previous chapter trailing excerpt to this run.
        previous_tail = ""
        if chapter_id > 1:
            prev = self.story_repository.get_chapter(story_id, chapter_id - 1) or {}
            if (prev.get("status") or "").lower() == "completed":
                previous_tail = _extract_tail_excerpt(str(prev.get("content") or ""))
        initial_state["previous_chapter_tail_excerpt"] = previous_tail

        initial_state["recent_b_story_types"] = []

        # Director anti-repetition inputs:
        # - all milestones (macro pace memory)
        # - recent 3 chapter summaries (detail-level reminder)
        # - global top-3 frequencies (anti-pattern guardrails)
        try:
            initial_state["all_milestone_summaries"] = self.story_repository.list_all_milestones(story_id)
            initial_state["recent_chapter_summaries"] = self.story_repository.get_recent_chapter_summaries(
                story_id, int(chapter_id), limit=3
            )
            initial_state["global_conflict_type_top3"] = self.story_repository.global_top_conflict_type(story_id, top_k=3)
            initial_state["global_resolution_method_top3"] = self.story_repository.global_top_resolution_method(
                story_id, top_k=3
            )
            initial_state["resolution_cooldown_constraint"] = build_resolution_cooldown_constraint(
                initial_state["recent_chapter_summaries"]
            )
            initial_state["ending_vibe_cooldown_constraint"] = build_ending_vibe_cooldown_constraint(
                initial_state["recent_chapter_summaries"]
            )
        except Exception:
            # Best-effort: director prompt can still run without these.
            initial_state["all_milestone_summaries"] = []
            initial_state["recent_chapter_summaries"] = []
            initial_state["global_conflict_type_top3"] = []
            initial_state["global_resolution_method_top3"] = []
            initial_state["resolution_cooldown_constraint"] = {"active": False}
            initial_state["ending_vibe_cooldown_constraint"] = {"active": False}

        bible = story.get("bible_json") or {}
        rt = story.get("story_runtime_json") if isinstance(story.get("story_runtime_json"), dict) else {}
        initial_state["storyline_metadata"] = list(story.get("storylines_json") or [])
        initial_state["anchor_nodes"] = list(story.get("anchor_nodes_json") or [])
        initial_state["resolved_anchors"] = list(rt.get("resolved_anchors") or [])
        initial_state["anchor_candidates"] = list(rt.get("anchor_candidates") or [])
        # Canonical runtime source is anchor_nodes. Normalize legacy fields for consistency.
        node_ids = {str(n.get("id") or "").strip() for n in initial_state["anchor_nodes"] if str(n.get("id") or "").strip()}
        initial_node_by_id = {
            str(n.get("id") or "").strip(): n for n in initial_state["anchor_nodes"] if str(n.get("id") or "").strip()
        }
        initial_state["resolved_anchors"] = [x for x in initial_state["resolved_anchors"] if str(x).strip() in node_ids]
        if not initial_state["anchor_candidates"] and initial_state["anchor_nodes"]:
            initial_state["anchor_candidates"] = [
                str(n.get("id"))
                for n in initial_state["anchor_nodes"]
                if str(n.get("status") or "").upper() == "UNLOCKED" and not _is_terminal_anchor_node(n)
            ]
        else:
            initial_state["anchor_candidates"] = [
                x
                for x in initial_state["anchor_candidates"]
                if str(x).strip() in node_ids
                and not _is_terminal_anchor_node(initial_node_by_id[str(x).strip()])
            ]
        initial_state["active_anchors"] = []
        initial_state["state_version"] = 2
        initial_state["lore_mysteries_progression"] = list(rt.get("lore_mysteries_progression") or [])
        initial_state["general_world_lore"] = effective_general_world_lore(bible)
        _refresh_anchor_runtime_state(self.story_repository, initial_state)
        normalize_workflow_state(initial_state)
        canonicalize_workflow_state_contract(initial_state)
        apply_length_bounds_to_state(initial_state)
        if extraction_surface_hints:
            _merge_surface_hints(initial_state, extraction_surface_hints)
        if selected_anchor_ids:
            initial_state["selected_anchor_ids"] = [str(x).strip() for x in selected_anchor_ids if str(x).strip()][:2]
        if next_anchor_ids:
            initial_state["next_anchor_ids"] = [str(x).strip() for x in next_anchor_ids if str(x).strip()][:2]
        _validate_anchor_selection_guardrails(
            anchor_nodes=list(initial_state.get("anchor_nodes") or []),
            resolved_anchors=list(initial_state.get("resolved_anchors") or []),
            selected=list(initial_state.get("selected_anchor_ids") or []),
            nxt=list(initial_state.get("next_anchor_ids") or []),
        )
        if waive_mandatory_node_ids:
            cur = {str(x).strip() for x in (initial_state.get("mandatory_extraction_skips") or []) if str(x).strip()}
            cur.update(str(x).strip() for x in waive_mandatory_node_ids if str(x).strip())
            initial_state["mandatory_extraction_skips"] = sorted(cur)
        run = self.workflow_repository.create_run(story_id, chapter_id, initial_state)
        return self.get_workflow(run.run_id)

    def execute_stored_run(self, run_id: str) -> None:
        """Resume graph from DB state (used after start_run_chapter or HITL)."""
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        if int(state.get("state_version") or 1) < 2:
            state["workflow_status"] = WorkflowStatus.FAILED.value
            state["requires_hitl"] = False
            state["hitl_reason"] = "Legacy run is readonly after Anchor DAG V2 migration."
            self.workflow_repository.update_run(run_id, state)
            return
        if str(state.get("workflow_status") or "") == WorkflowStatus.CANCELLED.value:
            # Run was abandoned by the user; do not resume execution.
            return
        try:
            self._execute_workflow(run_id, state)
        except Exception as exc:
            try:
                state = self.workflow_repository.get_run_state(run_id)
                state["workflow_status"] = WorkflowStatus.FAILED.value
                state["requires_hitl"] = False
                state["hitl_reason"] = str(exc)[:500]
                state["failure_type"] = "TIMEOUT" if isinstance(exc, WorkflowNodeTimeoutError) else "ERROR"
                if isinstance(exc, WorkflowNodeTimeoutError):
                    node_name = str(exc.node_name or "").strip().lower()
                    state["timeout_bucket"] = "llm" if node_name in {"director", "planner", "author", "reader"} else "logic"
                else:
                    state["timeout_bucket"] = ""
                state["thread_reset_done"] = True
                state["workflow_thread_id"] = str(uuid4())
                state["pending_db_commit"] = {}
                state["commit_executed"] = False
                self.workflow_repository.update_run(run_id, state)
            except Exception:
                logger.exception(
                    "execute_stored_run could not persist FAILED state (run_id=%s)",
                    run_id,
                )
                raise
            # Do not re-raise: Starlette BackgroundTasks would log it as an ASGI error
            # even though the run is already marked FAILED in SQLite.
            logger.error(
                "Workflow run failed (run_id=%s)",
                run_id,
                exc_info=exc,
            )

    def get_workflow(self, run_id: str) -> dict:
        run = self.workflow_repository.get_run(run_id)
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        run_payload = run.model_dump(mode="json")
        if should_expose_hitl_context(state):
            hc = build_hitl_context_payload(state)
            run_payload["hitl_context"] = hc.model_dump(mode="json") if hc else None
        else:
            run_payload["hitl_context"] = None
        return {
            "run": run_payload,
            "state": state,
            "steps": self.workflow_repository.list_steps(run_id),
        }

    def get_story_workflow_metrics(self, story_id: str, *, limit: int = 200, offset: int = 0) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        summaries = self.workflow_repository.list_run_summaries_for_story(
            story_id, chapter_id=None, limit=limit, offset=offset
        )
        runs_metrics = []
        for s in summaries:
            rid = str(s["run_id"])
            state = normalize_workflow_state(self.workflow_repository.get_run_state(rid))
            steps = self.workflow_repository.list_steps(rid)
            hitl = self.workflow_repository.list_hitl_actions(rid, limit=500)
            runs_metrics.append(build_single_run_metrics(s, state, steps, hitl))
        rollup = rollup_metrics(runs_metrics)
        payload = WorkflowMetricsResponse(
            story_id=story_id,
            scope="story",
            chapter_id=None,
            rollup=rollup,
            runs=runs_metrics,
        )
        return payload.model_dump(mode="json")

    def get_chapter_workflow_metrics(self, story_id: str, chapter_id: int, *, limit: int = 200, offset: int = 0) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        chapter = self.story_repository.get_chapter(story_id, chapter_id)
        if not chapter:
            raise KeyError(f"Chapter not found: {story_id}:{chapter_id}")
        summaries = self.workflow_repository.list_run_summaries_for_story(
            story_id, chapter_id=chapter_id, limit=limit, offset=offset
        )
        runs_metrics = []
        for s in summaries:
            rid = str(s["run_id"])
            state = normalize_workflow_state(self.workflow_repository.get_run_state(rid))
            steps = self.workflow_repository.list_steps(rid)
            hitl = self.workflow_repository.list_hitl_actions(rid, limit=500)
            runs_metrics.append(build_single_run_metrics(s, state, steps, hitl))
        rollup = rollup_metrics(runs_metrics)
        payload = WorkflowMetricsResponse(
            story_id=story_id,
            scope="chapter",
            chapter_id=chapter_id,
            rollup=rollup,
            runs=runs_metrics,
        )
        return payload.model_dump(mode="json")

    def list_chapters(self, story_id: str) -> list[dict]:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        return self.story_repository.list_chapters(story_id)

    def list_hitl_actions(self, run_id: str, *, limit: int = 100, offset: int = 0) -> list[dict]:
        self.workflow_repository.get_run(run_id)
        return self.workflow_repository.list_hitl_actions(run_id, limit=limit, offset=offset)

    def get_chapter(self, story_id: str, chapter_id: int) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        chapter = self.story_repository.get_chapter(story_id, chapter_id)
        if not chapter:
            raise KeyError(f"Chapter not found: {story_id}:{chapter_id}")
        return chapter

    def regenerate_chapter_plot_summary(self, story_id: str, chapter_id: int) -> dict:
        """Re-run chapter_summarizer LLM path from stored chapter body (no workflow fallbacks)."""
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        chapter = self.story_repository.get_chapter(story_id, chapter_id)
        if not chapter:
            raise KeyError(f"Chapter not found: {story_id}:{chapter_id}")
        body = str(chapter.get("content") or "").strip()
        if not body:
            raise ValueError("Chapter has no content to summarize")

        ol = normalize_output_language(str(story.get("output_language") or ""))
        context = WorkflowContext(
            story_repository=self.story_repository,
            workflow_repository=self.workflow_repository,
            bible_service=self.bible_service,
            anchor_service=self.anchor_service,
            graph_store=self.graph_store,
            vector_store=self.vector_store,
            llm_client=self.llm_client,
            run_id=f"regenerate-summary:{story_id}:{chapter_id}",
            output_language=ol,
        )
        state = build_minimal_state_for_regenerate(
            story_id=story_id,
            chapter_id=chapter_id,
            chapter_content=body,
        )
        result = persist_chapter_summary(state, context, allow_fallback=False)
        if not result.get("written"):
            raise ChapterSummaryRegenerateFailed(str(result.get("error") or "Regenerate failed"))
        return {
            "regenerated": True,
            "plot_summary": result.get("plot_summary", ""),
            "plot_summary_source": result.get("plot_summary_source", ""),
        }

    def apply_hitl_decision(self, run_id: str, request: HitlDecisionRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        prev_hitl_reason = str(state.get("hitl_reason", "") or "")
        self.workflow_repository.append_hitl_action(run_id, "decision", request.model_dump(mode="json"))

        if request.option_id == "ABORT_AND_RESTART":
            _apply_abort_and_restart_chapter_state(self.story_repository, state)
            state["requires_hitl"] = False
            state["hitl_reason"] = ""
            state["hitl_decision_mode"] = "NONE"
            state["pending_hitl_options"] = []
            state["workflow_status"] = WorkflowStatus.RUNNING.value
            state["resume_from"] = "planner"
            self.workflow_repository.update_run(run_id, state)
            return

        if request.option_id == "RERUN_KEEP_DIRECTOR" and prev_hitl_reason == HitlReason.CHAPTER_DRAFT_REVIEW:
            _apply_abort_and_restart_chapter_state(self.story_repository, state)
            state["requires_hitl"] = False
            state["hitl_reason"] = ""
            state["hitl_decision_mode"] = "NONE"
            state["pending_hitl_options"] = []
            state["workflow_status"] = WorkflowStatus.RUNNING.value
            state["resume_from"] = "planner"
            self.workflow_repository.update_run(run_id, state)
            return

        if request.option_id == "ABANDON_CHAPTER" and prev_hitl_reason == HitlReason.CHAPTER_DRAFT_REVIEW:
            state["requires_hitl"] = False
            state["hitl_reason"] = ""
            state["hitl_decision_mode"] = "NONE"
            state["pending_hitl_options"] = []
            state["workflow_status"] = WorkflowStatus.CANCELLED.value
            state["resume_from"] = ""
            self.workflow_repository.update_run(run_id, state)
            return

        if request.option_id == "APPROVE_DRAFT" and prev_hitl_reason == HitlReason.CHAPTER_DRAFT_REVIEW:
            state["requires_hitl"] = False
            state["hitl_reason"] = ""
            state["hitl_decision_mode"] = "NONE"
            state["pending_hitl_options"] = []
            state["workflow_status"] = WorkflowStatus.RUNNING.value
            state["resume_from"] = "chunker"
            self.workflow_repository.update_run(run_id, state)
            return

        resume = str(state.get("resume_from") or "director")

        if request.option_id == "relax_word_count":
            state["target_word_count"] = max(800, int(state["target_word_count"] * 0.6))
            apply_length_bounds_to_state(state)
        if request.option_id in ("force_rewrite_plan", "allow_adjust_anchor"):
            state["plan_retry_count"] = 0
            state["plan_feedback"] = []
        if request.option_id == "force_approve_plan" and prev_hitl_reason == HitlReason.PLAN_LOOP_EXCEEDED:
            state["plan_retry_count"] = 0
            state["plan_feedback"] = []
            state["manual_plan_force_approve"] = True
            resume = "author"
        if request.option_id == "extraction_return_author" and prev_hitl_reason == HitlReason.EXTRACTION_GATE_FAILED:
            state["extraction_gate_failure_streak"] = 0
            resume = "author"
        if prev_hitl_reason == HitlReason.OUTPUT_LANGUAGE_MISMATCH:
            if request.option_id == "language_force_continue":
                state["output_language_hitl_waived"] = True
                resume = "output_language_gate"
            elif request.option_id == "language_return_author":
                state["output_language_hitl_waived"] = False
                note = (
                    "Output language check: chapter text likely does not match the story "
                    "output_language setting; rewrite the chapter body in the configured language."
                )
                draft_feedback = list(state.get("draft_feedback") or [])
                draft_feedback.append(
                    {
                        "attempt": int(state.get("draft_retry_count") or 0) + 1,
                        "violation": "OUTPUT_LANGUAGE",
                        "suggestion": "REWRITE",
                        "length_adjustment": "NONE",
                        "message": note,
                    }
                )
                state["draft_feedback"] = draft_feedback
                resume = "author"
        if request.option_id == "keep_current_logic":
            state["draft_loop_retry_count"] = 0
            state["draft_retry_count"] = 0
            state["reader_retry_count"] = 0

        if prev_hitl_reason == HitlReason.DRAFT_LOOP_EXCEEDED:
            state["draft_loop_retry_count"] = 0
            state["draft_retry_count"] = 0
            state["reader_retry_count"] = 0

        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["pending_hitl_options"] = []
        state["resume_from"] = resume
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_decision(self, run_id: str, request: HitlDecisionRequest) -> dict:
        self.apply_hitl_decision(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_outline_edit(self, run_id: str, request: HitlOutlineEditRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        if not request.ground_truth_events:
            raise ValueError("ground_truth_events must contain at least one event")
        prev_hitl_reason = str(state.get("hitl_reason", "") or "")
        state["ground_truth_events"] = [event.model_dump(mode="json") for event in request.ground_truth_events]
        if request.narrative_script:
            state["narrative_script"] = request.narrative_script
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        if prev_hitl_reason == HitlReason.PLAN_LOOP_EXCEEDED:
            state["resume_from"] = "planner"
        else:
            state["resume_from"] = "author"
        self.workflow_repository.append_hitl_action(run_id, "outline_edit", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_outline_edit(self, run_id: str, request: HitlOutlineEditRequest) -> dict:
        self.apply_hitl_outline_edit(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_state_injection(self, run_id: str, request: HitlStateInjectionRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        prev_hitl_reason = str(state.get("hitl_reason", "") or "")
        if prev_hitl_reason == HitlReason.ALIGNMENT_RULES_REQUIRED:
            rules = (request.chapter_hard_rules or "").strip()
            if not rules:
                raise ValueError("Alignment HITL requires non-empty chapter_hard_rules")
        resume = (request.resume_from or state.get("resume_from", "author") or "author").strip()
        if resume not in _ALLOWED_HITL_RESUME_NODES:
            resume = str(state.get("resume_from", "author") or "author")
        if request.mutations:
            self.graph_store.apply_mutations(state["story_id"], request.mutations)
        if request.cast_evolutions:
            pending = list(state.get("pending_cast_evolutions") or [])
            pending.extend([row.model_dump(mode="json") for row in request.cast_evolutions])
            state["pending_cast_evolutions"] = pending
        pacing = (request.this_chapter_pacing_limit or "").strip()
        state["this_chapter_pacing_limit"] = pacing[:2000] if pacing else ""
        if (request.future_anchor_title or "").strip() or (request.future_anchor_description or "").strip():
            _merge_hitl_future_anchor(
                self.story_repository,
                str(state["story_id"]),
                int(state["chapter_id"]),
                request.future_anchor_title,
                request.future_anchor_description,
                request.chapters_to_delay,
            )
            _refresh_anchor_runtime_state(self.story_repository, state)
        patched_rules = (request.chapter_hard_rules or "").strip()
        if patched_rules:
            state["chapter_hard_rules"] = patched_rules[:8000]
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        if prev_hitl_reason == HitlReason.ALIGNMENT_RULES_REQUIRED:
            state["resume_from"] = "logic_alignment"
        else:
            state["resume_from"] = resume
        self.workflow_repository.append_hitl_action(run_id, "state_injection", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_state_injection(self, run_id: str, request: HitlStateInjectionRequest) -> dict:
        self.apply_hitl_state_injection(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_draft_edit(self, run_id: str, request: HitlDraftEditRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        resume = (request.resume_from or "reader").strip()
        if resume not in _ALLOWED_HITL_RESUME_NODES:
            resume = "reader"
        state["current_draft"] = request.chapter_content
        best_raw = (request.best_draft_content or "").strip()
        state["best_draft_content"] = best_raw if best_raw else request.chapter_content
        if not request.merge_extraction_hints:
            state["author_extraction_surface_hints"] = []
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["resume_from"] = resume
        self.workflow_repository.append_hitl_action(run_id, "draft_edit", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_draft_edit(self, run_id: str, request: HitlDraftEditRequest) -> dict:
        self.apply_hitl_draft_edit(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_director_patch(self, run_id: str, request: HitlDirectorPatchRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        prev_hitl_reason = str(state.get("hitl_reason", "") or "")
        if request.chapter_type is not None:
            state["chapter_type"] = request.chapter_type
        if request.b_story_directive is not None:
            state["b_story_directive"] = request.b_story_directive
        if getattr(request, "b_story_type", None) is not None:
            state["b_story_type"] = request.b_story_type
        if request.new_elements_to_introduce is not None:
            state["new_elements_to_introduce"] = [
                e.model_dump(mode="json") for e in request.new_elements_to_introduce
            ]
        if request.request_new_b_story is not None:
            state["request_new_b_story"] = request.request_new_b_story.model_dump(mode="json")
        if request.narrative_directive is not None:
            state["narrative_directive"] = request.narrative_directive
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        if prev_hitl_reason == HitlReason.DRAFT_LOOP_EXCEEDED:
            state["resume_from"] = "author"
        else:
            state["resume_from"] = "planner"
        self.workflow_repository.append_hitl_action(run_id, "director_patch", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_director_patch(self, run_id: str, request: HitlDirectorPatchRequest) -> dict:
        self.apply_hitl_director_patch(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_extraction_hints(self, run_id: str, request: HitlExtractionHintsRequest) -> None:
        raise HitlExtractionHintsDisabledError(
            "extraction_surface_hints and waive_mandatory_node_ids belong in POST /stories/{id}/chapters/{n}/run "
            "(ChapterRunRequest), not /hitl/extraction-hints."
        )

    def handle_hitl_extraction_hints(self, run_id: str, request: HitlExtractionHintsRequest) -> dict:
        self.apply_hitl_extraction_hints(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_extraction_remap(self, run_id: str, request: HitlExtractionRemapRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        if not request.entity_remaps and not request.waive_mandatory_node_ids:
            raise ValueError("Provide at least one entity remap or one waive_mandatory_node_ids entry")
        for row in request.entity_remaps:
            if not str(row.from_node_id).strip() or not str(row.to_node_id).strip():
                raise ValueError("Each entity remap must have non-empty from_node_id and to_node_id")
        manual = list(state.get("manual_entity_remap") or [])
        for row in request.entity_remaps:
            manual.append({"from_node_id": row.from_node_id, "to_node_id": row.to_node_id})
        state["manual_entity_remap"] = manual
        if request.waive_mandatory_node_ids:
            cur = {str(x).strip() for x in (state.get("mandatory_extraction_skips") or []) if str(x).strip()}
            cur.update(str(x).strip() for x in request.waive_mandatory_node_ids if str(x).strip())
            state["mandatory_extraction_skips"] = sorted(cur)
        state["extraction_gate_failure_streak"] = 0
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["resume_from"] = "extraction_gate"
        self.workflow_repository.append_hitl_action(run_id, "extraction_remap", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_extraction_remap(self, run_id: str, request: HitlExtractionRemapRequest) -> dict:
        self.apply_hitl_extraction_remap(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_b_story_judgement(self, run_id: str, request: HitlBStoryJudgementRequest) -> None:
        mapped = HitlAnchorResolutionRequest(
            action="force_resolve" if request.action == "force_resolve" else "rewrite",
            resolved_anchor_ids=list(request.resolved_b_stories or []),
            reject_resume_from=request.reject_resume_from or "planner",
            reason=request.reason or request.resolution_analysis or "",
        )
        self.apply_hitl_anchor_resolution(run_id, mapped)

    def handle_hitl_b_story_judgement(self, run_id: str, request: HitlBStoryJudgementRequest) -> dict:
        self.apply_hitl_b_story_judgement(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_anchor_resolution(self, run_id: str, request: HitlAnchorResolutionRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        resolved = set(str(x).strip() for x in (state.get("resolved_anchors") or []) if str(x).strip())
        if request.action == "force_resolve":
            resolved.update(str(x).strip() for x in request.resolved_anchor_ids if str(x).strip())
            state["resolved_anchors"] = sorted(resolved)
            # Keep standard graph handoff to ensure pending cast evolution materializes.
            state["resume_from"] = "profile_expander"
        elif request.action == "delay_anchor":
            delayed = {str(x).strip() for x in request.delayed_anchor_ids if str(x).strip()}
            state["anchor_candidates"] = [x for x in (state.get("anchor_candidates") or []) if str(x) not in delayed]
            state["resume_from"] = "planner"
        else:
            resume = (request.reject_resume_from or "planner").strip()
            if resume not in _ALLOWED_HITL_RESUME_NODES:
                resume = "planner"
            state["resume_from"] = resume
            fb = list(state.get("draft_feedback") or [])
            fb.append(
                {
                    "attempt": int(state.get("draft_retry_count", 0) or 0) + 1,
                    "violation": "ANCHOR_RESOLUTION_REJECTED",
                    "suggestion": "REWRITE",
                    "message": request.reason or "Anchor 目標未達成，請依選定錨點重規劃或重寫章節。",
                }
            )
            state["draft_feedback"] = fb

        state["anchor_hitl_required"] = False
        state["anchor_resolution_hitl_candidate"] = {}
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        self.workflow_repository.append_hitl_action(run_id, "anchor_resolution", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_anchor_resolution(self, run_id: str, request: HitlAnchorResolutionRequest) -> dict:
        self.apply_hitl_anchor_resolution(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_anchor_delay(self, run_id: str, request: HitlAnchorDelayRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        story_id = str(state["story_id"])
        story = self.story_repository.get_story(story_id) or {}
        storylines = [dict(x) for x in (story.get("storylines_json") or []) if isinstance(x, dict)]
        nodes = [dict(n) for n in (story.get("anchor_nodes_json") or []) if isinstance(n, dict)]
        updated = False
        for node in nodes:
            if str(node.get("id") or "").strip() != str(request.anchor_id).strip():
                continue
            props = dict(node.get("properties") or {})
            props["hitl_deferred"] = True
            node["properties"] = props
            updated = True
            break
        if not updated:
            raise KeyError(f"Anchor not found: {story_id}/{request.anchor_id}")
        self.story_repository.update_story_macro_topology(story_id, storylines=storylines, anchor_nodes=nodes)
        _refresh_anchor_runtime_state(self.story_repository, state)
        state["plan_retry_count"] = 0
        state["plan_feedback"] = []
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["resume_from"] = "planner"
        self.workflow_repository.append_hitl_action(run_id, "anchor_delay", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_anchor_delay(self, run_id: str, request: HitlAnchorDelayRequest) -> dict:
        self.apply_hitl_anchor_delay(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_context_prune(self, run_id: str, request: HitlContextPruneRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        state["graph_rag_context_tier"] = _internal_graph_rag_tier_from_product(int(request.graph_rag_context_tier))
        state["context_overflow_char_estimate"] = 0
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["resume_from"] = "graph_rag"
        self.workflow_repository.append_hitl_action(run_id, "context_prune", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_context_prune(self, run_id: str, request: HitlContextPruneRequest) -> dict:
        self.apply_hitl_context_prune(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def replay_state_transaction(self, transaction_id: str) -> dict:
        transaction = self.workflow_repository.get_state_transaction(transaction_id)
        payload = deepcopy(transaction.payload)
        parsed_output = StateUpdaterOutput.model_validate(payload["state_updater_output"])

        if not transaction.graph_applied:
            self.graph_store.apply_mutations(transaction.story_id, parsed_output.mutations)
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.GRAPH_APPLIED,
                graph_applied=True,
                error_text="",
            )

        if not transaction.vector_applied:
            self.vector_store.add_documents(transaction.story_id, parsed_output.vector_documents)
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.VECTOR_APPLIED,
                vector_applied=True,
                error_text="",
            )

        if not transaction.sqlite_applied:
            self.story_repository.upsert_chapter_content(
                story_id=transaction.story_id,
                chapter_id=transaction.chapter_id,
                title=payload["chapter_title"],
                content=payload["chapter_content"],
                status="completed",
            )
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.SQLITE_APPLIED,
                sqlite_applied=True,
                error_text="",
            )

        final_record = self.workflow_repository.update_state_transaction(
            transaction_id,
            status=StateTransactionStatus.COMMITTED,
            error_text="",
        )
        return final_record.model_dump(mode="json")
