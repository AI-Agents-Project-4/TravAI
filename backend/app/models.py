"""Database tables (SQLAlchemy 2.0 ORM).

Shapes follow docs/api-contract.md. Money is stored as NUMERIC(12, 2) plus an
ISO 4217 currency code, never as a float. Nested plan data (days, cost
breakdown, warnings) is JSONB because it's always read and written as a whole.

Schema changes go through Alembic: edit this file, then add a migration in
migrations/versions/. tests/test_migrations.py fails if the two disagree.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Predictable constraint names, so migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TRANSPORT_MODES = ("fly", "drive")
TRIP_STATUSES = ("researching", "planning", "done", "failed")
OPTION_KINDS = ("flight", "hotel", "activity", "transport", "food")
AGENTS = ("research", "planner", "single")


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def _jsonb(default: str) -> Mapped[Any]:
    return mapped_column(JSONB, nullable=False, server_default=text(f"'{default}'::jsonb"))


class Trip(Base):
    """One planning request from the trip form (POST /trips)."""

    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint(_in("transport_mode", TRANSPORT_MODES), name="transport_mode"),
        CheckConstraint(_in("status", TRIP_STATUSES), name="status"),
        CheckConstraint("duration_days > 0", name="duration_days_positive"),
        CheckConstraint("travelers > 0", name="travelers_positive"),
        CheckConstraint("budget_amount > 0", name="budget_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    origin: Mapped[str | None] = mapped_column(String(200))
    destination: Mapped[str] = mapped_column(String(200))
    end_destination: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    duration_days: Mapped[int] = mapped_column(Integer)
    travelers: Mapped[int] = mapped_column(Integer)
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    budget_currency: Mapped[str] = mapped_column(String(3))
    transport_mode: Mapped[str] = mapped_column(String(10))

    status: Mapped[str] = mapped_column(String(20), server_default="researching")
    # Warnings shown before planning, e.g. a safety warning (product rule 4).
    warnings: Mapped[list[dict[str, Any]]] = _jsonb("[]")
    # Set by the planner. feasible=False comes with a reason and a minimum cost (rule 3).
    feasible: Mapped[bool | None]
    infeasible_reason: Mapped[str | None] = mapped_column(Text)
    min_estimated_cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    steps: Mapped[list["ProgressStep"]] = relationship(
        back_populates="trip", order_by="ProgressStep.id", cascade="all, delete-orphan"
    )
    plans: Mapped[list["Plan"]] = relationship(back_populates="trip", cascade="all, delete-orphan")


class ProgressStep(Base):
    """A progress message for the UI, e.g. "Found 4 flights, checking hotel prices"."""

    __tablename__ = "progress_steps"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), index=True
    )
    message: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trip: Mapped[Trip] = relationship(back_populates="steps")


class Option(Base):
    """One researched flight, hotel, activity, etc. with a sourced price.

    Options are cached by destination so later trips can reuse them while
    they're fresh (see fetched_at). trip_id records which trip found it.
    """

    __tablename__ = "options"
    __table_args__ = (
        CheckConstraint(_in("kind", OPTION_KINDS), name="kind"),
        CheckConstraint("price_amount >= 0", name="price_not_negative"),
        # Product rule 2: every price has a source.
        CheckConstraint("source_url <> ''", name="source_url_not_empty"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trips.id", ondelete="SET NULL"), index=True
    )
    # Normalized destination used as the cache key (e.g. "tokyo, japan").
    destination: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)

    # Total for the whole party, taxes and fees included. Estimates are rounded up.
    price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    price_currency: Mapped[str] = mapped_column(String(3))
    price_is_estimate: Mapped[bool]
    source_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    location_name: Mapped[str | None] = mapped_column(String(300))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    opening_hours: Mapped[str | None] = mapped_column(Text)
    # Per-kind extras (airline, stops, check-in time, ...).
    details: Mapped[dict[str, Any]] = _jsonb("{}")

    created_at: Mapped[datetime] = _created_at()


class Plan(Base):
    """One of the three itineraries for a trip. Days etc. follow the contract's Plan type."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    trip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    flight_option_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("options.id", ondelete="SET NULL")
    )
    hotel_option_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("options.id", ondelete="SET NULL")
    )
    days: Mapped[list[dict[str, Any]]] = _jsonb("[]")
    cost_breakdown: Mapped[list[dict[str, Any]]] = _jsonb("[]")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_currency: Mapped[str] = mapped_column(String(3))
    warnings: Mapped[list[dict[str, Any]]] = _jsonb("[]")
    saved: Mapped[bool] = mapped_column(server_default=text("false"))

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    trip: Mapped[Trip] = relationship(back_populates="plans")


class ModelCall(Base):
    """Token usage and cost of one LLM call, for cost per task and the eval.

    agent='single' is the single-agent baseline the eval compares against.
    """

    __tablename__ = "model_calls"
    __table_args__ = (CheckConstraint(_in("agent", AGENTS), name="agent"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trips.id", ondelete="SET NULL"), index=True
    )
    agent: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    tool_calls: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = _created_at()
