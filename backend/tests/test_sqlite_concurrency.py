"""Smoke tests for SQLite WAL + timeout under concurrent API-style access."""

from __future__ import annotations

import threading

from app.domain.state import build_initial_state
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.workflow_repository import WorkflowRepository


def test_concurrent_reads_and_writes_on_workflow_run(tmp_path) -> None:
    db_path = str(tmp_path / "concurrent.sqlite3")
    db = SQLiteDatabase(db_path)
    repo = WorkflowRepository(db)
    state = dict(
        build_initial_state(
            "story_concurrent",
            1,
            [],
            trace_id="trace-1",
            plan_retry_limit=3,
            draft_loop_retry_limit=3,
        )
    )
    run = repo.create_run("story_concurrent", 1, state)
    run_id = run.run_id
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def write_loop(tag: int) -> None:
        try:
            barrier.wait()
            for i in range(25):
                st = repo.get_run_state(run_id)
                st["concurrent_touch"] = f"w{tag}-{i}"
                repo.update_run(run_id, st)
        except BaseException as exc:
            errors.append(exc)

    def read_loop() -> None:
        try:
            barrier.wait()
            for _ in range(50):
                repo.get_run_state(run_id)
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=write_loop, args=(0,)),
        threading.Thread(target=write_loop, args=(1,)),
        threading.Thread(target=read_loop),
        threading.Thread(target=read_loop),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
