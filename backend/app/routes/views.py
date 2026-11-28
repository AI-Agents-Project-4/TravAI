"""Database rows -> response models (docs/api-contract.md shapes)."""

from __future__ import annotations

from decimal import Decimal

from app.models import Option, Plan, Trip
from app.schemas import CostLine, Day, Location, MoneyOut, OptionOut, PlanOut, Warning


def option_out(o: Option) -> OptionOut:
    location = None
    if o.location_name:
        location = Location(name=o.location_name, lat=o.lat, lng=o.lng)
    return OptionOut(
        id=str(o.id),
        kind=o.kind,  # limited by a DB check constraint
        title=o.title,
        description=o.description,
        price=MoneyOut(amount=o.price_amount, currency=o.price_currency),
        price_is_estimate=o.price_is_estimate,
        source_url=o.source_url,
        fetched_at=o.fetched_at,
        location=location,
        duration_minutes=o.duration_minutes,
        opening_hours=o.opening_hours,
        details=o.details or {},
    )


def plan_out(p: Plan, trip: Trip) -> PlanOut:
    return PlanOut(
        id=str(p.id),
        trip_id=str(p.trip_id),
        title=p.title,
        summary=p.summary,
        flight_option_id=str(p.flight_option_id) if p.flight_option_id else None,
        hotel_option_id=str(p.hotel_option_id) if p.hotel_option_id else None,
        days=[Day.model_validate(d) for d in p.days],
        cost_breakdown=[
            CostLine(
                category=c["category"],
                total=MoneyOut(
                    amount=Decimal(str(c["total"]["amount"])), currency=c["total"]["currency"]
                ),
            )
            for c in p.cost_breakdown
        ],
        total=MoneyOut(amount=p.total_amount, currency=p.total_currency),
        budget=MoneyOut(amount=trip.budget_amount, currency=trip.budget_currency),
        warnings=[Warning.model_validate(w) for w in p.warnings],
        saved=p.saved,
    )
