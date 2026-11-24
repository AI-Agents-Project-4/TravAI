"""Per-trip limits and usage logging for the research agent (threat model T6).

One `TripBudget` per research run. Call `charge_*` before doing the work; each raises
`BudgetExceeded` once a limit is hit, so the agent stops cleanly and can tell the user
it stopped early instead of looping. Every model call is also recorded so the eval can
report tokens and cost per task.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

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


@dataclass(frozen=True)
class ModelCall:
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    tool_calls: int


@dataclass
class TripBudget:
    limits: Limits = field(default_factory=Limits)
    clock: Callable[[], float] = time.monotonic
    tool_calls: int = 0
    tokens: int = 0
    pages: int = 0
    stopped_by: str | None = None
    model_calls: list[ModelCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._started = self.clock()
        self._lock = threading.Lock()

    def _stop(self, limit: str, detail: str) -> BudgetExceeded:
        self.stopped_by = self.stopped_by or limit
        return BudgetExceeded(limit, detail)

    def check_time(self) -> None:
        elapsed = self.clock() - self._started
        if elapsed >= self.limits.max_seconds:
            raise self._stop("time", f"{elapsed:.0f}s of {self.limits.max_seconds:.0f}s used")

    def charge_tool_call(self) -> None:
        """Call before running any tool."""
        with self._lock:
            self.check_time()
            if self.tool_calls >= self.limits.max_tool_calls:
                raise self._stop("tool_calls", f"limit is {self.limits.max_tool_calls}")
            self.tool_calls += 1

    def charge_page(self) -> None:
        """Call before fetching a page."""
        with self._lock:
            self.check_time()
            if self.pages >= self.limits.max_pages:
                raise self._stop("pages", f"limit is {self.limits.max_pages}")
            self.pages += 1

    def record_model_call(
        self,
        *,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        tool_calls: int = 0,
    ) -> None:
        """Call after every model call. Raises if the token limit is now exceeded,
        so the caller stops before making another one."""
        with self._lock:
            self.model_calls.append(
                ModelCall(agent, model, input_tokens, output_tokens, cached_tokens, tool_calls)
            )
            self.tokens += input_tokens + output_tokens
            if self.tokens > self.limits.max_tokens:
                raise self._stop(
                    "tokens", f"{self.tokens} used, limit is {self.limits.max_tokens}"
                )

    def usage(self) -> dict[str, object]:
        """Summary to store with the trip (cost is computed from this plus model prices)."""
        return {
            "tool_calls": self.tool_calls,
            "pages": self.pages,
            "tokens": self.tokens,
            "seconds": round(self.clock() - self._started, 2),
            "stopped_by": self.stopped_by,
            "model_calls": [mc.__dict__ for mc in self.model_calls],
        }
