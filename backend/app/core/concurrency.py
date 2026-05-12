"""Concurrency helpers that propagate ``contextvars`` across thread boundaries.

Python's standard :class:`concurrent.futures.ThreadPoolExecutor` does **not**
copy the calling thread's :class:`~contextvars.Context` to workers. That means
any :class:`~contextvars.ContextVar` set on the caller (e.g. the per-story
logging context bound by :mod:`app.core.story_logger`) is invisible inside the
worker, and per-story log records originating from pooled work get dropped.

``ContextThreadPoolExecutor`` is a drop-in replacement that wraps each
submitted callable in ``contextvars.copy_context().run(fn, *args, **kwargs)``,
preserving the caller's context. It accepts the same constructor arguments as
:class:`concurrent.futures.ThreadPoolExecutor`.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")


class ContextThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor that propagates contextvars to worker threads."""

    def submit(  # type: ignore[override]
        self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any
    ):
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)
