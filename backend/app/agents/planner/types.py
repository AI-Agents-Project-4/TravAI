"""Plain data the planner works with. No database, no web framework.

The planner reads only these structured options (the two-agent design): it never
sees the research agent's transcript. Ids are strings so the same code runs on
database rows (UUIDs) and on the eval's in-memory options (research ids).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Item:
    """One option, as the planner sees it."""

    id: str
    kind: str  # flight | hotel | activity | food | transport
    title: str
    price: Decimal  # total for the whole party, in `currency`
    currency: str
    is_estimate: bool
    source_url: str
    fetched_at: datetime
    duration_minutes: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    lat: float | None = None
    lng: float | None = None

    @property
    def role(self) -> str | None:
        """round_trip | outbound | return | intercity | lodging | activity | day_trip |
        airport_transfer | drive | car_rental | local (set by the research mapper)."""
        role = self.details.get("role")
        return str(role) if role else None

    @property
    def stop(self) -> str | None:
        """The trip stop (city) for hotels and transport. Activities only have a
        neighborhood ("area"); the planner works out their stop from location."""
        stop = self.details.get("stop")
        return str(stop) if stop else None

    @property
    def hours(self) -> dict[str, Any] | None:
        hours = self.details.get("hours")
        return hours if isinstance(hours, dict) and hours else None


@dataclass(frozen=True)
class TripFacts:
    destination: str
    duration_days: int
    travelers: int
    budget: Decimal
    currency: str
    transport_mode: str  # fly | drive
    start_date: date  # the date research priced
    start_date_assumed: bool  # True if the user left the date empty


@dataclass(frozen=True)
class ResearchFacts:
    """The parts of the research output that aren't options."""

    status: str  # ok | partial | infeasible | error
    # Food and local transport for the whole trip: an estimate with no option or link.
    other_costs: Decimal
    advisories: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Scheduled:
    option_id: str
    start_time: str | None = None
    end_time: str | None = None
    locked: bool = False


@dataclass
class DayPlan:
    day: int
    date: date | None
    items: list[Scheduled] = field(default_factory=list)


@dataclass
class PlanDraft:
    title: str
    summary: str
    flight_id: str | None
    hotel_id: str | None
    days: list[DayPlan]
    cost_breakdown: list[tuple[str, Decimal]]
    total: Decimal
    warnings: list[dict[str, Any]]


@dataclass(frozen=True)
class Dropped:
    option_id: str
    reason: str


@dataclass(frozen=True)
class ModelCallLog:
    """Token use and cost of one model call (saved to model_calls)."""

    agent: str  # planner | single
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal = Decimal("0")


@dataclass
class PlanningResult:
    feasible: bool
    plans: list[PlanDraft] = field(default_factory=list)
    infeasible_reason: str | None = None
    min_estimated_cost: Decimal | None = None
    calls: list[ModelCallLog] = field(default_factory=list)
    # True when the model failed and the plans came from the simple rule-based fallback.
    used_fallback: bool = False
    fallback_reason: str | None = None


@dataclass
class RedraftResult:
    plan: PlanDraft
    dropped: list[Dropped]
    calls: list[ModelCallLog] = field(default_factory=list)
    used_fallback: bool = False


class PlanningFailed(RuntimeError):
    """There isn't enough real data to plan honestly (no flights found, etc.)."""
