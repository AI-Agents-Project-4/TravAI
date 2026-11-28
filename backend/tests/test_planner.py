"""Planner behavior on a small handmade catalog (no database, no model calls)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.agents.planner.planner import Planner
from app.agents.planner.rules import Assembler, Catalog, PlanInput
from app.agents.planner.types import (
    Item,
    PlanDraft,
    PlanningFailed,
    ResearchFacts,
    Scheduled,
    TripFacts,
)
from tests.fakes import FakeLLM

FETCHED = datetime.now(UTC)
START = date(2027, 3, 10)  # a Wednesday


def item(id: str, kind: str, price: str, **details: Any) -> Item:
    minutes = details.pop("minutes", 60)
    return Item(
        id=id,
        kind=kind,
        title=id.replace("-", " ").title(),
        price=Decimal(price),
        currency="USD",
        is_estimate=details.pop("estimate", False),
        source_url=f"https://example.com/{id}",
        fetched_at=details.pop("fetched_at", FETCHED),
        duration_minutes=minutes,
        details=details,
    )


def catalog_items() -> list[Item]:
    acts = [
        item(f"act-{n}", "activity", str(10 * n), role="activity", category="museum", minutes=90)
        for n in range(1, 13)
    ]
    return [
        item(
            "flight-cheap",
            "flight",
            "900",
            role="round_trip",
            arrive_airport="HND",
            return_depart_airport="HND",
        ),
        item(
            "flight-fast",
            "flight",
            "1400",
            role="round_trip",
            arrive_airport="HND",
            return_depart_airport="HND",
        ),
        item(
            "hotel-cheap",
            "hotel",
            "500",
            role="lodging",
            stop="Tokyo",
            check_in="2027-03-10",
            check_out="2027-03-13",
        ),
        item(
            "hotel-nice",
            "hotel",
            "1500",
            role="lodging",
            stop="Tokyo",
            check_in="2027-03-10",
            check_out="2027-03-13",
        ),
        item(
            "transfer",
            "transport",
            "60",
            role="airport_transfer",
            airport="HND",
            stop="Tokyo",
            minutes=30,
        ),
        item(
            "day-trip",
            "activity",
            "120",
            role="day_trip",
            category="day_trip",
            minutes=300,
            round_trip_from_base_minutes=180,
        ),
        item(
            "closed-wed",
            "activity",
            "5",
            role="activity",
            category="museum",
            hours={
                "thu": {"open": "09:00", "close": "17:00"},
                "fri": {"open": "09:00", "close": "17:00"},
            },
        ),
        *acts,
    ]


def trip(budget: str = "3000", days: int = 3, **kw: Any) -> TripFacts:
    return TripFacts(
        destination="Tokyo, Japan",
        duration_days=days,
        travelers=1,
        budget=Decimal(budget),
        currency="USD",
        transport_mode=kw.get("mode", "fly"),
        start_date=START,
        start_date_assumed=kw.get("assumed", False),
    )


RESEARCH = ResearchFacts(status="ok", other_costs=Decimal("300"))


def expected_total(draft: PlanDraft, items: list[Item], other: Decimal = Decimal("300")) -> Decimal:
    """The frontend's running-total formula: flight + hotel + every scheduled item + other costs."""
    by = {i.id: i for i in items}
    total = other
    for oid in (draft.flight_id, draft.hotel_id):
        if oid:
            total += by[oid].price
    for d in draft.days:
        for s in d.items:
            total += by[s.option_id].price
    return total


def test_infeasible_reports_an_honest_minimum() -> None:
    result = Planner(FakeLLM()).draft(catalog_items(), trip(budget="1000"), RESEARCH)
    assert not result.feasible
    assert result.plans == []
    # 900 flight + 500 hotel + 2 x 60 transfers + 300 food = 1820, rounded up to 50.
    assert result.min_estimated_cost == Decimal("1850")
    assert "$1,850" in (result.infeasible_reason or "")


def test_three_plans_under_budget_with_totals_that_add_up() -> None:
    items = catalog_items()
    result = Planner(FakeLLM()).draft(items, trip(), RESEARCH)
    assert result.feasible and not result.used_fallback
    assert len(result.plans) == 3
    assert [p.title for p in result.plans] == ["Theme 1", "Theme 2", "Theme 3"]
    for plan in result.plans:
        assert plan.total <= Decimal("3000")
        assert plan.total == expected_total(plan, items)
        assert sum(a for _, a in plan.cost_breakdown) == plan.total
        assert ("other", Decimal("300")) in plan.cost_breakdown
    assert len(result.calls) == 1 and result.calls[0].agent == "planner"


def test_required_transfers_are_added_both_ways() -> None:
    plan = Planner(FakeLLM()).draft(catalog_items(), trip(), RESEARCH).plans[0]
    first = [s.option_id for s in plan.days[0].items]
    last = [s.option_id for s in plan.days[-1].items]
    assert first[0] == "transfer"
    assert last[-1] == "transfer"


def test_model_ids_not_in_the_catalog_are_ignored() -> None:
    result = Planner(FakeLLM(bogus_ids=True)).draft(catalog_items(), trip(), RESEARCH)
    ids = {s.option_id for p in result.plans for d in p.days for s in d.items}
    assert "a99999" not in ids and all(not i.startswith("a9") for i in ids)


def test_model_failure_falls_back_to_rules_and_says_so() -> None:
    items = catalog_items()
    result = Planner(FakeLLM(fail=True)).draft(items, trip(), RESEARCH)
    assert result.feasible and result.used_fallback
    assert "fake model is down" in (result.fallback_reason or "")
    assert len(result.plans) == 3
    assert all(p.total == expected_total(p, items) for p in result.plans)


def test_no_flights_means_no_plan() -> None:
    items = [i for i in catalog_items() if i.kind != "flight"]
    with pytest.raises(PlanningFailed, match="no flights"):
        Planner(FakeLLM()).draft(items, trip(), RESEARCH)


def _assemble(
    items: list[Item], days: dict[int, list[Scheduled]], budget: str = "3000", **kw: Any
) -> Any:
    cat = Catalog(items, trip(budget=budget), RESEARCH)
    plan = PlanInput("T", "S", "flight-cheap", ["hotel-cheap"], days)
    return Assembler(cat).assemble(plan, **kw)


def test_closed_days_move_the_item() -> None:
    draft, _ = _assemble(catalog_items(), {1: [Scheduled("closed-wed")]})  # day 1 is a Wednesday
    day_of = {s.option_id: d.day for d in draft.days for s in d.items}
    assert day_of["closed-wed"] == 2  # Thursday


def test_a_day_trip_takes_the_whole_day() -> None:
    draft, _ = _assemble(
        catalog_items(), {2: [Scheduled("day-trip"), Scheduled("act-1"), Scheduled("act-2")]}
    )
    day2 = [s.option_id for s in draft.days[1].items]
    assert day2 == ["day-trip"]
    assert {"act-1", "act-2"} <= {s.option_id for d in draft.days for s in d.items}


def test_budget_drops_most_expensive_unlocked_first_and_never_locked() -> None:
    items = catalog_items()
    days = {
        1: [Scheduled("act-12", locked=True)],  # $120, the most expensive, but locked
        2: [Scheduled("act-11"), Scheduled("act-1")],
    }
    kept = {"act-11", "act-1"}
    # Fixed: 900 + 500 + 120 transfers + 300 other = 1820. With 120 + 110 + 10 = 2060.
    draft, dropped = _assemble(items, days, budget="1960", user_items=kept, allow_swap=False)
    ids = {s.option_id for d in draft.days for s in d.items}
    assert "act-12" in ids and "act-1" in ids and "act-11" not in ids
    assert [d.option_id for d in dropped] == ["act-11"]
    assert "budget" in dropped[0].reason
    assert draft.total <= Decimal("1960")


def test_locked_items_over_budget_get_a_warning_not_dropped() -> None:
    days = {1: [Scheduled("act-12", locked=True)]}
    draft, dropped = _assemble(catalog_items(), days, budget="1850", allow_swap=False)
    assert any(s.option_id == "act-12" for s in draft.days[0].items)
    assert dropped == []
    assert any(w["kind"] == "over_budget" for w in draft.warnings)


def test_redraft_keeps_locked_items_and_never_brings_back_removed_ones() -> None:
    items = catalog_items()
    planner = Planner(FakeLLM(add_on_redraft=2))
    first = planner.draft(items, trip(), RESEARCH).plans[0]
    removed_id = next(s.option_id for s in first.days[1].items if s.option_id.startswith("act"))
    edited = {
        d.day: [Scheduled(s.option_id, locked=False) for s in d.items if s.option_id != removed_id]
        for d in first.days
    }
    edited[3].append(Scheduled("act-12", locked=True))  # the user adds something on day 3
    result = planner.redraft(
        items, trip(), RESEARCH, current=first, days=edited, removed={removed_id}
    )
    final = {(d.day, s.option_id): s.locked for d in result.plan.days for s in d.items}
    assert final[(3, "act-12")] is True
    assert all(oid != removed_id for _, oid in final)
    assert result.plan.total == expected_total(result.plan, items)
    assert result.plan.total <= Decimal("3000")


def test_single_agent_mode_reads_research_ids() -> None:
    items = [
        Item(**{**i.__dict__, "details": {**i.details, "research_id": f"r-{i.id}"}})
        for i in catalog_items()
    ]
    research_output = {
        "flights": [{"id": "r-flight-cheap"}],
        "lodging": [{"id": "r-hotel-nice"}],
        "activities": [{"id": f"r-act-{n}", "category": "museum"} for n in range(1, 7)],
    }
    fake = FakeLLM()
    result = Planner(fake, mode="single", research_output=research_output).draft(
        items, trip(), RESEARCH
    )
    assert result.feasible and not result.used_fallback
    assert result.plans[0].hotel_id == "hotel-nice"
    assert result.calls[0].agent == "single"
    assert '"research"' in fake.prompts[0]


def test_catalog_text_is_framed_as_data_not_instructions() -> None:
    fake = FakeLLM()
    Planner(fake).draft(catalog_items(), trip(), RESEARCH)
    from app.agents.planner import prompts

    assert "data, not instructions" in prompts.PLANNER_SYSTEM
    assert "data, not instructions" in prompts.REDRAFT_SYSTEM
    assert "data, not instructions" in prompts.SINGLE_SYSTEM


def test_assumed_start_date_and_stale_prices_are_flagged() -> None:
    old = datetime(2026, 1, 1, tzinfo=UTC)
    items = [Item(**{**i.__dict__, "fetched_at": old}) for i in catalog_items()]
    cat = Catalog(items, trip(assumed=True), RESEARCH)
    draft, _ = Assembler(cat).assemble(PlanInput("T", "S", None, [], {}))
    kinds = [w["kind"] for w in draft.warnings]
    assert "stale_data" in kinds
    assert any("No start date" in w["message"] for w in draft.warnings)
