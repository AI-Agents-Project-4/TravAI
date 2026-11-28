import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Trip
from app.schemas import Progress, ProgressStepOut, TripCreate, TripCreated

router = APIRouter(prefix="/trips", tags=["trips"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_trip(body: TripCreate, db: DbSession) -> TripCreated:
    """Store a trip request.

    Research doesn't start yet: the research agent gets wired in once it
    exists, so the trip stays in 'researching'. Safety warnings come later too.
    """
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
    )
    db.add(trip)
    db.commit()
    return TripCreated(trip_id=trip.id, warnings=[])


@router.get("/{trip_id}/progress")
def get_progress(trip_id: uuid.UUID, db: DbSession) -> Progress:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    return Progress(
        status=trip.status,  # validated against the contract's statuses
        steps=[ProgressStepOut.model_validate(step) for step in trip.steps],
    )
