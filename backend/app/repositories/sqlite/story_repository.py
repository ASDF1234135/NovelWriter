from __future__ import annotations

import json
from datetime import datetime, UTC
from typing import Any

from app.domain.schema import (
    CharacterArcMilestone,
    ConflictType,
    EndingVibe,
    PlotSummarySource,
    ResolutionMethod,
    StoryCastMemberStored,
    StoryCastSeedEntry,
    StoryInput,
    StoryPatch,
    VolumePlan,
)
from app.repositories.sqlite.database import SQLiteDatabase


class StoryRepository:
    @staticmethod
    def _strip_macro_topology_from_bible(bible: dict[str, Any]) -> dict[str, Any]:
        out = dict(bible or {})
        out.pop("storylines", None)
        out.pop("anchor_nodes", None)
        return out

    @staticmethod
    def _coerce_json_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    @staticmethod
    def _sanitize_cast_row(raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        if not str(row.get("personality") or "").strip() and str(row.get("motivation") or "").strip():
            row["personality"] = str(row.get("motivation") or "")
        row.pop("motivation", None)
        try:
            return StoryCastMemberStored.model_validate(row).model_dump(mode="json")
        except Exception:
            return StoryCastMemberStored(
                node_id=str(row.get("node_id") or "").strip(),
                canonical_name=str(row.get("canonical_name") or "").strip() or str(row.get("node_id") or "").strip(),
                role="supporting",
            ).model_dump(mode="json")

    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def create_story(self, story_id: str, story_input: StoryInput) -> dict:
        created_at = datetime.now(UTC).isoformat()
        bible_raw = dict(story_input.bible or {})
        storylines = self._coerce_json_list(bible_raw.get("storylines"))
        anchor_nodes = self._coerce_json_list(bible_raw.get("anchor_nodes"))
        bible = self._strip_macro_topology_from_bible(bible_raw)
        compile_cfg = dict(bible.get("compile_config") or {})
        if story_input.branch_count_override is not None:
            compile_cfg["branch_count_override"] = int(story_input.branch_count_override)
        if compile_cfg:
            bible["compile_config"] = compile_cfg
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO stories (
                    story_id, title, premise, bible_json, target_total_words,
                    plan_retry_limit, draft_loop_retry_limit, macro_author_notes, cast_seed_json,
                    storylines_json, anchor_nodes_json, output_language, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    story_id,
                    story_input.title,
                    story_input.premise,
                    self.db.dumps(bible),
                    story_input.target_total_words,
                    story_input.plan_retry_limit,
                    story_input.draft_loop_retry_limit,
                    story_input.macro_author_notes,
                    self.db.dumps([s.model_dump(mode="json") for s in story_input.cast_seed]),
                    self.db.dumps(storylines),
                    self.db.dumps(anchor_nodes),
                    story_input.output_language,
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
            row["bible_json"] = self._strip_macro_topology_from_bible(
                row["bible_json"] if isinstance(row["bible_json"], dict) else {}
            )
            compile_cfg = row["bible_json"].get("compile_config") if isinstance(row["bible_json"], dict) else {}
            row["branch_count_override"] = (
                int(compile_cfg.get("branch_count_override"))
                if isinstance(compile_cfg, dict) and compile_cfg.get("branch_count_override") is not None
                else None
            )
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
            row.setdefault("storylines_json", "[]")
            row.setdefault("anchor_nodes_json", "[]")
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
            raw_storylines = row.get("storylines_json")
            if isinstance(raw_storylines, str) and raw_storylines.strip():
                try:
                    row["storylines_json"] = self._coerce_json_list(self.db.loads(raw_storylines))
                except (json.JSONDecodeError, TypeError, ValueError):
                    row["storylines_json"] = []
            else:
                row["storylines_json"] = self._coerce_json_list(raw_storylines)
            raw_anchor_nodes = row.get("anchor_nodes_json")
            if isinstance(raw_anchor_nodes, str) and raw_anchor_nodes.strip():
                try:
                    row["anchor_nodes_json"] = self._coerce_json_list(self.db.loads(raw_anchor_nodes))
                except (json.JSONDecodeError, TypeError, ValueError):
                    row["anchor_nodes_json"] = []
            else:
                row["anchor_nodes_json"] = self._coerce_json_list(raw_anchor_nodes)
            # Backward compatibility for old rows where macro topology was embedded in bible_json.
            if not row["storylines_json"]:
                row["storylines_json"] = self._coerce_json_list(row["bible_json"].get("storylines"))
            if not row["anchor_nodes_json"]:
                row["anchor_nodes_json"] = self._coerce_json_list(row["bible_json"].get("anchor_nodes"))
            row.setdefault("output_language", "zh-Hant")
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
        clean_bible = self._strip_macro_topology_from_bible(dict(bible or {}))
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE stories SET bible_json = ? WHERE story_id = ?",
                (self.db.dumps(clean_bible), story_id),
            )

    def store_macro_plan_snapshot(
        self,
        story_id: str,
        *,
        bible: dict,
        storylines: list[dict[str, Any]],
        anchor_nodes: list[dict[str, Any]],
        volumes: list[VolumePlan],
        cast: list[StoryCastMemberStored],
        protagonist_character_id: str,
    ) -> None:
        """
        Persist a complete macro plan snapshot in a single SQLite transaction.

        This makes the SQLite side internally strongly consistent: either all macro-plan
        writes (bible/topology/volumes/cast) commit together or none do.
        """
        clean_bible = self._strip_macro_topology_from_bible(dict(bible or {}))
        clean_storylines = self._coerce_json_list(storylines)
        clean_anchor_nodes = self._coerce_json_list(anchor_nodes)
        cast_payload = [self._sanitize_cast_row(member.model_dump(mode="json")) for member in cast]
        prot = str(protagonist_character_id or "").strip()
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE stories
                SET bible_json = ?,
                    storylines_json = ?,
                    anchor_nodes_json = ?,
                    cast_json = ?,
                    protagonist_character_id = ?
                WHERE story_id = ?
                """,
                (
                    self.db.dumps(clean_bible),
                    self.db.dumps(clean_storylines),
                    self.db.dumps(clean_anchor_nodes),
                    self.db.dumps(cast_payload),
                    prot,
                    story_id,
                ),
            )
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

    def update_story_macro_topology(
        self,
        story_id: str,
        *,
        storylines: list[dict[str, Any]],
        anchor_nodes: list[dict[str, Any]],
    ) -> None:
        clean_storylines = self._coerce_json_list(storylines)
        clean_anchor_nodes = self._coerce_json_list(anchor_nodes)
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE stories
                SET storylines_json = ?, anchor_nodes_json = ?
                WHERE story_id = ?
                """,
                (self.db.dumps(clean_storylines), self.db.dumps(clean_anchor_nodes), story_id),
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
        if "branch_count_override" in data:
            bible = dict(story.get("bible_json") or {})
            cfg = dict(bible.get("compile_config") or {})
            if data["branch_count_override"] is None:
                cfg.pop("branch_count_override", None)
            else:
                cfg["branch_count_override"] = int(data["branch_count_override"])
            if cfg:
                bible["compile_config"] = cfg
            elif "compile_config" in bible:
                bible.pop("compile_config", None)
            fields.append("bible_json = ?")
            values.append(self.db.dumps(bible))
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
        if "output_language" in data and data["output_language"] is not None:
            fields.append("output_language = ?")
            values.append(str(data["output_language"]))
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
        payload = [self._sanitize_cast_row(member.model_dump(mode="json")) for member in cast]
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
        """Backward-compatible wrapper; prefer soft_upsert_story_cast_member."""
        self.soft_upsert_story_cast_member(story_id, member)

    def soft_upsert_story_cast_member(self, story_id: str, member: StoryCastMemberStored) -> None:
        """Upsert cast row by node_id in fill-empty mode; never overwrite non-empty existing fields."""
        story = self.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        raw = story.get("cast_json") or []
        if not isinstance(raw, list):
            raw = []
        incoming = self._sanitize_cast_row(member.model_dump(mode="json"))
        node_id = str(incoming.get("node_id") or "").strip()
        if not node_id:
            return

        payload: list[dict[str, Any]] = []
        matched = False
        for row in raw:
            if not isinstance(row, dict):
                continue
            current = self._sanitize_cast_row(row)
            if str(current.get("node_id") or "").strip() != node_id:
                payload.append(current)
                continue
            merged = dict(current)
            for key, val in incoming.items():
                cur_val = merged.get(key)
                is_empty = cur_val is None or cur_val == "" or cur_val == []
                if is_empty:
                    merged[key] = val
            payload.append(self._sanitize_cast_row(merged))
            matched = True

        if not matched:
            payload.append(incoming)
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE stories SET cast_json = ? WHERE story_id = ?",
                (self.db.dumps(payload), story_id),
            )

    def apply_cast_update(self, story_id: str, payload: dict[str, Any]) -> None:
        mode = str(payload.get("update_mode") or "fill_empty").strip().lower()
        member_raw = payload.get("member")
        if not isinstance(member_raw, dict):
            return
        incoming = StoryCastMemberStored.model_validate(member_raw)
        if mode != "evolution":
            self.soft_upsert_story_cast_member(story_id, incoming)
            return
        story = self.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        raw = story.get("cast_json") or []
        if not isinstance(raw, list):
            raw = []
        milestone_raw = payload.get("milestone")
        milestone = CharacterArcMilestone.model_validate(milestone_raw or {})
        dedupe_key = (
            str(milestone.trigger_event_id or "").strip(),
            int(milestone.chapter_id or 0),
            str(incoming.node_id).strip(),
        )
        updated_rows: list[dict[str, Any]] = []
        matched = False
        for row in raw:
            if not isinstance(row, dict):
                continue
            current = StoryCastMemberStored.model_validate(self._sanitize_cast_row(row))
            if current.node_id != incoming.node_id:
                updated_rows.append(self._sanitize_cast_row(current.model_dump(mode="json")))
                continue
            matched = True
            existing = list(current.arc_history or [])
            already = any(
                (
                    str(item.trigger_event_id or "").strip(),
                    int(item.chapter_id or 0),
                    str(current.node_id).strip(),
                )
                == dedupe_key
                for item in existing
            )
            if not already:
                existing.append(milestone)
            merged = current.model_copy(
                update={
                    "personality": incoming.personality,
                    "speech_style": incoming.speech_style,
                    "arc_history": existing,
                }
            )
            updated_rows.append(self._sanitize_cast_row(merged.model_dump(mode="json")))
        if not matched:
            base = incoming.model_copy(update={"arc_history": [milestone]})
            updated_rows.append(self._sanitize_cast_row(base.model_dump(mode="json")))
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE stories SET cast_json = ? WHERE story_id = ?",
                (self.db.dumps(updated_rows), story_id),
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

    def upsert_chapter_summary(
        self,
        story_id: str,
        chapter_id: int,
        *,
        plot_summary: str,
        conflict_type: ConflictType | str,
        resolution_method: ResolutionMethod | str,
        ending_vibe: EndingVibe | str = EndingVibe.ON_THE_MOVE,
        plot_summary_source: PlotSummarySource | str = PlotSummarySource.CHAPTER_SUMMARIZER_LLM,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        ctype = conflict_type.value if hasattr(conflict_type, "value") else str(conflict_type)
        rmethod = resolution_method.value if hasattr(resolution_method, "value") else str(resolution_method)
        evibe = ending_vibe.value if hasattr(ending_vibe, "value") else str(ending_vibe)
        psrc = (
            plot_summary_source.value
            if hasattr(plot_summary_source, "value")
            else str(plot_summary_source)
        )
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO chapter_summaries (
                    story_id, chapter_id, plot_summary, conflict_type, resolution_method,
                    ending_vibe, plot_summary_source, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id, chapter_id) DO UPDATE SET
                    plot_summary = excluded.plot_summary,
                    conflict_type = excluded.conflict_type,
                    resolution_method = excluded.resolution_method,
                    ending_vibe = excluded.ending_vibe,
                    plot_summary_source = excluded.plot_summary_source,
                    created_at = excluded.created_at
                """,
                (story_id, int(chapter_id), plot_summary, ctype, rmethod, evibe, psrc, created_at),
            )

    def get_recent_chapter_summaries(self, story_id: str, before_chapter_id: int, limit: int = 3) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT chapter_id, plot_summary, conflict_type, resolution_method, ending_vibe,
                       plot_summary_source, created_at
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

    def count_chapter_summaries_before(self, story_id: str, before_chapter_id: int) -> int:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM chapter_summaries
                WHERE story_id = ?
                  AND chapter_id < ?
                  AND trim(plot_summary) != ''
                """,
                (story_id, int(before_chapter_id)),
            ).fetchone()
        return int(row["c"]) if row else 0

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
                SELECT chapter_id, plot_summary, conflict_type, resolution_method, ending_vibe,
                       plot_summary_source, created_at
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
            conn.execute("DELETE FROM chapter_summaries WHERE story_id = ?", (story_id,))
            conn.execute("DELETE FROM milestone_summaries WHERE story_id = ?", (story_id,))
            conn.execute("DELETE FROM stories WHERE story_id = ?", (story_id,))
