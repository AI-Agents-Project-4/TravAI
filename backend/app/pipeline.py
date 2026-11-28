"""A trip's background job: research -> options in Postgres -> planner -> plans.

Also the conversions between database rows and the planner's plain data, used by
the routes for redraft and save.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.planner.llm import LLM, make_llm
from app.agents.planner.planner import Planner
from app.agents.planner.types import (
    DayPlan,
    Item,
    ModelCallLog,
    PlanDraft,
    PlanningFailed,
    ResearchFacts,
    Scheduled,
    TripFacts,
)
from app.config import get_settings
from app.db import SessionFactory
from app.integration import research_agent
from app.integration.options import map_research
from app.models import ModelCall, Option, Plan, ProgressStep, ResearchRun, Trip

log = logging.getLogger(__name__)

USABLE_RESEARCH = ("ok", "partial", "infeasible")
GENERIC_FAILURE = "Something went wrong while planning this trip. Please try again."


def get_llm() -> LLM | None:
    """FastAPI dependency: the planner's model client (tests swap in a fake)."""
    s = get_settings()
    if s.planner_llm == "none":
        return None
    return make_llm(s.planner_llm, s.planner_model, s.planner_effort, s.planner_timeout_seconds)


# ---- conversions ---------------------------------------------------------------


def trip_request(trip: Trip) -> research_agent.TripRequest:
    return research_agent.TripRequest(
        origin=trip.origin,
        destination=trip.destination,
        end_destination=trip.end_destination,
        start_date=trip.start_date,
        duration_days=trip.duration_days,
        travelers=trip.travelers,
        budget=float(trip.budget_amount),
        currency=trip.budget_currency,
        transport_mode=trip.transport_mode,
    )


def trip_facts(trip: Trip) -> TripFacts:
    start = trip.priced_start_date or trip.start_date or date.today()
    return TripFacts(
        destination=trip.destination,
        duration_days=trip.duration_days,
        travelers=trip.travelers,
        budget=trip.budget_amount,
        currency=trip.budget_currency,
        transport_mode=trip.transport_mode,
        start_date=start,
        start_date_assumed=trip.start_date is None,
    )


def research_facts(output: dict[str, Any]) -> ResearchFacts:
    breakdown = (output.get("feasibility") or {}).get("breakdown") or {}
    food = Decimal(str(breakdown.get("food_and_local_transport") or 0))
    return ResearchFacts(
        status=str(output.get("status") or "error"),
        # An estimate with no single source: round up to a whole unit (rule 1).
        other_costs=food.quantize(Decimal("1"), rounding=ROUND_CEILING),
        advisories=list(output.get("advisories") or []),
        gaps=[f"{g.get('category')}: {g.get('reason')}" for g in output.get("gaps") or []],
        notes=list(output.get("notes") or []),
    )


def option_item(o: Option) -> Item:
    return Item(
        id=str(o.id),
        kind=o.kind,
        title=o.title,
        price=o.price_amount,
        currency=o.price_currency,
        is_estimate=o.price_is_estimate,
        source_url=o.source_url,
        fetched_at=o.fetched_at,
        duration_minutes=o.duration_minutes,
        details=dict(o.details or {}),
        lat=o.lat,
        lng=o.lng,
    )


def trip_items(db: Session, trip_id: uuid.UUID) -> list[Item]:
    rows = db.scalars(select(Option).where(Option.trip_id == trip_id).order_by(Option.created_at))
    return [option_item(o) for o in rows]


def days_to_json(days: list[DayPlan]) -> list[dict[str, Any]]:
    return [
        {
            "day": d.day,
            "date": d.date.isoformat() if d.date else None,
            "items": [
                {
                    "option_id": s.option_id,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "locked": s.locked,
                }
                for s in d.items
            ],
        }
        for d in days
    ]


def days_from_json(days: list[dict[str, Any]]) -> dict[int, list[Scheduled]]:
    return {
        int(d["day"]): [
            Scheduled(
                str(i["option_id"]),
                i.get("start_time"),
                i.get("end_time"),
                bool(i.get("locked")),
            )
            for i in d.get("items") or []
        ]
        for d in days
    }


def plan_draft(row: Plan) -> PlanDraft:
    by_day = days_from_json(row.days)
    return PlanDraft(
        title=row.title,
        summary=row.summary,
        flight_id=str(row.flight_option_id) if row.flight_option_id else None,
        hotel_id=str(row.hotel_option_id) if row.hotel_option_id else None,
        days=[DayPlan(d, None, by_day[d]) for d in sorted(by_day)],
        cost_breakdown=[],
        total=row.total_amount,
        warnings=row.warnings,
    )


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def apply_draft(row: Plan, draft: PlanDraft, currency: str) -> None:
    row.title = draft.title
    row.summary = draft.summary
    row.flight_option_id = _uuid(draft.flight_id)
    row.hotel_option_id = _uuid(draft.hotel_id)
    row.days = days_to_json(draft.days)
    row.cost_breakdown = [
        {"category": c, "total": {"amount": float(a), "currency": currency}}
        for c, a in draft.cost_breakdown
    ]
    row.total_amount = draft.total
    row.total_currency = currency
    row.warnings = draft.warnings


def log_calls(db: Session, trip_id: uuid.UUID | None, calls: list[ModelCallLog]) -> None:
    for c in calls:
        db.add(
            ModelCall(
                trip_id=trip_id,
                agent=c.agent,
                model=c.model,
                input_tokens=c.input_tokens,
                output_tokens=c.output_tokens,
                cache_read_tokens=c.cache_read_tokens,
                cache_write_tokens=c.cache_write_tokens,
                cost_usd=c.cost_usd,
            )
        )


def research_calls(usage: dict[str, Any]) -> list[ModelCallLog]:
    """The research agent's `_usage.model_calls`, as model_calls rows (agent="research")."""
    out = []
    for mc in usage.get("model_calls") or []:
        if not isinstance(mc, dict):
            continue
        out.append(
            ModelCallLog(
                agent="research",
                model=str(mc.get("model") or "default"),
                input_tokens=int(mc.get("input_tokens") or 0),
                output_tokens=int(mc.get("output_tokens") or 0),
                cache_read_tokens=int(mc.get("cached_tokens") or 0),
                cost_usd=Decimal(str(mc.get("cost_usd") or 0)),
            )
        )
    return out


# ---- the job ------------------------------------------------------------------


class _Progress:
    """Writes progress steps from any thread (the research agent reports from its pool)."""

    def __init__(self, factory: SessionFactory, trip_id: uuid.UUID):
        self.factory = factory
        self.trip_id = trip_id
        self.lock = threading.Lock()

    def say(self, message: str, status: str | None = None) -> None:
        with self.lock, self.factory() as db:
            db.add(ProgressStep(trip_id=self.trip_id, message=message[:500]))
            if status:
                trip = db.get(Trip, self.trip_id)
                if trip is not None:
                    trip.status = status
            db.commit()

    def research_callback(self, stage: str, message: str) -> None:
        try:
            self.say(message)
        except Exception:  # progress is nice to have; never fail research over it
            log.exception("could not save a progress step")


def _fail(factory: SessionFactory, trip_id: uuid.UUID, reason: str) -> None:
    with factory() as db:
        trip = db.get(Trip, trip_id)
        if trip is None:
            return
        trip.status = "failed"
        trip.failure_reason = reason
        db.add(ProgressStep(trip_id=trip_id, message=reason[:500]))
        db.commit()


def _find_reusable(db: Session, key: str) -> ResearchRun | None:
    hours = get_settings().research_reuse_hours
    if hours <= 0:
        return None
    since = datetime.now(UTC) - timedelta(hours=hours)
    return db.scalars(
        select(ResearchRun)
        .where(
            ResearchRun.request_key == key,
            ResearchRun.status.in_(USABLE_RESEARCH),
            ResearchRun.created_at >= since,
        )
        .order_by(ResearchRun.created_at.desc())
        .limit(1)
    ).first()


def _research(factory: SessionFactory, trip_id: uuid.UUID, progress: _Progress) -> dict[str, Any]:
    """Run (or reuse) research and store its options. Returns the public research output."""
    with factory() as db:
        trip = db.get(Trip, trip_id)
        assert trip is not None
        request = research_agent.build_request(
            trip_request(trip), str(trip.id), today=datetime.now(UTC).date()
        )
        trip.priced_start_date = request.priced_start_date
        db.commit()
        reusable = _find_reusable(db, request.key)
        travelers = trip.travelers
        destination = trip.destination

    for note in request.notes:
        progress.say(note)

    calls: list[ModelCallLog] = []
    if reusable is not None:
        age = datetime.now(UTC) - reusable.created_at
        progress.say(
            f"Reusing research for the same trip from {int(age.total_seconds() // 60)} minutes ago"
        )
        output, run_id = reusable.output, reusable.id
    else:
        raw = research_agent.run_research(request, progress=progress.research_callback)
        output, usage = research_agent.split_private(raw)
        calls = research_calls(usage)
        with factory() as db:
            run = ResearchRun(
                request_key=request.key,
                request=request.body,
                status=str(output.get("status") or "error"),
                output=output,
            )
            db.add(run)
            db.flush()
            run_id = run.id
            log_calls(db, trip_id, calls)
            db.commit()

    if output.get("status") not in USABLE_RESEARCH:
        gaps = "; ".join(str(g.get("reason")) for g in output.get("gaps") or [])[:400]
        raise PlanningFailed(
            "The research couldn't find enough to plan this trip." + (f" {gaps}" if gaps else "")
        )

    mapped = map_research(output, travelers=travelers)
    if mapped.rejected:
        log.warning(
            "trip %s: %d options rejected: %s", trip_id, len(mapped.rejected), mapped.rejected[:5]
        )
    with factory() as db:
        trip = db.get(Trip, trip_id)
        assert trip is not None
        trip.research_run_id = run_id
        for m in mapped.options:
            db.add(
                Option(
                    trip_id=trip_id,
                    destination=destination.strip().lower(),
                    kind=m.kind,
                    title=m.title,
                    description=m.description,
                    price_amount=m.price_amount,
                    price_currency=m.price_currency,
                    price_is_estimate=m.price_is_estimate,
                    source_url=m.source_url,
                    fetched_at=m.fetched_at,
                    location_name=m.location_name,
                    lat=m.lat,
                    lng=m.lng,
                    duration_minutes=m.duration_minutes,
                    opening_hours=m.opening_hours,
                    details=m.details,
                )
            )
        db.commit()
    counts = {k: sum(1 for m in mapped.options if m.kind == k) for k in ("flight", "hotel")}
    acts = sum(1 for m in mapped.options if m.kind in ("activity", "food"))
    progress.say(
        f"Saved {counts['flight']} flights, {counts['hotel']} hotels and {acts} activities"
    )
    return output


def run_trip(trip_id: uuid.UUID, factory: SessionFactory, llm: LLM | None) -> None:
    """The whole background job for one trip. Never raises: failures are recorded on the trip."""
    progress = _Progress(factory, trip_id)
    try:
        progress.say("Starting research", status="researching")
        output = _research(factory, trip_id, progress)

        progress.say("Building three itineraries", status="planning")
        with factory() as db:
            trip = db.get(Trip, trip_id)
            assert trip is not None
            mode = trip.agent_mode
            facts = trip_facts(trip)
            items = trip_items(db, trip_id)
        planner = Planner(llm, mode=mode, research_output=output if mode == "single" else None)
        result = planner.draft(items, facts, research_facts(output))

        with factory() as db:
            trip = db.get(Trip, trip_id)
            assert trip is not None
            log_calls(db, trip_id, result.calls)
            trip.feasible = result.feasible
            if not result.feasible:
                trip.infeasible_reason = result.infeasible_reason
                trip.min_estimated_cost_amount = result.min_estimated_cost
            for position, draft in enumerate(result.plans):
                row = Plan(
                    trip_id=trip_id,
                    position=position,
                    title="",
                    summary="",
                    total_amount=Decimal(0),
                    total_currency=trip.budget_currency,
                )
                apply_draft(row, draft, trip.budget_currency)
                db.add(row)
            if result.used_fallback:
                db.add(
                    ProgressStep(
                        trip_id=trip_id,
                        message="The planner model wasn't available, so these plans were built with simple rules.",
                    )
                )
                log.warning(
                    "trip %s used the fallback planner: %s", trip_id, result.fallback_reason
                )
            trip.status = "done"
            db.add(
                ProgressStep(
                    trip_id=trip_id,
                    message="Done" if result.feasible else "This trip doesn't fit the budget",
                )
            )
            db.commit()
    except PlanningFailed as exc:
        _fail(factory, trip_id, str(exc))
    except (ValueError, research_agent.ResearchUnavailable) as exc:
        _fail(factory, trip_id, str(exc))
    except Exception:
        log.exception("trip %s failed", trip_id)
        _fail(factory, trip_id, GENERIC_FAILURE)
