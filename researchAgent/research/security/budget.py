"""Per-trip limits and usage logging for the research agent (threat model T6).

One `TripBudget` per research run. `run()` makes it the *active* budget with `use(...)`,
and every real network request and `claude -p` call charges it. Cache hits cost nothing,
so offline replays use no budget. Each `charge_*` raises `BudgetExceeded` once a limit is
hit, so the agent stops instead of looping, and `stopped_by` says which limit it was.

Threads: the pipeline uses thread pools, and a worker thread does not inherit the active
budget by itself. Submit work with `submit_in_context` / `map_in_context` so it does.
"""

from __future__ import annotations

import contextvars
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Optional

from . import config


class BudgetExceeded(Exception):
    """A per-trip limit was reached. `limit` names which one."""

    def __init__(self, limit: str, detail: str):
        super().__init__(f"{limit}: {detail}")
        self.limit = limit


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = config.MAX_TOOL_CALLS_PER_TRIP
    max_tokens: int = config.MAX_TOKENS_PER_TRIP
    max_seconds: float = config.MAX_SECONDS_PER_TRIP
    max_pages: int = config.MAX_PAGES_PER_TRIP
    max_http_calls: int = config.MAX_HTTP_CALLS_PER_TRIP
    max_llm_calls: int = config.MAX_LLM_CALLS_PER_TRIP
    max_cost_usd: float = config.MAX_COST_USD_PER_TRIP


@dataclass(frozen=True)
class ModelCall:
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    tool_calls: int
    cost_usd: float = 0.0


@dataclass
class TripBudget:
    limits: Limits = field(default_factory=Limits)
    clock: Callable[[], float] = time.monotonic
    tool_calls: int = 0
    http_calls: int = 0
    llm_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    pages: int = 0
    stopped_by: Optional[str] = None
    model_calls: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self._started = self.clock()
        self._lock = threading.Lock()

    # -- internals (call with the lock held) --

    def _stop(self, limit: str, detail: str) -> BudgetExceeded:
        self.stopped_by = self.stopped_by or limit
        return BudgetExceeded(limit, detail)

    def _check_spend(self) -> None:
        elapsed = self.clock() - self._started
        if elapsed >= self.limits.max_seconds:
            raise self._stop("time", f"{elapsed:.0f}s of {self.limits.max_seconds:.0f}s used")
        if self.tokens > self.limits.max_tokens:
            raise self._stop("tokens", f"{self.tokens} used, limit is {self.limits.max_tokens}")
        if self.cost_usd > self.limits.max_cost_usd:
            raise self._stop(
                "cost", f"${self.cost_usd:.2f} used, limit is ${self.limits.max_cost_usd:.2f}"
            )

    def _charge(self, attr: str, limit_name: str, limit: int) -> None:
        with self._lock:
            self._check_spend()
            if getattr(self, attr) >= limit:
                raise self._stop(limit_name, f"limit is {limit}")
            setattr(self, attr, getattr(self, attr) + 1)

    # -- public --

    def check_time(self) -> None:
        with self._lock:
            self._check_spend()

    def charge_tool_call(self) -> None:
        """Generic: call before running any tool."""
        self._charge("tool_calls", "tool_calls", self.limits.max_tool_calls)

    def charge_page(self) -> None:
        """Call before fetching a page."""
        self._charge("pages", "pages", self.limits.max_pages)

    def charge_http(self) -> None:
        """Call before every real network request (not cache hits)."""
        self._charge("http_calls", "http_calls", self.limits.max_http_calls)

    def charge_llm(self) -> None:
        """Call before every real model call (not cache hits)."""
        self._charge("llm_calls", "llm_calls", self.limits.max_llm_calls)

    def record_model_call(
        self,
        *,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        tool_calls: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Call after every model call. Raises if a token or cost limit is now exceeded,
        so the caller stops before making another one. The call is recorded either way."""
        with self._lock:
            self.model_calls.append(
                ModelCall(agent, model, input_tokens, output_tokens, cached_tokens, tool_calls, cost_usd)
            )
            self.tokens += input_tokens + output_tokens
            self.cost_usd += cost_usd
            if self.tokens > self.limits.max_tokens:
                raise self._stop(
                    "tokens", f"{self.tokens} used, limit is {self.limits.max_tokens}"
                )
            if self.cost_usd > self.limits.max_cost_usd:
                raise self._stop(
                    "cost", f"${self.cost_usd:.2f} used, limit is ${self.limits.max_cost_usd:.2f}"
                )

    def usage(self) -> dict:
        """Summary to store with the trip (the eval reports cost per task from this)."""
        return {
            "tool_calls": self.tool_calls,
            "http_calls": self.http_calls,
            "llm_calls": self.llm_calls,
            "pages": self.pages,
            "tokens": self.tokens,
            "cost_usd": round(self.cost_usd, 4),
            "seconds": round(self.clock() - self._started, 2),
            "stopped_by": self.stopped_by,
            "model_calls": [mc.__dict__ for mc in self.model_calls],
        }


# ---- the active budget ------------------------------------------------------

_current: "contextvars.ContextVar[Optional[TripBudget]]" = contextvars.ContextVar(
    "research_trip_budget", default=None
)


def current() -> Optional[TripBudget]:
    """The active budget, or None when none is set (unit tests, one-off scripts)."""
    return _current.get()


@contextmanager
def use(budget: TripBudget) -> Iterator[TripBudget]:
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def submit_in_context(executor: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any):
    """executor.submit(fn, ...) that keeps the active budget in the worker thread."""
    return executor.submit(contextvars.copy_context().run, lambda: fn(*args, **kwargs))


def map_in_context(executor: Any, fn: Callable[[Any], Any], items: Iterable[Any]) -> list:
    """list(executor.map(fn, items)) that keeps the active budget in the worker threads."""
    jobs = [(contextvars.copy_context(), item) for item in items]
    return list(executor.map(lambda job: job[0].run(fn, job[1]), jobs))
