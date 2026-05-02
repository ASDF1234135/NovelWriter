"""Read-only aggregate for the chapter run UI (plot progress + writing hints)."""

from __future__ import annotations

from app.repositories.sqlite.story_repository import StoryRepository
from app.services.workflow.bible_general_lore import effective_general_world_lore
from app.services.workflow.chapter_pacing import (
    build_ending_vibe_cooldown_constraint,
    build_resolution_cooldown_constraint,
)


def _human_pacing_hints(recent_for_cooldown: list[dict]) -> list[str]:
    """Friendly bullets when the same `active` rules as workflow cooldowns fire."""
    hints: list[str] = []
    res = build_resolution_cooldown_constraint(recent_for_cooldown)
    if res.get("active"):
        hints.append(
            "最近連續幾章的破局方式較為相似（偏重資訊／謎底直取）。"
            "本章不妨換一種收束路徑，例如肢體行動、環境利用、談判周旋或結盟反轉，讓節奏更有層次。"
        )
    endv = build_ending_vibe_cooldown_constraint(recent_for_cooldown)
    if endv.get("active"):
        hints.append(
            "上一章結尾偏「安全空間裡的說明與盤點」。"
            "本章收尾可考慮外向一點的張力：行動被截斷、威脅逼近門口，或留下更具動能的懸念。"
        )
    return hints


def _serialize_summary_row(row: dict) -> dict:
    return {
        "chapter_id": int(row["chapter_id"]),
        "plot_summary": str(row.get("plot_summary") or ""),
        "plot_summary_source": str(row.get("plot_summary_source") or "UNKNOWN"),
        "conflict_type": str(row.get("conflict_type") or ""),
        "resolution_method": str(row.get("resolution_method") or ""),
        "ending_vibe": str(row.get("ending_vibe") or ""),
    }


def _unachieved_from_anchor_nodes(story: dict) -> list[dict]:
    nodes = [dict(n) for n in (story.get("anchor_nodes_json") or []) if isinstance(n, dict)]
    if not nodes:
        return []
    unresolved = [n for n in nodes if str(n.get("status") or "").upper() != "RESOLVED"]
    unresolved.sort(key=lambda n: str(n.get("id") or ""))
    rows: list[dict] = []
    for n in unresolved:
        rows.append(
            {
                "anchor_id": str(n.get("id") or ""),
                "volume_id": str(n.get("volume_id") or ""),
                "title": str(n.get("title") or ""),
                "description": str(n.get("description") or ""),
            }
        )
    return rows


def build_writing_preamble(repo: StoryRepository, story_id: str, chapter_id: int) -> dict:
    """
    Aggregate milestones, recent summaries, next anchor, and human-readable pacing hints.
    Raises KeyError if story is missing; ValueError if chapter_id < 1.
    """
    story = repo.get_story(story_id)
    if not story:
        raise KeyError(f"Story not found: {story_id}")
    cid = int(chapter_id)
    if cid < 1:
        raise ValueError("chapter_id must be >= 1")

    bible = story.get("bible_json") or {}
    unachieved = _unachieved_from_anchor_nodes(story)

    next_focus: dict | None = None
    if unachieved:
        a = unachieved[0]
        next_focus = {
            "anchor_id": str(a["anchor_id"]),
            "volume_id": str(a.get("volume_id") or ""),
            "title": str(a.get("title") or ""),
            "description": str(a.get("description") or ""),
            "priority": int(a.get("priority") or 1),
        }

    recent_5_raw = repo.get_recent_chapter_summaries(story_id, cid, limit=5)
    recent_3_raw = repo.get_recent_chapter_summaries(story_id, cid, limit=3)
    pacing_hints = _human_pacing_hints(recent_3_raw)

    milestones_all = repo.list_all_milestones(story_id)
    milestones = [
        {
            "chapter_start": int(m["chapter_start"]),
            "chapter_end": int(m["chapter_end"]),
            "milestone_summary": str(m.get("milestone_summary") or ""),
        }
        for m in milestones_all
        if int(m["chapter_end"]) < cid
    ]

    prev_num: int | None = None
    prev_block: dict = {"chapter_id": None, "plot_summary": "", "status": ""}
    if cid > 1:
        prev_num = cid - 1
        prev_ch = repo.get_chapter(story_id, prev_num)
        prev_status = str((prev_ch or {}).get("status") or "")
        rows_prev = repo.get_chapter_summaries_in_range(story_id, prev_num, prev_num)
        prev_block = {
            "chapter_id": prev_num,
            "plot_summary": "",
            "status": prev_status,
        }
        if rows_prev:
            prev_block["plot_summary"] = str(rows_prev[0].get("plot_summary") or "")
            prev_block["plot_summary_source"] = str(rows_prev[0].get("plot_summary_source") or "UNKNOWN")

    earlier_count = repo.count_chapter_summaries_before(story_id, cid)

    return {
        "chapter_id": cid,
        "plot_progress": {
            "previous_chapter": prev_block,
            "recent_summaries": [_serialize_summary_row(dict(r)) for r in recent_5_raw],
            "milestones": milestones,
            "earlier_chapters_with_summary_count": earlier_count,
        },
        "writing_hints": {
            "writing_notes": [
                ln.strip() for ln in effective_general_world_lore(dict(bible)).split("\n") if ln.strip()
            ],
            "macro_author_notes": str(story.get("macro_author_notes") or ""),
            "next_focus_anchor": next_focus,
            "pacing_hints": pacing_hints,
        },
    }
