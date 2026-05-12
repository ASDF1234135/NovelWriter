"""Per-story logging: ContextVar-routed JSON Lines logger.

This module provides a `logging.Handler` (`StoryFileLogRouter`) that routes log
records to a per-story file under `Settings.story_log_dir`. The routing is
driven by either:
- an explicit `extra={"story_id": "...", ...}` on the log call, or
- the `current_story_id` `ContextVar` (set by `bind_story_context`).

Only records that resolve to a `story_id` are written to a story file. All
other records pass through the normal root-logger handlers (e.g. the console
StreamHandler) without touching the per-story files.

Files are JSON Lines (one JSON object per line) and use a `RotatingFileHandler`
for size-based rotation. `delete_story_logs(story_id)` closes the cached
handler and removes the base file plus any rotated backups; this is called
during story deletion so per-story files do not outlive their story.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import threading
from datetime import datetime, UTC
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterator

from app.core.config import get_settings

current_story_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_story_id", default=None
)
current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_run_id", default=None
)
current_chapter_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_chapter_id", default=None
)


# Reserved keys on LogRecord we never want to re-emit under "extra".
_RESERVED_RECORD_KEYS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info", "thread",
    "threadName", "taskName",
    # Custom routing attrs handled separately.
    "story_id", "run_id", "chapter_id", "source", "extra_payload",
}


def _resolve_story_id(record: logging.LogRecord) -> str | None:
    sid = getattr(record, "story_id", None)
    if sid:
        return str(sid)
    sid_cv = current_story_id.get()
    return str(sid_cv) if sid_cv else None


def _resolve_run_id(record: logging.LogRecord) -> str | None:
    rid = getattr(record, "run_id", None)
    if rid:
        return str(rid)
    rid_cv = current_run_id.get()
    return str(rid_cv) if rid_cv else None


def _resolve_chapter_id(record: logging.LogRecord) -> int | None:
    cid = getattr(record, "chapter_id", None)
    if cid is not None:
        try:
            return int(cid)
        except (TypeError, ValueError):
            return None
    cid_cv = current_chapter_id.get()
    if cid_cv is None:
        return None
    try:
        return int(cid_cv)
    except (TypeError, ValueError):
        return None


def _record_extra_payload(record: logging.LogRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    explicit = getattr(record, "extra_payload", None)
    if isinstance(explicit, dict):
        payload.update(explicit)
    for key, value in record.__dict__.items():
        if key in _RESERVED_RECORD_KEYS:
            continue
        if key.startswith("_"):
            continue
        payload[key] = value
    return payload


class StoryJsonFormatter(logging.Formatter):
    """Render a LogRecord as a single JSON line for the per-story file."""

    def format(self, record: logging.LogRecord) -> str:
        source_attr = getattr(record, "source", None)
        source = str(source_attr) if source_attr else record.name
        line: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "source": source,
            "story_id": _resolve_story_id(record),
            "run_id": _resolve_run_id(record),
            "chapter_id": _resolve_chapter_id(record),
            "message": record.getMessage(),
        }
        if record.exc_info:
            line["exc_info"] = self.formatException(record.exc_info)
        extra = _record_extra_payload(record)
        if extra:
            line["extra"] = _json_safe(extra)
        return json.dumps(line, ensure_ascii=False, default=str)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class StoryFileLogRouter(logging.Handler):
    """Route records carrying a `story_id` to a per-story rotating file.

    Records without a resolvable `story_id` are silently skipped so that
    general system logs (e.g. startup messages) do not create empty files.
    """

    def __init__(self, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self.setFormatter(StoryJsonFormatter())
        self._handlers: dict[str, RotatingFileHandler] = {}
        self._handlers_lock = threading.Lock()

    def _log_dir(self) -> Path:
        settings = get_settings()
        path = Path(settings.story_log_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _get_or_create_handler(self, story_id: str) -> RotatingFileHandler:
        with self._handlers_lock:
            cached = self._handlers.get(story_id)
            if cached is not None:
                return cached
            settings = get_settings()
            file_path = self._log_dir() / f"{story_id}.log"
            handler = RotatingFileHandler(
                str(file_path),
                maxBytes=int(settings.story_log_max_bytes),
                backupCount=int(settings.story_log_backup_count),
                encoding="utf-8",
                delay=True,
            )
            handler.setFormatter(self.formatter)
            self._handlers[story_id] = handler
            return handler

    def emit(self, record: logging.LogRecord) -> None:
        try:
            story_id = _resolve_story_id(record)
            if not story_id:
                return
            handler = self._get_or_create_handler(story_id)
            handler.emit(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)

    def close_story(self, story_id: str) -> None:
        with self._handlers_lock:
            handler = self._handlers.pop(story_id, None)
        if handler is not None:
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        with self._handlers_lock:
            handlers = list(self._handlers.values())
            self._handlers.clear()
        for handler in handlers:
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass
        super().close()


_router_singleton_lock = threading.Lock()
_router_singleton: StoryFileLogRouter | None = None


def get_story_log_router() -> StoryFileLogRouter:
    """Return the process-wide router, creating it lazily."""
    global _router_singleton
    with _router_singleton_lock:
        if _router_singleton is None:
            settings = get_settings()
            level_name = str(settings.story_log_level or "INFO").upper()
            level = logging.getLevelName(level_name)
            if not isinstance(level, int):
                level = logging.INFO
            _router_singleton = StoryFileLogRouter(level=level)
        return _router_singleton


def delete_story_logs(story_id: str) -> None:
    """Close the cached handler and remove the story log file + rotated backups."""
    if not story_id:
        return
    router = get_story_log_router()
    router.close_story(story_id)
    settings = get_settings()
    log_dir = Path(settings.story_log_dir).resolve()
    base = log_dir / f"{story_id}.log"
    candidates = [base]
    for i in range(1, int(settings.story_log_backup_count) + 1):
        candidates.append(log_dir / f"{story_id}.log.{i}")
    for path in candidates:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            # Best-effort: a stale Windows handle would surface here.
            pass


@contextlib.contextmanager
def bind_story_context(
    story_id: str | None = None,
    *,
    run_id: str | None = None,
    chapter_id: int | None = None,
) -> Iterator[None]:
    """Bind story / run / chapter context vars for the wrapped block.

    Only sets a contextvar if the corresponding argument is not None, so
    callers can selectively narrow the context (e.g. add `run_id` while
    `story_id` is already bound by an outer scope).
    """
    tokens: list[tuple[contextvars.ContextVar[Any], contextvars.Token[Any]]] = []
    if story_id is not None:
        tokens.append((current_story_id, current_story_id.set(str(story_id))))
    if run_id is not None:
        tokens.append((current_run_id, current_run_id.set(str(run_id))))
    if chapter_id is not None:
        try:
            tokens.append((current_chapter_id, current_chapter_id.set(int(chapter_id))))
        except (TypeError, ValueError):
            pass
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            try:
                var.reset(token)
            except ValueError:
                # Token was created in a different Context (e.g. across thread
                # boundaries with copy_context().run). Ignore: the new Context
                # will be discarded when the worker frame unwinds anyway.
                pass
