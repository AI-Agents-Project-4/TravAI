import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.planner.llm import LLM
from app.config import get_settings
from app.db import SessionFactory, get_db, get_session_factory
from app.integration import research_agent
from app.jobs import JobRunner, get_job_runner
from app.models import Option, Plan, Trip
from app.pipeline import get_llm, run_trip
from app.routes.views import option_out, plan_out
from app.schemas import (
    FeasiblePlans,
    InfeasiblePlans,
    MoneyOut,
    Progress,
    ProgressStepOut,
    TripCreate,
    TripCreated,
    Warning,
)

router = APIRouter(prefix="/trips", tags=["trips"])

DbSession = Annotated[Session, Depends(get_db)]
Factory = Annotated[SessionFactory, Depends(get_session_factory)]
Jobs = Annotated[JobRunner, Depends(get_job_runner)]
Model = Annotated[LLM | None, Depends(get_llm)]


def _get_trip(db: Session, trip_id: uuid.UUID) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found.")
    return trip


@router.post("", status_code=status.HTTP_201_CREATED)
def create_trip(
    body: TripCreate, db: DbSession, factory: Factory, jobs: Jobs, llm: Model
) -> TripCreated:
    """Store the request and start research in the background.

    A destination under a State Dept Level 3/4 advisory gets a safety warning, and
    research waits until the user confirms with POST /trips/{id}/proceed (rule 4).
    """
    warnings = research_agent.safety_warnings(body.destination)
    if body.end_destination:
        warnings += research_agent.safety_warnings(body.end_destination)
    trip = Trip(
        origin=body.origin,
        destination=body.destination,
        end_destination=body.end_destination,
        start_date=body.start_date,
        duration_days=body.duration_days,
        travelers=body.travelers,
        budget_amount=body.budget.amount,
        budget_currency=body.budget.currency,
        transport_mode=body.transport_mode,
        agent_mode=get_settings().agent_mode,
        warnings=warnings,
        status="awaiting_confirmation" if warnings else "researching",
    )
    db.add(trip)
    db.commit()
    if not warnings:
        jobs(run_trip, trip.id, factory, llm)
    return TripCreated(trip_id=trip.id, warnings=[Warning.model_validate(w) for w in warnings])


@router.post("/{trip_id}/proceed", status_code=status.HTTP_204_NO_CONTENT)
def proceed(
    trip_id: uuid.UUID, db: DbSession, factory: Factory, jobs: Jobs, llm: Model
) -> Response:
    """The user saw the safety warning and wants to go ahead. Safe to call twice."""
    trip = _get_trip(db, trip_id)
    if trip.status == "awaiting_confirmation":
        trip.status = "researching"
        db.commit()
        jobs(run_trip, trip.id, factory, llm)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{trip_id}/progress")
def get_progress(trip_id: uuid.UUID, db: DbSession) -> Progress:
    trip = _get_trip(db, trip_id)
    # Waiting for the user's confirmation shows as "researching" with no steps yet.
    shown = "researching" if trip.status == "awaiting_confirmation" else trip.status
    return Progress(
        status=shown,  # limited by a DB check constraint
        steps=[ProgressStepOut.model_validate(step) for step in trip.steps],
    )


@router.get("/{trip_id}/plans")
def get_plans(trip_id: uuid.UUID, db: DbSession) -> FeasiblePlans | InfeasiblePlans:
    trip = _get_trip(db, trip_id)
    if trip.status == "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, trip.failure_reason or "Planning failed.")
    if trip.status != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "Plans aren't ready yet.")
    if trip.feasible is False:
        return InfeasiblePlans(
            reason=trip.infeasible_reason or "This trip doesn't fit the budget.",
            min_estimated_cost=MoneyOut(
                amount=trip.min_estimated_cost_amount or trip.budget_amount,
                currency=trip.budget_currency,
            ),
        )
    plans = db.scalars(select(Plan).where(Plan.trip_id == trip.id).order_by(Plan.position))
    options = db.scalars(
        select(Option).where(Option.trip_id == trip.id).order_by(Option.created_at)
    )
    return FeasiblePlans(
        plans=[plan_out(p, trip) for p in plans],
        options=[option_out(o) for o in options],
    )
