from __future__ import annotations

import json
from typing import Any

from app.domain.schema import BStoryType, ChapterType, DirectorNewElement, DirectorOutput
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import visible_unachieved_anchors
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
                or "探索周遭環境與風土民情，累積感官與生活細節，不強制推進主線。"
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
                "need": "本章敘事變數（背景人物、地點或道具擇一，勿與 graph 既有專名重複）",
                "reason": "章節類型需要至少一項可觀的新元素，避免只重述前情。",
            }
        ]
    out["new_elements_to_introduce"] = neo
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
        profile = get_profile("director")
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
            f"推進第 {state['chapter_id']} 章，朝向錨點「{next_anchor['title']}」前進"
            if next_anchor
            else f"推進第 {state['chapter_id']} 章的結局收束"
        ),
        tone_direction="懸疑壓抑",
        target_anchor_id=next_anchor["anchor_id"] if next_anchor else None,
        chapter_type=mock_type,
        b_story_directive=b_first,
        b_story_type=(active[0].get("type") if active and isinstance(active[0], dict) else None),
        new_elements_to_introduce=(
            [
                DirectorNewElement(
                    need="側寫配角",
                    reason="本章以人物細節支撐節奏，服務主線調查方向。",
                )
            ]
            if mock_type != ChapterType.PLOT_DRIVEN
            else []
        ),
        request_new_b_story=None,
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
    milestone_block = "\n".join(milestone_lines) if milestone_lines else "-（尚無里程碑摘要）"

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
        recent_lines.append(f"- 第{cid}章: {plot[:420]} | conflict_type={ctype} | resolution_method={rmethod}")
    recent_block = "\n".join(recent_lines) if recent_lines else "-（尚無近期摘要）"

    top_conf = state.get("global_conflict_type_top3") or []
    top_conf_lines: list[str] = []
    for row in top_conf:
        if not isinstance(row, dict):
            continue
        top_conf_lines.append(f"- {row.get('conflict_type')}: {row.get('cnt')}")
    top_conf_block = "\n".join(top_conf_lines) if top_conf_lines else "-（尚無統計）"

    top_res = state.get("global_resolution_method_top3") or []
    top_res_lines: list[str] = []
    for row in top_res:
        if not isinstance(row, dict):
            continue
        top_res_lines.append(f"- {row.get('resolution_method')}: {row.get('cnt')}")
    top_res_block = "\n".join(top_res_lines) if top_res_lines else "-（尚無統計）"
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
    lore_block = "\n".join(lore_lines) if lore_lines else "-（無待揭露謎團階段）"
    writing_note_block = "\n".join(f"- {x}" for x in writing_note[:10]) if writing_note else "-（無）"
    cooldown_block = (cooldown.get("ban_text") or "無")
    vibe_block = (vibe_cooldown.get("interrupt_text") or "無")

    return (
        "## 章節定位\n"
        f"- chapter_id: {state['chapter_id']}\n\n"
        "## 故事核心\n"
        f"- story_title: {story.get('title', '')}\n"
        f"- story_premise: {story.get('premise', '')}\n\n"
        "## 當前卷資訊（敘事節奏參考；本章字數由後續 Planner 決定，與卷字數預算無硬性綁定）\n"
        f"- volume_title: {vol.get('title', '')}\n"
        f"- volume_summary: {vol.get('summary', '')}\n"
        f"- volume_chapter_range: {(vol.get('chapter_start', ''), vol.get('chapter_end', ''))}\n\n"
        "## 本章主要推進目標\n"
        f"- current_anchor_id: {(next_anchor or {}).get('anchor_id')}\n"
        f"- current_anchor_title: {(next_anchor or {}).get('title', '')}\n"
        f"- current_anchor_description: {(next_anchor or {}).get('description', '')}\n"
        "- visible_unachieved_anchors: 以下僅列出「最近數個」尚未達成的錨點（滑動視窗），"
        "供你把握中期節奏；**本章仍以 current_anchor 為主**，勿替更遠的錨點編排具體情節或劇透。\n"
        f"- visible_unachieved_anchors: {json.dumps(visible_unachieved_anchors, ensure_ascii=False)}\n\n"
        "## 世界與狀態背景\n"
        f"- bible_context: {bible_context[:1800]}\n"
        f"- graph_hint: {state.get('graph_context', '')[:1800]}\n"
        f"- previous_chapter_tail_excerpt: {(state.get('previous_chapter_tail_excerpt') or '')[:800]}\n"
        f"- distance_to_anchor: {state.get('distance_to_anchor')}\n"
        f"- recent_b_story_types: {json.dumps(state.get('recent_b_story_types') or [], ensure_ascii=False)[:800]}\n"
        f"- active_b_stories: {json.dumps(state.get('active_b_stories') or [], ensure_ascii=False)[:1200]}\n\n"
        "## 宏觀節奏記憶（至今所有 milestone）\n"
        f"{milestone_block}\n\n"
        "## 最近 3 章結構化摘要（含衝突類型與收束方式）\n"
        f"{recent_block}\n\n"
        "## 全局套路統計（Top-3）\n"
        "conflict_type 頻率：\n"
        f"{top_conf_block}\n"
        "resolution_method 頻率：\n"
        f"{top_res_block}\n\n"
        "## Lore 謎團進度樹（待揭露階段）\n"
        f"{lore_block}\n\n"
        "## Writing Notes（全域寫作規定）\n"
        f"{writing_note_block}\n\n"
        "## 系統強制約束（不可違反）\n"
        f"- resolution_tactic_cooldown: {cooldown_block}\n"
        f"- ending_vibe_cooldown: {vibe_block}\n\n"
        "## 你的輸出要求\n"
        "- 請決定 chapter_type（PLOT_DRIVEN / CHARACTER_DRIVEN / WORLD_BUILDING）、POV、Epoch、tone、narrative_directive。\n"
        "- 若 distance_to_anchor >= 2：chapter_type 必須為 CHARACTER_DRIVEN 或 WORLD_BUILDING，"
        "並從 active_b_stories 指定一條副線寫入 b_story_directive；同時輸出 b_story_type（必須對應該副線 type）。"
        "若 b_story_type 落在 recent_b_story_types 禁止清單中，視為違規並需在 HITL 手動修正。\n"
        "- 反重複規則：請避免重現全局 Top-3 的 conflict_type 與 resolution_method 組合；當你構思時若發現可能落在 Top-3，請轉向其他類型。\n"
        "- 反套路規則：請避免與最近 3 章的 plot_summary 呈現相同的推進節拍（同類衝突 + 同類收束）。\n"
        "- 若 distance_to_anchor 為 0 或 1：chapter_type 必須為 PLOT_DRIVEN，並全力收束朝向 target_anchor。\n"
        "- CHARACTER_DRIVEN 或 WORLD_BUILDING 時 new_elements_to_introduce 至少 1 項；"
        "每一項為 {need, reason}：need 描述要引入的對象或變數，reason 說明為何本章需要它（推進調查／壓力／資訊缺口等）。"
        "須避免與 graph 重複專名。\n"
        "- 若你認為需要拖延主線或增加阻礙、且適合開一條**新**副線：輸出 request_new_b_story {type, purpose}；"
        "type 必須是 BStoryType 之一，且**不得**落在 recent_b_story_types 冷卻清單。\n"
        "- 若不需要新副線，request_new_b_story 請輸出 null。\n"
        "- narrative_directive 必須明確指出本章要新增的劇情推進，不能只寫氛圍延續。\n"
        "- 若本章涉及移動、潛入、撤離或追逐，必須把起點、目的地或章末有效位置寫清楚。\n"
        "- 若本章存在秘密行動，narrative_directive 應點出其戲劇功能，但不要把秘密誤寫成任何人都知道的常識。\n"
        "- 若系統強制約束啟用，你的 narrative_directive 必須明確寫出替代手段與章末節奏，不得沿用被禁套路。\n"
    )


def _resolve_current_volume(chapter_id: int, volumes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for volume in volumes:
        start = volume.get("chapter_start")
        end = volume.get("chapter_end")
        if isinstance(start, int) and isinstance(end, int) and start <= chapter_id <= end:
            return volume
    return None
