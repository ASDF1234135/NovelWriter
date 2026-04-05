from __future__ import annotations

import json
from typing import Any

from app.domain.schema import ChapterSummaryOutput, MilestoneSummaryOutput
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.profiles import get_profile


def _compact_ground_truth_events(state: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    events = state.get("ground_truth_events") or []
    out: list[dict[str, Any]] = []
    for e in events[:limit]:
        if not isinstance(e, dict):
            continue
        out.append(
            {
                "event_id": e.get("event_id"),
                "description": str(e.get("description") or "")[:220],
            }
        )
    return out


def _compact_pending_extraction(state: dict[str, Any], limit_entities: int = 12) -> dict[str, Any]:
    pending = state.get("pending_chapter_extraction") or {}
    chapter_mem = pending.get("chapter_memory") or {}
    entities = pending.get("entities") or []

    entity_names: list[str] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("canonical_name") or "").strip()
        if name and name not in entity_names:
            entity_names.append(name)
        if len(entity_names) >= limit_entities:
            break

    return {
        "chapter_memory": {
            "summary": str(chapter_mem.get("summary") or "")[:600],
            "unresolved_threads": [str(x)[:180] for x in (chapter_mem.get("unresolved_threads") or [])[:6] if x],
            "notable_entities": [str(x)[:80] for x in (chapter_mem.get("notable_entities") or [])[:8] if x],
            "latest_location": str(chapter_mem.get("latest_location") or "")[:120],
        },
        "entity_names": entity_names,
    }


def _build_chapter_summarizer_prompt(state: dict[str, Any]) -> str:
    compact_extraction = _compact_pending_extraction(state)
    gt_events = _compact_ground_truth_events(state)
    chapter_draft = (state.get("best_draft_content") or state.get("current_draft") or "")[:6000]
    return (
        "你是章節摘要器。任務：為『本章』輸出一份結構化摘要，用於宏觀 Director 的反重複規則與節奏統計。\n"
        "請使用 JSON Schema Structured Outputs（invoke_json）回傳：plot_summary、conflict_type、resolution_method、ending_vibe。\n"
        "規則：\n"
        "- plot_summary：用 2-4 句，概述本章的新增推進、衝突核心與局勢轉折（不可只是氛圍延續）。\n"
        "- conflict_type：只能在 enum 列表選擇最貼近本章核心衝突類型。\n"
        "- resolution_method：只能在 enum 列表選擇本章主要解決/收束方式。\n"
        "- 不要編造輸入中不存在的事件。\n\n"
        f"chapter_id: {state.get('chapter_id')}\n"
        f"chapter_type: {state.get('chapter_type')}\n"
        f"b_story_directive: {(state.get('b_story_directive') or '')[:240]}\n\n"
        "ground_truth_events（僅供事件依據，description 已截斷）:\n"
        f"{json.dumps(gt_events, ensure_ascii=False)}\n\n"
        "pending_chapter_extraction（僅供摘要/關鍵線索，已截斷）:\n"
        f"{json.dumps(compact_extraction, ensure_ascii=False)}\n\n"
        "本章正文摘錄（僅供語意理解，已截斷）:\n"
        f"{chapter_draft}"
    )


def _build_milestone_summarizer_prompt(plot_summaries: list[str]) -> str:
    return (
        "你是里程碑摘要器。任務：把連續 5 章（或少於 5 章但為同一區間）的 plot_summary 壓縮成一份 milestone_summary。\n"
        "milestone_summary 需體現：宏觀推進主軸、主要衝突連鎖、以及收束方式的總體走向。\n"
        "輸出只包含你被要求的字段（透過 invoke_json）。\n\n"
        f"plot_summaries: {json.dumps(plot_summaries, ensure_ascii=False)}"
    )


def run_chapter_summarizer(state: dict[str, Any], context: WorkflowContext) -> None:
    # Best-effort: never break the workflow if summarization fails.
    chapter_id = int(state["chapter_id"])

    # Fallback placeholders (per plan: conflict/resolution -> OTHER, plot_summary allowed empty).
    plot_summary: str = ""
    conflict_type: str = "OTHER"
    resolution_method: str = "OTHER"
    ending_vibe: str = "ON_THE_MOVE"

    # 1) Chapter summary (LLM call is best-effort; DB upsert should still happen).
    try:
        if isinstance(context.llm_client, MockLLMClient):
            summary = ChapterSummaryOutput(
                plot_summary="（Mock）本章新增一段可辨識的衝突與推進，並在章末形成可追蹤的局勢變化。",
                conflict_type="OTHER",
                resolution_method="OTHER",
                ending_vibe="ON_THE_MOVE",
            )
        else:
            profile = get_profile("chapter_summarizer")
            prompt = _build_chapter_summarizer_prompt(state)
            summary, _raw = context.llm_client.invoke_json(prompt, ChapterSummaryOutput, profile)

        plot_summary = getattr(summary, "plot_summary", "") or ""
        conflict_type = getattr(summary, "conflict_type", "OTHER")
        resolution_method = getattr(summary, "resolution_method", "OTHER")
        ending_vibe = getattr(summary, "ending_vibe", "ON_THE_MOVE")
    except Exception:
        # Keep placeholders; still upsert placeholder summary.
        pass

    try:
        context.story_repository.upsert_chapter_summary(
            state["story_id"],
            chapter_id,
            plot_summary=plot_summary,
            conflict_type=conflict_type,
            resolution_method=resolution_method,
            ending_vibe=ending_vibe,
        )
    except Exception:
        # Fail open: if DB upsert fails, skip milestones too.
        return

    # 2) Milestone generation (best-effort; should not break the workflow).
    try:
        if chapter_id % 5 != 0:
            return

        start = chapter_id - 4
        end = chapter_id
        recent = context.story_repository.get_chapter_summaries_in_range(state["story_id"], start, end)
        plot_summaries = [x.get("plot_summary") for x in recent if x.get("plot_summary")]
        if not plot_summaries:
            return

        if isinstance(context.llm_client, MockLLMClient):
            ms = MilestoneSummaryOutput(milestone_summary="（Mock）本 5 章里程碑摘要：推進主線並形成新的局勢轉折。")
        else:
            profile = get_profile("milestone_summarizer")
            prompt = _build_milestone_summarizer_prompt(plot_summaries)
            ms, _raw = context.llm_client.invoke_json(prompt, MilestoneSummaryOutput, profile)

        context.story_repository.upsert_milestone_summary(
            state["story_id"],
            chapter_start=start,
            chapter_end=end,
            milestone_summary=ms.milestone_summary,
        )
    except Exception:
        # Skip milestone on any error.
        return

