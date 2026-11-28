import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.planner.llm import LLM
from app.agents.planner.planner import Planner
from app.agents.planner.rules import Assembler, Catalog, PlanInput
from app.agents.planner.types import Scheduled
from app.db import get_db
from app.models import Plan, ResearchRun, Trip
from app.pipeline import (
    apply_draft,
    get_llm,
    log_calls,
    plan_draft,
    research_facts,
    trip_facts,
    trip_items,
)
from app.routes.views import plan_out
from app.schemas import Day, DroppedItem, PlanIn, PlanOut, RedraftRequest, RedraftResponse

router = APIRouter(prefix="/plans", tags=["plans"])

DbSession = Annotated[Session, Depends(get_db)]
Model = Annotated[LLM | None, Depends(get_llm)]


def _load(db: Session, plan_id: uuid.UUID) -> tuple[Plan, Trip]:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.")
    trip = db.get(Trip, plan.trip_id)
    assert trip is not None
    return plan, trip


def _research_output(db: Session, trip: Trip) -> dict:  # type: ignore[type-arg]
    run = db.get(ResearchRun, trip.research_run_id) if trip.research_run_id else None
    return run.output if run else {}


def _days(days: list[Day], trip: Trip, known: set[str]) -> dict[int, list[Scheduled]]:
    """The client's days, checked: day numbers in range, option ids from this trip."""
    out: dict[int, list[Scheduled]] = {}
    for d in days:
        if d.day > trip.duration_days:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Day {d.day} is past the end of a {trip.duration_days}-day trip.",
            )
        for item in d.items:
            if item.option_id not in known:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Unknown option {item.option_id} for this trip.",
                )
        out[d.day] = out.get(d.day, []) + [
            Scheduled(i.option_id, i.start_time, i.end_time, i.locked) for i in d.items
        ]
    return out


@router.get("/{plan_id}")
def get_plan(plan_id: uuid.UUID, db: DbSession) -> PlanOut:
    plan, trip = _load(db, plan_id)
    return plan_out(plan, trip)


@router.post("/{plan_id}/redraft")
def redraft(plan_id: uuid.UUID, body: RedraftRequest, db: DbSession, llm: Model) -> RedraftResponse:
    """Keep the user's locked items, leave out removed ones, refit the rest (rule 5).

    Runs the planner model in the request (tens of seconds). If the model fails, the
    user's plan is kept as sent and only refit to the budget.
    """
    plan, trip = _load(db, plan_id)
    items = trip_items(db, trip.id)
    known = {i.id for i in items}
    days = _days(body.days, trip, known)
    output = _research_output(db, trip)
    planner = Planner(
        llm, mode=trip.agent_mode, research_output=output if trip.agent_mode == "single" else None
    )
    result = planner.redraft(
        items,
        trip_facts(trip),
        research_facts(output),
        current=plan_draft(plan),
        days=days,
        removed=set(body.removed_option_ids),
    )
    apply_draft(plan, result.plan, trip.budget_currency)
    plan.saved = False
    log_calls(db, trip.id, result.calls)
    db.commit()
    return RedraftResponse(
        plan=plan_out(plan, trip),
        dropped_items=[DroppedItem(option_id=d.option_id, reason=d.reason) for d in result.dropped],
    )


@router.put("/{plan_id}")
def save_plan(plan_id: uuid.UUID, body: PlanIn, db: DbSession) -> PlanOut:
    """Save the user's edited plan as is. Totals are recomputed from stored prices."""
    plan, trip = _load(db, plan_id)
    items = trip_items(db, trip.id)
    days = _days(body.days, trip, {i.id for i in items})
    cat = Catalog(items, trip_facts(trip), research_facts(_research_output(db, trip)))
    draft = Assembler(cat).price(
        PlanInput(
            title=body.title.strip(),
            summary=body.summary.strip(),
            flight_id=str(plan.flight_option_id) if plan.flight_option_id else None,
            hotel_ids=[str(plan.hotel_option_id)] if plan.hotel_option_id else [],
            days=days,
        )
    )
    apply_draft(plan, draft, trip.budget_currency)
    plan.saved = True
    db.commit()
    return plan_out(plan, trip)
