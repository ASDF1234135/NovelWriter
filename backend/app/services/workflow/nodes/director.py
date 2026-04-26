from __future__ import annotations

import json
from typing import Any

from app.domain.schema import ChapterType, DirectorOutput
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import visible_unachieved_anchors
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile


def normalize_director_output(state: dict, raw: dict) -> dict:
    """Normalize director output under Anchor DAG semantics."""
    out = dict(raw)
    dist = state.get("distance_to_anchor")
    active = state.get("active_b_stories") or []
    bdir = (out.get("b_story_directive") or "").strip()
    try:
        dval = int(dist) if dist is not None else None
    except (TypeError, ValueError):
        dval = None
    # Backward-compatible fallback for legacy tests/runs.
    if dval is not None and dval >= 2:
        has_active_story = any(isinstance(row, dict) and str(row.get("id") or "").strip() for row in active)
        if not has_active_story or not bdir:
            out["chapter_type"] = ChapterType.WORLD_BUILDING.value
            out["b_story_directive"] = (
                bdir
                or "Explore surroundings and local texture; accumulate sensory and everyday detail without forcing the main plot."
            )
    if dval is not None and dval <= 1:
        out["chapter_type"] = ChapterType.PLOT_DRIVEN.value
    ct = str(out.get("chapter_type") or ChapterType.PLOT_DRIVEN.value)
    neo_raw = list(out.get("new_elements_to_introduce") or [])
    neo: list[dict[str, str]] = []
    for item in neo_raw:
        if isinstance(item, str):
            t = item.strip()
            if t:
                neo.append({"need": t, "reason": ""})
        elif isinstance(item, dict):
            need = str(item.get("need") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if need or reason:
                neo.append({"need": need, "reason": reason})
    if ct in (ChapterType.CHARACTER_DRIVEN.value, ChapterType.WORLD_BUILDING.value) and not neo:
        neo = [
            {
                "need": "A chapter-scale narrative variable (pick one: background figure, location, or prop; avoid duplicating existing graph proper names).",
                "reason": "This chapter type needs at least one tangible new element so the chapter is not only rehashing prior context.",
            }
        ]
    out["new_elements_to_introduce"] = neo
    selected = [str(x).strip() for x in (out.get("selected_anchor_ids") or []) if str(x).strip()]
    if not selected and out.get("target_anchor_id"):
        selected = [str(out.get("target_anchor_id"))]
    out["selected_anchor_ids"] = selected[:2]
    nxt = [str(x).strip() for x in (out.get("next_anchor_ids") or []) if str(x).strip()]
    if not nxt:
        candidates = [str(x).strip() for x in (state.get("anchor_candidates") or []) if str(x).strip()]
        nxt = [x for x in candidates if x not in set(selected)][:2]
    # Guardrails: next anchors must be unresolved + dependency-ready + ending-reachable.
    resolved = {str(x).strip() for x in (state.get("resolved_anchors") or []) if str(x).strip()}
    nodes = {str(n.get("id")): n for n in (state.get("anchor_nodes") or []) if isinstance(n, dict)}
    children: dict[str, list[str]] = {nid: [] for nid in nodes.keys()}
    for nid, row in nodes.items():
        for dep in row.get("depends_on") or []:
            dep_id = str(dep).strip()
            if dep_id in children:
                children[dep_id].append(nid)
    ending_ids = {
        nid
        for nid, row in nodes.items()
        if str(row.get("node_kind") or "").upper() == "ENDING" or "ending" in str(row.get("title") or "").lower()
    }
    if not ending_ids and nodes:
        ending_ids = {next(reversed(nodes.keys()))}

    def _reachable_to_ending(start: str) -> bool:
        stack = [start]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in ending_ids:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(children.get(cur, []))
        return False

    allowed: list[str] = []
    for nid in nxt:
        row = nodes.get(nid) or {}
        deps = [str(x).strip() for x in (row.get("depends_on") or []) if str(x).strip()]
        if nid in resolved:
            continue
        if any(dep not in resolved and dep not in selected for dep in deps):
            continue
        if str(row.get("node_kind") or "").upper() in {"CHECKPOINT", "ENDING"}:
            continue
        if not _reachable_to_ending(nid):
            continue
        allowed.append(nid)
    if not allowed:
        for nid in (state.get("anchor_candidates") or []):
            if not isinstance(nid, str) or nid in resolved:
                continue
            if nid in nodes and _reachable_to_ending(nid):
                allowed.append(nid)
    out["next_anchor_ids"] = allowed[:2]
    out["director_state_brief"] = str(out.get("state_operational_brief") or "").strip()
    return out


def run_director(state: dict, context: WorkflowContext) -> dict:
    selected_by_user = [str(x).strip() for x in (state.get("selected_anchor_ids") or []) if str(x).strip()]
    if selected_by_user:
        return {
            "selected_anchor_ids": selected_by_user[:2],
            "next_anchor_ids": [str(x).strip() for x in (state.get("next_anchor_ids") or []) if str(x).strip()][:2],
            "director_state_brief": "User pre-selected anchors; director bypassed.",
        }

    anchors = state.get("unachieved_anchors", [])
    next_anchor = anchors[0] if anchors else None
    story = context.story_repository.get_story(state["story_id"]) or {}
    volumes = context.story_repository.list_volumes(state["story_id"])
    bible_context = context.bible_service.compile_context(
        story.get("bible_json") or {},
        macro_author_notes=str(story.get("macro_author_notes") or ""),
    )
    previous_outline = _previous_chapter_outline(state)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = augment_profile_system_prompt(get_profile("director"), context.output_language)
        prompt = _build_director_prompt(state, story, next_anchor, bible_context, previous_outline)
        output, _ = context.llm_client.invoke_json(prompt, DirectorOutput, profile)
        return normalize_director_output(state, output.model_dump(mode="json"))

    dval = int(state.get("distance_to_anchor") or 0)
    mock_type = ChapterType.PLOT_DRIVEN if dval <= 1 else ChapterType.CHARACTER_DRIVEN
    output = DirectorOutput(
        chapter_id=state["chapter_id"],
        active_epoch_id="epoch_present",
        pov_character_id=state.get("pov_character_id") or "char_public_observer",
        narrative_directive=(
            f"Advance chapter {state['chapter_id']} toward anchor “{next_anchor['title']}”"
            if next_anchor
            else f"Advance chapter {state['chapter_id']} toward finale closure"
        ),
        tone_direction="tense, restrained suspense",
        target_anchor_id=next_anchor["anchor_id"] if next_anchor else None,
        chapter_type=mock_type,
        selected_anchor_ids=([next_anchor["anchor_id"]] if next_anchor else []),
        next_anchor_ids=[str(a.get("anchor_id")) for a in anchors[1:3] if isinstance(a, dict)],
        b_story_directive=None,
        b_story_type=None,
        new_elements_to_introduce=[],
        request_new_b_story=None,
        state_operational_brief=(
            "Director selects chapter anchors from bible context and previous chapter outline "
            "when user selection is absent."
        ),
    )
    return normalize_director_output(state, output.model_dump(mode="json"))


def _build_director_prompt(
    state: dict,
    story: dict[str, Any],
    next_anchor: dict[str, Any] | None,
    bible_context: str = "",
    previous_outline: str = "",
) -> str:
    window = visible_unachieved_anchors(state)
    return (
        "Director scope: choose chapter navigation anchors only.\n"
        "Do not design pacing, B-story, or new elements.\n\n"
        "## Chapter\n"
        f"- chapter_id: {state['chapter_id']}\n\n"
        "## Story Core\n"
        f"- story_title: {story.get('title', '')}\n"
        f"- story_premise: {story.get('premise', '')}\n\n"
        "## Anchor Context\n"
        f"- current_anchor_id: {(next_anchor or {}).get('anchor_id')}\n"
        f"- current_anchor_title: {(next_anchor or {}).get('title', '')}\n"
        f"- current_anchor_description: {(next_anchor or {}).get('description', '')}\n"
        f"- visible_unachieved_anchors: {json.dumps(window, ensure_ascii=False)}\n\n"
        "## Inputs You Must Use\n"
        f"- bible_context: {bible_context[:1800]}\n"
        f"- previous_chapter_outline: {previous_outline[:1200]}\n\n"
        "## Output Requirements\n"
        "- Choose selected_anchor_ids with 1-2 anchor ids for this chapter.\n"
        "- Choose next_anchor_ids with 1-2 reachable unresolved ids for the next chapter.\n"
        "- Keep chapter_type conservative (PLOT_DRIVEN unless evidence supports otherwise).\n"
        "- Keep narrative_directive concise and anchor-focused.\n"
        "- Keep b_story_directive empty unless required by bible continuity.\n"
        "- Keep new_elements_to_introduce empty by default.\n"
        "- state_operational_brief must be 1-3 short lines explaining why the selected anchors fit bible + previous chapter outline.\n"
        "- Never assume user-selected anchors in this node; director is called only when user did not select anchors.\n"
        "- Do not output extra meta commentary.\n"
    )


def _previous_chapter_outline(state: dict) -> str:
    rows = state.get("recent_chapter_summaries") or []
    if not isinstance(rows, list):
        return ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("plot_summary") or "").strip()
        if text:
            return text
    return str(state.get("previous_chapter_summary") or "").strip()


def _resolve_current_volume(chapter_id: int, volumes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for volume in volumes:
        start = volume.get("chapter_start")
        end = volume.get("chapter_end")
        if isinstance(start, int) and isinstance(end, int) and start <= chapter_id <= end:
            return volume
    return None
