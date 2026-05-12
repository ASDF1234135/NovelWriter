"""HTTP middleware that binds per-story logging context for the request lifetime.

For story-scoped URLs we extract identifiers from the path with a precompiled
regex and bind them to the `story_logger` context vars so any `logger.*` call
made by the route handler (and the FastAPI BackgroundTasks it schedules) is
routed to the per-story log file automatically. The middleware also emits an
INFO `api.access` line after `call_next` returns, capturing the HTTP method,
path, status code, and elapsed time in milliseconds.

Failures within the route propagate to the registered FastAPI exception
handlers (see `app.main`); this middleware never swallows or transforms them.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.story_logger import bind_story_context

logger = logging.getLogger(__name__)

_STORY_RE = re.compile(r"^/api/stories/(?P<story_id>[^/]+)(?:/|$)")
_WORKFLOW_RE = re.compile(r"^/api/workflows/(?P<run_id>[^/]+)(?:/|$)")


def _resolve_story_id_from_run(run_id: str) -> str | None:
    """Look up the story_id that owns this workflow run. Best-effort: any
    exception (including the row not yet existing) returns None so middleware
    never fails the request just to attach a log tag."""
    try:
        from app.dependencies import get_workflow_repository

        repo = get_workflow_repository()
        with repo.db.connection() as conn:
            row = conn.execute(
                "SELECT story_id FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            sid = row["story_id"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
            return str(sid) if sid else None
    except Exception:
        return None


class StoryContextMiddleware(BaseHTTPMiddleware):
    """Bind story / run / chapter context vars and emit per-request access logs."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path or ""
        story_id: str | None = None
        run_id: str | None = None

        m_story = _STORY_RE.match(path)
        if m_story:
            story_id = m_story.group("story_id")
        else:
            m_run = _WORKFLOW_RE.match(path)
            if m_run:
                run_id = m_run.group("run_id")
                story_id = _resolve_story_id_from_run(run_id)

        request.state.story_id = story_id
        request.state.run_id = run_id

        start = time.perf_counter()
        with bind_story_context(story_id=story_id, run_id=run_id):
            response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        # Emit the access line outside the context manager so the bound vars
        # are already torn down; pass identifiers explicitly via extra so the
        # router still routes the line to the correct story file.
        logger.info(
            "API request",
            extra={
                "source": "api.access",
                "story_id": story_id,
                "run_id": run_id,
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        return response
