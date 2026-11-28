"""Request and response shapes (see docs/api-contract.md)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Kept as Decimal inside the backend, sent as a JSON number (the contract's `number`).
Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class Money(BaseModel):
    amount: Amount = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$", examples=["USD"])


class Warning(BaseModel):
    kind: Literal["safety", "stale_data", "estimate", "over_budget"]
    message: str
    source_url: str | None = None


class TripCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    origin: str | None = Field(default=None, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    start_date: date | None = None
    duration_days: int = Field(ge=1, le=90)
    travelers: int = Field(ge=1, le=20)
    budget: Money
    transport_mode: Literal["fly", "drive"]
    end_destination: str | None = Field(default=None, max_length=200)


class TripCreated(BaseModel):
    trip_id: uuid.UUID
    warnings: list[Warning]


class ProgressStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message: str
    at: datetime


class Progress(BaseModel):
    status: Literal["researching", "planning", "done", "failed"]
    steps: list[ProgressStepOut]


# ---- Options and plans (docs/api-contract.md "Shared types") -------------------


class MoneyOut(BaseModel):
    """Money in a response. Unlike `Money` (a budget), it can be 0 (a free museum)."""

    amount: Amount
    currency: str


class Location(BaseModel):
    name: str
    lat: float | None = None
    lng: float | None = None


class OptionOut(BaseModel):
    id: str
    kind: Literal["flight", "hotel", "activity", "transport", "food"]
    title: str
    description: str | None = None
    price: MoneyOut
    price_is_estimate: bool
    source_url: str
    fetched_at: datetime
    location: Location | None = None
    duration_minutes: int | None = None
    opening_hours: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ScheduledItem(BaseModel):
    option_id: str
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    locked: bool = False


class Day(BaseModel):
    day: int = Field(ge=1, le=366)
    date: str | None = None
    items: list[ScheduledItem] = Field(default_factory=list, max_length=50)


class CostLine(BaseModel):
    category: Literal["flight", "hotel", "activity", "transport", "food", "other"]
    total: MoneyOut


class PlanOut(BaseModel):
    id: str
    trip_id: str
    title: str
    summary: str
    flight_option_id: str | None = None
    hotel_option_id: str | None = None
    days: list[Day]
    cost_breakdown: list[CostLine]
    total: MoneyOut
    budget: MoneyOut
    warnings: list[Warning]
    saved: bool


class PlanIn(BaseModel):
    """Body of PUT /plans/{id}: the client's edited plan.

    Only the editable parts are used. Totals, breakdown and warnings are worked out
    again on the server from stored prices, so a client can't save a wrong total.
    """

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    days: list[Day] = Field(max_length=366)


class FeasiblePlans(BaseModel):
    feasible: Literal[True] = True
    plans: list[PlanOut]
    options: list[OptionOut]


class InfeasiblePlans(BaseModel):
    feasible: Literal[False] = False
    reason: str
    min_estimated_cost: MoneyOut


class RedraftRequest(BaseModel):
    days: list[Day] = Field(max_length=366)
    removed_option_ids: list[str] = Field(default_factory=list, max_length=500)


class DroppedItem(BaseModel):
    option_id: str
    reason: str


class RedraftResponse(BaseModel):
    plan: PlanOut
    dropped_items: list[DroppedItem]
