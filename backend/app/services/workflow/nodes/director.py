from __future__ import annotations

import json
from typing import Any

from app.domain.schema import BStoryType, ChapterType, DirectorNewElement, DirectorOutput
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import visible_unachieved_anchors
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile


def _active_b_stories_nonempty(active: list) -> bool:
    for row in active or []:
        if isinstance(row, dict) and str(row.get("id") or "").strip():
            return True
    return False


def normalize_director_output(state: dict, raw: dict) -> dict:
    """Graceful degradation: fill chapter_type / b_story when distance>=2 and pool empty."""
    out = dict(raw)
    dist = state.get("distance_to_anchor")
    active = state.get("active_b_stories") or []
    bdir = (out.get("b_story_directive") or "").strip()
    try:
        dval = int(dist) if dist is not None else None
    except (TypeError, ValueError):
        dval = None
    if dval is not None and dval >= 2:
        if not _active_b_stories_nonempty(active) or not bdir:
            out["chapter_type"] = ChapterType.WORLD_BUILDING.value
            out["b_story_directive"] = (
                bdir
                or "Explore surroundings and local texture; accumulate sensory and everyday detail without forcing the main plot."
            )
            out.setdefault("b_story_type", BStoryType.UNKNOWN.value)
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
    out["director_state_brief"] = str(out.get("state_operational_brief") or "").strip()
    return out


def run_director(state: dict, context: WorkflowContext) -> dict:
    anchors = state.get("unachieved_anchors", [])
    next_anchor = anchors[0] if anchors else None
    anchor_prompt_window = visible_unachieved_anchors(state)
    story = context.story_repository.get_story(state["story_id"]) or {}
    active = state.get("active_b_stories") or []
    volumes = context.story_repository.list_volumes(state["story_id"])
    bible_context = context.bible_service.compile_context(
        story.get("bible_json") or {},
        macro_author_notes=str(story.get("macro_author_notes") or ""),
    )
    current_volume = _resolve_current_volume(state["chapter_id"], volumes)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = augment_profile_system_prompt(get_profile("director"), context.output_language)
        prompt = _build_director_prompt(
            state, story, volumes, next_anchor, anchor_prompt_window, bible_context, current_volume
        )
        output, _ = context.llm_client.invoke_json(prompt, DirectorOutput, profile)
        return normalize_director_output(state, output.model_dump(mode="json"))

    dist = state.get("distance_to_anchor")
    dval = int(dist) if isinstance(dist, int) else 0
    b_first = (active[0].get("desc") if active and isinstance(active[0], dict) else None) or None
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
        b_story_directive=b_first,
        b_story_type=(active[0].get("type") if active and isinstance(active[0], dict) else None),
        new_elements_to_introduce=(
            [
                DirectorNewElement(
                    need="Spotlight a supporting character",
                    reason="Use character texture to pace the chapter and support the investigation thrust.",
                )
            ]
            if mock_type != ChapterType.PLOT_DRIVEN
            else []
        ),
        request_new_b_story=None,
        state_operational_brief="(Mock) Sparse-outline brief: progress using anchors, B-story pool, and distance_to_anchor.",
    )
    return normalize_director_output(state, output.model_dump(mode="json"))


def _build_director_prompt(
    state: dict,
    story: dict[str, Any],
    volumes: list[dict[str, Any]],
    next_anchor: dict[str, Any] | None,
    visible_unachieved_anchors: list[dict[str, Any]],
    bible_context: str = "",
    current_volume: dict[str, Any] | None = None,
) -> str:
    vol = current_volume if current_volume is not None else _resolve_current_volume(state["chapter_id"], volumes)
    vol = vol or {}

    milestones = state.get("all_milestone_summaries") or []
    milestone_lines: list[str] = []
    for ms in milestones:
        if not isinstance(ms, dict):
            continue
        cs = ms.get("chapter_start")
        ce = ms.get("chapter_end")
        summ = str(ms.get("milestone_summary") or "")
        if cs is None or ce is None or not summ:
            continue
        milestone_lines.append(f"- [{cs}-{ce}]: {summ[:600]}")
    milestone_block = "\n".join(milestone_lines) if milestone_lines else "- (No milestone summaries yet)"

    recent_summaries = state.get("recent_chapter_summaries") or []
    recent_lines: list[str] = []
    for rs in recent_summaries:
        if not isinstance(rs, dict):
            continue
        cid = rs.get("chapter_id")
        plot = str(rs.get("plot_summary") or "")
        ctype = rs.get("conflict_type") or ""
        rmethod = rs.get("resolution_method") or ""
        if cid is None or not plot:
            continue
        recent_lines.append(f"- Ch.{cid}: {plot[:420]} | conflict_type={ctype} | resolution_method={rmethod}")
    recent_block = "\n".join(recent_lines) if recent_lines else "- (No recent summaries yet)"

    top_conf = state.get("global_conflict_type_top3") or []
    top_conf_lines: list[str] = []
    for row in top_conf:
        if not isinstance(row, dict):
            continue
        top_conf_lines.append(f"- {row.get('conflict_type')}: {row.get('cnt')}")
    top_conf_block = "\n".join(top_conf_lines) if top_conf_lines else "- (No stats yet)"

    top_res = state.get("global_resolution_method_top3") or []
    top_res_lines: list[str] = []
    for row in top_res:
        if not isinstance(row, dict):
            continue
        top_res_lines.append(f"- {row.get('resolution_method')}: {row.get('cnt')}")
    top_res_block = "\n".join(top_res_lines) if top_res_lines else "- (No stats yet)"
    cooldown = state.get("resolution_cooldown_constraint") or {}
    vibe_cooldown = state.get("ending_vibe_cooldown_constraint") or {}
    writing_note = [str(x).strip() for x in (state.get("writing_note") or []) if str(x).strip()]
    lore = state.get("lore_mysteries_progression") or []
    lore_lines: list[str] = []
    for row in lore:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("mystery_id") or "").strip()
        desc = str(row.get("description") or "").strip()
        pending = row.get("pending_stages") or []
        next_stage = pending[0] if isinstance(pending, list) and pending else {}
        if mid and next_stage:
            lore_lines.append(f"- {mid}: {desc} | next_stage={next_stage}")
    lore_block = "\n".join(lore_lines) if lore_lines else "- (No pending lore mystery stages)"
    writing_note_block = "\n".join(f"- {x}" for x in writing_note[:10]) if writing_note else "- (none)"
    cooldown_block = (cooldown.get("ban_text") or "none")
    vibe_block = (vibe_cooldown.get("interrupt_text") or "none")

    ap = (state.get("chapter_outline") or state.get("author_chapter_plan") or "").strip()
    freedom = str(state.get("ai_freedom_level") or "balanced")
    bind = str(state.get("outline_binding_mode") or "ABSENT")
    author_plan_block = ""
    if ap:
        if bind == "FULL":
            author_plan_block = (
                "## Human chapter outline (outline_binding_mode=FULL; binding when ai_freedom_level=strict)\n"
                "Do not invent main-plot turns in narrative_directive that contradict the following; only restate/structure.\n"
                f"{ap[:1600]}\n\n"
            )
        elif bind == "PARTIAL":
            author_plan_block = (
                "## Human chapter outline (outline_binding_mode=PARTIAL; fragment—Planner fills blanks)\n"
                f"{ap[:1600]}\n\n"
            )
        else:
            author_plan_block = f"## Human chapter outline\n{ap[:1600]}\n\n"
    mode_block = (
        "## Execution mode (system fields)\n"
        f"- ai_freedom_level: {freedom}\n"
        f"- outline_binding_mode: {bind}\n\n"
    )

    return (
        "## Chapter placement\n"
        f"- chapter_id: {state['chapter_id']}\n\n"
        "## Story core\n"
        f"- story_title: {story.get('title', '')}\n"
        f"- story_premise: {story.get('premise', '')}\n\n"
        "## Current volume (pacing reference; chapter length is decided later by Planner—not hard-tied to volume word budget)\n"
        f"- volume_title: {vol.get('title', '')}\n"
        f"- volume_summary: {vol.get('summary', '')}\n"
        f"- volume_chapter_range: {(vol.get('chapter_start', ''), vol.get('chapter_end', ''))}\n\n"
        "## Primary thrust this chapter\n"
        f"- current_anchor_id: {(next_anchor or {}).get('anchor_id')}\n"
        f"- current_anchor_title: {(next_anchor or {}).get('title', '')}\n"
        f"- current_anchor_description: {(next_anchor or {}).get('description', '')}\n"
        "- visible_unachieved_anchors: sliding window of the nearest unfinished anchors for mid-term rhythm; "
        "**this chapter still centers on current_anchor**—do not script concrete beats or spoilers for far future anchors.\n"
        f"- visible_unachieved_anchors: {json.dumps(visible_unachieved_anchors, ensure_ascii=False)}\n\n"
        "## World and state context\n"
        f"- bible_context: {bible_context[:1800]}\n"
        f"- graph_hint: {state.get('graph_context', '')[:1800]}\n"
        f"- previous_chapter_tail_excerpt: {(state.get('previous_chapter_tail_excerpt') or '')[:800]}\n"
        f"- distance_to_anchor: {state.get('distance_to_anchor')}\n"
        f"- recent_b_story_types: {json.dumps(state.get('recent_b_story_types') or [], ensure_ascii=False)[:800]}\n"
        f"- active_b_stories: {json.dumps(state.get('active_b_stories') or [], ensure_ascii=False)[:1200]}\n\n"
        "## Macro rhythm memory (all milestones to date)\n"
        f"{milestone_block}\n\n"
        "## Last ~3 chapter structured summaries (conflict_type + resolution_method)\n"
        f"{recent_block}\n\n"
        "## Global trope stats (Top-3)\n"
        "conflict_type counts:\n"
        f"{top_conf_block}\n"
        "resolution_method counts:\n"
        f"{top_res_block}\n\n"
        "## Lore mystery progression (pending stages)\n"
        f"{lore_block}\n\n"
        "## Writing notes (global craft rules)\n"
        f"{writing_note_block}\n\n"
        f"{mode_block}"
        f"{author_plan_block}"
        "## System hard constraints (must obey)\n"
        f"- resolution_tactic_cooldown: {cooldown_block}\n"
        f"- ending_vibe_cooldown: {vibe_block}\n\n"
        "## Output requirements\n"
        "- You MUST output state_operational_brief as short bullet sentences in the story output_language: anchor distance, open B-story threads, continuity/spatial state, and Planner execution reminders.\n"
        "- Choose chapter_type (PLOT_DRIVEN / CHARACTER_DRIVEN / WORLD_BUILDING), POV, Epoch, tone, narrative_directive.\n"
        "- If distance_to_anchor >= 2: chapter_type MUST be CHARACTER_DRIVEN or WORLD_BUILDING, "
        "pick one active_b_story into b_story_directive, and output b_story_type matching that row's type. "
        "If b_story_type is in the recent_b_story_types ban list, that is a violation requiring manual HITL correction.\n"
        "- Anti-repeat: avoid repeating the global Top-3 conflict_type + resolution_method pairings; if your idea lands in Top-3, pivot.\n"
        "- Anti-rut: avoid the same forward beat as the last 3 plot_summary entries (same conflict + same resolution cadence).\n"
        "- If distance_to_anchor is 0 or 1: chapter_type MUST be PLOT_DRIVEN and drive hard toward target_anchor.\n"
        "- For CHARACTER_DRIVEN or WORLD_BUILDING, new_elements_to_introduce needs at least one item; "
        "each item is {need, reason}: need names the object/variable; reason explains why this chapter needs it (pressure, intel gap, etc.). "
        "Avoid duplicating graph proper names.\n"
        "- If you want to slow the spine or add friction with a **new** B-story: output request_new_b_story {type, purpose}; "
        "type must be a BStoryType and must NOT be on the recent_b_story_types cooldown list.\n"
        "- If no new B-story is needed, set request_new_b_story to null.\n"
        "- narrative_directive must name new plot advancement—not only mood continuation.\n"
        "- If the chapter involves movement, infiltration, extraction, or chase, spell out start, destination, or end-of-chapter effective position.\n"
        "- If there are secret actions, narrative_directive should name their dramatic function without treating secrets as public common knowledge.\n"
        "- When system hard constraints are active, narrative_directive must specify replacement tactics and ending rhythm—do not reuse banned patterns.\n"
    )


def _resolve_current_volume(chapter_id: int, volumes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for volume in volumes:
        start = volume.get("chapter_start")
        end = volume.get("chapter_end")
        if isinstance(start, int) and isinstance(end, int) and start <= chapter_id <= end:
            return volume
    return None
