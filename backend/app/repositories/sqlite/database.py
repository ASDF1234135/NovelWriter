from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import get_settings


def _dict_factory(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class SQLiteDatabase:
    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path or settings.sqlite_file)
        self._connect_timeout = float(settings.sqlite_connect_timeout_seconds)
        self._busy_timeout_ms = int(settings.sqlite_busy_timeout_ms)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=self._connect_timeout)
        conn.row_factory = _dict_factory
        conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout_ms)}")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS stories (
                    story_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    premise TEXT NOT NULL,
                    bible_json TEXT NOT NULL,
                    target_total_words INTEGER NOT NULL,
                    plan_retry_limit INTEGER NOT NULL DEFAULT 3,
                    draft_loop_retry_limit INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS volumes (
                    volume_id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    chapter_start INTEGER NOT NULL,
                    chapter_end INTEGER NOT NULL,
                    target_volume_words INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS chapters (
                    chapter_key TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    chapter_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    chapter_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    current_agent TEXT NOT NULL,
                    requires_hitl INTEGER NOT NULL,
                    hitl_reason TEXT NOT NULL,
                    hitl_decision_mode TEXT NOT NULL,
                    current_state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_steps (
                    step_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_payload_json TEXT NOT NULL,
                    output_payload_json TEXT NOT NULL,
                    masked_payload_json TEXT NOT NULL,
                    token_usage INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    route_decision TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS hitl_actions (
                    action_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS state_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    story_id TEXT NOT NULL,
                    chapter_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    graph_applied INTEGER NOT NULL,
                    vector_applied INTEGER NOT NULL,
                    sqlite_applied INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    error_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- Structured chapter/milestone summaries (for director anti-repetition + macro pacing)
                CREATE TABLE IF NOT EXISTS chapter_summaries (
                    story_id TEXT NOT NULL,
                    chapter_id INTEGER NOT NULL,
                    plot_summary TEXT NOT NULL,
                    conflict_type TEXT NOT NULL,
                    resolution_method TEXT NOT NULL,
                    ending_vibe TEXT NOT NULL DEFAULT 'ON_THE_MOVE',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (story_id, chapter_id)
                );

                CREATE TABLE IF NOT EXISTS milestone_summaries (
                    story_id TEXT NOT NULL,
                    chapter_start INTEGER NOT NULL,
                    chapter_end INTEGER NOT NULL,
                    milestone_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (story_id, chapter_start, chapter_end)
                );
                """
            )
            self._ensure_column(conn, "stories", "plan_retry_limit", "INTEGER NOT NULL DEFAULT 3")
            self._ensure_column(conn, "stories", "draft_loop_retry_limit", "INTEGER NOT NULL DEFAULT 3")
            self._ensure_column(conn, "stories", "cast_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "stories", "protagonist_character_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "stories", "macro_author_notes", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "stories", "macro_compile_status", "TEXT NOT NULL DEFAULT 'IDLE'")
            self._ensure_column(conn, "stories", "macro_compile_updated_at", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "stories", "macro_compile_error", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "stories", "cast_seed_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "stories", "storylines_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "stories", "anchor_nodes_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(
                conn,
                "stories",
                "output_language",
                "TEXT NOT NULL DEFAULT 'zh-Hant'",
            )
            self._ensure_column(
                conn,
                "stories",
                "require_chapter_review",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(conn, "volumes", "target_volume_words", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(
                conn,
                "chapter_summaries",
                "ending_vibe",
                "TEXT NOT NULL DEFAULT 'ON_THE_MOVE'",
            )
            self._ensure_column(
                conn,
                "chapter_summaries",
                "plot_summary_source",
                "TEXT NOT NULL DEFAULT 'UNKNOWN'",
            )
            self._ensure_column(
                conn,
                "stories",
                "story_runtime_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._migrate_story_runtime_split(conn)
            # Legacy table removed: runtime/navigation now reads storylines + anchor_nodes_json.
            conn.execute("DROP TABLE IF EXISTS anchors")
            conn.execute("PRAGMA journal_mode=WAL")

    @staticmethod
    def dumps(payload: object) -> str:
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def loads(payload: str) -> object:
        return json.loads(payload)

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        existing_columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    @staticmethod
    def _migrate_story_runtime_split(conn: sqlite3.Connection) -> None:
        """One-time: move bible_json runtime keys + anchor status into story_runtime_json; skeleton-only anchors."""
        ver_row = conn.execute("PRAGMA user_version").fetchone()
        current_v = int(ver_row["user_version"]) if ver_row and ver_row["user_version"] is not None else 0
        if current_v >= 6:
            return

        from app.domain.story_runtime import (
            anchor_nodes_to_skeleton_rows,
            extract_runtime_from_bible,
            parse_story_runtime,
            resolved_anchors_from_skeleton_and_legacy,
            strip_runtime_keys_from_bible,
        )

        rows = conn.execute(
            """
            SELECT story_id, bible_json, anchor_nodes_json,
                   COALESCE(NULLIF(trim(story_runtime_json), ''), '{}') AS srj
            FROM stories
            """
        ).fetchall()

        for row in rows:
            story_id = str(row["story_id"])
            try:
                bible_loaded = json.loads(row["bible_json"]) if row["bible_json"] else {}
            except (json.JSONDecodeError, TypeError, ValueError):
                bible_loaded = {}
            bible = bible_loaded if isinstance(bible_loaded, dict) else {}

            try:
                anchor_loaded = json.loads(row["anchor_nodes_json"]) if row["anchor_nodes_json"] else []
            except (json.JSONDecodeError, TypeError, ValueError):
                anchor_loaded = []
            nodes = [dict(n) for n in anchor_loaded if isinstance(n, dict)]

            try:
                existing_rt = parse_story_runtime(json.loads(row["srj"]))
            except (json.JSONDecodeError, TypeError, ValueError):
                existing_rt = parse_story_runtime({})

            rt_from_bible = extract_runtime_from_bible(bible)
            merged_resolved = resolved_anchors_from_skeleton_and_legacy(
                bible_resolved=rt_from_bible["resolved_anchors"],
                nodes_skeleton_or_full=nodes,
            )
            runtime = parse_story_runtime(existing_rt)
            runtime["resolved_anchors"] = merged_resolved
            if rt_from_bible["anchor_candidates"]:
                runtime["anchor_candidates"] = list(rt_from_bible["anchor_candidates"])
            if rt_from_bible["lore_mysteries_progression"]:
                runtime["lore_mysteries_progression"] = list(rt_from_bible["lore_mysteries_progression"])

            skeleton, prop_updates = anchor_nodes_to_skeleton_rows(nodes)
            runtime["anchor_properties"] = {**runtime["anchor_properties"], **prop_updates}

            bible_clean = strip_runtime_keys_from_bible(bible)
            conn.execute(
                """
                UPDATE stories
                SET bible_json = ?, anchor_nodes_json = ?, story_runtime_json = ?
                WHERE story_id = ?
                """,
                (
                    json.dumps(bible_clean, ensure_ascii=False),
                    json.dumps(skeleton, ensure_ascii=False),
                    json.dumps(runtime, ensure_ascii=False),
                    story_id,
                ),
            )

        conn.execute("PRAGMA user_version = 6")
