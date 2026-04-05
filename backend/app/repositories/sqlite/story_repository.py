from __future__ import annotations

import json
from datetime import datetime, UTC
from typing import Any

from app.domain.schema import (
    ConflictType,
    EndingVibe,
    ResolutionMethod,
    StateAnchor,
    StoryCastMemberStored,
    StoryCastSeedEntry,
    StoryInput,
    StoryPatch,
    VolumePlan,
)
from app.repositories.sqlite.database import SQLiteDatabase


class StoryRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def create_story(self, story_id: str, story_input: StoryInput) -> dict:
        created_at = datetime.now(UTC).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO stories (
                    story_id, title, premise, bible_json, target_total_words,
                    plan_retry_limit, draft_loop_retry_limit, macro_author_notes, cast_seed_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    story_id,
                    story_input.title,
                    story_input.premise,
                    self.db.dumps(story_input.bible),
                    story_input.target_total_words,
                    story_input.plan_retry_limit,
                    story_input.draft_loop_retry_limit,
                    story_input.macro_author_notes,
                    self.db.dumps([s.model_dump(mode="json") for s in story_input.cast_seed]),
                    created_at,
                ),
            )
        return self.get_story(story_id)

    def list_stories(self) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT story_id, title, premise, target_total_words, created_at
                FROM stories
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_story(self, story_id: str) -> dict | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM stories WHERE story_id = ?", (story_id,)).fetchone()
            if not row:
                return None
            row["bible_json"] = self.db.loads(row["bible_json"])
            raw_cast = row.get("cast_json")
            if isinstance(raw_cast, str) and raw_cast.strip():
                try:
                    row["cast_json"] = self.db.loads(raw_cast)
                except (json.JSONDecodeError, TypeError, ValueError):
                    row["cast_json"] = []
            elif isinstance(raw_cast, list):
                row["cast_json"] = raw_cast
            else:
                row["cast_json"] = []
            row.setdefault("protagonist_character_id", "")
            row.setdefault("macro_author_notes", "")
            row.setdefault("macro_compile_status", "IDLE")
            row.setdefault("macro_compile_updated_at", "")
            row.setdefault("macro_compile_error", "")
            row.setdefault("cast_seed_json", "[]")
            raw_seed = row.get("cast_seed_json")
            if isinstance(raw_seed, str) and raw_seed.strip():
                try:
                    parsed = self.db.loads(raw_seed)
                    row["cast_seed"] = (
                        [StoryCastSeedEntry.model_validate(x) for x in parsed] if isinstance(parsed, list) else []
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    row["cast_seed"] = []
            elif isinstance(raw_seed, list):
                row["cast_seed"] = [StoryCastSeedEntry.model_validate(x) for x in raw_seed]
            else:
                row["cast_seed"] = []
            return row

    def try_begin_macro_compile(self, story_id: str) -> bool:
        """Set RUNNING if story exists and status is not already RUNNING. Returns True if acquired."""
        now = datetime.now(UTC).isoformat()
        with self.db.connection() as conn:
            cur = conn.execute(
                """
                UPDATE stories
                SET macro_compile_status = 'RUNNING',
                    macro_compile_updated_at = ?,
                    macro_compile_error = ''
                WHERE story_id = ?
                  AND macro_compile_status IN ('IDLE', 'SUCCEEDED', 'FAILED')
                """,
                (now, story_id),
            )
            return cur.rowcount == 1

    def finish_macro_compile(self, story_id: str, *, success: bool, error_message: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        status = "SUCCEEDED" if success else "FAILED"
        err = (error_message or "")[:2000]
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE stories
                SET macro_compile_status = ?,
                    macro_compile_updated_at = ?,
                    macro_compile_error = ?
                WHERE story_id = ?
                """,
                (status, now, err, story_id),
            )

    def update_story_bible_json(self, story_id: str, bible: dict) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE stories SET bible_json = ? WHERE story_id = ?",
                (self.db.dumps(bible), story_id),
            )

    def patch_story(self, story_id: str, patch: StoryPatch) -> dict:
        story = self.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        data = patch.model_dump(exclude_unset=True)
        if not data:
            return story
        fields: list[str] = []
        values: list[object] = []
        if "title" in data:
            fields.append("title = ?")
            values.append(data["title"])
        if "premise" in data:
            fields.append("premise = ?")
            values.append(data["premise"])
        if "target_total_words" in data:
            fields.append("target_total_words = ?")
            values.append(int(data["target_total_words"]))
        if "plan_retry_limit" in data:
            fields.append("plan_retry_limit = ?")
            values.append(int(data["plan_retry_limit"]))
        if "draft_loop_retry_limit" in data:
            fields.append("draft_loop_retry_limit = ?")
            values.append(int(data["draft_loop_retry_limit"]))
        if "macro_author_notes" in data:
            fields.append("macro_author_notes = ?")
            values.append(data["macro_author_notes"])
        if "cast_seed" in data:
            raw_seeds = data["cast_seed"] or []
            seeds = [StoryCastSeedEntry.model_validate(x) for x in raw_seeds]
            fields.append("cast_seed_json = ?")
            values.append(self.db.dumps([s.model_dump(mode="json") for s in seeds]))
        if not fields:
            return story
        values.append(story_id)
        with self.db.connection() as conn:
            conn.execute(
                f"UPDATE stories SET {', '.join(fields)} WHERE story_id = ?",
                tuple(values),
            )
        return self.get_story(story_id)

    def update_story_cast(
        self, story_id: str, cast: list[StoryCastMemberStored], protagonist_character_id: str
    ) -> None:
        payload = [member.model_dump(mode="json") for member in cast]
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE stories
                SET cast_json = ?, protagonist_character_id = ?
                WHERE story_id = ?
                """,
                (self.db.dumps(payload), protagonist_character_id, story_id),
            )

    def append_story_cast_member_if_absent(self, story_id: str, member: StoryCastMemberStored) -> None:
        """Append one cast row to cast_json if node_id is not already present."""
        story = self.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        raw = story.get("cast_json") or []
        if not isinstance(raw, list):
            raw = []
        seen = {str(x.get("node_id")) for x in raw if isinstance(x, dict) and x.get("node_id")}
        if str(member.node_id).strip() in seen:
            return
        payload = list(raw)
        payload.append(member.model_dump(mode="json"))
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE stories SET cast_json = ? WHERE story_id = ?",
                (self.db.dumps(payload), story_id),
            )

    def store_volumes(self, story_id: str, volumes: list[VolumePlan]) -> None:
        with self.db.connection() as conn:
            conn.execute("DELETE FROM volumes WHERE story_id = ?", (story_id,))
            for volume in volumes:
                conn.execute(
                    """
                    INSERT INTO volumes (volume_id, story_id, title, summary, chapter_start, chapter_end, target_volume_words)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        volume.volume_id,
                        story_id,
                        volume.title,
                        volume.summary,
                        volume.chapter_start,
                        volume.chapter_end,
                        volume.target_volume_words,
                    ),
                )

    def list_volumes(self, story_id: str) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM volumes WHERE story_id = ? ORDER BY chapter_start",
                (story_id,),
            ).fetchall()
            return list(rows)

    def store_anchors(self, story_id: str, anchors: list[StateAnchor]) -> None:
        with self.db.connection() as conn:
            conn.execute("DELETE FROM anchors WHERE story_id = ?", (story_id,))
            for anchor in anchors:
                conn.execute(
                    """
                    INSERT INTO anchors (anchor_id, story_id, volume_id, title, description, target_state_json, chapter_target, priority)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        anchor.anchor_id,
                        story_id,
                        anchor.volume_id,
                        anchor.title,
                        anchor.description,
                        self.db.dumps(anchor.target_state),
                        anchor.chapter_target,
                        anchor.priority,
                    ),
                )

    def list_anchors(self, story_id: str) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM anchors WHERE story_id = ? ORDER BY chapter_target, priority",
                (story_id,),
            ).fetchall()
            for row in rows:
                row["target_state_json"] = self.db.loads(row["target_state_json"])
            return list(rows)

    def update_anchor_chapter_target(self, story_id: str, anchor_id: str, new_chapter_target: int) -> None:
        with self.db.connection() as conn:
            cur = conn.execute(
                """
                UPDATE anchors SET chapter_target = ?
                WHERE story_id = ? AND anchor_id = ?
                """,
                (int(new_chapter_target), story_id, anchor_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Anchor not found: {story_id}/{anchor_id}")

    def upsert_chapter_content(self, story_id: str, chapter_id: int, title: str, content: str, status: str) -> None:
        chapter_key = f"{story_id}:{chapter_id}"
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO chapters (chapter_key, story_id, chapter_id, title, content, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chapter_key) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    status = excluded.status
                """,
                (chapter_key, story_id, chapter_id, title, content, status),
            )

    def get_chapter(self, story_id: str, chapter_id: int) -> dict | None:
        chapter_key = f"{story_id}:{chapter_id}"
        with self.db.connection() as conn:
            return conn.execute(
                "SELECT * FROM chapters WHERE chapter_key = ?",
                (chapter_key,),
            ).fetchone()

    def list_recent_chapters_with_content(self, story_id: str, before_chapter_id: int, limit: int = 2) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT chapter_key, story_id, chapter_id, title, content, status
                FROM chapters
                WHERE story_id = ? AND chapter_id < ? AND status = 'completed'
                ORDER BY chapter_id DESC
                LIMIT ?
                """,
                (story_id, before_chapter_id, limit),
            ).fetchall()
        return list(reversed(rows))

    def list_chapters(self, story_id: str) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT chapter_key, story_id, chapter_id, title, status
                FROM chapters
                WHERE story_id = ?
                ORDER BY chapter_id ASC
                """,
                (story_id,),
            ).fetchall()
            return list(rows)

    def merge_active_b_stories_seed(self, story_id: str, entries: list[dict[str, Any]]) -> None:
        """Append macro-planner (or other) b-story seeds into bible_json.active_b_stories (dedupe by id)."""
        if not entries:
            return
        story = self.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        bible = dict(story.get("bible_json") or {})
        active: list[dict] = list(bible.get("active_b_stories") or [])
        seen = {str(x.get("id")) for x in active if isinstance(x, dict) and x.get("id")}
        for raw in entries:
            bid = str(raw.get("id") or "").strip()
            if not bid or bid in seen:
                continue
            seen.add(bid)
            active.append(
                {
                    "id": bid,
                    "desc": str(raw.get("desc") or "")[:800],
                    # Optional typology label (for cooldown). Backward compatible: missing => "UNKNOWN".
                    "type": str(raw.get("type") or "UNKNOWN"),
                    "resolution_condition": str(raw.get("resolution_condition") or "")[:800],
                }
            )
        bible["active_b_stories"] = active
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE stories SET bible_json = ? WHERE story_id = ?",
                (self.db.dumps(bible), story_id),
            )

    def remove_resolved_b_stories_from_bible(self, story_id: str, resolved_ids: list[str]) -> None:
        """Remove completed b-story ids from bible_json.active_b_stories (same transaction context as caller)."""
        if not resolved_ids:
            return
        story = self.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        rid_set = {str(x).strip() for x in resolved_ids if str(x).strip()}
        if not rid_set:
            return
        bible = dict(story.get("bible_json") or {})
        active = [x for x in (bible.get("active_b_stories") or []) if str(x.get("id", "")) not in rid_set]
        bible["active_b_stories"] = active
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE stories SET bible_json = ? WHERE story_id = ?",
                (self.db.dumps(bible), story_id),
            )

    def upsert_chapter_summary(
        self,
        story_id: str,
        chapter_id: int,
        *,
        plot_summary: str,
        conflict_type: ConflictType | str,
        resolution_method: ResolutionMethod | str,
        ending_vibe: EndingVibe | str = EndingVibe.ON_THE_MOVE,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        ctype = conflict_type.value if hasattr(conflict_type, "value") else str(conflict_type)
        rmethod = resolution_method.value if hasattr(resolution_method, "value") else str(resolution_method)
        evibe = ending_vibe.value if hasattr(ending_vibe, "value") else str(ending_vibe)
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO chapter_summaries (story_id, chapter_id, plot_summary, conflict_type, resolution_method, ending_vibe, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id, chapter_id) DO UPDATE SET
                    plot_summary = excluded.plot_summary,
                    conflict_type = excluded.conflict_type,
                    resolution_method = excluded.resolution_method,
                    ending_vibe = excluded.ending_vibe,
                    created_at = excluded.created_at
                """,
                (story_id, int(chapter_id), plot_summary, ctype, rmethod, evibe, created_at),
            )

    def get_recent_chapter_summaries(self, story_id: str, before_chapter_id: int, limit: int = 3) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT chapter_id, plot_summary, conflict_type, resolution_method, ending_vibe, created_at
                FROM chapter_summaries
                WHERE story_id = ? AND chapter_id < ?
                ORDER BY chapter_id DESC
                LIMIT ?
                """,
                (story_id, int(before_chapter_id), int(limit)),
            ).fetchall()
        # Return ascending for more natural reading in prompts.
        rows = list(rows)
        rows.reverse()
        return [dict(r) for r in rows]

    def upsert_milestone_summary(
        self,
        story_id: str,
        *,
        chapter_start: int,
        chapter_end: int,
        milestone_summary: str,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO milestone_summaries (story_id, chapter_start, chapter_end, milestone_summary, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(story_id, chapter_start, chapter_end) DO UPDATE SET
                    milestone_summary = excluded.milestone_summary,
                    created_at = excluded.created_at
                """,
                (story_id, int(chapter_start), int(chapter_end), milestone_summary, created_at),
            )

    def list_all_milestones(self, story_id: str) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT chapter_start, chapter_end, milestone_summary, created_at
                FROM milestone_summaries
                WHERE story_id = ?
                ORDER BY chapter_start ASC
                """,
                (story_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def global_top_conflict_type(self, story_id: str, top_k: int = 3) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT conflict_type, COUNT(*) as cnt
                FROM chapter_summaries
                WHERE story_id = ?
                GROUP BY conflict_type
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (story_id, int(top_k)),
            ).fetchall()
        return [dict(r) for r in rows]

    def global_top_resolution_method(self, story_id: str, top_k: int = 3) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT resolution_method, COUNT(*) as cnt
                FROM chapter_summaries
                WHERE story_id = ?
                GROUP BY resolution_method
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (story_id, int(top_k)),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_chapter_summaries_in_range(self, story_id: str, chapter_start: int, chapter_end: int) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT chapter_id, plot_summary, conflict_type, resolution_method, ending_vibe, created_at
                FROM chapter_summaries
                WHERE story_id = ?
                  AND chapter_id >= ?
                  AND chapter_id <= ?
                ORDER BY chapter_id ASC
                """,
                (story_id, int(chapter_start), int(chapter_end)),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_story_cascade(self, story_id: str) -> None:
        """Delete chapters, macro plan, summaries, and the story row. Caller must delete workflow_runs first."""
        with self.db.connection() as conn:
            conn.execute("DELETE FROM chapters WHERE story_id = ?", (story_id,))
            conn.execute("DELETE FROM volumes WHERE story_id = ?", (story_id,))
            conn.execute("DELETE FROM anchors WHERE story_id = ?", (story_id,))
            conn.execute("DELETE FROM chapter_summaries WHERE story_id = ?", (story_id,))
            conn.execute("DELETE FROM milestone_summaries WHERE story_id = ?", (story_id,))
            conn.execute("DELETE FROM stories WHERE story_id = ?", (story_id,))
