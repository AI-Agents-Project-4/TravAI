"""The whole flow through the API: trip -> research (offline replay) -> plans -> redraft -> save.

These requests match cases in researchAgent/tests/test_cases.json exactly, so the
research agent answers them from its committed cache with no network.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ModelCall, ResearchRun, Trip
from tests.fakes import FakeLLM

TOKYO = {
    "origin": "DEN",
    "destination": "Tokyo, Japan",
    "start_date": "2027-03-10",
    "duration_days": 5,
    "travelers": 1,
    "budget": {"amount": 5000, "currency": "USD"},
    "transport_mode": "fly",
    "end_destination": None,
}
JAPAN_MONTH = {
    **TOKYO,
    "destination": "Japan",
    "start_date": "2027-04-01",
    "duration_days": 30,
    "budget": {"amount": 500, "currency": "USD"},
}
DAY_TRIP = {
    **TOKYO,
    "origin": "Denver, CO",
    "destination": "Colorado Springs, CO",
    "start_date": "2027-05-15",
    "duration_days": 1,
    "budget": {"amount": 500, "currency": "USD"},
    "transport_mode": "drive",
}


def plan_trip(client: TestClient, body: dict[str, Any]) -> str:
    response = client.post("/trips", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["trip_id"])


def frontend_total(plan: dict[str, Any], options: dict[str, dict[str, Any]], other: float) -> float:
    ids = [plan["flight_option_id"], plan["hotel_option_id"]] + [
        i["option_id"] for d in plan["days"] for i in d["items"]
    ]
    return round(sum(float(options[i]["price"]["amount"]) for i in ids if i) + other, 2)


def other_costs(plan: dict[str, Any]) -> float:
    return sum(
        float(c["total"]["amount"]) for c in plan["cost_breakdown"] if c["category"] == "other"
    )


def test_tokyo_end_to_end(client: TestClient, db_session: Session) -> None:
    trip_id = plan_trip(client, TOKYO)

    progress = client.get(f"/trips/{trip_id}/progress").json()
    assert progress["status"] == "done"
    messages = [s["message"] for s in progress["steps"]]
    assert "Found 6 flights" in messages  # straight from the research agent
    assert "Building three itineraries" in messages and messages[-1] == "Done"

    body = client.get(f"/trips/{trip_id}/plans").json()
    assert body["feasible"] is True
    plans, options = body["plans"], {o["id"]: o for o in body["options"]}
    assert len(plans) == 3 and len({p["title"] for p in plans}) == 3
    assert all(o["source_url"] and o["fetched_at"] for o in options.values())  # rule 2
    for plan in plans:
        assert plan["total"]["amount"] <= 5000
        assert plan["budget"] == {"amount": 5000.0, "currency": "USD"}
        assert plan["total"]["amount"] == pytest.approx(
            frontend_total(plan, options, other_costs(plan))
        )
        assert options[plan["flight_option_id"]]["kind"] == "flight"
        assert options[plan["hotel_option_id"]]["kind"] == "hotel"
        assert len(plan["days"]) == 5
        # The fake model proposes 2 activities a day. Neighborhood names ("Ginza") must not
        # be mistaken for a different stop and thrown away (a bug caught here once).
        content = [
            i
            for d in plan["days"]
            for i in d["items"]
            if options[i["option_id"]]["kind"] in ("activity", "food")
        ]
        assert len(content) >= 8, [len(d["items"]) for d in plan["days"]]
        kinds = {w["kind"] for w in plan["warnings"]}
        assert "estimate" in kinds  # synthetic test data and the food estimate are labeled
        assert any("TEST DATA" in w["message"] for w in plan["warnings"])

    trip = db_session.get(Trip, uuid.UUID(trip_id))
    assert trip is not None and trip.research_run_id is not None
    calls = db_session.scalars(select(ModelCall).where(ModelCall.trip_id == trip.id)).all()
    assert [c.agent for c in calls] == ["planner"]  # cached research made no model calls


def test_redraft_keeps_locked_items_and_reports_drops(client: TestClient) -> None:
    trip_id = plan_trip(client, TOKYO)
    body = client.get(f"/trips/{trip_id}/plans").json()
    plan, options = body["plans"][0], body["options"]
    used = {i["option_id"] for d in plan["days"] for i in d["items"]}
    removed = next(
        i["option_id"]
        for i in plan["days"][1]["items"]
        if options and i["option_id"] in {o["id"] for o in options if o["kind"] == "activity"}
    )
    added = next(o["id"] for o in options if o["kind"] == "activity" and o["id"] not in used)
    days = [
        {**d, "items": [i for i in d["items"] if i["option_id"] != removed]} for d in plan["days"]
    ]
    days[2]["items"].append({"option_id": added, "locked": True})

    response = client.post(
        f"/plans/{plan['id']}/redraft", json={"days": days, "removed_option_ids": [removed]}
    )
    assert response.status_code == 200, response.text
    new = response.json()["plan"]
    placed = {(d["day"], i["option_id"]): i["locked"] for d in new["days"] for i in d["items"]}
    assert placed[(3, added)] is True  # the user's addition stays on day 3, locked
    assert all(oid != removed for _, oid in placed)  # removed stays removed
    assert new["total"]["amount"] <= 5000
    assert new["summary"] == "Redrafted around your changes."
    assert isinstance(response.json()["dropped_items"], list)


def test_redraft_rejects_options_from_another_trip(client: TestClient) -> None:
    trip_id = plan_trip(client, TOKYO)
    plan = client.get(f"/trips/{trip_id}/plans").json()["plans"][0]
    days = [{"day": 1, "items": [{"option_id": str(uuid.uuid4()), "locked": True}]}]
    response = client.post(
        f"/plans/{plan['id']}/redraft", json={"days": days, "removed_option_ids": []}
    )
    assert response.status_code == 422


def test_save_recomputes_the_total_and_keeps_the_users_plan(client: TestClient) -> None:
    trip_id = plan_trip(client, TOKYO)
    body = client.get(f"/trips/{trip_id}/plans").json()
    plan, options = body["plans"][0], {o["id"]: o for o in body["options"]}
    plan["days"][0]["items"] = plan["days"][0]["items"][:1]  # the user trims day 1
    plan["total"] = {"amount": 1, "currency": "USD"}  # and the client sends a wrong total
    plan["title"] = "My Tokyo"

    response = client.put(f"/plans/{plan['id']}", json=plan)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["saved"] is True and saved["title"] == "My Tokyo"
    assert [i["option_id"] for i in saved["days"][0]["items"]] == [
        i["option_id"] for i in plan["days"][0]["items"]
    ]
    assert saved["total"]["amount"] == pytest.approx(
        frontend_total(saved, options, other_costs(saved))
    )
    assert client.get(f"/plans/{plan['id']}").json() == saved


def test_a_month_in_japan_on_500_is_honestly_infeasible(client: TestClient) -> None:
    trip_id = plan_trip(client, JAPAN_MONTH)
    body = client.get(f"/trips/{trip_id}/plans").json()
    assert body["feasible"] is False
    assert body["min_estimated_cost"]["amount"] > 500
    assert body["min_estimated_cost"]["amount"] % 50 == 0  # rounded up, never down
    assert "$500 budget" in body["reason"]


def test_a_day_trip_drives_there_and_back(client: TestClient) -> None:
    trip_id = plan_trip(client, DAY_TRIP)
    body = client.get(f"/trips/{trip_id}/plans").json()
    assert body["feasible"] is True
    options = {o["id"]: o for o in body["options"]}
    for plan in body["plans"]:
        assert plan["flight_option_id"] is None and plan["hotel_option_id"] is None
        items = [options[i["option_id"]] for i in plan["days"][0]["items"]]
        drives = [o for o in items if o["details"].get("role") == "drive"]
        assert len(drives) == 2  # there and back
        assert plan["total"]["amount"] <= 500


def test_identical_trips_reuse_research(client: TestClient, db_session: Session) -> None:
    first, second = plan_trip(client, TOKYO), plan_trip(client, TOKYO)
    runs = db_session.scalar(select(func.count()).select_from(ResearchRun))
    assert runs == 1
    steps = [s["message"] for s in client.get(f"/trips/{second}/progress").json()["steps"]]
    assert any(m.startswith("Reusing research") for m in steps)
    assert client.get(f"/trips/{first}/plans").json()["feasible"] is True
    assert client.get(f"/trips/{second}/plans").json()["feasible"] is True


def test_risky_destination_warns_first_and_waits_for_proceed(
    client: TestClient, db_session: Session
) -> None:
    response = client.post("/trips", json={**TOKYO, "destination": "Lviv, Ukraine"})
    assert response.status_code == 201
    body = response.json()
    assert body["warnings"][0]["kind"] == "safety"
    assert "Level 4" in body["warnings"][0]["message"]
    trip_id = body["trip_id"]

    progress = client.get(f"/trips/{trip_id}/progress").json()
    assert progress == {"status": "researching", "steps": []}  # nothing has started
    assert client.get(f"/trips/{trip_id}/plans").status_code == 409

    assert client.post(f"/trips/{trip_id}/proceed").status_code == 204
    trip = db_session.get(Trip, uuid.UUID(trip_id))
    assert trip is not None and trip.status != "awaiting_confirmation"
    assert client.post(f"/trips/{trip_id}/proceed").status_code == 204  # safe to repeat


def test_no_origin_fails_with_a_reason(client: TestClient) -> None:
    trip_id = plan_trip(client, {**TOKYO, "origin": None})
    progress = client.get(f"/trips/{trip_id}/progress").json()
    assert progress["status"] == "failed"
    assert "origin" in progress["steps"][-1]["message"]
    response = client.get(f"/trips/{trip_id}/plans")
    assert response.status_code == 409 and "origin" in response.json()["detail"]


def test_planner_model_down_still_gives_honest_plans(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.fail = True
    trip_id = plan_trip(client, TOKYO)
    steps = [s["message"] for s in client.get(f"/trips/{trip_id}/progress").json()["steps"]]
    assert any("simple rules" in m for m in steps)
    body = client.get(f"/trips/{trip_id}/plans").json()
    assert body["feasible"] is True and len(body["plans"]) == 3


def test_unknown_plan_is_404(client: TestClient) -> None:
    assert client.get(f"/plans/{uuid.uuid4()}").status_code == 404
    assert client.post(f"/trips/{uuid.uuid4()}/proceed").status_code == 404


def test_money_is_sent_as_numbers(client: TestClient) -> None:
    trip_id = plan_trip(client, TOKYO)
    plan = client.get(f"/trips/{trip_id}/plans").json()["plans"][0]
    assert isinstance(plan["total"]["amount"], float)
    assert Decimal(str(plan["total"]["amount"])) == Decimal(str(plan["total"]["amount"])).quantize(
        Decimal("0.01")
    )
