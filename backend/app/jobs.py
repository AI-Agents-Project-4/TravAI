"""Background work: a trip's research and planning run outside the request.

One worker thread, so runs happen one at a time. That's deliberate: the research
agent's settings (data mode, cache TTL) are process-wide, so two runs at once
could interfere (researchAgent/README.md). Fine for a class demo; a real
deployment would use a proper job queue.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trip-job")

JobRunner = Callable[..., None]


def _safe(fn: Callable[..., Any], *args: Any) -> None:
    try:
        fn(*args)
    except Exception:  # the job records its own failure; this is the last resort
        log.exception("background job crashed")


def run_in_background(fn: Callable[..., Any], *args: Any) -> None:
    _executor.submit(_safe, fn, *args)


def get_job_runner() -> JobRunner:
    """FastAPI dependency: how routes start background work (tests run it inline)."""
    return run_in_background
