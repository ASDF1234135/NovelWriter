"""Per-story log system: router, context propagation, deletion, middleware,
and exception-handler tests."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor as RawThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.concurrency import ContextThreadPoolExecutor


@pytest.fixture(autouse=True)
def _isolated_log_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each test gets its own log dir + a fresh router singleton + clean settings cache."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NOVEL_BUILDER_STORY_LOG_DIR", str(log_dir))
    monkeypatch.setenv("NOVEL_BUILDER_STORY_LOG_MAX_BYTES", "1024")
    monkeypatch.setenv("NOVEL_BUILDER_STORY_LOG_BACKUP_COUNT", "2")
    monkeypatch.setenv("NOVEL_BUILDER_STORY_LOG_LEVEL", "INFO")

    # Drop cached settings + cached router so the new env vars take effect.
    from app.core.config import get_settings
    import app.core.story_logger as story_logger_mod

    get_settings.cache_clear()
    story_logger_mod._router_singleton = None  # noqa: SLF001

    # Detach any previously attached routers from prior tests to avoid cross-test
    # bleed when multiple tests configure logging.
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.__class__.__name__ == "StoryFileLogRouter":
            root.removeHandler(handler)

    yield log_dir

    # Cleanup: close handlers and detach router so the tmp_path can be removed.
    if story_logger_mod._router_singleton is not None:  # noqa: SLF001
        story_logger_mod._router_singleton.close()  # noqa: SLF001
        story_logger_mod._router_singleton = None  # noqa: SLF001
    for handler in list(root.handlers):
        if handler.__class__.__name__ == "StoryFileLogRouter":
            root.removeHandler(handler)
    get_settings.cache_clear()


def _read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        out.append(json.loads(raw))
    return out


def _attach_router() -> logging.Handler:
    from app.core.story_logger import get_story_log_router

    router = get_story_log_router()
    logging.getLogger().addHandler(router)
    logging.getLogger().setLevel(logging.INFO)
    return router


def test_router_drops_records_without_story_id(_isolated_log_env: Path) -> None:
    _attach_router()
    log = logging.getLogger("test.no_story")
    log.info("plain line with no story context")
    # No story files should appear at all.
    assert list(_isolated_log_env.iterdir()) == []


def test_router_writes_when_story_id_in_extra(_isolated_log_env: Path) -> None:
    _attach_router()
    log = logging.getLogger("test.via_extra")
    log.info(
        "hello via extra",
        extra={"story_id": "story_a", "source": "unit.test", "extra_key": 1},
    )
    log.warning(
        "watch out",
        extra={"story_id": "story_a", "source": "unit.test"},
    )

    lines = _read_lines(_isolated_log_env / "story_a.log")
    assert len(lines) == 2
    assert lines[0]["story_id"] == "story_a"
    assert lines[0]["level"] == "INFO"
    assert lines[0]["source"] == "unit.test"
    assert lines[0]["message"] == "hello via extra"
    assert lines[0]["extra"]["extra_key"] == 1
    assert lines[1]["level"] == "WARNING"


def test_router_writes_when_story_id_from_contextvar(_isolated_log_env: Path) -> None:
    _attach_router()
    from app.core.story_logger import bind_story_context

    log = logging.getLogger("test.via_ctx")
    with bind_story_context(story_id="story_b", run_id="run_1", chapter_id=3):
        log.error("ctx-bound error")

    lines = _read_lines(_isolated_log_env / "story_b.log")
    assert len(lines) == 1
    line = lines[0]
    assert line["level"] == "ERROR"
    assert line["story_id"] == "story_b"
    assert line["run_id"] == "run_1"
    assert line["chapter_id"] == 3


def test_router_extra_overrides_contextvar(_isolated_log_env: Path) -> None:
    _attach_router()
    from app.core.story_logger import bind_story_context

    log = logging.getLogger("test.priority")
    with bind_story_context(story_id="story_ctx"):
        log.info("explicit wins", extra={"story_id": "story_extra"})

    assert (_isolated_log_env / "story_extra.log").exists()
    assert not (_isolated_log_env / "story_ctx.log").exists()


def test_log_lines_are_jsonl_with_required_fields(_isolated_log_env: Path) -> None:
    _attach_router()
    log = logging.getLogger("test.schema")
    log.info("a", extra={"story_id": "story_schema", "source": "src.x"})

    line = _read_lines(_isolated_log_env / "story_schema.log")[0]
    for key in ("timestamp", "level", "source", "story_id", "run_id", "chapter_id", "message"):
        assert key in line
    # Timestamp must be ISO 8601 with offset.
    assert "T" in line["timestamp"]


def test_router_rotation_creates_backups(_isolated_log_env: Path) -> None:
    """story_log_max_bytes=1024 in the fixture; flooding should rotate."""
    _attach_router()
    log = logging.getLogger("test.rotation")
    for i in range(200):
        log.info(
            "x" * 100,
            extra={"story_id": "story_rot", "source": "rot.test", "i": i},
        )

    base = _isolated_log_env / "story_rot.log"
    assert base.exists()
    backups = list(_isolated_log_env.glob("story_rot.log.*"))
    assert len(backups) >= 1, "RotatingFileHandler should have produced at least one backup"


def test_delete_story_logs_removes_file_and_backups(_isolated_log_env: Path) -> None:
    _attach_router()
    from app.core.story_logger import delete_story_logs

    log = logging.getLogger("test.delete")
    for i in range(200):
        log.info("y" * 100, extra={"story_id": "story_del", "i": i})

    base = _isolated_log_env / "story_del.log"
    assert base.exists()
    backups_before = list(_isolated_log_env.glob("story_del.log.*"))
    assert backups_before, "expected at least one rotated backup before deletion"

    delete_story_logs("story_del")

    assert not base.exists()
    assert list(_isolated_log_env.glob("story_del.log*")) == []


def test_delete_story_logs_is_safe_when_nothing_exists(_isolated_log_env: Path) -> None:
    from app.core.story_logger import delete_story_logs

    delete_story_logs("never_existed")  # must not raise


def test_bind_story_context_nests_and_unwinds(_isolated_log_env: Path) -> None:
    _attach_router()
    from app.core.story_logger import (
        bind_story_context,
        current_chapter_id,
        current_run_id,
        current_story_id,
    )

    assert current_story_id.get() is None
    with bind_story_context(story_id="outer"):
        assert current_story_id.get() == "outer"
        with bind_story_context(run_id="r1", chapter_id=2):
            assert current_story_id.get() == "outer"
            assert current_run_id.get() == "r1"
            assert current_chapter_id.get() == 2
        assert current_run_id.get() is None
        assert current_chapter_id.get() is None
    assert current_story_id.get() is None


# --- ContextThreadPoolExecutor ------------------------------------------------


_probe_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_test_probe", default=None
)


def _read_probe() -> str | None:
    return _probe_var.get()


def test_raw_threadpool_drops_contextvars() -> None:
    """Negative control: stdlib ThreadPoolExecutor does NOT propagate context."""
    token = _probe_var.set("main-thread-value")
    try:
        with RawThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(_read_probe).result(timeout=5)
        assert result is None
    finally:
        _probe_var.reset(token)


def test_context_threadpool_propagates_contextvars() -> None:
    token = _probe_var.set("main-thread-value")
    try:
        with ContextThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(_read_probe).result(timeout=5)
        assert result == "main-thread-value"
    finally:
        _probe_var.reset(token)


def test_context_threadpool_isolates_per_submit() -> None:
    """Mutations done by a worker must not leak back to the caller's Context."""
    token = _probe_var.set("initial")
    try:
        def _mutate_and_read() -> tuple[str | None, str | None]:
            seen = _probe_var.get()
            _probe_var.set("worker-only")
            return seen, _probe_var.get()

        with ContextThreadPoolExecutor(max_workers=1) as pool:
            seen_in_worker, after_set = pool.submit(_mutate_and_read).result(timeout=5)
        assert seen_in_worker == "initial"
        assert after_set == "worker-only"
        # Caller thread's value is untouched.
        assert _probe_var.get() == "initial"
    finally:
        _probe_var.reset(token)


def test_story_id_propagates_through_context_threadpool(_isolated_log_env: Path) -> None:
    """The whole point of this whole subsystem: per-story logs from pooled work."""
    _attach_router()
    from app.core.story_logger import bind_story_context

    log = logging.getLogger("test.pool")

    def _worker() -> None:
        log.info("from worker", extra={"source": "pool.worker"})

    with bind_story_context(story_id="story_pool"):
        with ContextThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_worker) for _ in range(4)]
            for f in futures:
                f.result(timeout=5)

    lines = _read_lines(_isolated_log_env / "story_pool.log")
    assert len(lines) == 4
    for line in lines:
        assert line["story_id"] == "story_pool"
        assert line["source"] == "pool.worker"


# --- Middleware & exception handlers ------------------------------------------


def _build_test_app() -> FastAPI:
    """Build a minimal FastAPI app that mirrors the real middleware + handlers
    so we can exercise the per-request context binding and the handler
    logging without booting the full backend."""
    import logging as _logging
    import traceback

    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from app.api.middleware import StoryContextMiddleware

    app = FastAPI()
    app.add_middleware(StoryContextMiddleware)

    api_logger = _logging.getLogger("app.main")

    def _api_log_extra(request, source: str) -> dict:
        story_id = getattr(request.state, "story_id", None)
        run_id = getattr(request.state, "run_id", None)
        return {
            "source": source,
            "story_id": story_id,
            "run_id": run_id,
            "method": request.method,
            "path": request.url.path,
        }

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request, exc):
        level = _logging.ERROR if exc.status_code >= 500 else _logging.WARNING
        api_logger.log(
            level,
            "HTTP exception",
            extra={
                **_api_log_extra(request, "api.http_exception"),
                "status_code": exc.status_code,
                "detail": str(exc.detail)[:500],
            },
        )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def _val_handler(request, exc):
        api_logger.warning(
            "Request validation failed",
            extra={
                **_api_log_extra(request, "api.validation_error"),
                "status_code": 422,
                "errors": exc.errors(),
            },
        )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(Exception)
    async def _unhandled(request, exc):
        api_logger.error(
            "Unhandled exception",
            extra={
                **_api_log_extra(request, "api.unhandled"),
                "status_code": 500,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "traceback": traceback.format_exc()[-4000:],
            },
            exc_info=exc,
        )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    router = APIRouter()

    @router.get("/api/stories/{story_id}/ok")
    def _ok(story_id: str) -> dict:
        return {"story_id": story_id}

    @router.get("/api/stories/{story_id}/boom")
    def _boom(story_id: str) -> dict:
        raise RuntimeError(f"forced failure for {story_id}")

    @router.get("/api/stories/{story_id}/missing")
    def _missing(story_id: str) -> dict:
        raise HTTPException(status_code=404, detail=f"not found: {story_id}")

    app.include_router(router)
    return app


def test_middleware_logs_successful_request_per_story(_isolated_log_env: Path) -> None:
    _attach_router()
    app = _build_test_app()
    client = TestClient(app)

    resp = client.get("/api/stories/story_ok/ok")
    assert resp.status_code == 200

    lines = _read_lines(_isolated_log_env / "story_ok.log")
    sources = {line["source"] for line in lines}
    assert "api.access" in sources
    access_line = next(line for line in lines if line["source"] == "api.access")
    assert access_line["story_id"] == "story_ok"
    assert access_line["extra"]["method"] == "GET"
    assert access_line["extra"]["status_code"] == 200
    assert isinstance(access_line["extra"]["elapsed_ms"], int)


def test_http_exception_handler_logs_warning(_isolated_log_env: Path) -> None:
    _attach_router()
    app = _build_test_app()
    client = TestClient(app)

    resp = client.get("/api/stories/story_404/missing")
    assert resp.status_code == 404

    lines = _read_lines(_isolated_log_env / "story_404.log")
    http_lines = [line for line in lines if line["source"] == "api.http_exception"]
    assert len(http_lines) == 1
    assert http_lines[0]["level"] == "WARNING"
    assert http_lines[0]["story_id"] == "story_404"
    assert http_lines[0]["extra"]["status_code"] == 404


def test_unhandled_exception_handler_logs_error(_isolated_log_env: Path) -> None:
    _attach_router()
    app = _build_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/stories/story_500/boom")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal Server Error"}

    lines = _read_lines(_isolated_log_env / "story_500.log")
    err_lines = [line for line in lines if line["source"] == "api.unhandled"]
    assert len(err_lines) == 1
    err = err_lines[0]
    assert err["level"] == "ERROR"
    assert err["story_id"] == "story_500"
    assert err["extra"]["error_type"] == "RuntimeError"
    assert "forced failure for story_500" in err["extra"]["error"]
    # Traceback is truncated to the most recent 4000 chars (so the "Traceback
    # (most recent call last):" header may be sliced off); assert on stable
    # markers that are guaranteed to land near the tail of the trace.
    tb = err["extra"]["traceback"]
    assert "RuntimeError: forced failure for story_500" in tb
    assert "_boom" in tb
