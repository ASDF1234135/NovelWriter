from __future__ import annotations

import json
from datetime import datetime, UTC

from app.domain.schema import StateAnchor, StoryCastMemberStored, StoryInput, VolumePlan
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
                    plan_retry_limit, draft_loop_retry_limit, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    story_id,
                    story_input.title,
                    story_input.premise,
                    self.db.dumps(story_input.bible),
                    story_input.target_total_words,
                    story_input.plan_retry_limit,
                    story_input.draft_loop_retry_limit,
                    created_at,
                ),
            )
        return self.get_story(story_id)

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
            return row

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
