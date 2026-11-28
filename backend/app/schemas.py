"""Request and response shapes (see docs/api-contract.md)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

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
