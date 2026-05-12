from __future__ import annotations

from datetime import datetime, UTC
from typing import Any
from uuid import uuid4

from app.domain.schema import StateTransactionRecord, StateTransactionStatus, WorkflowRun, WorkflowStatus, WorkflowStepLog
from app.repositories.sqlite.database import SQLiteDatabase


class WorkflowRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self.db = db

    def create_run(self, story_id: str, chapter_id: int, initial_state: dict) -> WorkflowRun:
        run = WorkflowRun(
            run_id=str(uuid4()),
            story_id=story_id,
            chapter_id=chapter_id,
            status=WorkflowStatus.RUNNING,
            current_agent="bootstrap",
            requires_hitl=False,
        )
        now = datetime.now(UTC).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, story_id, chapter_id, status, current_agent, requires_hitl,
                    hitl_reason, hitl_decision_mode, current_state_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    story_id,
                    chapter_id,
                    run.status.value,
                    run.current_agent,
                    int(run.requires_hitl),
                    run.hitl_reason,
                    run.hitl_decision_mode.value,
                    self.db.dumps(initial_state),
                    now,
                    now,
                ),
            )
        return run

    def update_run(self, run_id: str, state: dict) -> WorkflowRun:
        now = datetime.now(UTC).isoformat()
        status = state.get("workflow_status", WorkflowStatus.RUNNING.value)
        current_agent = state.get("last_agent", "unknown")
        requires_hitl = bool(state.get("requires_hitl", False))
        hitl_reason = state.get("hitl_reason", "")
        hitl_decision_mode = state.get("hitl_decision_mode", "NONE")
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?, current_agent = ?, requires_hitl = ?, hitl_reason = ?,
                    hitl_decision_mode = ?, current_state_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    current_agent,
                    int(requires_hitl),
                    hitl_reason,
                    hitl_decision_mode,
                    self.db.dumps(state),
                    now,
                    run_id,
                ),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> WorkflowRun:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise KeyError(f"Workflow run not found: {run_id}")
        return WorkflowRun(
            run_id=row["run_id"],
            story_id=row["story_id"],
            chapter_id=row["chapter_id"],
            status=WorkflowStatus(row["status"]),
            current_agent=row["current_agent"],
            requires_hitl=bool(row["requires_hitl"]),
            hitl_reason=row["hitl_reason"],
            hitl_decision_mode=row["hitl_decision_mode"],
        )

    def get_run_state(self, run_id: str) -> dict:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT current_state_json FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Workflow run not found: {run_id}")
        return self.db.loads(row["current_state_json"])

    def list_run_summaries_for_story(
        self,
        story_id: str,
        *,
        chapter_id: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lightweight run listing for metrics (no current_state_json). Newest first."""
        lim = max(1, min(int(limit), 500))
        off = max(0, int(offset))
        with self.db.connection() as conn:
            if chapter_id is None:
                rows = conn.execute(
                    """
                    SELECT run_id, story_id, chapter_id, status, current_agent, requires_hitl,
                           hitl_reason, hitl_decision_mode, created_at, updated_at
                    FROM workflow_runs
                    WHERE story_id = ?
                    ORDER BY updated_at DESC, run_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (story_id, lim, off),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT run_id, story_id, chapter_id, status, current_agent, requires_hitl,
                           hitl_reason, hitl_decision_mode, created_at, updated_at
                    FROM workflow_runs
                    WHERE story_id = ? AND chapter_id = ?
                    ORDER BY updated_at DESC, run_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (story_id, chapter_id, lim, off),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "run_id": row["run_id"],
                    "story_id": row["story_id"],
                    "chapter_id": int(row["chapter_id"]),
                    "status": row["status"],
                    "current_agent": row["current_agent"],
                    "requires_hitl": bool(row["requires_hitl"]),
                    "hitl_reason": row["hitl_reason"],
                    "hitl_decision_mode": row["hitl_decision_mode"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return out

    def append_step(self, log: WorkflowStepLog) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO workflow_steps (
                    step_id, run_id, step_index, agent_name, status, input_payload_json,
                    output_payload_json, masked_payload_json, token_usage, latency_ms,
                    route_decision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.step_id,
                    log.run_id,
                    log.step_index,
                    log.agent_name,
                    log.status,
                    self.db.dumps(log.input_payload),
                    self.db.dumps(log.output_payload),
                    self.db.dumps(log.masked_payload),
                    log.token_usage,
                    log.latency_ms,
                    log.route_decision,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def append_step_and_update_run(self, log: WorkflowStepLog, state: dict) -> None:
        """Single transaction: step log + workflow run snapshot (reduces SQLite lock contention)."""
        now = datetime.now(UTC).isoformat()
        status = state.get("workflow_status", WorkflowStatus.RUNNING.value)
        current_agent = state.get("last_agent", "unknown")
        requires_hitl = bool(state.get("requires_hitl", False))
        hitl_reason = state.get("hitl_reason", "")
        hitl_decision_mode = state.get("hitl_decision_mode", "NONE")
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO workflow_steps (
                    step_id, run_id, step_index, agent_name, status, input_payload_json,
                    output_payload_json, masked_payload_json, token_usage, latency_ms,
                    route_decision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.step_id,
                    log.run_id,
                    log.step_index,
                    log.agent_name,
                    log.status,
                    self.db.dumps(log.input_payload),
                    self.db.dumps(log.output_payload),
                    self.db.dumps(log.masked_payload),
                    log.token_usage,
                    log.latency_ms,
                    log.route_decision,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?, current_agent = ?, requires_hitl = ?, hitl_reason = ?,
                    hitl_decision_mode = ?, current_state_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    current_agent,
                    int(requires_hitl),
                    hitl_reason,
                    hitl_decision_mode,
                    self.db.dumps(state),
                    now,
                    log.run_id,
                ),
            )

    def list_steps(self, run_id: str) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_steps
                WHERE run_id = ?
                ORDER BY step_index ASC
                """,
                (run_id,),
            ).fetchall()
        for row in rows:
            row["input_payload_json"] = self.db.loads(row["input_payload_json"])
            row["output_payload_json"] = self.db.loads(row["output_payload_json"])
            row["masked_payload_json"] = self.db.loads(row["masked_payload_json"])
        return list(rows)

    def append_hitl_action(self, run_id: str, action_type: str, payload: dict) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO hitl_actions (action_id, run_id, action_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    run_id,
                    action_type,
                    self.db.dumps(payload),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def list_hitl_actions(self, run_id: str, *, limit: int = 100, offset: int = 0) -> list[dict]:
        lim = max(1, min(int(limit), 500))
        off = max(0, int(offset))
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT action_id, run_id, action_type, payload_json, created_at
                FROM hitl_actions
                WHERE run_id = ?
                ORDER BY created_at ASC, action_id ASC
                LIMIT ? OFFSET ?
                """,
                (run_id, lim, off),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "action_id": row["action_id"],
                    "run_id": row["run_id"],
                    "action_type": row["action_type"],
                    "payload": self.db.loads(row["payload_json"]),
                    "created_at": row["created_at"],
                }
            )
        return out

    def create_state_transaction(self, run_id: str, story_id: str, chapter_id: int, payload: dict) -> StateTransactionRecord:
        record = StateTransactionRecord(
            transaction_id=str(uuid4()),
            run_id=run_id,
            story_id=story_id,
            chapter_id=chapter_id,
            status=StateTransactionStatus.PENDING,
            payload=payload,
        )
        now = datetime.now(UTC).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO state_transactions (
                    transaction_id, run_id, story_id, chapter_id, status, graph_applied,
                    vector_applied, sqlite_applied, payload_json, error_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.transaction_id,
                    run_id,
                    story_id,
                    chapter_id,
                    record.status.value,
                    0,
                    0,
                    0,
                    self.db.dumps(payload),
                    "",
                    now,
                    now,
                ),
            )
        return record

    def update_state_transaction(
        self,
        transaction_id: str,
        *,
        status: StateTransactionStatus | None = None,
        graph_applied: bool | None = None,
        vector_applied: bool | None = None,
        sqlite_applied: bool | None = None,
        error_text: str | None = None,
    ) -> StateTransactionRecord:
        current = self.get_state_transaction(transaction_id)
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE state_transactions
                SET status = ?, graph_applied = ?, vector_applied = ?, sqlite_applied = ?,
                    error_text = ?, updated_at = ?
                WHERE transaction_id = ?
                """,
                (
                    (status or current.status).value,
                    int(current.graph_applied if graph_applied is None else graph_applied),
                    int(current.vector_applied if vector_applied is None else vector_applied),
                    int(current.sqlite_applied if sqlite_applied is None else sqlite_applied),
                    current.error_text if error_text is None else error_text,
                    datetime.now(UTC).isoformat(),
                    transaction_id,
                ),
            )
        return self.get_state_transaction(transaction_id)

    def get_state_transaction(self, transaction_id: str) -> StateTransactionRecord:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM state_transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"State transaction not found: {transaction_id}")
        return StateTransactionRecord(
            transaction_id=row["transaction_id"],
            run_id=row["run_id"],
            story_id=row["story_id"],
            chapter_id=row["chapter_id"],
            status=StateTransactionStatus(row["status"]),
            graph_applied=bool(row["graph_applied"]),
            vector_applied=bool(row["vector_applied"]),
            sqlite_applied=bool(row["sqlite_applied"]),
            payload=self.db.loads(row["payload_json"]),
            error_text=row["error_text"],
        )

    def count_workflow_runs_for_story(self, story_id: str) -> int:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM workflow_runs WHERE story_id = ?",
                (story_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def delete_all_for_story(self, story_id: str) -> None:
        """Delete workflow runs and dependent rows for a story (SQLite has no FK CASCADE)."""
        with self.db.connection() as conn:
            rows = conn.execute("SELECT run_id FROM workflow_runs WHERE story_id = ?", (story_id,)).fetchall()
            for row in rows:
                run_id = row["run_id"]
                conn.execute("DELETE FROM workflow_steps WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM hitl_actions WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM state_transactions WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM workflow_runs WHERE story_id = ?", (story_id,))
