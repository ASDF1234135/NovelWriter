from __future__ import annotations

import json
import logging
from typing import Any

from app.domain.schema import (
    ChapterSummaryOutput,
    ChapterType,
    ConflictType,
    EndingVibe,
    MilestoneSummaryOutput,
    PlotSummarySource,
    ResolutionMethod,
)
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile

logger = logging.getLogger(__name__)

_DEFAULT_NARRATIVE_DIRECTIVE = "推進劇情"
_MAX_FALLBACK_CHARS = 1200
_DRAFT_FALLBACK_CLIP = 560


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
        "You are the chapter summarizer. Produce a structured summary for THIS chapter for macro Director anti-repeat rules and cadence stats.\n"
        "Use JSON Schema structured outputs (invoke_json): plot_summary, conflict_type, resolution_method, ending_vibe.\n"
        "Rules:\n"
        "- plot_summary: 2–4 sentences covering new advancement, conflict core, and situational turn (not only mood continuation).\n"
        "- conflict_type: pick the enum value closest to this chapter's core conflict.\n"
        "- resolution_method: pick the enum value for the chapter's main resolution/closing approach.\n"
        "- Do not invent events absent from the inputs.\n\n"
        f"chapter_id: {state.get('chapter_id')}\n"
        f"chapter_type: {state.get('chapter_type')}\n"
        f"selected_anchor_ids: {json.dumps(state.get('selected_anchor_ids') or [], ensure_ascii=False)}\n"
        f"next_anchor_ids: {json.dumps(state.get('next_anchor_ids') or [], ensure_ascii=False)}\n\n"
        "ground_truth_events (event grounding only; descriptions truncated):\n"
        f"{json.dumps(gt_events, ensure_ascii=False)}\n\n"
        "pending_chapter_extraction (summary/key clues only; truncated):\n"
        f"{json.dumps(compact_extraction, ensure_ascii=False)}\n\n"
        "Chapter body excerpt (semantic understanding only; truncated):\n"
        f"{chapter_draft}"
    )


def _build_milestone_summarizer_prompt(plot_summaries: list[str]) -> str:
    return (
        "You are the milestone summarizer. Compress five consecutive chapters' plot_summary values (or fewer if the range is short) into one milestone_summary.\n"
        "milestone_summary should reflect macro spine progress, main conflict chaining, and overall resolution-method drift.\n"
        "Return only the requested fields (via invoke_json).\n\n"
        f"plot_summaries: {json.dumps(plot_summaries, ensure_ascii=False)}"
    )


def _extraction_memory_summary(state: dict[str, Any]) -> str:
    pending = state.get("pending_chapter_extraction") or {}
    chapter_mem = pending.get("chapter_memory") or {}
    return str(chapter_mem.get("summary") or "").strip()


def _draft_fallback_text(state: dict[str, Any]) -> str:
    draft = (state.get("best_draft_content") or state.get("current_draft") or "").strip()
    if not draft:
        return ""
    clip = draft[:_DRAFT_FALLBACK_CLIP]
    return f"[備援摘要] {clip}"


def _directive_fallback_text(state: dict[str, Any]) -> str:
    d = str(state.get("narrative_directive") or "").strip()
    if not d or d == _DEFAULT_NARRATIVE_DIRECTIVE:
        return ""
    return f"[本章創作意圖] {d}"[:_MAX_FALLBACK_CHARS]


def _resolve_fallback(state: dict[str, Any]) -> tuple[str, PlotSummarySource]:
    ext = _extraction_memory_summary(state)
    if ext:
        return ext[:_MAX_FALLBACK_CHARS], PlotSummarySource.FALLBACK_EXTRACTION
    draft_fb = _draft_fallback_text(state)
    if draft_fb:
        return draft_fb[:_MAX_FALLBACK_CHARS], PlotSummarySource.FALLBACK_DRAFT
    dir_fb = _directive_fallback_text(state)
    if dir_fb:
        return dir_fb[:_MAX_FALLBACK_CHARS], PlotSummarySource.FALLBACK_DIRECTIVE
    return "（摘要未產生：無可用備援）", PlotSummarySource.PLACEHOLDER


def _enum_value(obj: object, fallback: str) -> str:
    if hasattr(obj, "value"):
        return str(getattr(obj, "value"))
    return str(obj or fallback)


def persist_chapter_summary(
    state: dict[str, Any],
    context: WorkflowContext,
    *,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    """
    Compute and upsert chapter summary (+ optional milestone).

    allow_fallback=False: only LLM/Mock success with non-empty plot_summary writes DB; otherwise returns written=False.
    """
    chapter_id = int(state["chapter_id"])
    story_id = str(state["story_id"])

    plot_summary = ""
    conflict_type: str = ConflictType.OTHER.value
    resolution_method: str = ResolutionMethod.OTHER.value
    ending_vibe: str = EndingVibe.ON_THE_MOVE.value
    plot_summary_source = PlotSummarySource.CHAPTER_SUMMARIZER_LLM
    llm_ok = False

    try:
        if isinstance(context.llm_client, MockLLMClient):
            summary = ChapterSummaryOutput(
                plot_summary="(Mock) This chapter adds recognizable conflict and forward motion, ending on a trackable situational shift.",
                conflict_type=ConflictType.OTHER,
                resolution_method=ResolutionMethod.OTHER,
                ending_vibe=EndingVibe.ON_THE_MOVE,
            )
        else:
            profile = augment_profile_system_prompt(
                get_profile("chapter_summarizer"), context.output_language
            )
            prompt = _build_chapter_summarizer_prompt(state)
            summary, _raw = context.llm_client.invoke_json(prompt, ChapterSummaryOutput, profile)

        plot_summary = (getattr(summary, "plot_summary", None) or "").strip()
        conflict_type = _enum_value(getattr(summary, "conflict_type", None), ConflictType.OTHER.value)
        resolution_method = _enum_value(getattr(summary, "resolution_method", None), ResolutionMethod.OTHER.value)
        ending_vibe = _enum_value(getattr(summary, "ending_vibe", None), EndingVibe.ON_THE_MOVE.value)
        llm_ok = bool(plot_summary)
        if not llm_ok:
            logger.warning(
                "chapter_summarizer returned empty plot_summary (story_id=%s chapter_id=%s)",
                story_id,
                chapter_id,
            )
    except Exception as exc:
        logger.warning(
            "chapter_summarizer LLM failed (story_id=%s chapter_id=%s): %s",
            story_id,
            chapter_id,
            exc,
            exc_info=True,
        )
        llm_ok = False
        plot_summary = ""
        conflict_type = ConflictType.OTHER.value
        resolution_method = ResolutionMethod.OTHER.value
        ending_vibe = EndingVibe.ON_THE_MOVE.value

    if not llm_ok:
        if not allow_fallback:
            return {
                "written": False,
                "plot_summary": "",
                "plot_summary_source": "",
                "error": "LLM summarization failed or returned empty plot_summary",
            }
        plot_summary, plot_summary_source = _resolve_fallback(state)
        conflict_type = ConflictType.OTHER.value
        resolution_method = ResolutionMethod.OTHER.value
        ending_vibe = EndingVibe.ON_THE_MOVE.value

    try:
        context.story_repository.upsert_chapter_summary(
            story_id,
            chapter_id,
            plot_summary=plot_summary,
            conflict_type=conflict_type,
            resolution_method=resolution_method,
            ending_vibe=ending_vibe,
            plot_summary_source=plot_summary_source,
        )
    except Exception:
        logger.exception("chapter_summaries upsert failed (story_id=%s chapter_id=%s)", story_id, chapter_id)
        return {
            "written": False,
            "plot_summary": plot_summary,
            "plot_summary_source": plot_summary_source.value if hasattr(plot_summary_source, "value") else str(plot_summary_source),
            "error": "Database upsert failed",
        }

    _maybe_write_milestone(state, context, chapter_id, story_id)

    return {
        "written": True,
        "plot_summary": plot_summary,
        "plot_summary_source": plot_summary_source.value if hasattr(plot_summary_source, "value") else str(plot_summary_source),
        "regenerated_llm": llm_ok,
    }


def _maybe_write_milestone(state: dict[str, Any], context: WorkflowContext, chapter_id: int, story_id: str) -> None:
    try:
        if chapter_id % 5 != 0:
            return

        start = chapter_id - 4
        end = chapter_id
        recent = context.story_repository.get_chapter_summaries_in_range(story_id, start, end)
        plot_summaries = [str(x.get("plot_summary") or "") for x in recent if str(x.get("plot_summary") or "").strip()]
        if not plot_summaries:
            return

        if isinstance(context.llm_client, MockLLMClient):
            ms = MilestoneSummaryOutput(
                milestone_summary="(Mock) Five-chapter milestone: advances the spine and introduces a new situational pivot."
            )
        else:
            profile = augment_profile_system_prompt(
                get_profile("milestone_summarizer"), context.output_language
            )
            prompt = _build_milestone_summarizer_prompt(plot_summaries)
            ms, _raw = context.llm_client.invoke_json(prompt, MilestoneSummaryOutput, profile)

        context.story_repository.upsert_milestone_summary(
            story_id,
            chapter_start=start,
            chapter_end=end,
            milestone_summary=ms.milestone_summary,
        )
    except Exception:
        logger.warning(
            "milestone summarizer skipped after chapter summary (story_id=%s)",
            story_id,
            exc_info=True,
        )


def run_chapter_summarizer(state: dict[str, Any], context: WorkflowContext) -> None:
    """Workflow node entry: best-effort persistence with fallbacks."""
    persist_chapter_summary(state, context, allow_fallback=True)


def build_minimal_state_for_regenerate(
    *,
    story_id: str,
    chapter_id: int,
    chapter_content: str,
    chapter_type: ChapterType | None = None,
    b_story_directive: str = "",
    ground_truth_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ct = chapter_type or ChapterType.PLOT_DRIVEN
    ct_val = ct.value if hasattr(ct, "value") else str(ct)
    return {
        "story_id": story_id,
        "chapter_id": int(chapter_id),
        "chapter_type": ct_val,
        "b_story_directive": (b_story_directive or "")[:800],
        "best_draft_content": chapter_content,
        "current_draft": chapter_content,
        "ground_truth_events": list(ground_truth_events or []),
        "pending_chapter_extraction": {
            "chapter_memory": {
                "summary": "",
                "unresolved_threads": [],
                "notable_entities": [],
                "latest_location": "",
            },
            "entities": [],
        },
        "narrative_directive": "",
    }
