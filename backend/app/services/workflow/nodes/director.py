from __future__ import annotations

import json
from typing import Any

from app.domain.schema import DirectorOutput
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import visible_unachieved_anchors
from app.services.workflow.profiles import get_profile


def run_director(state: dict, context: WorkflowContext) -> dict:
    anchors = state.get("unachieved_anchors", [])
    next_anchor = anchors[0] if anchors else None
    anchor_prompt_window = visible_unachieved_anchors(state)
    story = context.story_repository.get_story(state["story_id"]) or {}
    volumes = context.story_repository.list_volumes(state["story_id"])
    bible_context = context.bible_service.compile_context(story.get("bible_json", {}))
    guidance = _compute_target_word_guidance(state["chapter_id"], volumes, next_anchor)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = get_profile("director")
        prompt = _build_director_prompt(
            state, story, volumes, next_anchor, anchor_prompt_window, bible_context, guidance
        )
        output, _ = context.llm_client.invoke_json(prompt, DirectorOutput, profile)
        return output.model_dump(mode="json") | {
            "target_word_count": _clamp_target_word_count(output.target_word_count, guidance),
        }

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
        target_word_count=guidance["suggested_target_word_count"],
        target_anchor_id=next_anchor["anchor_id"] if next_anchor else None,
    )
    return output.model_dump()


def _build_director_prompt(
    state: dict,
    story: dict[str, Any],
    volumes: list[dict[str, Any]],
    next_anchor: dict[str, Any] | None,
    visible_unachieved_anchors: list[dict[str, Any]],
    bible_context: str = "",
    guidance: dict[str, Any] | None = None,
) -> str:
    current_volume = _resolve_current_volume(state["chapter_id"], volumes)
    guidance = guidance or _compute_target_word_guidance(state["chapter_id"], volumes, next_anchor)
    return (
        "## 章節定位\n"
        f"- chapter_id: {state['chapter_id']}\n\n"
        "## 故事核心\n"
        f"- story_title: {story.get('title', '')}\n"
        f"- story_premise: {story.get('premise', '')}\n\n"
        "## 當前卷資訊\n"
        f"- volume_title: {(current_volume or {}).get('title', '')}\n"
        f"- volume_summary: {(current_volume or {}).get('summary', '')}\n\n"
        f"- volume_target_words: {(current_volume or {}).get('target_volume_words', 0)}\n"
        f"- volume_chapter_range: {((current_volume or {}).get('chapter_start', ''), (current_volume or {}).get('chapter_end', ''))}\n"
        f"- chapter_position_in_volume: {guidance['chapter_position_in_volume']}/{guidance['volume_chapter_count']}\n"
        f"- suggested_target_word_count: {guidance['suggested_target_word_count']}\n"
        f"- suggested_word_count_range: {guidance['min_target_word_count']}-{guidance['max_target_word_count']}\n\n"
        "## 本章主要推進目標\n"
        f"- current_anchor_id: {(next_anchor or {}).get('anchor_id')}\n"
        f"- current_anchor_title: {(next_anchor or {}).get('title', '')}\n"
        f"- current_anchor_description: {(next_anchor or {}).get('description', '')}\n"
        "- visible_unachieved_anchors: 以下僅列出「最近數個」尚未達成的錨點（滑動視窗），"
        "供你把握中期節奏；**本章仍以 current_anchor 為主**，勿替更遠的錨點編排具體情節或劇透。\n"
        f"- visible_unachieved_anchors: {json.dumps(visible_unachieved_anchors, ensure_ascii=False)}\n\n"
        "## 世界與狀態背景\n"
        f"- bible_context: {bible_context[:1800]}\n"
        f"- graph_hint: {state.get('graph_context', '')[:1800]}\n\n"
        "## 你的輸出要求\n"
        "- 請決定本章 POV、Epoch、tone、target_word_count 與 narrative_directive。\n"
        "- target_word_count 必須優先參考 volume_target_words、chapter_position_in_volume 與 suggested_target_word_count，不可明顯偏離 suggested_word_count_range。\n"
        "- narrative_directive 必須明確指出本章要新增的劇情推進，不能只寫氛圍延續。\n"
        "- 請讓本章至少推進一個新的行動或發現，並與當前 anchor 收斂。\n"
        "- 若本章涉及移動、潛入、撤離或追逐，必須把起點、目的地或章末有效位置寫清楚。\n"
        "- 若本章存在秘密行動，narrative_directive 應點出其戲劇功能，但不要把秘密誤寫成任何人都知道的常識。\n"
    )


def _resolve_current_volume(chapter_id: int, volumes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for volume in volumes:
        start = volume.get("chapter_start")
        end = volume.get("chapter_end")
        if isinstance(start, int) and isinstance(end, int) and start <= chapter_id <= end:
            return volume
    return None


def _compute_target_word_guidance(
    chapter_id: int,
    volumes: list[dict[str, Any]],
    next_anchor: dict[str, Any] | None,
) -> dict[str, int]:
    current_volume = _resolve_current_volume(chapter_id, volumes)
    volume_start = int((current_volume or {}).get("chapter_start", chapter_id))
    volume_end = int((current_volume or {}).get("chapter_end", chapter_id))
    volume_chapter_count = max(1, volume_end - volume_start + 1)
    chapter_position = max(1, chapter_id - volume_start + 1)
    volume_target_words = int((current_volume or {}).get("target_volume_words", 0) or 0)
    fallback_words = volume_chapter_count * 2500
    base_target = max(1600, int(round((volume_target_words or fallback_words) / volume_chapter_count / 50) * 50))

    multiplier = 1.0
    if chapter_position == 1:
        multiplier += 0.08
    if chapter_position == volume_chapter_count:
        multiplier += 0.10
    anchor_target = int(next_anchor.get("chapter_target", -999)) if next_anchor else -999
    if anchor_target == chapter_id:
        multiplier += 0.12
    elif volume_start <= anchor_target <= volume_end:
        distance_to_anchor = anchor_target - chapter_id
        if distance_to_anchor == 1:
            multiplier += 0.08
        elif distance_to_anchor == 2:
            multiplier += 0.04

    suggested = max(1600, int(round(base_target * multiplier / 50) * 50))
    min_target = max(1200, int(round(base_target * 0.8 / 50) * 50))
    max_target = max(min_target, int(round(base_target * 1.2 / 50) * 50))
    return {
        "chapter_position_in_volume": chapter_position,
        "volume_chapter_count": volume_chapter_count,
        "suggested_target_word_count": suggested,
        "min_target_word_count": min_target,
        "max_target_word_count": max_target,
    }


def _clamp_target_word_count(target_word_count: int, guidance: dict[str, Any]) -> int:
    lower = int(guidance["min_target_word_count"])
    upper = int(guidance["max_target_word_count"])
    return max(lower, min(upper, target_word_count))
